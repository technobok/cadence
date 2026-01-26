"""Authentication blueprint with magic link login."""

import functools
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from cadence.db import get_db, transaction
from cadence.models import User
from cadence.services.email_service import send_magic_link

bp = Blueprint("auth", __name__, url_prefix="/auth")


def get_serializer() -> URLSafeTimedSerializer:
    """Get the serializer for magic link tokens."""
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_magic_link(email: str) -> str:
    """Generate a magic link URL for the given email."""
    serializer = get_serializer()
    token = serializer.dumps(email, salt="magic-link")
    return url_for("auth.verify", token=token, _external=True)


def verify_magic_token(token: str) -> str | None:
    """
    Verify a magic link token and return the email if valid.
    Returns None if invalid or expired.
    """
    serializer = get_serializer()
    max_age = current_app.config.get("MAGIC_LINK_EXPIRY_SECONDS", 3600)

    try:
        email = serializer.loads(token, salt="magic-link", max_age=max_age)
        return email
    except (BadSignature, SignatureExpired):
        return None


def create_trusted_session(user_id: int, device_name: str | None = None) -> str:
    """
    Create a persistent trusted session for the user.
    Returns the plain token to store in cookie.
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session_uuid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    days = current_app.config.get("TRUSTED_SESSION_DAYS", 365)
    expires_at = (datetime.now(UTC) + timedelta(days=days)).isoformat()

    with transaction() as cursor:
        cursor.execute(
            "INSERT INTO session (uuid, user_id, token_hash, device_name, "
            "is_trusted, created_at, expires_at, last_used_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
            (session_uuid, user_id, token_hash, device_name, now, expires_at, now),
        )

    return token


def verify_trusted_session(token: str) -> User | None:
    """
    Verify a trusted session token.
    Returns User if valid, None otherwise.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT user_id, expires_at FROM session WHERE token_hash = ? AND is_trusted = 1",
        (token_hash,),
    )
    row = cursor.fetchone()

    if not row:
        return None

    user_id, expires_at = row

    if datetime.fromisoformat(expires_at) < datetime.now(UTC):
        # Session expired, delete it
        cursor.execute("DELETE FROM session WHERE token_hash = ?", (token_hash,))
        return None

    # Update last_used_at
    now = datetime.now(UTC).isoformat()
    cursor.execute(
        "UPDATE session SET last_used_at = ? WHERE token_hash = ?",
        (now, token_hash),
    )

    return User.get_by_id(user_id)


def invalidate_trusted_session(token: str) -> None:
    """Invalidate a trusted session by its token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM session WHERE token_hash = ?", (token_hash,))


@bp.before_app_request
def load_logged_in_user() -> None:
    """Load user from session or trusted cookie before each request."""
    user_id = session.get("user_id")

    if user_id is None:
        # Check for trusted session cookie
        trusted_token = request.cookies.get("cadence_session")
        if trusted_token:
            user = verify_trusted_session(trusted_token)
            if user:
                session["user_id"] = user.id
                g.user = user
                return

    if user_id is None:
        g.user = None
    else:
        g.user = User.get_by_id(user_id)


def login_required(view):
    """Decorator that redirects anonymous users to the login page."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.url))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    """Decorator that requires admin role."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.url))
        if not g.user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return view(**kwargs)

    return wrapped_view


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page - enter email to receive magic link."""
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("Please enter your email address.", "error")
            return render_template("auth/login.html")

        # Get or create user
        user, created = User.get_or_create(email)

        if not user.is_active:
            flash("Your account has been deactivated.", "error")
            return render_template("auth/login.html")

        # Generate and send magic link
        magic_link = generate_magic_link(email)

        if current_app.config.get("DEBUG"):
            # In debug mode, also log the link
            current_app.logger.info(f"Magic link for {email}: {magic_link}")

        if send_magic_link(email, magic_link):
            return render_template("auth/login_sent.html", email=email)
        else:
            # Email failed but in debug mode, show the link anyway
            if current_app.config.get("DEBUG"):
                flash(f"Email not configured. Debug link: {magic_link}", "info")
                return render_template("auth/login_sent.html", email=email, debug_link=magic_link)
            else:
                flash("Failed to send login email. Please try again.", "error")

    return render_template("auth/login.html")


@bp.route("/verify")
def verify():
    """Verify magic link token and log user in."""
    token = request.args.get("token", "")
    trust = request.args.get("trust", "0") == "1"

    email = verify_magic_token(token)

    if not email:
        flash("Invalid or expired login link. Please request a new one.", "error")
        return redirect(url_for("auth.login"))

    user = User.get_by_email(email)

    if not user:
        flash("User not found.", "error")
        return redirect(url_for("auth.login"))

    if not user.is_active:
        flash("Your account has been deactivated.", "error")
        return redirect(url_for("auth.login"))

    # Log the user in
    session.clear()
    session["user_id"] = user.id

    # Check if this is a new user who needs to set up their profile
    if not user.display_name:
        return redirect(url_for("auth.setup_profile", trust="1" if trust else "0"))

    response = redirect(url_for("index"))

    # If user wants to trust this device, create persistent session
    if trust:
        device_name = request.user_agent.string[:100] if request.user_agent else None
        token = create_trusted_session(user.id, device_name)
        days = current_app.config.get("TRUSTED_SESSION_DAYS", 365)
        response.set_cookie(
            "cadence_session",
            token,
            max_age=days * 24 * 60 * 60,
            httponly=True,
            secure=not current_app.config.get("DEBUG", False),
            samesite="Lax",
        )

    flash("You have been logged in.", "success")
    return response


@bp.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile():
    """Set up profile for new users."""
    trust = request.args.get("trust", "0")

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()

        if not display_name:
            flash("Please enter your name.", "error")
            return render_template("auth/setup_profile.html", trust=trust)

        g.user.update(display_name=display_name)

        response = redirect(url_for("index"))

        # Handle trust device after profile setup
        if trust == "1":
            device_name = request.user_agent.string[:100] if request.user_agent else None
            token = create_trusted_session(g.user.id, device_name)
            days = current_app.config.get("TRUSTED_SESSION_DAYS", 365)
            response.set_cookie(
                "cadence_session",
                token,
                max_age=days * 24 * 60 * 60,
                httponly=True,
                secure=not current_app.config.get("DEBUG", False),
                samesite="Lax",
            )

        flash(f"Welcome, {display_name}!", "success")
        return response

    return render_template("auth/setup_profile.html", trust=trust)


@bp.route("/logout")
def logout():
    """Log out the current user."""
    # Invalidate trusted session if exists
    trusted_token = request.cookies.get("cadence_session")
    if trusted_token:
        invalidate_trusted_session(trusted_token)

    session.clear()

    response = redirect(url_for("index"))
    response.delete_cookie("cadence_session")

    flash("You have been logged out.", "info")
    return response
