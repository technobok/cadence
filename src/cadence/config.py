"""Configuration registry and type system.

Every configurable setting is declared here with its key, type, default,
description, and whether it contains a secret.  The registry is the single
source of truth for what settings exist.
"""

from dataclasses import dataclass
from enum import Enum


class ConfigType(Enum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"
    STRING_LIST = "string_list"


@dataclass(frozen=True, slots=True)
class ConfigEntry:
    key: str
    type: ConfigType
    default: str | int | bool | list[str]
    description: str
    secret: bool = False


# ---------------------------------------------------------------------------
# Registry -- every known setting
# ---------------------------------------------------------------------------

REGISTRY: list[ConfigEntry] = [
    # -- server --
    ConfigEntry("server.host", ConfigType.STRING, "0.0.0.0", "Bind address for production server"),
    ConfigEntry("server.port", ConfigType.INT, 5000, "Port for production server"),
    ConfigEntry("server.dev_host", ConfigType.STRING, "127.0.0.1", "Bind address for dev server"),
    ConfigEntry("server.dev_port", ConfigType.INT, 5000, "Port for dev server"),
    ConfigEntry("server.debug", ConfigType.BOOL, False, "Enable Flask debug mode"),
    # -- mail --
    ConfigEntry("mail.smtp_server", ConfigType.STRING, "", "SMTP server hostname"),
    ConfigEntry("mail.smtp_port", ConfigType.INT, 587, "SMTP server port"),
    ConfigEntry("mail.smtp_use_tls", ConfigType.BOOL, True, "Use TLS for SMTP"),
    ConfigEntry("mail.smtp_username", ConfigType.STRING, "", "SMTP authentication username"),
    ConfigEntry(
        "mail.smtp_password", ConfigType.STRING, "", "SMTP authentication password", secret=True
    ),
    ConfigEntry("mail.mail_sender", ConfigType.STRING, "", "Email sender address"),
    # -- ntfy --
    ConfigEntry("ntfy.server", ConfigType.STRING, "https://ntfy.sh", "ntfy server URL"),
    # -- uploads --
    ConfigEntry("uploads.max_size_mb", ConfigType.INT, 10, "Maximum upload size in MB"),
    # -- blobs --
    ConfigEntry("blobs.directory", ConfigType.STRING, "instance/blobs", "Blob storage directory"),
    # -- backups --
    ConfigEntry(
        "backups.directory", ConfigType.STRING, "instance/backups", "Backup storage directory"
    ),
    # -- auth --
    ConfigEntry(
        "auth.magic_link_expiry_seconds", ConfigType.INT, 3600, "Magic link token lifetime"
    ),
    ConfigEntry(
        "auth.trusted_session_days", ConfigType.INT, 365, "Trusted session duration in days"
    ),
    # -- comments --
    ConfigEntry(
        "comments.edit_window_seconds", ConfigType.INT, 300, "Comment edit window in seconds"
    ),
    # -- worker --
    ConfigEntry("worker.poll_interval", ConfigType.INT, 5, "Worker poll interval in seconds"),
    ConfigEntry("worker.batch_size", ConfigType.INT, 50, "Notifications to process per batch"),
    ConfigEntry("worker.max_retries", ConfigType.INT, 3, "Maximum retry attempts per notification"),
    # -- proxy --
    ConfigEntry("proxy.x_forwarded_for", ConfigType.INT, 0, "Trust X-Forwarded-For (hop count)"),
    ConfigEntry(
        "proxy.x_forwarded_proto", ConfigType.INT, 0, "Trust X-Forwarded-Proto (hop count)"
    ),
    ConfigEntry("proxy.x_forwarded_host", ConfigType.INT, 0, "Trust X-Forwarded-Host (hop count)"),
    ConfigEntry(
        "proxy.x_forwarded_prefix", ConfigType.INT, 0, "Trust X-Forwarded-Prefix (hop count)"
    ),
]

# Fast lookup by key
_REGISTRY_MAP: dict[str, ConfigEntry] = {e.key: e for e in REGISTRY}


def resolve_entry(key: str) -> ConfigEntry | None:
    """Look up a registry entry by key."""
    return _REGISTRY_MAP.get(key)


# ---------------------------------------------------------------------------
# Value parsing / serialization
# ---------------------------------------------------------------------------


def parse_value(entry: ConfigEntry, raw: str) -> str | int | bool | list[str]:
    """Parse a raw string value according to the entry's type."""
    match entry.type:
        case ConfigType.STRING:
            return raw
        case ConfigType.INT:
            return int(raw)
        case ConfigType.BOOL:
            return raw.lower() in ("true", "1", "yes", "on")
        case ConfigType.STRING_LIST:
            return [s.strip() for s in raw.split(",") if s.strip()]


def serialize_value(entry: ConfigEntry, value: str | int | bool | list[str]) -> str:
    """Serialize a typed value to a string for storage."""
    match entry.type:
        case ConfigType.BOOL:
            return "true" if value else "false"
        case ConfigType.STRING_LIST:
            if isinstance(value, list):
                return ", ".join(value)
            return str(value)
        case _:
            return str(value)


# ---------------------------------------------------------------------------
# Mapping from registry keys to Flask app.config keys
# ---------------------------------------------------------------------------

KEY_MAP: dict[str, str] = {
    "server.host": "HOST",
    "server.port": "PORT",
    "server.dev_host": "DEV_HOST",
    "server.dev_port": "DEV_PORT",
    "server.debug": "DEBUG",
    "mail.smtp_server": "SMTP_SERVER",
    "mail.smtp_port": "SMTP_PORT",
    "mail.smtp_use_tls": "SMTP_USE_TLS",
    "mail.smtp_username": "SMTP_USERNAME",
    "mail.smtp_password": "SMTP_PASSWORD",
    "mail.mail_sender": "MAIL_SENDER",
    "ntfy.server": "NTFY_SERVER",
    "uploads.max_size_mb": "MAX_UPLOAD_SIZE_MB",
    "blobs.directory": "BLOBS_DIRECTORY",
    "backups.directory": "BACKUPS_DIRECTORY",
    "auth.magic_link_expiry_seconds": "MAGIC_LINK_EXPIRY_SECONDS",
    "auth.trusted_session_days": "TRUSTED_SESSION_DAYS",
    "comments.edit_window_seconds": "COMMENT_EDIT_WINDOW_SECONDS",
    "worker.poll_interval": "WORKER_POLL_INTERVAL",
    "worker.batch_size": "WORKER_BATCH_SIZE",
    "worker.max_retries": "WORKER_MAX_RETRIES",
    "proxy.x_forwarded_for": "PROXY_X_FORWARDED_FOR",
    "proxy.x_forwarded_proto": "PROXY_X_FORWARDED_PROTO",
    "proxy.x_forwarded_host": "PROXY_X_FORWARDED_HOST",
    "proxy.x_forwarded_prefix": "PROXY_X_FORWARDED_PREFIX",
}


# ---------------------------------------------------------------------------
# INI section/key -> registry key mapping (for config import)
# ---------------------------------------------------------------------------

INI_MAP: dict[tuple[str, str], str | None] = {
    ("server", "SECRET_KEY"): None,  # handled specially -- stored as secret_key in app_setting
    ("server", "HOST"): "server.host",
    ("server", "PORT"): "server.port",
    ("server", "DEV_HOST"): "server.dev_host",
    ("server", "DEV_PORT"): "server.dev_port",
    ("server", "DEBUG"): "server.debug",
    ("database", "PATH"): None,  # handled specially -- not a config setting
    ("mail", "SMTP_SERVER"): "mail.smtp_server",
    ("mail", "SMTP_PORT"): "mail.smtp_port",
    ("mail", "SMTP_USE_TLS"): "mail.smtp_use_tls",
    ("mail", "SMTP_USERNAME"): "mail.smtp_username",
    ("mail", "SMTP_PASSWORD"): "mail.smtp_password",
    ("mail", "MAIL_SENDER"): "mail.mail_sender",
    ("ntfy", "SERVER"): "ntfy.server",
    ("uploads", "MAX_SIZE_MB"): "uploads.max_size_mb",
    ("blobs", "DIRECTORY"): "blobs.directory",
    ("backups", "DIRECTORY"): "backups.directory",
    ("auth", "MAGIC_LINK_EXPIRY_SECONDS"): "auth.magic_link_expiry_seconds",
    ("auth", "TRUSTED_SESSION_DAYS"): "auth.trusted_session_days",
    ("comments", "EDIT_WINDOW_SECONDS"): "comments.edit_window_seconds",
    ("worker", "POLL_INTERVAL"): "worker.poll_interval",
    ("worker", "BATCH_SIZE"): "worker.batch_size",
    ("worker", "MAX_RETRIES"): "worker.max_retries",
    ("proxy", "X_FORWARDED_FOR"): "proxy.x_forwarded_for",
    ("proxy", "X_FORWARDED_PROTO"): "proxy.x_forwarded_proto",
    ("proxy", "X_FORWARDED_HOST"): "proxy.x_forwarded_host",
    ("proxy", "X_FORWARDED_PREFIX"): "proxy.x_forwarded_prefix",
}
