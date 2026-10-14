# Deploying song-study

## Context

The app has only ever run locally. The goal is a small deployment that a
handful of people can reach, run the way AGENTS.md asks: the same origin
layout, cookie and auth behavior, and database engine as local dev, with
only env vars differing.

The app code needs no changes for this:

- `APP_URL` drives the OAuth redirect (`backend/app/auth.py`) and the
  session cookie's `Secure` flag (`backend/app/main.py`).
- The frontend reads no build-time env vars and calls `/api` on its own
  origin.
- The README already expects a reverse proxy that sends `/api/*` to the
  backend and everything else to the built frontend.

What's missing is the deployment files (step 1), an update script that
deploys merged changes on its own (step 2), and a backup script (step 3).
The rest is work only the operator can do: accounts, DNS, the VM, secrets.
That's covered under "Initial deploy" and "Updating" below.

### Decided (2026-10-08)

- **Host: a Google Cloud e2-micro VM on the free tier,** running Docker
  Compose. Nothing in the repo is specific to Google Cloud, so moving to a
  paid VPS later (Hetzner, DigitalOcean) means copying `.env` and a database
  dump to the new machine and repointing DNS.
- **Not GitHub Pages:** it serves static files only. The backend would then
  live on another origin, which needs CORS and a cross-site session cookie.
  That's the split origin AGENTS.md rules out, and Safari blocks third-party
  cookies anyway.
- **Not a free PaaS tier:**
  - Those tiers sleep when idle, and a cold start here includes loading the
    dictionaries.
  - Their free databases expire or pause.
  - Free tiers get withdrawn.
- **Three containers.** **postgres** is the same `postgres:16-alpine` image
  as dev. **backend** runs migrations, then uvicorn. **caddy** handles
  HTTPS, serves the built frontend, and proxies `/api/*` to the backend.
- **One uvicorn worker.** Measured locally, a process peaks at about 200 MB:
  - Sudachi memory-maps its 343 MB `system.dic`, and only about 90 MB of it
    is loaded after use. Those pages are backed by the file, so the kernel
    can drop them under memory pressure.
  - About 100 MB more is ordinary memory, and every extra worker pays that
    again.
  - JMDict is a 325 MB SQLite file that's queried on disk and adds about
    14 MB.

  1 GB of RAM plus a 2 GB swap file is enough. The swap is mostly for
  building the images.

- **Who can sign in:** the Google OAuth consent screen stays in **Testing**
  status, so only the test users listed there can sign in (up to 100). The
  code has no allowlist of its own, and this way it doesn't need one.
- **Debugging prod from the laptop:**
  - The local Vite dev server can proxy `/api` to the prod backend, chosen
    by an env var.
  - Postgres is published on the VM's loopback interface only, and reached
    through an SSH tunnel as a read-only role.

  Neither opens anything to the internet.

- **Routes that need no sign-in** (checked 2026-10-09) are:
  - sign-in, sign-out and the OAuth callback;
  - `GET /api/jmdict/search`, which reads only the public dictionary;
  - the API schema at `/api/docs` and `/api/openapi.json`.

  Every route that touches documents, cards or users requires a signed-in
  user and is limited to that user's own data. Leaving the dictionary search
  and the schema public is accepted for now.

- **Auto-deploy pulls from the VM** (2026-10-14). A systemd timer on the VM
  checks `origin/main` every few minutes and deploys new commits, rather
  than a GitHub Actions job pushing to it:
  - It uses the read-only deploy key the VM already has. No SSH key or
    host address goes into GitHub's secrets, and nothing new has to reach
    the VM from outside.
  - Nothing in it is specific to Google Cloud or GitHub Actions, so it
    moves to another VPS with the rest of the clone.
  - The images still build on the VM, as they do by hand today. Docker's
    layer cache keeps a code-only change to a minute or two; only a change
    to `requirements.txt` repeats the long dictionary install.

  Pausing it and holding it at a chosen commit are commands of the same
  script, run over SSH (step 2).

- **Later, only when asked:** a VM setup script. Until then the operator
  steps below are done by hand.

## Build order

There are three steps after this doc, each on its own branch and PR. Steps 2
and 3 need step 1, and step 3 also adds a hook to step 2's script, so it
goes after step 2.

