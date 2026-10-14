#!/usr/bin/env bash
# Keeps the VM's deployment on origin/main, or on a pinned commit, and the
# controls for that. The systemd timer in deploy/systemd/ runs it with no
# arguments every few minutes; deploy/README.md's "Updating" covers the rest.
#
#   update.sh                    deploy the target if it isn't what's deployed
#   update.sh status             what's deployed, the target, pause, next run
#   update.sh pause [why]        stop runs from deploying
#   update.sh resume             clear the pause, then run once
#   update.sh pin [--unmerged] [--db-restored] <commit>
#                                hold the deployment at <commit>, deploying it now
#   update.sh unpin              go back to following origin/main
#
# Run from anywhere: it works in the clone it's part of. COMPOSE_PROJECT_NAME,
# DEPLOY_ENV_FILE and DEPLOY_PG_PORT pass through to compose.

set -euo pipefail

STATE=.deploy-state
MIGRATIONS=backend/migrations/versions/
HEALTH_TIMEOUT=120

log() { printf '%s\n' "$*"; }
die() {
  printf 'update.sh: %s\n' "$*" >&2
  exit 1
}
now() { date -u +%FT%TZ; }
short() { git rev-parse --short "$1"; }
describe() { git log -1 --format='%h %s' "$1"; }

