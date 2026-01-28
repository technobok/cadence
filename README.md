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

## Requirements

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) for dependency management

## Quick Start

```bash
# Clone and enter directory
git clone https://github.com/YOUR_USERNAME/cadence.git
cd cadence

# Install dependencies
make sync

# Create config file
cp config.ini.example instance/config.ini
# Edit instance/config.ini with your settings

# Initialize database
make init-db

# Run development server
make rundev
```

The app will be available at http://127.0.0.1:5000

## Configuration

Copy `config.ini.example` to `instance/config.ini` and configure:

- **[server]** - SECRET_KEY, DEBUG, HOST, PORT, DEV_HOST, DEV_PORT
- **[database]** - PATH to SQLite database
- **[mail]** - SMTP settings for magic link emails
- **[ntfy]** - ntfy server for push notifications
- **[blobs]** - Directory for file attachments
- **[auth]** - Magic link expiry, trusted session duration

## Development

```bash
make sync      # Install/update dependencies
make init-db   # Create blank database
make rundev    # Start dev server (DEV_HOST:DEV_PORT, debug=True)
make run       # Start server (HOST:PORT, production settings)
make check     # Run ruff + ty (format, lint, typecheck)
make worker    # Start notification worker
make clean     # Remove temp files and database
```

## Docker Deployment

### Quick Start

```bash
# Copy and configure production settings
cp config.production.ini instance/config.ini

# Edit instance/config.ini:
# - Set SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_hex(32))")
# - Configure SMTP settings for magic link emails
# - Set APP_URL to your domain

# Start all services
docker compose up -d
```

The app will be available at http://localhost:5001

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
3. Enable proxy headers in `instance/config.ini`:
   ```ini
   [proxy]
   X_FORWARDED_FOR = 1
   X_FORWARDED_PROTO = 1
   X_FORWARDED_HOST = 1
   ```

### Optional: Self-hosted ntfy

To use a self-hosted ntfy server instead of ntfy.sh:

1. Edit `docker-compose.yml` - uncomment the `ntfy` service and `ntfy-cache` volume
2. Update `instance/config.ini`:
   ```ini
   [ntfy]
   SERVER = http://ntfy:80
   ```

### Data Persistence

All persistent data is stored in `./instance/`:
- `cadence.sqlite3` - Database
- `blobs/` - File attachments
- `backups/` - Database backups
- `config.ini` - Configuration

### Manual Deployment (without Docker)

When running behind a reverse proxy, enable proxy header support in `config.ini`:

```ini
[proxy]
X_FORWARDED_FOR = 1
X_FORWARDED_PROTO = 1
X_FORWARDED_HOST = 1
```

Run the app and worker:
```bash
make run      # Start Flask app
make worker   # Start notification worker (separate terminal)
```

## Tech Stack

- **Backend**: Flask, APSW (SQLite)
- **Frontend**: HTMX, PicoCSS
- **Tools**: uv, ruff, ty

## License

MIT