| Step                 | Status | Ships                                                                                                                                                                                                                               | Model    | Effort | Size | Actual        | Why                                                                                                                                                                            |
| -------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------ | ---- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 0 — Doc              | Done   | This plan as `docs/ongoing/deploy.md`                                                                                                                                                                                               | Opus 5   | medium | —    | —             | Planning                                                                                                                                                                       |
| 1 — Deployment files | Done   | `backend/Dockerfile`, `frontend/Dockerfile`, `.dockerignore`s, `deploy/Caddyfile`, `docker-compose.prod.yml`, deployment notes in `.env.example`, `API_PROXY_TARGET` in `vite.config.ts`, a local run of the whole stack            | Sonnet 5 | medium | M    | M; simplify S | Conventional Docker work against a clear spec. The traps (below) are a shared volume name, lost certificates and the SPA fallback, and each one shows up in the local check    |
| 2 — Auto-deploy      |        | `deploy/update.sh` (deploys `origin/main` or a pinned commit; `pause`, `resume`, `pin`, `unpin`, `status`), its systemd timer and service, a rollback when the new version doesn't come up, a local check against a throwaway clone | Opus 5   | medium | L    |               | Most of its mistakes are silent: a pin that drifts, a pause the timer runs through, or a rollback to code older than the database's migrations. Each needs a case in the check |
| 3 — Backup script    |        | `deploy/backup.sh`: a dated `pg_dump`, kept for 14 days locally, copied off the box. `update.sh` runs it before deploying a new migration                                                                                           | Sonnet 5 | medium | S    |               | Short, but a backup that quietly writes an empty or unrestorable dump is the worst kind of failure, so it's checked by restoring the dump                                      |

Each step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Escalate a step that stalls rather
than starting higher.

Other sessions may be switching branches in the main checkout at the same
time. Do each step's git work in its own worktree (`git worktree add
<dir> -b <branch> origin/main`), and confirm the PR's commits and files
before opening it.

Size is the expected token use of a step's initial pass, before
`/simplify`, as a bucket from `docs/token-usage.md`. Actual is what the
pass and its `/simplify` measured, recorded in that ledger when the step's
PR opens.

### Before step 1 (operator)

- **Add `http://localhost/api/auth/callback`** [DONE] to the dev Google OAuth
  client's authorized redirect URIs. Step 1's local check signs in through
  Caddy on port 80, not through Vite on 5173.
- **Have Docker running** on the laptop, with **port 80 free**: the local
  check publishes Caddy on 80, because Caddy listens on the port in
  `APP_URL`. The check publishes Postgres on 127.0.0.1:15433 instead of
  5432, so a local Postgres doesn't conflict. The dev database on 5544
  doesn't either.
- **Pull `main`** before starting the session, so its worktree starts from
  the merged plan.

## Step 1 — Deployment files

**`backend/Dockerfile`:**

- Based on `python:3.11-slim`. It runs `pip install -r requirements.txt` and
  copies in `app/`, `migrations/` and `alembic.ini`.
- The command runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` with one
  worker and no `--reload`. Migrations run in `docker-compose.prod.yml`'s
  one-shot `migrate` service (same image), which the backend waits on.
- Install the requirements before copying the code, so a code-only change
  doesn't reinstall the 650 MB of dictionaries.
- `app/env.py`'s `load_dotenv` leaves variables that are already set alone,
  and does nothing when there's no `.env` file. So env vars passed in by
  compose work without code changes.

**`frontend/Dockerfile`:** two stages.

- A `node` stage runs `npm ci && npm run build`.
- A `caddy:2` stage copies `dist/` into `/srv`.

**`.dockerignore`** in `backend/` and in `frontend/`. Without these, the
build context sends `.venv` (about 785 MB) and `node_modules` to Docker on
every build. Exclude `.venv`, `venv`, `__pycache__`, `node_modules` and
`dist`.

**`deploy/Caddyfile`:** the site address is `{$APP_URL}`, so Caddy and the
app read the same variable. A full URL works as a Caddy site address:
`https://songs.example.com` gets a certificate, and `http://localhost` serves
plain HTTP.

```
{$APP_URL} {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        root * /srv
        try_files {path} /index.html
        file_server
    }
}
```

`try_files` sends unknown paths to `index.html`, so a reload on a React
Router path like `/documents/12` works.

**`docker-compose.prod.yml`:**

- **The `name:` must differ from the dev compose project.** The dev file
  takes its name from the directory (`song-study`), so its volume is
  `song-study_postgres-data`. A prod file with the same name would reuse
  that volume, and the local check below would run against the dev data.
