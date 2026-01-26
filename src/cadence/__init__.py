"""Cadence - A self-contained task and issue tracker."""

import configparser
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from cadence.db import close_db, init_db_command


def get_user_timezone() -> ZoneInfo:
    """Get user's timezone from request header or cookie."""
    tz_name = request.headers.get("X-Timezone") or request.cookies.get("tz") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Application factory for Cadence."""
    # Project root is two levels up from this file (src/cadence/__init__.py)
    project_root = Path(__file__).parent.parent.parent
    instance_path = project_root / "instance"

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=True,
    )

    # Default configuration
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE_PATH=str(instance_path / "cadence.sqlite3"),
        BLOBS_DIRECTORY=str(instance_path / "blobs"),
        BACKUPS_DIRECTORY=str(instance_path / "backups"),
        MAX_UPLOAD_SIZE=10 * 1024 * 1024,  # 10MB
        MAGIC_LINK_EXPIRY_SECONDS=3600,
        TRUSTED_SESSION_DAYS=365,
    )

    if test_config is None:
        # Load config.ini if it exists
        config_path = instance_path / "config.ini"
        if not config_path.exists():
            config_path = project_root / "config.ini"

        if config_path.exists():
            config = configparser.ConfigParser()
            config.read(config_path)

            if config.has_section("server"):
                if config.has_option("server", "SECRET_KEY"):
                    app.config["SECRET_KEY"] = config.get("server", "SECRET_KEY")
                if config.has_option("server", "DEBUG"):
                    app.config["DEBUG"] = config.getboolean("server", "DEBUG")

            if config.has_section("database"):
                if config.has_option("database", "PATH"):
                    db_path = config.get("database", "PATH")
                    if not os.path.isabs(db_path):
                        db_path = str(project_root / db_path)
                    app.config["DATABASE_PATH"] = db_path

            if config.has_section("uploads"):
                if config.has_option("uploads", "MAX_SIZE_MB"):
                    app.config["MAX_UPLOAD_SIZE"] = (
                        config.getint("uploads", "MAX_SIZE_MB") * 1024 * 1024
                    )

            if config.has_section("blobs"):
                if config.has_option("blobs", "DIRECTORY"):
                    blobs_dir = config.get("blobs", "DIRECTORY")
                    if not os.path.isabs(blobs_dir):
                        blobs_dir = str(project_root / blobs_dir)
                    app.config["BLOBS_DIRECTORY"] = blobs_dir

            if config.has_section("backups"):
                if config.has_option("backups", "DIRECTORY"):
                    backups_dir = config.get("backups", "DIRECTORY")
                    if not os.path.isabs(backups_dir):
                        backups_dir = str(project_root / backups_dir)
                    app.config["BACKUPS_DIRECTORY"] = backups_dir

            if config.has_section("mail"):
                app.config["SMTP_SERVER"] = config.get("mail", "SMTP_SERVER", fallback="")
                app.config["SMTP_PORT"] = config.getint("mail", "SMTP_PORT", fallback=587)
                app.config["SMTP_USE_TLS"] = config.getboolean(
                    "mail", "SMTP_USE_TLS", fallback=True
                )
                app.config["SMTP_USERNAME"] = config.get("mail", "SMTP_USERNAME", fallback="")
                app.config["SMTP_PASSWORD"] = config.get("mail", "SMTP_PASSWORD", fallback="")
                app.config["MAIL_SENDER"] = config.get("mail", "MAIL_SENDER", fallback="")

            if config.has_section("ntfy"):
                app.config["NTFY_SERVER"] = config.get("ntfy", "SERVER", fallback="https://ntfy.sh")

            if config.has_section("auth"):
                app.config["MAGIC_LINK_EXPIRY_SECONDS"] = config.getint(
                    "auth", "MAGIC_LINK_EXPIRY_SECONDS", fallback=3600
                )
                app.config["TRUSTED_SESSION_DAYS"] = config.getint(
                    "auth", "TRUSTED_SESSION_DAYS", fallback=365
                )

            # Proxy settings - enable when running behind reverse proxy (Caddy, nginx)
            if config.has_section("proxy"):
                x_for = config.getint("proxy", "X_FORWARDED_FOR", fallback=1)
                x_proto = config.getint("proxy", "X_FORWARDED_PROTO", fallback=1)
                x_host = config.getint("proxy", "X_FORWARDED_HOST", fallback=1)
                x_prefix = config.getint("proxy", "X_FORWARDED_PREFIX", fallback=0)
                app.wsgi_app = ProxyFix(  # type: ignore[assignment]
                    app.wsgi_app,
                    x_for=x_for,
                    x_proto=x_proto,
                    x_host=x_host,
                    x_prefix=x_prefix,
                )
    else:
        app.config.from_mapping(test_config)

    # Ensure directories exist
    instance_path.mkdir(parents=True, exist_ok=True)
    Path(app.config["BLOBS_DIRECTORY"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["BACKUPS_DIRECTORY"]).mkdir(parents=True, exist_ok=True)

    # Register database teardown and CLI command
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    # Jinja filters for date formatting
    @app.template_filter("localdate")
    def localdate_filter(iso_string: str | None) -> str:
        """Format ISO date string in user's timezone (date only)."""
        if not iso_string:
            return ""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            user_tz = get_user_timezone()
            local_dt = dt.astimezone(user_tz)
            return local_dt.strftime("%b %d, %Y")
        except Exception:
            return iso_string[:10] if iso_string else ""

    @app.template_filter("localdatetime")
    def localdatetime_filter(iso_string: str | None) -> str:
        """Format ISO datetime string in user's timezone (with time and tz)."""
        if not iso_string:
            return ""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            user_tz = get_user_timezone()
            local_dt = dt.astimezone(user_tz)
            tz_abbr = local_dt.strftime("%Z")
            return local_dt.strftime(f"%b %d, %Y %H:%M {tz_abbr}")
        except Exception:
            return iso_string[:16].replace("T", " ") if iso_string else ""

    # Register blueprints
    from cadence.blueprints import auth, tasks

    app.register_blueprint(auth.bp)
    app.register_blueprint(tasks.bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app
