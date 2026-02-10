"""Admin blueprint for user management and system administration."""

from datetime import UTC, datetime, timedelta
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

from cadence.blueprints.auth import admin_required
from cadence.models import Activity, Task, user_helpers

bp = Blueprint("admin", __name__, url_prefix="/admin")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def render_partial_or_full(partial: str, full: str, **context: Any) -> str:
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


def _get_known_usernames() -> list[str]:
    """Get all usernames that have interacted with Cadence."""
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
    return [str(row[0]) for row in cursor.fetchall()]


# --- Dashboard ---


@bp.route("/")
@admin_required
def index() -> str:
    """Admin dashboard."""
    task_count = Task.count()

    # Recent activity (last 24 hours)
    recent_activity = Activity.get_recent(hours=24)

    return render_template(
        "admin/index.html",
        task_count=task_count,
        recent_activity_count=len(recent_activity),
    )


# --- User Management ---


@bp.route("/users")
@admin_required
def users() -> str:
    """List all known Cadence users with their gatekeeper info."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")
    usernames = _get_known_usernames()

    user_list: list[dict[str, Any]] = []
    for username in usernames:
        gk_user = gk.get_user(username) if gk else None
        fullname = gk_user.fullname if gk_user else ""
        user_list.append({
            "username": username,
            "email": gk_user.email if gk_user else "",
            "fullname": fullname,
            "display_name": user_helpers.get_display_name(
                gk, username, fullname
            ),
            "is_admin": user_helpers.is_admin(gk, username) if gk else False,
            "enabled": gk_user.enabled if gk_user else False,
        })

    # Sort
    sort_by = request.args.get("sort", "username")
    sort_dir = request.args.get("dir", "asc")
    reverse = sort_dir == "desc"

    if sort_by == "username":
        user_list.sort(key=lambda u: u["username"].lower(), reverse=reverse)
    elif sort_by == "email":
        user_list.sort(key=lambda u: u["email"].lower(), reverse=reverse)
    elif sort_by == "name":
        user_list.sort(
            key=lambda u: u["display_name"].lower(), reverse=reverse
        )
    elif sort_by == "admin":
        user_list.sort(key=lambda u: u["is_admin"], reverse=reverse)
    elif sort_by == "enabled":
        user_list.sort(key=lambda u: u["enabled"], reverse=reverse)

    return render_partial_or_full(
        "admin/_users_list.html",
        "admin/users.html",
        users=user_list,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@bp.route("/users/<username>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(username: str) -> str | Response:
    """Toggle admin status for a user."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")

    # Prevent removing own admin status
    if username == g.user.username:
        flash("Cannot modify your own admin status.", "error")
        return redirect(url_for("admin.users"))

    if not gk:
        flash("Gatekeeper not configured.", "error")
        return redirect(url_for("admin.users"))

    current_admin = user_helpers.is_admin(gk, username)
    user_helpers.set_cadence_prop(
        gk, username, "is_admin", "0" if current_admin else "1"
    )

    status = "revoked" if current_admin else "granted"
    display_name = user_helpers.get_display_name(gk, username, username)
    flash(f"Admin access {status} for {display_name}.", "success")

    if is_htmx_request():
        # Rebuild the user dict for the row template
        gk_user = gk.get_user(username)
        fullname = gk_user.fullname if gk_user else ""
        user = {
            "username": username,
            "email": gk_user.email if gk_user else "",
            "fullname": fullname,
            "display_name": user_helpers.get_display_name(
                gk, username, fullname
            ),
            "is_admin": not current_admin,
            "enabled": gk_user.enabled if gk_user else False,
        }
        return render_template("admin/_user_row.html", user=user)

    return redirect(url_for("admin.users"))


# --- Database Backup ---