- **postgres:** `postgres:16-alpine` with dev's healthcheck and a named
  volume. It gets only `POSTGRES_USER`, `POSTGRES_PASSWORD` and
  `POSTGRES_DB`, as an `environment:` block interpolated from the shell and
  the project's `.env` (`--env-file` when the file has another name), so
  `SESSION_SECRET` and the Google secret stay out of that container. The
  check is `pg_isready -U $$POSTGRES_USER`: the doubled `$` has the
  container read its own environment, where `${POSTGRES_USER}` would be
  read from the host shell.
  - Publishes `127.0.0.1:${DEPLOY_PG_PORT:-5432}:5432` and nothing wider.
    That makes it reachable from the VM itself, and so through an SSH
    tunnel, but not from the internet. The VM uses the default; the local
    check sets `DEPLOY_PG_PORT=15433`. Compose reads it from the shell, not
    from the env file, so it goes on the command line and not in `.env.example`.
  - Write out the `127.0.0.1`. Docker's published ports bypass the host
    firewall, so a bare `5432:5432` would expose the database to the
    internet.
- **backend:** built from `backend/`, starts once postgres is healthy
  (`depends_on` with `condition: service_healthy`), and has no published
  ports.
- **caddy:** built from `frontend/`.
  - Publishes `80:80` and `443:443`.
  - Mounts `deploy/Caddyfile` at `/etc/caddy/Caddyfile`, read-only.
  - Has named volumes for `/data` and `/config`. `/data` holds the
    certificates. Without it, every rebuild requests a new certificate, and
    Let's Encrypt's rate limits lock the domain out after a few.
- `restart: unless-stopped` on all but `migrate`, so they come back after a
  reboot.
- `env_file: ${DEPLOY_ENV_FILE:-.env}` for migrate and backend, the three `POSTGRES_*`
  values for postgres (above), and `APP_URL` passed through to caddy. The
  local check points `DEPLOY_ENV_FILE` and `--env-file` at its own file,
  since the repo-root `.env` belongs to dev.

**`.env.example`:** a short deployment section.

- `APP_URL=https://<domain>`.
- `DATABASE_URL` with the host `postgres` (the compose service name), port
  5432, and a strong password that matches `POSTGRES_PASSWORD`.
- A real `SESSION_SECRET`.
- `TEST_DATABASE_URL` and `POSTGRES_PORT` aren't used in a deployment.

The dev `docker-compose.yml` doesn't change.

**`frontend/vite.config.ts`:** the `/api` proxy's target comes from the
environment, so the dev server can point at prod for debugging. Only the
address changes, which AGENTS.md allows.

```ts
proxy: {
  '/api': {
    target: process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    // Caddy picks the site by Host, so a remote target needs its own hostname
    changeOrigin: true,
  },
},
```

Mention `API_PROXY_TARGET` in the README's Getting started section, next to
the existing note about the proxy.

### Local check

1. Write an env file outside the repo, or anywhere gitignored, with:
   - `APP_URL=http://localhost`
   - a throwaway database password and session secret
   - the dev Google OAuth client's ID and secret

   The operator adds `http://localhost/api/auth/callback` to that OAuth
   client's redirect URIs before step 1 starts (see "Before step 1"). If
   sign-in fails with a redirect URI mismatch, ask rather than working around
   it.

2. Run

   ```
   DEPLOY_PG_PORT=15433 DEPLOY_ENV_FILE=<that file> docker compose \
     --env-file <that file> -f docker-compose.prod.yml \
     -p song-study-deploycheck up -d --build
   ```

   then confirm with `docker volume ls` that the volumes are prefixed
   `song-study-deploycheck_`. Give every later `docker compose` command in
   this check the same `--env-file`, `-p` and `DEPLOY_PG_PORT`.

3. Check, using the headless browser from `docs/browser-checks.md`:
   - Sign in with Google.
   - Create a document from the public-domain text in
     `backend/tests/fixtures/kumo_no_ito.py` (not song lyrics), and check it
     gets furigana and glosses.
   - Reload on the document's URL: the page loads instead of returning 404.
   - `docker compose ... restart backend` keeps you signed in.
4. Run `docker stats` once and note the backend's memory after a document
   has been processed. It should be well under 1 GB.
5. Check the debugging paths against this stack:
   - Run `API_PROXY_TARGET=http://localhost npm run dev` and copy the
     session cookie across as described under "Debugging against prod".
     `localhost:5173` should then show the same signed-in user.
   - Create the read-only role as that section describes, then connect with
     `psql -h 127.0.0.1 -p 15433` as that role. A `SELECT` should work, and
     an `UPDATE` should be refused.
6. Run `docker compose ... down -v` with the same `-p`, which removes only
   the check's volumes.

## Step 2 — Auto-deploy

**`deploy/update.sh`**, run from the clone's root on the VM. With no
arguments it deploys whatever should be running, if that isn't already
running. The timer runs it that way, and so can the operator.

### Commands

