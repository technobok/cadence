"""User property helpers backed by gatekeeper user_property (app='cadence')."""

from typing import Any


def get_cadence_props(gk: Any, username: str) -> dict[str, str | None]:
    """Get all cadence-specific properties for a user."""
    return gk.get_user_properties(username, "cadence")


def get_cadence_prop(gk: Any, username: str, key: str) -> str | None:
    """Get a single cadence-specific property."""
    return gk.get_user_property(username, "cadence", key)


def set_cadence_prop(gk: Any, username: str, key: str, value: str | None) -> None:
    """Set a single cadence-specific property."""
    gk.set_user_property(username, "cadence", key, value)


def is_admin(gk: Any, username: str) -> bool:
    """Check if user is a cadence admin."""
    return get_cadence_prop(gk, username, "is_admin") == "1"


def get_display_name(gk: Any, username: str, fallback_fullname: str = "") -> str:
    """Get user's display name, falling back to gatekeeper fullname."""
    dn = get_cadence_prop(gk, username, "display_name")
    return dn or fallback_fullname or username


def get_email_notifications(gk: Any, username: str) -> bool:
    """Check if email notifications are enabled (default: True)."""
    val = get_cadence_prop(gk, username, "email_notifications")
    if val is None:
        return True  # default enabled
    return val == "1"


def get_ntfy_topic(gk: Any, username: str) -> str | None:
    """Get user's ntfy topic, or None if not configured."""
    topic = get_cadence_prop(gk, username, "ntfy_topic")
    return topic if topic else None
