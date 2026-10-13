#!/usr/bin/env bash
# Starts, stops and reports on the browser harness's two servers: the
# test-database backend (backend/tests/browser_server.py) and a Vite proxying
# /api to it. See docs/browser-checks.md.
#
#   servers.sh up [--fresh]   start both (reusing them if already up), or
#                             with --fresh restart and re-seed
#   servers.sh down           stop both, and any headless browser a check left
#   servers.sh status         what's running, and where the logs are
#
# `up` returns once both answer, or fails within BROWSER_UP_TIMEOUT seconds
# (default 90) with the tail of whichever log explains it. It never leaves a
# server running in the foreground.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
STATE="$REPO/.browser-harness"
API_PORT=${BROWSER_API_PORT:-8001}
WEB_PORT=${BROWSER_WEB_PORT:-5199}
TIMEOUT=${BROWSER_UP_TIMEOUT:-90}
# tests.support's TEST_USER_ID: answering as this user is how a backend shows
# it's the harness's, not the app's on its real database.
TEST_USER_ID=1000
mkdir -p "$STATE"

answers_as_test_user() {
  curl -sf -m 2 "$1/api/auth/me" | grep -q "\"id\":$TEST_USER_ID[,}]"
}
api_up() { answers_as_test_user "http://127.0.0.1:$API_PORT"; }
# Through Vite's proxy, so this also shows Vite is pointed at the right backend.
web_up() { answers_as_test_user "http://localhost:$WEB_PORT"; }

port_holder() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

# The pid in $1.pid, if that process is still alive and is the one we started.
our_pid() {
  local file="$STATE/$1.pid" pid
  [[ -f $file ]] || return 1
  pid=$(cat "$file")
  ps -p "$pid" -o command= 2>/dev/null | grep -q "$2" && echo "$pid"
}

stop() {
  local pid
  if pid=$(our_pid "$1" "$2"); then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
    echo "stopped $1 ($pid)"
  fi
  rm -f "$STATE/$1.pid"
}

down() {
  stop vite vite
  stop backend tests.browser_server
  # Headless browsers a check left behind when its node process was killed
  # from outside (a watchdog exit cleans up after itself). Playwright's
  # launch profile directory names them, so a browser you're using is safe.
  pkill -f 'playwright_chromiumdev_profile' 2>/dev/null && echo "stopped leftover headless browsers" || true
}

show_logs() {
  for name in backend vite; do
    echo "--- $STATE/$name.log (last 20 lines)"
    tail -20 "$STATE/$name.log" 2>/dev/null || true
  done
}

up() {
  if [[ ${1-} == --fresh ]]; then
    down
  # Only servers this checkout started: another worktree's harness answers the
  # same way, but serves that worktree's code.
  elif our_pid vite vite >/dev/null && our_pid backend tests.browser_server >/dev/null &&
    api_up && web_up; then
    echo "already up at http://localhost:$WEB_PORT (seed: $(cat "$STATE/seed.json" 2>/dev/null))"
    return
  fi
  # Half up (one server died, or an earlier `up` was interrupted): start over.
  down >/dev/null

  local port holder
  for port in "$API_PORT" "$WEB_PORT"; do
    if holder=$(port_holder "$port"); then
      echo "port $port is held by something other than this harness:"
      ps -p "$holder" -o pid=,command= || true
      echo "stop it, or pick other ports with BROWSER_API_PORT / BROWSER_WEB_PORT"
      exit 1
    fi
  done

  rm -f "$STATE/seed.json"
  (
    cd "$REPO/backend"
    BROWSER_SEED_FILE="$STATE/seed.json" PORT="$API_PORT" \
      nohup .venv/bin/python -m tests.browser_server >"$STATE/backend.log" 2>&1 </dev/null &
    echo $! >"$STATE/backend.pid"
  )
  (
    cd "$REPO/frontend"
    API_PROXY_TARGET="http://127.0.0.1:$API_PORT" \
      nohup node_modules/.bin/vite --port "$WEB_PORT" --strictPort >"$STATE/vite.log" 2>&1 </dev/null &
    echo $! >"$STATE/vite.pid"
  )

  local deadline=$((SECONDS + TIMEOUT))
  until api_up && web_up; do
    if ! our_pid backend tests.browser_server >/dev/null || ! our_pid vite vite >/dev/null; then
      echo "a server exited during startup"
      show_logs
      down >/dev/null
      exit 1
    fi
    if ((SECONDS >= deadline)); then
      echo "not up after ${TIMEOUT}s (seeding re-creates and migrates the database, then tokenizes a document)"
      show_logs
      down >/dev/null
      exit 1
    fi
    sleep 0.5
  done
  echo "up at http://localhost:$WEB_PORT (seed: $(cat "$STATE/seed.json"))"
}

status() {
  local name
  for name in backend vite; do
    if pid=$(our_pid "$name" "$([[ $name == backend ]] && echo tests.browser_server || echo vite)"); then
      echo "$name: running ($pid), log $STATE/$name.log"
    else
      echo "$name: not running"
    fi
  done
  if api_up && web_up; then
    echo "answering at http://localhost:$WEB_PORT (seed: $(cat "$STATE/seed.json" 2>/dev/null))"
  fi
}

case ${1-} in
  up) up "${2-}" ;;
  down) down ;;
  status) status ;;
  *)
    echo "usage: $0 up [--fresh] | down | status" >&2
    exit 2
    ;;
esac