| Command                  | Effect                                                                                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `update.sh`              | Deploys the target (the pin if there is one, else `origin/main`) if it differs from what's deployed. Does nothing while paused                                                        |
| `update.sh status`       | What's deployed (commit, subject, when), the target and whether it's a pin, how many commits on `origin/main` aren't deployed, whether it's paused and why, and the timer's next run  |
| `update.sh pause [why]`  | Stops the timer's runs from deploying, recording the reason and time. A deploy already running finishes                                                                               |
| `update.sh resume`       | Clears the pause, then runs once as the timer would                                                                                                                                   |
| `update.sh pin <commit>` | Holds the deployment at that commit and deploys it now, even while paused, since the operator asked for that commit. New commits on `main` are fetched but not deployed until `unpin` |
| `update.sh unpin`        | Clears the pin. The next unpaused run goes back to `origin/main`                                                                                                                      |

- `pin` takes anything `git rev-parse` resolves after a fetch (a SHA, a
  tag, `origin/main~3`) and stores the full SHA, so a pin never moves on
  its own. A commit that isn't on `origin/main` is refused unless
  `--unmerged` is given: trying out unmerged code on prod is what
  "Debugging against prod" warns against.
- `pin --db-restored <commit>` skips the missing-migration check below,
  for after the operator has restored a backup from before that migration
  (see "Rolling back" under "Updating"). The check reads git, not the
  database, so it can't tell on its own.
- From the laptop, any command runs over SSH:
  `gcloud compute ssh <vm> --zone <zone> -- song-study/deploy/update.sh pause "why"`.

### State

In `.deploy-state/` at the clone's root, gitignored, which `git checkout`
leaves alone:

- `deployed`: the SHA and time of the last successful deploy.
- `pin`: the pinned SHA, if any.
- `paused`: the reason and time, if paused. A pause the script sets itself
  says so and names the commit that caused it.
- `lock`: taken with `flock` for the whole run, so the timer and a manual
  command never deploy at once. A run that finds it held exits at once:
  quietly for the timer, with a message for a manual command.

### A run

1. `git fetch --prune origin`, then pick the target. If it's what's
   deployed, stop.
2. Refuse, pausing with the reason, when:
   - **tracked files in the clone have changes** (`git status --porcelain
--untracked-files=no`). Someone edited on the VM, and a checkout would
     either fail or carry the edits along.
   - **the target is missing a migration the deployed commit has**
     (`git diff --diff-filter=D --name-only <deployed> <target> --
backend/migrations/versions/`). The database is already past what the
     target's code knows: `alembic upgrade head` fails, and if it didn't,
     old code would run against the new schema. This covers a `pin` to an
     older commit and a revert on `main` alike. The message points at
     "Rolling back" under "Updating".
3. `git checkout --detach <target>`, then `docker compose --env-file
"${DEPLOY_ENV_FILE:-.env}" -f docker-compose.prod.yml up -d --build
--remove-orphans`. Compose exits non-zero if the build fails or the
   `migrate` service does.
4. Wait up to two minutes for `GET /api/openapi.json` to return 200
   through Caddy, from the VM itself:
   `curl --resolve <host>:<port>:127.0.0.1 "$APP_URL/api/openapi.json"`.
   That covers Caddy, TLS and the backend without leaving the box, and
   works the same for the local check's `http://localhost`.
5. On success, write `deployed` and run `docker image prune -f`.
6. On failure at step 3 or 4:
   - If the change added no migration
     (`git diff --diff-filter=A ... -- backend/migrations/versions/` is
     empty), check out the previously deployed commit and run the same
     `up -d --build` and health check. Its images are cached, so this is
     quick. A failed build never stopped the old containers, but checking
     out the old commit keeps the clone matching what's running.
   - If it added a migration, leave it as is. The migration may already
     have run, and rolling the code back over it is the hazard the run
     refuses above.
   - Either way, pause with the reason and the failed commit, and exit
     non-zero so systemd records the unit as failed. A pause stops the
     timer from rebuilding the same broken commit every few minutes.
     `resume` once a fix is merged, or `pin` a good commit.

**Notifications:** if `DEPLOY_NOTIFY_URL` is set in the env file, POST a
one-line plain-text message to it after each deploy, rollback and pause the
script sets itself. ntfy.sh accepts that body as-is. A failed notification
is logged and never fails the run. Where messages go is a value, like
`BACKUP_BUCKET`.

**Details that matter:**

- **The script replaces itself.** `git checkout` rewrites `update.sh`
  while bash is reading it, and bash reads a script as it goes. Put the
  whole body in functions and call `main "$@"` on the last line, so bash
  has parsed everything before the checkout. A change to `update.sh` takes
  effect from the run after the one that deploys it.
- **Read only the keys it needs** (`APP_URL`, `DEPLOY_NOTIFY_URL`) from the
  env file, rather than sourcing it: a value with a `$` or a space in it
  would break or run as shell.
