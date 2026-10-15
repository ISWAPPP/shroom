# Shroom — multi-user web portal for Hermes Agent

Shroom is a self-hosted web portal that lets several people chat with a real
[Hermes agent](https://github.com/NousResearch/hermes-agent) installation through a browser.
Each portal user is bound to a Hermes profile, so every user gets their own agent home (configuration,
sessions, memory, skills) while an administrator controls what each user may do.

The portal does not reimplement the agent: chats are served by the native Hermes TUI gateway
(`hermes --run-module tui_gateway.entry`), one process per profile, behind a narrow bridge.

The user interface is in Ukrainian.

## Features

Chat

- Chats are stored as Hermes sessions of the user's profile; the portal keeps its own index of dialogs, turns and
  usage in a separate SQLite database.
- Streaming answers with an activity view of tool calls, approval and clarification requests answered in the
  browser, stop/interrupt, edit and regenerate, undo/rewind, side questions and background prompts.
- Native slash commands (completion and execution through Hermes), filtered by the user's permissions.
- Per-chat model and reasoning-effort switch among the providers connected to the profile.
- Attachments: UTF-8 text files up to 2 MiB and PNG/JPEG/WebP images up to 10 MiB, with a per-user storage quota.
  Files produced in chats are listed in a files ("artifacts") view.
- Full-text search across the user's chats, pinning, renaming.
- Read-only share links for a chat; a recipient can copy a shared chat into their own account.
- Scheduled jobs: Hermes runs a task on a schedule and posts the report into a chat (per-user limits on job count
  and minimum interval).
- Installable as a PWA (web manifest and service worker); several colour themes.

Users and permissions

- Password login (Argon2 hashes), optional TOTP two-factor authentication, login throttling.
- Roles `admin` and `user`. The main Hermes profile (`default`) is reserved for admins.
- Permission keys `cmd:<name>`, `skill:<name>`, `provider:<slug>` and `feature:<name>`, with wildcards.
  Deny by default; resolution order: user exact > role exact > user wildcard > role wildcard; admins have everything.
  Features include own subscriptions, own skills, own plugins, model switching, editing the profile's SOUL.md and
  MEMORY.md/USER.md, scheduled jobs, and a Cursor Agent key.
- Admins can impersonate a user (password and 2FA changes are blocked while impersonating).

Profiles, models and subscriptions

- Admins create and delete Hermes profiles, set their model, choose enabled tools and plugins, edit profile
  documents and memory settings, and start/stop/restart each profile's bridge.
- Users can connect their own AI subscriptions to their profile: API keys, or OAuth login for providers that support
  it. Usage on a user's own key is excluded from portal spending limits.
- Monthly USD spending limits per user and per profile, based on per-turn usage reported by Hermes.

Skills

- A shared, admin-curated skill library at `/root/.hermes/shared-skills`, mounted into profiles through the native
  `skills.external_dirs` setting. An optional timer commits library changes to git.
- Per-profile enable/disable of skills; personal (agent-created) skills can be promoted to the shared library.

Sandbox

- Per-profile Docker sandbox using the native Hermes `terminal.backend: docker`. Terminal, file and code tools are
  refused for a profile unless its sandbox is enabled; plugins can only be enabled for sandboxed profiles.

Administration

- Overview (active responses, online users, stopped bridges, monthly cost, failed logins, denied commands),
  host load and per-service resource usage, usage and limits, and an audit log of auth, user, permission, profile,
  skill, subscription, limit, command and turn events with client IP.

## Architecture

```
browser ──HTTPS──> proxy (nginx) ──> frontend (nginx serving the React build)
                        │
                        └── /api/ ──> backend (FastAPI) ── data/portal.db, data/files
                                          │
                                          │ HTTP over Unix sockets in bridge-ipc/ (Bearer token = bridge.key)
                     ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ host (systemd, root) ─ ─ ─
                                          ├── hermes-web-bridge.service         -> profile "default"
                                          ├── hermes-web-bridge@<profile>.service -> other profiles
                                          │       each: bridge.py -> hermes --run-module tui_gateway.entry
                                          └── hermes-web-admin.service          -> admin_host.py (profile_admin.py ops)
```

Docker Compose (`compose.yaml`):

- `proxy` (`hermes-web-proxy`): official nginx image, ports 80 and 443, TLS termination, security headers,
  ACME HTTP-01 webroot. Its configuration is `nginx/default.conf.template`, rendered at container start by the
  image's built-in envsubst with `PORTAL_HOST`.
- `frontend` (`hermes-web-frontend`): React 19 + TypeScript + Vite, built in a multi-stage Dockerfile and served by
  an internal nginx. No published ports.
- `backend` (`hermes-web-backend`): FastAPI/uvicorn on Python 3.12, runs as UID 10001 with a read-only root
  filesystem, all capabilities dropped and no published ports. It owns the portal database `data/portal.db`
  (users, sessions, dialogs, turns, permissions, audit, usage, limits), which is separate from Hermes' own
  `state.db`. It mounts `bridge-ipc/` read-only and `bridge.key` as a secret.
- `certbot`: only in the `maintenance` profile; used to issue and renew certificates into `letsencrypt/`.

Host side (systemd, run as root, working directory `/srv/hermes-web`):

- `bridge.py`: one process per profile. `hermes-web-bridge.service` serves the `default` profile;
  the template `hermes-web-bridge@<profile>.service` serves any other profile (`PORTAL_PROFILE=%i`).
  Each bridge starts `hermes --run-module tui_gateway.entry` with that profile's `HERMES_HOME`, exposes a fixed
  allowlist of JSON-RPC methods on `bridge-ipc/bridge.sock` or `bridge-ipc/bridge-<profile>.sock`
  (socket mode `0660`, group 10001), and forces a managed policy from `managed-policy/config.yaml`
  (manual approvals, empty command allowlist, secret redaction). It refuses to start if that policy is not in effect.
- `admin_host.py` (`hermes-web-admin.service`): runs the host operations in `profile_admin.py` (profile
  create/delete, model and tool configuration, skills, credentials, bridge control, scheduled jobs) on
  `bridge-ipc/admin.sock`. It holds no Hermes agent and reloads `profile_admin.py` automatically when the file changes.
- Timers: certificate renewal (`hermes-web-cert-renew.timer` -> `renew.sh`), daily backup, and the optional shared
  skill library autocommit.

## Requirements

- A Linux host with systemd, Docker Engine and the Docker Compose plugin.
- Hermes installed for root at the standard locations used by the code: launcher `/root/.local/bin/hermes`,
  source `/root/.hermes/hermes-agent`, home `/root/.hermes` with a `/root/.hermes/.env` file (read by the owner
  bridge and the admin service). At least one model provider must be configured in Hermes.
- `python3` on the host (bridges, admin service, backup, test helpers).
- A public hostname or IP address with ports 80 and 443 reachable for certificate issuance.
- `git` on the host if you use the shared skill library autocommit.
- Docker images for the sandbox are pulled by Hermes when a profile's sandbox is enabled (default image
  `nousresearch/hermes-sandbox:desktop`).