@bp.route("/backup", methods=["POST"])
@admin_required
def backup() -> Response:
    """Create a consistent backup of the database using APSW's backup API."""
    from pathlib import Path

    import apsw

    from cadence.db import get_db

    # Get backups directory from config
    backups_dir = current_app.config.get("BACKUPS_DIRECTORY")
    if not backups_dir:
        flash("Backups directory not configured.", "error")
        return redirect(url_for("admin.index"))

    # Ensure directory exists
    backups_path = Path(backups_dir)
    backups_path.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"cadence_backup_{timestamp}.db"
    backup_file = backups_path / filename

    try:
        # Get the current database connection
        source_db = get_db()

        # Create backup file as destination
        dest_db = apsw.Connection(str(backup_file))

        # Use APSW's backup API to create a consistent snapshot
        with dest_db.backup("main", source_db, "main") as backup_obj:
            while not backup_obj.done:
                backup_obj.step(100)  # Copy 100 pages at a time

        dest_db.close()

    except Exception as e:
        flash(f"Backup failed: {e}", "error")
        return redirect(url_for("admin.index"))

    flash(f"Backup created: {filename}", "success")
    return redirect(url_for("admin.backups"))


@bp.route("/backups")
@admin_required
def backups() -> str:
    """List available backups."""
    from pathlib import Path

    backups_dir = current_app.config.get("BACKUPS_DIRECTORY")
    backup_files: list[dict[str, Any]] = []

    if backups_dir:
        backups_path = Path(backups_dir)
        if backups_path.exists():
            for f in sorted(backups_path.glob("cadence_backup_*.db"), reverse=True):
                stat = f.stat()
                backup_files.append(
                    {
                        "name": f.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime, UTC),
                    }
                )

    return render_template("admin/backups.html", backups=backup_files)


@bp.route("/backups/<filename>")
@admin_required
def download_backup(filename: str) -> Response:
    """Download a specific backup file."""
    from pathlib import Path

    from flask import send_file

    # Sanitize filename to prevent directory traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for("admin.backups"))

    backups_dir = current_app.config.get("BACKUPS_DIRECTORY")
    if not backups_dir:
        flash("Backups directory not configured.", "error")
        return redirect(url_for("admin.index"))

    backup_file = Path(backups_dir) / filename
    if not backup_file.exists():
        flash("Backup file not found.", "error")
        return redirect(url_for("admin.backups"))

    return send_file(
        backup_file,
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/backups/<filename>/delete", methods=["POST"])
@admin_required
def delete_backup(filename: str) -> Response:
    """Delete a backup file."""
    from pathlib import Path

    # Sanitize filename
    if "/" in filename or "\\" in filename or ".." in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for("admin.backups"))

    backups_dir = current_app.config.get("BACKUPS_DIRECTORY")
    if not backups_dir:
        flash("Backups directory not configured.", "error")
        return redirect(url_for("admin.index"))

    backup_file = Path(backups_dir) / filename
    if backup_file.exists():
        backup_file.unlink()
        flash(f"Deleted: {filename}", "success")
    else:
        flash("Backup file not found.", "error")

    return redirect(url_for("admin.backups"))


# --- Activity Reports ---


@bp.route("/reports")
@admin_required
def reports() -> str:
    """Activity reports with date filtering."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")

    # Default to last 7 days
    end_date = request.args.get("end_date", "")
    start_date = request.args.get("start_date", "")

    if not end_date:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")

    # Get activities in date range
    activities = Activity.get_in_date_range(start_date, end_date)

    # Build username -> display name map
    usernames: set[str] = {a.username for a in activities if a.username}
    users: dict[str, str] = {}
    for uname in usernames:
        gk_user = gk.get_user(uname) if gk else None
        fallback = gk_user.fullname if gk_user else ""
        users[uname] = user_helpers.get_display_name(gk, uname, fallback)

    # Get task map for display
    task_ids: set[int] = {a.task_id for a in activities if a.task_id}
    tasks: dict[int, Task] = {
        t.id: t for t in [Task.get_by_id(tid) for tid in task_ids] if t
    }

    # Compute summary stats
    action_counts: dict[str, int] = {}
    user_activity: dict[str, int] = {}

    for activity in activities:
        action_counts[activity.action] = action_counts.get(activity.action, 0) + 1
        if activity.username:
            user_activity[activity.username] = (
                user_activity.get(activity.username, 0) + 1
            )

    # Sort action counts by count descending
    sorted_actions = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)

    # Sort user activity by count descending
    sorted_users = sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:10]

    return render_partial_or_full(
        "admin/_reports.html",
        "admin/reports.html",
        activities=activities,
        users=users,
        tasks=tasks,
        start_date=start_date,
        end_date=end_date,
        total_activities=len(activities),
        action_counts=sorted_actions,
        user_activity=[
            (users.get(uname, uname), count) for uname, count in sorted_users
        ],
    )