- `set -euo pipefail`, with the failure path above handled explicitly
  rather than left to `-e`.
- `COMPOSE_PROJECT_NAME`, `DEPLOY_ENV_FILE` and `DEPLOY_PG_PORT` pass
  through from the environment, so the local check can point the script at
  its own stack. The VM uses the defaults.

**`deploy/systemd/song-study-update.service` and `.timer`,** as user units,
so no path or user name is written into them:

- The service is `Type=oneshot`, with `WorkingDirectory=%h/song-study`,
  `ExecStart=%h/song-study/deploy/update.sh`, and `TimeoutStartSec=90min`
  for a build that reinstalls the dictionaries.
- The timer uses `OnBootSec=5min` and `OnUnitInactiveSec=5min`, so the
  interval counts from the end of the last run and a long build never
  queues another.
- Logs go to the journal: `journalctl --user -u song-study-update`.

Add `.deploy-state/` to `.gitignore`.

### Local check

macOS has no systemd, so this checks the script directly; the operator
checks the units on the VM (step 10 of "Initial deploy"). Don't use the main checkout
or GitHub: other sessions share the checkout, and test commits mustn't be
pushed.

1. In the scratchpad, make a bare repo whose `main` is this branch's head,
   to stand in for GitHub, and two clones of it: one standing in for the
   VM's clone, and one to push test commits from.
2. Export `COMPOSE_PROJECT_NAME=song-study-deploycheck`,
   `DEPLOY_PG_PORT=15433` and `DEPLOY_ENV_FILE` pointing at step 1's check
   env file (`APP_URL=http://localhost`), and run every command from the
   VM clone.
3. Check each of these, using `status` and `curl http://localhost` to see
   what's running. A change to the `<title>` in `frontend/index.html` makes
   each commit easy to tell apart.
   - The first run deploys `main`. A second run does nothing.
   - A pushed commit is deployed by the next run.
   - While paused, a run deploys nothing. `resume` deploys.
   - `pin` an earlier commit: it's deployed, and a run after a new push
     stays on it. `unpin`, and the next run deploys `main`'s head.
   - `pin` a commit that isn't on `main` is refused without `--unmerged`.
   - A commit whose backend fails at import: the run rolls back, the old
     title is still served, the state is paused with the reason, and the
     exit status is non-zero.
   - A commit that adds an empty migration and also breaks the backend: no
     rollback, paused.
   - After a commit with an empty migration deploys, `pin` the commit
     before it: refused, nothing changes. Then downgrade the database by
     hand (`alembic downgrade -1` in the backend container, standing in for
     a restore) and `pin --db-restored` the same commit: it deploys.
   - A commit that edits `update.sh` near its top deploys cleanly.
   - A run started while another holds the lock exits at once.
   - With `DEPLOY_NOTIFY_URL` pointing at a local `nc -l` listener, a
     deploy and a failure each send one line.
4. Run `docker compose ... down -v` with the same project name, then
   delete the scratch repos.

## Step 3 — Backup script

**`deploy/backup.sh`**, run from the repo root on the VM:

- Dumps with `docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"` into
  `backups/song_study-<UTC date>.dump`. `backups/` is gitignored.
- Fails loudly with `set -euo pipefail`. A failed `pg_dump` must not leave a
  dump file that looks valid.
- Deletes local dumps older than 14 days.
- If `BACKUP_BUCKET` is set, copies the new dump there with `gcloud storage cp`. Choosing where backups go is a value: after a move to another host,
  only that line changes.
- Reads `POSTGRES_USER` and `POSTGRES_DB` from the same env file as compose.

**Restore,** documented at the top of the script: `pg_restore --clean
--if-exists -d <db>` from the dump, run with `docker compose ... exec -T
postgres`.

**Before a migration:** `update.sh` runs `backup.sh` before its checkout
whenever the target adds a file under `backend/migrations/versions/`
(the same `--diff-filter=A` test it uses to decide on a rollback). If the
backup fails, the deploy doesn't happen, and the script pauses with the
reason. Until this step merges, auto-deploy applies migrations without a
backup, as the manual update did.

**Check** it against the step 1 local stack, not the dev database:

- Run the script, then restore the dump into a scratch database
  (`createdb song_study_restorecheck`) in the same container.
- Compare row counts for `documents`, `tokens` and `study_cards`.
- Drop the scratch database.
- With step 2's local check setup, push a commit adding an empty
  migration: the run takes a dump before deploying. Make `backup.sh` fail
  (an unset `POSTGRES_DB`, say) and push another migration: nothing is deployed and the
  state is paused.

## Initial deploy (operator)

