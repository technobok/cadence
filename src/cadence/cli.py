"""CLI entry point for cadence-admin."""

import configparser
import os
import stat
import sys
from datetime import UTC, datetime

import click
from flask import Flask

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


def _make_app() -> Flask:
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
def main() -> None:
    """Cadence administration tool."""


# ---- config group --------------------------------------------------------


@main.group()
def config() -> None:
    """View and manage configuration settings."""


@config.command("list")
def config_list() -> None:
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
def config_get(key: str) -> None:
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
def config_set(key: str, value: str) -> None:
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


@config.command("export")
@click.argument("output_file", type=click.Path())
def config_export(output_file: str) -> None:
    """Export all settings as a shell script of make config-set calls."""
    db_values = _db_get_all()
    lines = [
        "#!/bin/bash",
        "# Configuration export for Cadence",
        f"# Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    for entry in REGISTRY:
        raw = db_values.get(entry.key)
        if raw is not None:
            value = raw
            lines.append(f"make config-set KEY={entry.key} VAL='{value}'")
        else:
            value = serialize_value(entry, entry.default)
            lines.append(f"# default: {entry.key}")
            lines.append(f"# make config-set KEY={entry.key} VAL='{value}'")

    with open(output_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(output_file, os.stat(output_file).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    click.echo(f"Exported {len(REGISTRY)} settings to {output_file}")
    close_standalone_db()


@config.command("import")
@click.argument("ini_file", type=click.Path(exists=True))
def config_import(ini_file: str) -> None:
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
def init_db_command() -> None:
    """Initialize the database schema."""
    db_path = get_db_path()
    init_db_at(db_path)
    click.echo("Database initialized.")


@main.command("make-admin")
@click.argument("username")
def make_admin_command(username: str) -> None:
    """Grant cadence admin privileges to a user by username."""
    app = _make_app()
    with app.app_context():
        from cadence.models import user_helpers

        gk = app.config.get("GATEKEEPER_CLIENT")
        if not gk:
            click.echo("Gatekeeper not configured.", err=True)
            sys.exit(1)

        gk_user = gk.get_user(username)
        if not gk_user:
            click.echo(f"User '{username}' not found in Gatekeeper.", err=True)
            sys.exit(1)

        if user_helpers.is_admin(gk, username):
            click.echo(f"User '{username}' is already a cadence admin.")
        else:
            user_helpers.set_cadence_prop(gk, username, "is_admin", "1")
            click.echo(f"Granted cadence admin privileges to: {username}")


@main.command("list-users")
def list_users_command() -> None:
    """List all users known to Cadence."""
    app = _make_app()
    with app.app_context():
        from cadence.models import user_helpers

        gk = app.config.get("GATEKEEPER_CLIENT")
        if not gk:
            click.echo("Gatekeeper not configured.", err=True)
            sys.exit(1)

        # Get all usernames that have interacted with Cadence
        from cadence.db import get_db

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT DISTINCT username FROM (
                SELECT owner AS username FROM task
                UNION SELECT username FROM comment
                UNION SELECT username FROM task_watcher
                UNION SELECT username FROM activity_log WHERE username IS NOT NULL
                UNION SELECT uploaded_by AS username FROM attachment
            )
            ORDER BY username
        """)
        usernames = [str(row[0]) for row in cursor.fetchall()]

        if not usernames:
            click.echo("No users found.")
            return

        click.echo(f"{'Username':<25} {'Name':<30} {'Admin':<8} {'Enabled':<8}")
        click.echo("-" * 71)
        for uname in usernames:
            gk_user = gk.get_user(uname)
            display_name = user_helpers.get_display_name(
                gk, uname, gk_user.fullname if gk_user else ""
            )
            admin = "Yes" if user_helpers.is_admin(gk, uname) else "No"
            enabled = "Yes" if (gk_user and gk_user.enabled) else "No"
            click.echo(f"{uname:<25} {display_name:<30} {admin:<8} {enabled:<8}")