## Installation

All commands run as root. The install path `/srv/hermes-web` is hardcoded in the systemd units, `bridge.py`,
`renew.sh` and several helper scripts; use exactly this path.

1. Get the code:

   ```sh
   git clone <repository-url> /srv/hermes-web
   cd /srv/hermes-web
   ```

2. Create the shared bridge token, the IPC directory and the data directory:

   ```sh
   umask 077
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > bridge.key
   chown root:10001 bridge.key && chmod 0640 bridge.key
   mkdir -p bridge-ipc data
   chown 10001:10001 bridge-ipc data && chmod 0750 bridge-ipc data
   ```

   The backend (UID 10001) must be able to read `bridge.key` and reach the sockets in `bridge-ipc/`.

3. Configure the portal:

   ```sh
   cp .env.example .env
   # edit PORTAL_HOST and PORTAL_ORIGIN
   ```

4. Obtain a TLS certificate. The proxy expects `letsencrypt/live/$PORTAL_HOST/fullchain.pem` and `privkey.pem`.
   Before the proxy is running, port 80 is free, so the first certificate can be issued with the certbot
   maintenance service in standalone mode:

   ```sh
   . ./.env
   docker compose run --rm -p 80:80 certbot certonly --standalone \
     -d "$PORTAL_HOST" --cert-name "$PORTAL_HOST"
   ```

   Renewals run through `renew.sh` (`docker compose run --rm certbot renew`) while the proxy is up, so switch the
   certificate to the webroot authenticator once step 6 is done:

   ```sh
   docker compose run --rm certbot certonly --webroot -w /var/www/acme \
     -d "$PORTAL_HOST" --cert-name "$PORTAL_HOST" --force-renewal \
     --deploy-hook 'touch /etc/letsencrypt/.proxy-reload-required'
   ```

   `renew.sh` reloads nginx when it finds `letsencrypt/.proxy-reload-required`. If you use a bare IP address,
   check the current Let's Encrypt and certbot documentation for IP address certificates.