These steps need your accounts, DNS and judgment, so you do them by hand.
Steps 1–7 don't depend on the repo, so they can happen while build step 1
is being built. Step 8 onward needs build step 1 merged, step 10 needs
build step 2, and step 11 needs build step 3. Build step 3 can wait while
you're the only user, but merge it before inviting anyone.

### Decide first

- **The hostname,** such as `songs.example.com`, on a domain you control.
  Steps 3, 6 and 7 all use it. It has to be a hostname of its own, not a
  path like `example.com/song-study`: the app is served from `/`, and Caddy
  site addresses can't carry a path.
- **The OAuth client:** reuse the dev client and add the prod redirect URI,
  which is simplest, or create a separate client for prod so its secret
  isn't shared with dev.
- **Where backups go.** A Cloud Storage bucket needs the VM's Storage access
  scope set to Read Write **when the VM is created** (step 2). Changing it
  later means stopping the VM.
- **Whether to copy your local data across** (step 12) or start with an
  empty database. Copy it before inviting anyone, since the restore
  replaces the whole database.

The Google Cloud free tier's terms change. Check the current free-tier page
before creating anything; what's below is how it stood when this was
written.

### 1. Google Cloud project and billing

1. Reuse the project that holds the OAuth client, or create a new one.
2. Turn on billing. Google requires a card even for free-tier use.
3. **Set a budget alert first:** Billing → Budgets & alerts, with $1–2 and
   email alerts. If any setting falls outside the free tier, this is how
   you'll find out.
4. Enable the Compute Engine API.

### 2. The VM

Go to Compute Engine → VM instances → Create instance:

| Setting       | Value                                                                                                                                                                                                            |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Region        | `us-west1`, `us-central1` or `us-east1` (only these are free)                                                                                                                                                    |
| Machine type  | E2 → **`e2-micro`**                                                                                                                                                                                              |
| Boot disk     | Debian 12, Debian 13 (amd64; the first deploy used it, and Docker's install script in step 4 supports it) or Ubuntu 24.04 LTS, disk type **Standard persistent disk** (the default "Balanced" isn't free), 30 GB |
| Firewall      | Tick **Allow HTTP traffic** and **Allow HTTPS traffic**                                                                                                                                                          |
| Access scopes | Set **Storage** to **Read Write** if backups will go to a Cloud Storage bucket. Changing this later means stopping the VM                                                                                        |

The cost estimate on the page may show a monthly price anyway. The free
tier is credited on the bill, and the budget alert is the real check.

Then go to VPC network → IP addresses and **promote the VM's external
address to static**. Otherwise it can change when the VM stops, and DNS
would point at the wrong place. Watch the first few days of billing for an
IP address charge.

### 3. Domain

At your DNS provider, add an **A record** for the hostname, such as
`songs.example.com`, pointing at the static IP. Caddy can't get a
certificate until this resolves, so check with `dig +short
songs.example.com`.

### 4. Prepare the machine

SSH in with the console's **SSH** button or `gcloud compute ssh <vm>`.

```bash
# Swap, so building the images doesn't run out of memory on 1 GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Automatic security updates
sudo apt update && sudo apt install -y unattended-upgrades git
sudo dpkg-reconfigure -plow unattended-upgrades

# Docker and the Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in for this to apply
```

### 5. Clone the repo

The repo is private, so give the VM a **read-only deploy key**:

```bash
ssh-keygen -t ed25519 -C song-study-vm -f ~/.ssh/id_ed25519 -N ''
cat ~/.ssh/id_ed25519.pub
```

Add the public key under the repo's Settings → Deploy keys, leaving write
access off. Then run `git clone git@github.com:DT-1236/song-study.git`.

### 6. Google OAuth

In the Cloud console under APIs & Services:

- **Credentials:** add `https://songs.example.com/api/auth/callback` to the
  OAuth client's authorized redirect URIs. You can reuse the dev client or
  create a separate one for the deployment.
- **OAuth consent screen:** leave it in **Testing** and add each user's
  Google account under **Test users**.

### 7. `.env` on the VM

In the clone's root, write a `.env` following `.env.example`'s deployment
section:

- `APP_URL=https://songs.example.com`
- `POSTGRES_USER`, `POSTGRES_DB`, and a strong `POSTGRES_PASSWORD`, which
  you can generate with `openssl rand -base64 24`.
- `DATABASE_URL=postgresql+psycopg2://<user>:<password>@postgres:5432/<db>`
- `SESSION_SECRET`, from `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep it stable: changing it signs
  everyone out.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

Run `chmod 600 .env`. Keep a copy of it somewhere safe off the VM, such as
a password manager, because a move to another host needs it.

### 8. Start it

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f   # Ctrl-C to stop following
```