# A value from the env file, read rather than sourced: a value with a `$` or a
# space in it would otherwise break or run as shell.
env_value() {
  local line
  [[ -f $ENV_FILE ]] || return 0
  line=$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -n 1) || return 0
  line=${line#*=}
  line=${line%$'\r'}
  # Compose strips one pair of surrounding quotes, so do the same.
  if [[ $line =~ ^\"(.*)\"$ || $line =~ ^\'(.*)\'$ ]]; then
    line=${BASH_REMATCH[1]}
  fi
  printf '%s' "$line"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml "$@"
}

# Never fails the run: a notification is a courtesy, the journal is the record.
notify() {
  local url
  url=$(env_value DEPLOY_NOTIFY_URL)
  [[ -n $url ]] || return 0
  curl -fsS --max-time 10 -H 'Content-Type: text/plain' --data-raw "$1" \
    "$url" >/dev/null || log "Notification to DEPLOY_NOTIFY_URL failed"
}

deployed_sha() {
  local sha _
  [[ -f $STATE/deployed ]] || return 0
  read -r sha _ <"$STATE/deployed"
  printf '%s' "$sha"
}

pinned_sha() {
  [[ -f $STATE/pin ]] || return 0
  cat "$STATE/pin"
}

target_sha() {
  local pin
  pin=$(pinned_sha)
  printf '%s' "${pin:-$(git rev-parse origin/main)}"
}

is_paused() { [[ -f $STATE/paused ]]; }

set_paused() {
  printf '%s %s\n' "$(now)" "$1" >"$STATE/paused"
}

# A pause the script sets itself, so says so, and tells whoever's subscribed.
pause_self() {
  set_paused "update.sh paused itself: $1"
  log "Paused: $1"
  notify "song-study: $1. Auto-deploy is paused."
}

# Takes the run lock on fd 9 for the rest of the process, or exits: at once and
# quietly under systemd (which sets INVOCATION_ID), with a message otherwise.
take_lock() {
  exec 9>"$STATE/lock"
  if ! flock -n 9; then
    [[ -n ${INVOCATION_ID:-} ]] && exit 0
    die "another run holds the lock (a deploy in progress?); try again once it's done"
  fi
}

fetch() {
  git fetch --quiet --prune origin
}

migrations_changed() { # filter from to
  git diff --diff-filter="$1" --name-only "$2" "$3" -- "$MIGRATIONS"
}

# Why deploying `target` over `deployed` would be wrong, or nothing if it's
# fine. `db_restored` skips the migration check, which reads git and so can't
# see that the database was restored to before the migration.
refusal() { # deployed target db_restored
  local deployed=$1 target=$2 db_restored=$3 missing
  if [[ -n $(git status --porcelain --untracked-files=no) ]]; then
    printf 'tracked files in the clone have local changes (git status shows them), so a checkout would fail or carry them along'
    return
  fi
  [[ -n $deployed && $db_restored != yes ]] || return 0
  missing=$(migrations_changed D "$deployed" "$target")
  if [[ -n $missing ]]; then
    printf '%s lacks migrations the deployed %s applied (%s), so its code is older than the database; see "Rolling back" in deploy/README.md' \
      "$(short "$target")" "$(short "$deployed")" "$(tr '\n' ' ' <<<"$missing")"
  fi
}

# Waits for the API's schema to come back through Caddy, from this machine,
# so the check covers Caddy, TLS and the backend without leaving the box.
wait_healthy() {
  local app_url deadline
  app_url=$(env_value APP_URL)
  app_url=${app_url%/}
  if [[ -z $app_url ]]; then
    log "APP_URL isn't set in $ENV_FILE"
    return 1
  fi
  deadline=$((SECONDS + HEALTH_TIMEOUT))
  while ((SECONDS < deadline)); do
    # Connects to this machine whatever APP_URL's host and port, keeping them
    # for the Host header and TLS.
    if curl -fsS -o /dev/null --max-time 5 --connect-to ::127.0.0.1: \
      "$app_url/api/openapi.json" 2>/dev/null; then
      return 0
    fi
    sleep 3
  done
  log "No 200 from $app_url/api/openapi.json within ${HEALTH_TIMEOUT}s"
  return 1
}

# Checks out `sha` and brings the stack up on it. Called only as a condition,
# where `set -e` is off, so each step is chained explicitly.
bring_up() {
  git checkout --quiet --detach "$1" &&
    compose up -d --build --remove-orphans &&
    wait_healthy
}

# Deploys `target` over `deployed` (empty on the first run). On failure, rolls
# back when the target added no migration, and pauses either way.
deploy() { # deployed target
  local deployed=$1 target=$2 what outcome
  what=$(describe "$target")
  log "Deploying $what"
  if bring_up "$target"; then
    printf '%s %s\n' "$target" "$(now)" >"$STATE/deployed"
    docker image prune -f >/dev/null || log "docker image prune failed"
    log "Deployed $what"
    notify "song-study: deployed $what"
    return 0
  fi

  if [[ -z $deployed ]]; then
    outcome="nothing was deployed before it to roll back to"
  elif [[ -n $(migrations_changed A "$deployed" "$target") ]]; then
    # The migration may already have run, and rolling the code back over it
    # is the hazard `refusal` guards against.
    outcome="not rolled back, since it adds a migration"
  else
    log "Rolling back to $(describe "$deployed")"
    # The old images are cached, so this is quick. A failed build never
    # stopped the old containers, but the checkout keeps the clone matching
    # what's running.
    if bring_up "$deployed"; then
      outcome="rolled back to $(short "$deployed")"
    else
      outcome="the rollback to $(short "$deployed") failed too"
    fi
  fi
  pause_self "deploying $what failed; $outcome"
  return 1
}

# One run as the timer does it: deploys the target unless paused or current.
cmd_run() {
  local deployed target why
  take_lock
  fetch
  if is_paused; then
    log "Paused, so not deploying: $(cut -d' ' -f2- "$STATE/paused")"
    return 0
  fi
  deployed=$(deployed_sha)
  target=$(target_sha)
  if [[ $target == "$deployed" ]]; then
    log "Up to date at $(describe "$target")"
    return 0
  fi
  why=$(refusal "$deployed" "$target" no)
  if [[ -n $why ]]; then
    pause_self "not deploying $(short "$target"): $why"
    return 1
  fi
  deploy "$deployed" "$target"
}

cmd_status() {
  local deployed='' target pin when why behind
  if [[ -f $STATE/deployed ]]; then
    read -r deployed when <"$STATE/deployed"
    log "Deployed:  $(describe "$deployed") (at $when)"
  else
    log "Deployed:  nothing yet"
  fi
  pin=$(pinned_sha)
  target=${pin:-$(git rev-parse origin/main)}
  if [[ -n $pin ]]; then
    log "Target:    $(describe "$target") (pinned)"
  else
    log "Target:    $(describe "$target") (origin/main as last fetched)"
  fi
  if [[ -n $deployed ]]; then
    behind=$(git rev-list --count "$deployed..origin/main")
    log "Behind:    $behind commit(s) on origin/main not deployed"
  fi
  if is_paused; then
    read -r when why <"$STATE/paused"
    log "Paused:    since $when: $why"
  else
    log "Paused:    no"
  fi
  if ! (flock -n 9) 9>"$STATE/lock"; then
    log "Running:   a run holds the lock now"
  fi
  if command -v systemctl >/dev/null; then
    log "Timer:"
    systemctl --user list-timers song-study-update.timer --no-pager | sed 's/^/  /'
  else
    log "Timer:     no systemd here"
  fi
}

cmd_pause() {
  set_paused "${*:-no reason given}"
  log "Paused. A deploy already running finishes; 'update.sh resume' undoes this."
}

cmd_resume() {
  rm -f "$STATE/paused"
  log "Resumed"
  cmd_run
}

cmd_pin() {
  local unmerged=no db_restored=no ref sha deployed why
  while (($#)); do
    case $1 in
    --unmerged) unmerged=yes ;;
    --db-restored) db_restored=yes ;;
    -*) die "unknown option $1" ;;
    *)
      [[ -z ${ref:-} ]] || die "pin takes one commit"
      ref=$1
      ;;
    esac
    shift
  done
  [[ -n ${ref:-} ]] || die "usage: update.sh pin [--unmerged] [--db-restored] <commit>"

  take_lock
  fetch
  sha=$(git rev-parse --verify --quiet "$ref^{commit}") || die "no commit $ref"
  if [[ $unmerged != yes ]] && ! git merge-base --is-ancestor "$sha" origin/main; then
    die "$(short "$sha") isn't on origin/main; pass --unmerged to deploy unmerged code to prod anyway"
  fi
  deployed=$(deployed_sha)
  if [[ $sha == "$deployed" ]]; then
    printf '%s\n' "$sha" >"$STATE/pin"
    log "Pinned to $(describe "$sha"), which is already deployed"
    return 0
  fi
  # Refused here rather than paused over: the operator is asking, so tell
  # them and change nothing.
  why=$(refusal "$deployed" "$sha" "$db_restored")
  [[ -z $why ]] || die "refusing to pin: $why"
  printf '%s\n' "$sha" >"$STATE/pin"
  log "Pinned to $(describe "$sha")"
  # Deployed even while paused, since the operator asked for this commit.
  deploy "$deployed" "$sha"
}

cmd_unpin() {
  rm -f "$STATE/pin"
  log "Unpinned; the next unpaused run deploys origin/main"
}

main() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  ENV_FILE=${DEPLOY_ENV_FILE:-.env}
  mkdir -p "$STATE"
  local cmd=${1:-run}
  (($#)) && shift
  case $cmd in
  run) cmd_run ;;
  status) cmd_status ;;
  pause) cmd_pause "$@" ;;
  resume) cmd_resume ;;
  pin) cmd_pin "$@" ;;
  unpin) cmd_unpin ;;
  *) die "unknown command $cmd (run, status, pause, resume, pin, unpin)" ;;
  esac
}

# On one line, so bash has read all of it before running: a deploy checks out
# a new copy of this file while bash is still reading it, and the exit keeps
# bash from reading on into the new copy afterwards.
main "$@"; exit
