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
make run
```

The app will be available at http://localhost:5000

## Configuration

Copy `config.ini.example` to `instance/config.ini` and configure:

- **[server]** - SECRET_KEY, DEBUG, HOST, PORT
- **[database]** - PATH to SQLite database
- **[mail]** - SMTP settings for magic link emails
- **[ntfy]** - ntfy server for push notifications
- **[blobs]** - Directory for file attachments
- **[auth]** - Magic link expiry, trusted session duration

## Development

```bash
make sync      # Install/update dependencies
make init-db   # Create blank database
make run       # Start dev server (0.0.0.0:5000)
make check     # Run ruff + ty (format, lint, typecheck)
make worker    # Start notification worker
make clean     # Remove temp files and database
```

## Tech Stack

- **Backend**: Flask, APSW (SQLite)
- **Frontend**: HTMX, PicoCSS
- **Tools**: uv, ruff, ty

## License

MIT