The first build took about 30 minutes on an e2-micro, and the output goes
quiet while the backend's `pip install` unpacks the dictionaries. Watch for
the backend's migrations finishing and Caddy reporting that it got a
certificate.

If Caddy's log says `Timeout during connect (likely firewall problem)`, the
internet can't reach ports 80 and 443. On the VM, `sudo ss -tlnp | grep -E
':(80|443)\b'` should show Docker listening; if it does, the block is Google's
firewall. The VM needs the `http-server` and `https-server` network tags,
and the VPC has to have `default-allow-http` and `default-allow-https` rules
for them. Caddy retries by itself once they're right.

### 9. Check it

- `https://songs.example.com` loads with a valid certificate.
- A test user can sign in. An account that isn't a test user is refused by
  Google's consent screen.
- Creating a document gives it furigana and glosses.
- In the browser's dev tools, the session cookie is marked `Secure`.
- `docker compose -f docker-compose.prod.yml restart backend` keeps you
  signed in.

### 10. Auto-deploy (after build step 2)

1. `git pull` once by hand, so the clone has `deploy/update.sh` and its
   units.
2. Optionally, set `DEPLOY_NOTIFY_URL` in `.env`, such as
   `https://ntfy.sh/<topic>` with a long random topic: anyone who guesses an
   ntfy.sh topic can read it. Subscribe to it in the ntfy app.
3. Install the units and start the timer:

   ```bash
   loginctl enable-linger $USER   # user units keep running with no SSH session open
   systemctl --user link ~/song-study/deploy/systemd/song-study-update.{service,timer}
   systemctl --user enable --now song-study-update.timer
   systemctl --user list-timers   # shows the next run
   ```

4. Run `./deploy/update.sh` once by hand. With nothing recorded as
   deployed yet, it deploys `main`'s head, which Docker's cache makes quick,
   and records it.
5. Merge a small change, then watch it arrive:
   `journalctl --user -u song-study-update -f`, and `./deploy/update.sh
status` afterwards.

### 11. Backups (after build step 3)

- If backups go to a bucket, create one in the VM's region (Cloud Storage's
  free tier is 5 GB in the same US regions) and set `BACKUP_BUCKET` in
  `.env`.
- Add a nightly cron entry with `crontab -e`:

  ```
  15 3 * * * cd ~/song-study && ./deploy/backup.sh >> backups/backup.log 2>&1
  ```

- The day after, check that a dump exists, and restore one into a scratch
  database once, as in build step 3's check. A backup you haven't restored
  isn't known to work.

### 12. Copy your local data across (optional)

Pause auto-deploy first (`./deploy/update.sh pause "restoring local data"`),
so a deploy doesn't restart the backend mid-restore, and resume after.

To start with the documents already in your local database, dump it
locally. This only reads from it:

```bash
docker compose exec -T postgres pg_dump -U song_study -Fc song_study > song_study.dump
```

Copy the file up with `gcloud compute scp`. On the VM, stop the backend,
restore with `pg_restore --clean --if-exists`, then start the backend
again. Users and their `google_sub` come across too, so you stay the same
user as long as you sign in with the same Google account.

## Updating (operator)

Once step 10 is done, a merge to `main` is deployed within about five
minutes, with nothing to do. The commands below run from the clone on the
VM, or from the laptop over `gcloud compute ssh`. The script owns the
clone's checkout, so don't `git pull` or `git checkout` there by hand.

- **Where things stand:** `./deploy/update.sh status`.
- **Hold deploys:** `./deploy/update.sh pause "why"`, then `resume`.
- **Deploy a particular commit:** `./deploy/update.sh pin <commit>`. It
  stays there until `unpin`, which goes back to following `main`.
- **Deploy now,** rather than waiting for the timer: `./deploy/update.sh`.
- **A failed deploy** rolls back if it added no migration, and pauses
  either way. Read the reason in `status` and the journal, then merge a fix
  and `resume`, or `pin` a commit that works.
- **Migrations** run on their own when the backend starts, and after build
  step 3, `update.sh` takes a backup first. Rolling the code back doesn't
  undo a migration that has already been applied.
- **Rolling back:** `./deploy/update.sh pin <previous commit>`. If a
  migration ran in between, the script refuses. Restore the backup taken
  before that deploy instead (the restore notes are at the top of
  `deploy/backup.sh`), then `pin --db-restored <commit>`, which skips that
  one check. Pause first, so the timer doesn't redeploy `main` and re-run
  the migration while you restore.
- **Downtime** is a few seconds while the backend restarts, plus the
  dictionaries loading on the first request. Sessions survive, since
  `SESSION_SECRET` doesn't change.
