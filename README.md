# Cadence

A self-hosted task and issue tracker built with Python, Flask, HTMX, and SQLite.

## Features

- **Gatekeeper SSO authentication** - passwordless login via [Gatekeeper](../gatekeeper/) centralised SSO
- **Task management** - create, track, and manage tasks with status workflows
- **Comments & attachments** - with automatic file deduplication
- **Activity logging** - immutable audit trail of all changes
- **Notifications** - email and ntfy support
- **Dark mode** - system/light/dark theme toggle

## Quick Start

Requires Python 3.14+, [uv](https://docs.astral.sh/uv/), and a [Gatekeeper](../gatekeeper/) instance.

```bash
# Install dependencies
make sync

# Create a blank database
make init-db

# Point Cadence at your Gatekeeper database (for authentication)
export GATEKEEPER_DB=/path/to/gatekeeper/instance/gatekeeper.sqlite3

# Grant admin privileges to a Gatekeeper user
.venv/bin/cadence-admin make-admin jsmith

# Start the development server
make rundev
```

The app will be available at http://127.0.0.1:5000. Users log in via Gatekeeper's centralised SSO page (requires `server.login_url` to be set in Gatekeeper — see below).

### Database location

By default the database is created at `instance/cadence.sqlite3` relative to the project root. Set the `CADENCE_DB` environment variable to override:

```bash
export CADENCE_DB=/data/cadence.sqlite3
```

The resolution order is:

1. `CADENCE_DB` environment variable (if set)
2. Flask `DATABASE_PATH` config (when running inside the web server)
3. `instance/cadence.sqlite3` relative to the source tree (fallback)

All CLI commands (`cadence-admin`, `make config-*`, `make init-db`) and the web server use the same resolution logic — set `CADENCE_DB` once and everything finds the database.

### Gatekeeper authentication

Cadence uses [Gatekeeper](../gatekeeper/) for all authentication. Set `GATEKEEPER_DB` to the path of the Gatekeeper SQLite database:

```bash
export GATEKEEPER_DB=/path/to/gatekeeper/instance/gatekeeper.sqlite3
```

Cadence reads the database in local mode (direct SQLite access, no network calls) for per-request session validation.

For login to work, Gatekeeper must have `server.login_url` configured (see the [Gatekeeper README](../gatekeeper/README.md#centralised-sso-login)). Unauthenticated users are redirected to Gatekeeper's login page, which sends a magic link via outbox. The magic link redirects back to Cadence's `/auth/verify` endpoint, which validates the token and sets a session cookie.

User preferences (display name, email notifications, ntfy topic, admin status) are stored in Gatekeeper's `user_property` table with app `"cadence"`. Grant admin access with:

```bash
.venv/bin/cadence-admin make-admin USERNAME
```

## Docker Deployment

The `docker-compose.yml` joins a shared Docker network (`platform-net`) for use behind a reverse proxy.

The Gatekeeper database is mounted read-only into the container via `GATEKEEPER_DB_PATH` (defaults to `../gatekeeper/instance/gatekeeper.sqlite3`).

```bash
# First time only — initialize the database
docker compose --profile init up init

# Build and start
docker compose build
docker compose up -d
```

### Services

| Service | Description |
|---------|-------------|
| `app` | Flask application (port 5000 on platform-net) |
| `worker` | Background notification worker |
| `init` | One-time database initialization (profile: init) |

### Data Persistence

All persistent data is stored in the `cadence-data` Docker volume:
- `cadence.sqlite3` - Database (including all configuration)
- `blobs/` - File attachments
- `backups/` - Database backups

### Running without Docker

When running behind a reverse proxy, enable proxy header support:

```bash
make config-set KEY=proxy.x_forwarded_for VAL=1
make config-set KEY=proxy.x_forwarded_proto VAL=1
make config-set KEY=proxy.x_forwarded_host VAL=1
```

Run the app and worker:
```bash
make run      # Start Flask app
make worker   # Start notification worker (separate terminal)
```

## Makefile reference

| Target | Description |
|---|---|
| `make sync` | Install/sync dependencies with uv |
| `make init-db` | Create a blank database |
| `make run` | Start production server (HOST:PORT) |
| `make rundev` | Start development server (DEV_HOST:DEV_PORT, debug mode) |
| `make worker` | Start the notification worker |
| `make config-list` | Show all configuration settings |
| `make config-set KEY=... VAL=...` | Set a configuration value |
| `make config-import FILE=...` | Import settings from an INI file |
| `make config-export FILE=...` | Export all settings as a shell script |
| `make check` | Run ruff (format + lint) and ty (type check) |
| `make clean` | Remove bytecode and the database file |

## CLI commands

The `cadence-admin` CLI provides the same operations outside of Make:

```
cadence-admin init-db                # Initialize the database schema
cadence-admin make-admin USERNAME    # Grant cadence admin privileges to a Gatekeeper user
cadence-admin list-users             # List all known users (from Gatekeeper)
cadence-admin config list            # Show settings
cadence-admin config get KEY         # Get a single setting
cadence-admin config set KEY VAL     # Set a setting
cadence-admin config import FILE     # Import from INI
cadence-admin config export FILE     # Export all settings as a shell script
```

## Configuration reference

All settings are stored in the SQLite database (`app_setting` table) and managed via `make config-set` or `cadence-admin config set`. Use `make config-list` to see current values.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.host` | string | `0.0.0.0` | Bind address for production server |
| `server.port` | int | `5000` | Port for production server |
| `server.dev_host` | string | `127.0.0.1` | Bind address for dev server |
| `server.dev_port` | int | `5000` | Port for dev server |
| `server.debug` | bool | `false` | Enable Flask debug mode |
| `mail.smtp_server` | string | | SMTP server hostname |
| `mail.smtp_port` | int | `587` | SMTP server port |
| `mail.smtp_use_tls` | bool | `true` | Use TLS for SMTP |
| `mail.smtp_username` | string | | SMTP authentication username |
| `mail.smtp_password` | string | | SMTP authentication password |
| `mail.mail_sender` | string | | Email sender address |
| `ntfy.server` | string | `https://ntfy.sh` | ntfy server URL |
| `uploads.max_size_mb` | int | `10` | Maximum upload size in MB |
| `blobs.directory` | string | `instance/blobs` | Blob storage directory |
| `backups.directory` | string | `instance/backups` | Backup storage directory |
| `comments.edit_window_seconds` | int | `300` | Comment edit window in seconds |
| `worker.poll_interval` | int | `5` | Worker poll interval in seconds |
| `worker.batch_size` | int | `50` | Notifications to process per batch |
| `worker.max_retries` | int | `3` | Maximum retry attempts per notification |
| `proxy.x_forwarded_for` | int | `0` | Trust X-Forwarded-For (hop count) |
| `proxy.x_forwarded_proto` | int | `0` | Trust X-Forwarded-Proto (hop count) |
| `proxy.x_forwarded_host` | int | `0` | Trust X-Forwarded-Host (hop count) |
| `proxy.x_forwarded_prefix` | int | `0` | Trust X-Forwarded-Prefix (hop count) |

## Tech Stack

- **Backend**: Flask, APSW (SQLite)
- **Frontend**: HTMX, PicoCSS
- **Tools**: uv, ruff, ty

## License

MIT
