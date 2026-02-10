"""Cadence - A self-contained task and issue tracker."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import apsw
import mistune
from flask import Flask, g, render_template, request
from markupsafe import Markup

from cadence.config import KEY_MAP, REGISTRY, parse_value
from cadence.models import user_helpers


def get_user_timezone() -> ZoneInfo:
    """Get user's timezone from request header or cookie."""
    tz_name = request.headers.get("X-Timezone") or request.cookies.get("tz") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Application factory for Cadence."""
    # Resolve database path
    db_path = os.environ.get("CADENCE_DB")
    if not db_path:
        if "CADENCE_ROOT" in os.environ:
            project_root = Path(os.environ["CADENCE_ROOT"])
        else:
            source_root = Path(__file__).parent.parent.parent
            if (source_root / "src" / "cadence" / "__init__.py").exists():
                project_root = source_root
            else:
                project_root = Path.cwd()
        db_path = str(project_root / "instance" / "cadence.sqlite3")
        instance_path = project_root / "instance"
    else:
        instance_path = Path(db_path).parent

    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=True,
    )

    # Minimal defaults before DB config is loaded
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE_PATH=db_path,
    )

    if test_config is not None:
        app.config.from_mapping(test_config)
    else:
        _load_config_from_db(app)

    # Convert MAX_UPLOAD_SIZE_MB to bytes for Flask/blueprint usage
    max_mb = app.config.get("MAX_UPLOAD_SIZE_MB", 10)
    app.config["MAX_UPLOAD_SIZE"] = max_mb * 1024 * 1024

    # Ensure directories exist
    blobs_dir = app.config.get("BLOBS_DIRECTORY", str(instance_path / "blobs"))
    backups_dir = app.config.get("BACKUPS_DIRECTORY", str(instance_path / "backups"))
    Path(blobs_dir).mkdir(parents=True, exist_ok=True)
    Path(backups_dir).mkdir(parents=True, exist_ok=True)

    from cadence.db import close_db

    app.teardown_appcontext(close_db)

    # Gatekeeper client integration
    _init_gatekeeper(app)

    # Set cadence_is_admin on g after gatekeeper sets g.user
    @app.before_request
    def _set_cadence_admin() -> None:
        if g.get("user"):
            gk = app.config.get("GATEKEEPER_CLIENT")
            if gk:
                g.cadence_is_admin = user_helpers.is_admin(gk, g.user.username)
            else:
                g.cadence_is_admin = False
        else:
            g.cadence_is_admin = False

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

    # Simplified markdown renderer
    md = mistune.create_markdown(
        escape=True,
        plugins=["strikethrough"],
    )

    @app.template_filter("markdown")
    def markdown_filter(text: str | None) -> Markup:
        """Render simplified markdown to HTML."""
        if not text:
            return Markup("")
        # Render markdown (mistune escapes HTML by default with escape=True)
        html = str(md(text)).strip()
        # Strip wrapping <p> tags for inline use if single paragraph
        if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
            html = html[3:-4]
        return Markup(html)

    @app.template_filter("markdown_block")
    def markdown_block_filter(text: str | None) -> Markup:
        """Render markdown to HTML, preserving block structure."""
        if not text:
            return Markup("")
        return Markup(str(md(text)))

    # Register blueprints
    from cadence.blueprints import admin, auth, tags, tasks

    app.register_blueprint(auth.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(tags.bp)

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    return app


def _init_gatekeeper(app: Flask) -> None:
    """Initialize Gatekeeper client for SSO authentication."""
    import logging

    logger = logging.getLogger(__name__)

    gk_db_path = os.environ.get("GATEKEEPER_DB")
    if not gk_db_path:
        logger.info("GATEKEEPER_DB not set, authentication disabled")
        return

    try:
        from gatekeeper.client import GatekeeperClient
        from gatekeeper.client.flask_integration import setup_flask_integration

        client = GatekeeperClient(db_path=gk_db_path)
        app.config["GATEKEEPER_CLIENT"] = client
        setup_flask_integration(app, client)
        logger.info("Gatekeeper client initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Gatekeeper client: {e}")


def _load_config_from_db(app: Flask) -> None:
    """Load configuration from the database into Flask app.config."""
    db_path = app.config["DATABASE_PATH"]

    try:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY)
    except apsw.CantOpenError:
        # Database doesn't exist yet (init-db hasn't been run)
        return

    try:
        rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
    except apsw.SQLError:
        # Table doesn't exist yet
        conn.close()
        return

    db_values = {str(r[0]): str(r[1]) for r in rows}
    conn.close()

    # Load SECRET_KEY from database
    if "secret_key" in db_values:
        app.config["SECRET_KEY"] = db_values["secret_key"]

    # Apply registry entries
    for entry in REGISTRY:
        flask_key = KEY_MAP.get(entry.key)
        if not flask_key:
            continue

        raw = db_values.get(entry.key)
        if raw is not None:
            value = parse_value(entry, raw)
        else:
            value = entry.default

        app.config[flask_key] = value

    # Apply ProxyFix if any proxy values are non-zero
    x_for = app.config.get("PROXY_X_FORWARDED_FOR", 0)
    x_proto = app.config.get("PROXY_X_FORWARDED_PROTO", 0)
    x_host = app.config.get("PROXY_X_FORWARDED_HOST", 0)
    x_prefix = app.config.get("PROXY_X_FORWARDED_PREFIX", 0)
    if any((x_for, x_proto, x_host, x_prefix)):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(  # type: ignore[assignment]
            app.wsgi_app, x_for=x_for, x_proto=x_proto, x_host=x_host, x_prefix=x_prefix
        )
