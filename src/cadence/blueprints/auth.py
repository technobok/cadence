"""Authentication blueprint using Gatekeeper SSO."""

import functools
import secrets
from collections.abc import Callable
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.wrappers import Response

from cadence.models import user_helpers

bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that redirects anonymous users to the login page."""

    @functools.wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.url))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that requires cadence admin role."""

    @functools.wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.url))
        gk = current_app.config.get("GATEKEEPER_CLIENT")
        if not user_helpers.is_admin(gk, g.user.username):
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped_view


@bp.route("/login")
def login() -> str | Response:
    """Redirect to Gatekeeper SSO login, or show fallback page."""
    if g.get("user"):
        return redirect(url_for("index"))

    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        return render_template("auth/login.html", login_url=None)

    login_url = gk.get_login_url()
    if not login_url:
        return render_template("auth/login.html", login_url=None)

    next_url = request.args.get("next", "/")
    callback_url = url_for("auth.verify", _external=True)

    return redirect(
        f"{login_url}?app_name=Cadence"
        f"&callback_url={callback_url}"
        f"&next={next_url}"
    )


@bp.route("/verify")
def verify() -> str | Response:
    """Verify magic link token from Gatekeeper and establish session."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        flash("Authentication is not configured.", "error")
        return redirect(url_for("index"))

    token = request.args.get("token", "")
    result = gk.verify_magic_link(token)

    if not result:
        flash("Invalid or expired login link. Please request a new one.", "error")
        return redirect(url_for("auth.login"))

    user, redirect_url = result

    # Check if user has a display_name set in cadence properties
    display_name = user_helpers.get_cadence_prop(gk, user.username, "display_name")

    if not display_name:
        response = redirect(url_for("auth.setup_profile"))
    else:
        response = redirect(redirect_url or url_for("index"))
        flash(f"Welcome, {display_name}!", "success")

    gk.set_session_cookie(response, user)

    return response


@bp.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile() -> str | Response:
    """Set up profile for new users."""
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()

        if not display_name:
            flash("Please enter your name.", "error")
            return render_template("auth/setup_profile.html")

        gk = current_app.config.get("GATEKEEPER_CLIENT")
        user_helpers.set_cadence_prop(gk, g.user.username, "display_name", display_name)

        flash(f"Welcome, {display_name}!", "success")
        return redirect(url_for("index"))

    return render_template("auth/setup_profile.html")


@bp.route("/logout")
def logout() -> Response:
    """Log out the current user."""
    response = redirect(url_for("index"))
    response.delete_cookie("gk_session")
    flash("You have been logged out.", "info")
    return response


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings() -> str | Response:
    """User settings page."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")
    ntfy_server = current_app.config.get("NTFY_SERVER", "https://ntfy.sh")
    username = g.user.username

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            display_name = request.form.get("display_name", "").strip()
            if display_name:
                user_helpers.set_cadence_prop(gk, username, "display_name", display_name)
                flash("Profile updated.", "success")
            else:
                flash("Display name cannot be empty.", "error")

        elif action == "toggle_email":
            current_value = user_helpers.get_email_notifications(gk, username)
            new_value = not current_value
            user_helpers.set_cadence_prop(
                gk, username, "email_notifications", "1" if new_value else "0"
            )
            if new_value:
                flash("Email notifications enabled.", "success")
            else:
                flash("Email notifications disabled.", "success")

        elif action == "enable_ntfy":
            topic = f"cadence-{secrets.token_urlsafe(16)}"
            user_helpers.set_cadence_prop(gk, username, "ntfy_topic", topic)
            flash("Push notifications enabled.", "success")

        elif action == "disable_ntfy":
            user_helpers.set_cadence_prop(gk, username, "ntfy_topic", "")
            flash("Push notifications disabled.", "success")

        return redirect(url_for("auth.settings"))

    # Read current preferences for display
    display_name = user_helpers.get_display_name(gk, username, g.user.fullname)
    email_notifications = user_helpers.get_email_notifications(gk, username)
    ntfy_topic = user_helpers.get_ntfy_topic(gk, username)

    ntfy_subscribe_url = None
    if ntfy_topic:
        ntfy_subscribe_url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}"

    return render_template(
        "auth/settings.html",
        display_name=display_name,
        email_notifications=email_notifications,
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
        ntfy_subscribe_url=ntfy_subscribe_url,
    )