- **Logs:** `journalctl --user -u song-study-update` for deploys;
  `docker compose -f docker-compose.prod.yml logs -f backend`, or `caddy`
  for certificate and proxy errors.
- **Changes to `.env`** need `docker compose -f docker-compose.prod.yml up
-d`, not just a restart, so the containers are recreated with the new
  values. The script only redeploys when the commit changes.
- **Changes to the unit files** need `systemctl --user daemon-reload` after
  they deploy. The links point into the clone, so the new files are already
  in place.

## Debugging against prod (operator)

Both of these work against real users' data. Use them to look around, not
to try out unmerged changes. To test changes against realistic data,
restore a backup into a separate local database instead (not the dev
database and not `song_study_test`) and point a local backend at it with
`DATABASE_URL`.

### The local frontend against the prod backend

1. Run `API_PROXY_TARGET=https://songs.example.com npm run dev` in
   `frontend/`.
2. **Signing in through it doesn't work.** Google returns to the prod
   `APP_URL`, which can't see the sign-in state stored in the localhost
   cookie. Copy a session across instead:
   1. Sign in on `https://songs.example.com`.
   2. Open dev tools → Application → Cookies and copy the `session` cookie's
      value.
   3. Under `http://localhost:5173`, create a cookie named `session` with
      that value.

   Dev tools can edit it even though it's `HttpOnly`. Use Chrome, Brave or
   Firefox, which accept a `Secure` cookie on `http://localhost`. Safari
   doesn't.

3. The copied session lasts until it expires or `SESSION_SECRET` changes.

Your local frontend code is what's running. If it expects an API change
that isn't deployed yet, its writes can be accepted by prod and still be
wrong, so stick to reading.

### A connection string for the prod database

Postgres is published only on the VM's loopback interface, so you reach it
through an SSH tunnel, as a role that can only read.

**Once: create the read-only role.** On the VM, open a shell in the
database:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U <POSTGRES_USER> <POSTGRES_DB>
```

Then run this, with a password from `openssl rand -base64 24`:

```sql
CREATE ROLE debug_ro LOGIN PASSWORD '<password>';
GRANT CONNECT ON DATABASE <POSTGRES_DB> TO debug_ro;
GRANT USAGE ON SCHEMA public TO debug_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO debug_ro;
-- Tables added by later migrations, which run as the owner role
ALTER DEFAULT PRIVILEGES FOR ROLE <POSTGRES_USER> IN SCHEMA public
  GRANT SELECT ON TABLES TO debug_ro;
```

Keep the password in your password manager. It lives in the database volume,
so it moves with a dump.

**Each time: open the tunnel** from your laptop and leave it running:

```bash
gcloud compute ssh <vm> --zone <zone> -- -N -L 15432:127.0.0.1:5432
```

Local port 15432 keeps clear of the dev database on 5544 and of any local
Postgres on 5432.

**The connection string**, while the tunnel is open:

- psql, or a GUI such as TablePlus or DBeaver:
  `postgresql://debug_ro:<password>@localhost:15432/<POSTGRES_DB>`
- SQLAlchemy, for a Python REPL or a script:
  `postgresql+psycopg2://debug_ro:<password>@localhost:15432/<POSTGRES_DB>`

**Don't put it in the repo's `.env`:**

- `make start` runs migrations against `DATABASE_URL`, so a local backend
  pointed at prod would apply your branch's unmerged migrations. The
  read-only role would make them fail, but don't rely on that.
- `TEST_DATABASE_URL` is dropped and re-created on every test run.

Use a shell variable for the session instead.

**Changing prod data** is a separate, deliberate act:

1. Run `./deploy/backup.sh` first.
2. Make the change on the VM as the owner role, through the `docker compose exec ... psql` above, inside a `BEGIN` … `COMMIT`.

**Rows copied out of prod** follow AGENTS.md's fixture rules: nothing that
contains lyrics goes into `backend/tests/fixtures/`.

## Moving to a paid VPS later

1. Set up the new VM with steps 4, 5 and 7, using the same `.env`.
2. A day ahead, lower the DNS record's TTL to a few minutes.
3. Pause auto-deploy on the old VM, stop its backend, take a dump, copy it
   across, and restore it on the new VM.
4. Start the new stack and point the A record at the new IP address. Caddy
   gets a certificate on its own.
5. Once it works, set up auto-deploy on the new VM (step 10), and delete
   the old VM.

The redirect URI, test users and sessions all carry over, since the domain
and `SESSION_SECRET` stay the same. Only `BACKUP_BUCKET`'s copy line needs
replacing if the new host isn't Google Cloud.
