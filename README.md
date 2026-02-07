# Cadence

A self-hosted task and issue tracker built with Python, Flask, HTMX, and SQLite.

## Features

- **Magic link authentication** - passwordless login via email
- **Task management** - create, track, and manage tasks with status workflows
- **Comments & attachments** - with automatic file deduplication
- **Activity logging** - immutable audit trail of all changes
- **Notifications** - email and ntfy support
- **Dark mode** - system/light/dark theme toggle
- **Self-contained** - single SQLite database, no external dependencies

## Quick Start

```bash
# Install dependencies (requires Python 3.14+ and uv)
make sync

# Create a blank database
make init-db

# Configure mail sender (needed for magic links)
make config-set KEY=mail.mail_sender VAL=tasks@example.com

# Configure SMTP
make config-set KEY=mail.smtp_server VAL=smtp.example.com
make config-set KEY=mail.smtp_username VAL=tasks@example.com
make config-set KEY=mail.smtp_password VAL=secret

# Create an initial admin user
.venv/bin/cadence-admin make-admin admin@example.com

# Start the development server
make rundev
```

The app will be available at http://127.0.0.1:5000

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

## Docker Deployment

### Quick Start

```bash
# Build and start all services
docker compose build
docker compose up -d

# Set configuration
docker compose exec app make config-set KEY=mail.smtp_server VAL=smtp.example.com
docker compose exec app make config-set KEY=mail.smtp_username VAL=tasks@example.com
docker compose exec app make config-set KEY=mail.smtp_password VAL=secret
docker compose exec app make config-set KEY=mail.mail_sender VAL=tasks@example.com
```

The app will be available at http://localhost:5001

To replicate configuration from another instance, export and import:

```bash
# On the source instance
make config-export FILE=cadence-config.sh

# On the target instance
bash cadence-config.sh
```

### Services

The `docker-compose.yml` includes:

| Service | Description | Default |
|---------|-------------|---------|
| `app` | Flask application (port 5001) | Enabled |
| `worker` | Background notification worker | Enabled |
| `init` | One-time database initialization | Enabled |
| `caddy` | Reverse proxy with automatic HTTPS | Commented out |
| `ntfy` | Self-hosted push notifications | Commented out |

### Optional: Caddy Reverse Proxy

To enable the built-in Caddy reverse proxy with automatic HTTPS:

1. Edit `Caddyfile` - replace `cadence.example.com` with your domain
2. Edit `docker-compose.yml`:
   - Uncomment the `caddy` service
   - Uncomment the `caddy-data` and `caddy-config` volumes
   - Change `app` from `ports: "5001:5000"` to `expose: "5000"`
3. Enable proxy headers:
   ```bash
   make config-set KEY=proxy.x_forwarded_for VAL=1
   make config-set KEY=proxy.x_forwarded_proto VAL=1
   make config-set KEY=proxy.x_forwarded_host VAL=1
   ```

### Optional: Self-hosted ntfy

To use a self-hosted ntfy server instead of ntfy.sh:

1. Edit `docker-compose.yml` - uncomment the `ntfy` service and `ntfy-cache` volume
2. Update the ntfy server setting:
   ```bash
   make config-set KEY=ntfy.server VAL=http://ntfy:80
   ```

### Data Persistence

All persistent data is stored in `./instance/`:
- `cadence.sqlite3` - Database (including all configuration)
- `blobs/` - File attachments
- `backups/` - Database backups

### Manual Deployment (without Docker)

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
cadence-admin init-db              # Initialize the database schema
cadence-admin make-admin EMAIL     # Grant admin privileges to a user
cadence-admin list-users           # List all users
cadence-admin config list          # Show settings
cadence-admin config get KEY       # Get a single setting
cadence-admin config set KEY VAL   # Set a setting
cadence-admin config import FILE   # Import from INI
cadence-admin config export FILE   # Export all settings as a shell script
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
| `auth.magic_link_expiry_seconds` | int | `3600` | Magic link token lifetime |
| `auth.trusted_session_days` | int | `365` | Trusted session duration in days |
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
