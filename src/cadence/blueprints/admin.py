"""Admin blueprint for user management and system administration."""

from datetime import UTC, datetime, timedelta
from typing import Any

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.wrappers import Response

from cadence.blueprints.auth import admin_required
from cadence.models import Activity, Task, User

bp = Blueprint("admin", __name__, url_prefix="/admin")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def render_partial_or_full(partial: str, full: str, **context: Any) -> str:
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


# --- Dashboard ---


@bp.route("/")
@admin_required
def index() -> str:
    """Admin dashboard."""
    user_count = User.count()
    task_count = Task.count()

    # Recent activity (last 24 hours)
    recent_activity = Activity.get_recent(hours=24)

    return render_template(
        "admin/index.html",
        user_count=user_count,
        task_count=task_count,
        recent_activity_count=len(recent_activity),
    )


# --- User Management ---


@bp.route("/users")
@admin_required
def users() -> str:
    """List all users."""
    all_users = User.get_all(include_inactive=True)

    # Sort by email by default, or by query param
    sort_by = request.args.get("sort", "email")
    sort_dir = request.args.get("dir", "asc")

    if sort_by == "email":
        all_users.sort(key=lambda u: u.email.lower(), reverse=(sort_dir == "desc"))
    elif sort_by == "name":
        all_users.sort(key=lambda u: (u.display_name or "").lower(), reverse=(sort_dir == "desc"))
    elif sort_by == "admin":
        all_users.sort(key=lambda u: u.is_admin, reverse=(sort_dir == "desc"))
    elif sort_by == "active":
        all_users.sort(key=lambda u: u.is_active, reverse=(sort_dir == "desc"))
    elif sort_by == "created":
        all_users.sort(key=lambda u: u.created_at, reverse=(sort_dir == "desc"))

    return render_partial_or_full(
        "admin/_users_list.html",
        "admin/users.html",
        users=all_users,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@bp.route("/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(user_id: int) -> str | Response:
    """Toggle admin status for a user."""
    from flask import g

    user = User.get_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    # Prevent removing own admin status
    if user.id == g.user.id:
        flash("Cannot modify your own admin status.", "error")
        return redirect(url_for("admin.users"))

    user.update(is_admin=not user.is_admin)

    status = "granted" if user.is_admin else "revoked"
    flash(f"Admin access {status} for {user.email}.", "success")

    if is_htmx_request():
        return render_template("admin/_user_row.html", user=user)

    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(user_id: int) -> str | Response:
    """Toggle active status for a user."""
    from flask import g

    user = User.get_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    # Prevent deactivating self
    if user.id == g.user.id:
        flash("Cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))

    user.update(is_active=not user.is_active)

    status = "activated" if user.is_active else "deactivated"
    flash(f"User {user.email} has been {status}.", "success")

    if is_htmx_request():
        return render_template("admin/_user_row.html", user=user)

    return redirect(url_for("admin.users"))


# --- Database Backup ---


@bp.route("/backup", methods=["POST"])
@admin_required
def backup() -> Response:
    """Create a consistent backup of the database using APSW's backup API."""
    from pathlib import Path

    import apsw
    from flask import current_app

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

    from flask import current_app

    backups_dir = current_app.config.get("BACKUPS_DIRECTORY")
    backup_files = []

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

    from flask import current_app, send_file

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

    from flask import current_app

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
    # Default to last 7 days
    end_date = request.args.get("end_date", "")
    start_date = request.args.get("start_date", "")

    if not end_date:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")

    # Get activities in date range
    activities = Activity.get_in_date_range(start_date, end_date)

    # Get user map for display
    user_ids = {a.user_id for a in activities if a.user_id}
    users = {u.id: u for u in [User.get_by_id(uid) for uid in user_ids] if u}

    # Get task map for display
    task_ids = {a.task_id for a in activities if a.task_id}
    tasks = {t.id: t for t in [Task.get_by_id(tid) for tid in task_ids] if t}

    # Compute summary stats
    action_counts: dict[str, int] = {}
    user_activity: dict[int, int] = {}

    for activity in activities:
        action_counts[activity.action] = action_counts.get(activity.action, 0) + 1
        if activity.user_id:
            user_activity[activity.user_id] = user_activity.get(activity.user_id, 0) + 1

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
        user_activity=[(users.get(uid), count) for uid, count in sorted_users],
    )
