"""CLI entry point for cadence-admin."""

import configparser
import sys

import click

from cadence.config import (
    INI_MAP,
    REGISTRY,
    parse_value,
    resolve_entry,
    serialize_value,
)
from cadence.db import (
    close_standalone_db,
    get_db_path,
    get_standalone_db,
    init_db_at,
    standalone_transaction,
)


def _make_app():
    """Create a Flask app for commands that need app context."""
    from cadence import create_app

    return create_app()


# ---------------------------------------------------------------------------
# Config helpers (standalone DB, no Flask)
# ---------------------------------------------------------------------------


def _db_get(key: str) -> str | None:
    """Read a single value from app_setting."""
    db = get_standalone_db()
    row = db.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _db_get_all() -> dict[str, str]:
    """Read all app_setting rows into a dict."""
    db = get_standalone_db()
    rows = db.execute("SELECT key, value FROM app_setting ORDER BY key").fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def _db_set(key: str, value: str) -> None:
    """Upsert a value into app_setting."""
    with standalone_transaction() as cursor:
        cursor.execute(
            "INSERT INTO app_setting (key, value, description) VALUES (?, ?, '') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def main():
    """Cadence administration tool."""


# ---- config group --------------------------------------------------------


@main.group()
def config():
    """View and manage configuration settings."""


@config.command("list")
def config_list():
    """Show all settings with their effective values."""
    db_values = _db_get_all()

    current_group = ""
    for entry in REGISTRY:
        group = entry.key.split(".")[0]
        if group != current_group:
            if current_group:
                click.echo()
            click.echo(click.style(f"[{group}]", bold=True))
            current_group = group

        raw = db_values.get(entry.key)
        if raw is not None:
            value = raw
            source = "db"
        else:
            value = serialize_value(entry, entry.default)
            source = "default"

        if entry.secret and raw is not None:
            display = "********"
        else:
            display = value if value else "(empty)"

        source_tag = click.style(f"[{source}]", fg="cyan" if source == "db" else "yellow")
        click.echo(f"  {entry.key} = {display}  {source_tag}")
        click.echo(click.style(f"    {entry.description}", dim=True))

    close_standalone_db()


@config.command("get")
@click.argument("key")
def config_get(key: str):
    """Get the effective value of a setting."""
    entry = resolve_entry(key)
    if not entry:
        click.echo(f"Unknown setting: {key}", err=True)
        sys.exit(1)
    assert entry is not None

    raw = _db_get(key)
    if raw is not None:
        value = parse_value(entry, raw)
    else:
        value = entry.default

    if entry.secret and raw is not None:
        click.echo("********")
    elif isinstance(value, list):
        click.echo(", ".join(value) if value else "(empty)")
    elif isinstance(value, bool):
        click.echo("true" if value else "false")
    else:
        click.echo(value if value else "(empty)")

    close_standalone_db()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value in the database."""
    entry = resolve_entry(key)
    if not entry:
        click.echo(f"Unknown setting: {key}", err=True)
        sys.exit(1)
    assert entry is not None

    # Validate by parsing
    try:
        parse_value(entry, value)
    except (ValueError, TypeError) as exc:
        click.echo(f"Invalid value for {key} ({entry.type.value}): {exc}", err=True)
        sys.exit(1)

    _db_set(key, value)
    click.echo(f"{key} = {value}")
    close_standalone_db()


@config.command("import")
@click.argument("ini_file", type=click.Path(exists=True))
def config_import(ini_file: str):
    """Import settings from an INI config file."""
    cfg = configparser.ConfigParser()
    cfg.read(ini_file)

    imported = 0

    for section in cfg.sections():
        for ini_key, value in cfg.items(section):
            # Skip configparser's DEFAULT entries
            if ini_key == "__name__":
                continue
            lookup = (section, ini_key.upper())
            registry_key = INI_MAP.get(lookup)
            if registry_key is None:
                if lookup in INI_MAP:
                    # Explicitly skipped (e.g. database.PATH, server.SECRET_KEY)
                    click.echo(f"  (skip) [{section}] {ini_key}")
                else:
                    click.echo(f"  (unknown) [{section}] {ini_key}")
                continue
            _db_set(registry_key, value)
            click.echo(f"  {registry_key} = {value}")
            imported += 1

    click.echo(f"\nImported {imported} settings.")
    close_standalone_db()


# ---- admin commands ------------------------------------------------------


@main.command("init-db")
def init_db_command():
    """Initialize the database schema."""
    db_path = get_db_path()
    init_db_at(db_path)
    click.echo("Database initialized.")


@main.command("make-admin")
@click.argument("email")
def make_admin_command(email: str):
    """Grant admin privileges to a user by email."""
    app = _make_app()
    with app.app_context():
        from cadence.models import User

        user = User.get_by_email(email)
        if not user:
            user = User.create(email=email, is_admin=True)
            click.echo(f"Created admin user: {email}")
        elif user.is_admin:
            click.echo(f"User {email} is already an admin.")
        else:
            user.update(is_admin=True)
            click.echo(f"Granted admin privileges to: {email}")


@main.command("list-users")
def list_users_command():
    """List all users."""
    app = _make_app()
    with app.app_context():
        from cadence.models import User

        users = User.get_all(include_inactive=True)
        if not users:
            click.echo("No users found.")
            return
        click.echo(f"{'Email':<40} {'Admin':<8} {'Active':<8}")
        click.echo("-" * 56)
        for user in users:
            admin = "Yes" if user.is_admin else "No"
            active = "Yes" if user.is_active else "No"
            click.echo(f"{user.email:<40} {admin:<8} {active:<8}")
