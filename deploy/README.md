# Running song-study on a VM

The operator's runbook: the first deploy, updating, debugging against prod,
and moving to another host. The stack is `docker-compose.prod.yml` at the
repo root (postgres, a one-shot `migrate`, the backend, and Caddy serving the
frontend), configured by a `.env` that follows `.env.example`'s deployment
section. This folder holds the rest of the deployment files.

This describes what's on `main`. A PR that changes what the operator does
updates this file too.

## Initial deploy

These steps need your accounts, DNS and judgment, so you do them by hand.

### Decide first

- **The hostname,** such as `songs.example.com`, on a domain you control.
  Steps 3, 6 and 7 all use it. It has to be a hostname of its own, not a
  path like `example.com/song-study`: the app is served from `/`, and Caddy
  site addresses can't carry a path.
- **The OAuth client:** reuse the dev client and add the prod redirect URI,
  which is simplest, or create a separate client for prod so its secret
  isn't shared with dev.
- **Where backups will go.** A Cloud Storage bucket needs the VM's Storage
  access scope set to Read Write **when the VM is created** (step 2).
  Changing it later means stopping the VM.
- **Whether to copy your local data across** (step 10) or start with an
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

### 10. Copy your local data across (optional)

To start with the documents already in your local database, dump it
locally. This only reads from it:

```bash
docker compose exec -T postgres pg_dump -U song_study -Fc song_study > song_study.dump
```

Copy the file up with `gcloud compute scp`. On the VM, stop the backend,
restore with `pg_restore --clean --if-exists`, then start the backend
again. Users and their `google_sub` come across too, so you stay the same
user as long as you sign in with the same Google account.

## Updating

From the clone on the VM:

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker image prune -f   # old images add up fast on a 30 GB disk
```

- **Migrations** run on their own when the backend starts. Rolling the
  code back doesn't undo a migration that has already been applied, so if
  the update includes one (a file under `backend/migrations/versions/`),
  take a dump first:

  ```bash
  docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U <POSTGRES_USER> -Fc <POSTGRES_DB> > ~/song_study-$(date -u +%F).dump
  ```

- **Rolling back:** `git checkout <previous commit>`, then the same `up -d
--build`. If a migration ran in between, restore the dump taken before
  the update instead of relying on the old code to run against the new
  schema.
- **Downtime** is a few seconds while the backend restarts, plus the
  dictionaries loading on the first request. Sessions survive, since
  `SESSION_SECRET` doesn't change.
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f backend`, or
  `caddy` for certificate and proxy errors.
- **Changes to `.env`** need `up -d`, not just a restart, so the containers
  are recreated with the new values.

## Debugging against prod

Both of these work against real users' data. Use them to look around, not
to try out unmerged changes. To test changes against realistic data,
restore a dump into a separate local database instead (not the dev
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

1. Take a dump first, as under "Updating".
2. Make the change on the VM as the owner role, through the `docker compose exec ... psql` above, inside a `BEGIN` … `COMMIT`.

**Rows copied out of prod** follow AGENTS.md's fixture rules: nothing that
contains lyrics goes into `backend/tests/fixtures/`.

## Moving to another host

1. Set up the new VM with steps 4, 5 and 7, using the same `.env`.
2. A day ahead, lower the DNS record's TTL to a few minutes.
3. Stop the old backend, take a dump, copy it across, and restore it on the
   new VM.
4. Start the new stack and point the A record at the new IP address. Caddy
   gets a certificate on its own.
5. Once it works, delete the old VM.

The redirect URI, test users and sessions all carry over, since the domain
and `SESSION_SECRET` stay the same.