5. Link and enable the host services:

   ```sh
   systemctl link /srv/hermes-web/deploy/systemd/hermes-web-bridge.service \
                  /srv/hermes-web/deploy/systemd/hermes-web-bridge@.service \
                  /srv/hermes-web/ops/hermes-web-admin.service \
                  /srv/hermes-web/deploy/systemd/hermes-web-cert-renew.service \
                  /srv/hermes-web/deploy/systemd/hermes-web-cert-renew.timer
   systemctl enable --now hermes-web-bridge.service hermes-web-admin.service hermes-web-cert-renew.timer
   ```

   Bridges for additional profiles (`hermes-web-bridge@<profile>.service`) are enabled and started by the portal
   when an admin creates a profile or starts its bridge.

6. Build and start the containers:

   ```sh
   docker compose up -d --build
   ```

7. Create the first admin account (prints a generated password once):

   ```sh
   docker exec hermes-web-backend python app.py create-user admin admin default
   ```

   Sign in at `https://$PORTAL_HOST/`. Further users and profiles are managed in the settings window.

Optional:

- Backups: `ops/hermes-web-backup.{service,timer}` run `ops/hermes-web-backup` installed as
  `/usr/local/sbin/hermes-web-backup`; it writes to `/srv/hermes-web-backups/daily` (SQLite snapshot, code tree,
  shared skill library), keeps 14 days, and is the location reported in the admin overview. Hermes profile data is
  not included; back it up with Hermes' own tools (`hermes backup`, `hermes profile export`).
- Shared skill library history: create `/root/.hermes/shared-skills` as a git repository, install
  `ops/shared-skills-autocommit` as `/usr/local/sbin/shared-skills-autocommit`, and link/enable
  `ops/shared-skills-autocommit.{service,timer}` (commits changes every 5 minutes).

## Configuration

`.env` in the project root (read by Docker Compose):

| Variable        | Example                       | Purpose |
|-----------------|-------------------------------|---------|
| `PORTAL_HOST`   | `portal.example.com`          | Public hostname or IP. nginx `server_name` and certificate directory `letsencrypt/live/$PORTAL_HOST/`. |
| `PORTAL_ORIGIN` | `https://portal.example.com`  | Allowed `Origin` for state-changing API requests. The acceptance tests use it as their `Origin` header. |

Other configuration:

- `nginx/default.conf.template`: proxy configuration, rendered by the nginx image's envsubst at start.
- `managed-policy/config.yaml`: managed Hermes policy enforced on every bridge (`HERMES_MANAGED_DIR`).
- `/root/.hermes/.env`: Hermes provider settings for the owner bridge and the admin service.
- Everything else (users, roles, permissions, limits, profiles, models, tools, plugins, sandbox, skills) is
  configured in the portal's settings window by an admin.

After changing `bridge.py`, restart the bridges; `ops/restart-bridges-when-idle` restarts each bridge once its
profile has no running turn. `profile_admin.py` changes are picked up by the admin service without a restart.

## Tests

Acceptance tests (`tests/acceptance/*_acceptance.py`) exercise the running portal end to end:

```sh
tests/run_all.sh            # full suite
tests/run_all.sh perms cmd  # selected tests by name
```

- They run inside the backend container against the proxy and need a running installation.
- Credentials come from root-only files `secrets/<username>.json` of the form `{"password": "..."}`; they are passed
  on stdin and never printed. The suite uses an `admin` account and a `tester` account; many tests use a profile
  named `webtest`.
- They make real LLM calls through Hermes, which are billable.
- The runner refuses to start while any portal response is active, because some tests restart bridges.
- Output is written to `tests/<name>_acceptance.txt`; chats left in the `tester` account are cleaned up.

UI component checks (`tests/ui/run.sh`) render selected React components in jsdom; they need Node.js and
`npm ci` in `frontend/`, and never contact the portal.

`scripts/format.sh` formats the frontend (Prettier) and the Python sources (Black) in throwaway containers.

## Security notes

- Bridges and the admin service run as root on the host. They hold every profile's Hermes home and provider
  credentials. The backend container reaches them only through the Unix sockets in `bridge-ipc/` with the
  `bridge.key` token and a fixed RPC/operation allowlist.
- Hermes plugin code runs inside the bridge process, that is, as root on the host. The Docker sandbox isolates only
  the terminal, file and code tools. Enable plugins only for profiles and code you trust.
- Users with the same profile share that profile's agent home, memory and skills.
- Restrict access to port 443 with a host firewall (for example to known source addresses). Port 80 is needed only
  for ACME challenges and redirects.
- Never commit or publish `secrets/`, `bridge.key`, `.env`, `data/`, `letsencrypt/`, backups or bridge logs.
  `data/` contains the user database, sessions and uploaded files.

## License

MIT. See [LICENSE](LICENSE).
