"""Tasks blueprint for task management."""

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from cadence.blueprints.auth import login_required
from cadence.models import VALID_STATUSES, Activity, Attachment, Comment, Task, TaskWatcher, User
from cadence.models.task import STATUS_TRANSITIONS
from cadence.services import attachment_service, notification_service

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def get_base_url() -> str:
    """Get the base URL for notification links."""
    # Use configured APP_URL if available, otherwise construct from request
    app_url = current_app.config.get("APP_URL")
    if app_url:
        return app_url
    return request.host_url.rstrip("/")


def can_view_task(task: Task, user: User) -> bool:
    """Check if a user can view a task."""
    if not task.is_private:
        return True
    if task.owner_id == user.id:
        return True
    if user.is_admin:
        return True
    # Watchers can view private tasks
    if TaskWatcher.is_watching(task.id, user.id):
        return True
    return False


def render_partial_or_full(partial: str, full: str, **context):
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


def render_activity(task: Task) -> str:
    """Render the activity/timeline section for a task."""
    activities = Activity.get_for_task(task.id, limit=50)
    activity_user_ids = {a.user_id for a in activities if a.user_id}
    users = {u.id: u for u in [User.get_by_id(uid) for uid in activity_user_ids] if u}

    # Get comments for edit checking
    comments = Comment.get_for_task(task.id)
    comments_by_uuid = {c.uuid: c for c in comments}

    edit_window_seconds = current_app.config.get("COMMENT_EDIT_WINDOW_SECONDS", 300)

    return render_template(
        "tasks/_activity.html",
        task=task,
        activities=activities,
        users=users,
        comments_by_uuid=comments_by_uuid,
        format_file_size=attachment_service.format_file_size,
        edit_window_seconds=edit_window_seconds,
    )


def render_with_activity_oob(primary_template: str, task: Task, **context) -> str:
    """Render primary template plus out-of-band activity update for HTMX."""
    primary_html = render_template(primary_template, task=task, **context)
    activity_html = render_activity(task)

    # Wrap activity in OOB swap div
    oob_html = f'<div id="activity-section" hx-swap-oob="innerHTML">{activity_html}</div>'

    return primary_html + oob_html


def render_watchers_section(task: Task) -> str:
    """Render the watchers section for a task."""
    watcher_count = TaskWatcher.count(task.id)
    watchers_data = TaskWatcher.get_watchers(task.id)
    watchers = [User.get_by_id(w.user_id) for w in watchers_data]
    watchers = [w for w in watchers if w]
    watcher_ids = {w.id for w in watchers}

    # Can manage watchers if owner or admin
    can_manage_watchers = task.owner_id == g.user.id or g.user.is_admin

    # Available users to add as watchers
    available_users = []
    if can_manage_watchers:
        all_users = User.get_all()
        available_users = [u for u in all_users if u.id not in watcher_ids]

    return render_template(
        "tasks/_watchers.html",
        task=task,
        watcher_count=watcher_count,
        watchers=watchers,
        can_manage_watchers=can_manage_watchers,
        available_users=available_users,
    )


def render_activity_with_watchers_oob(task: Task) -> str:
    """Render activity section plus out-of-band watchers update for HTMX."""
    activity_html = render_activity(task)
    watchers_html = render_watchers_section(task)

    # Wrap watchers in OOB swap div
    oob_html = f'<div id="watchers-section" hx-swap-oob="innerHTML">{watchers_html}</div>'

    return activity_html + oob_html


@bp.route("/")
@login_required
def index():
    """List all tasks with optional filtering."""
    status_filter = request.args.get("status", "")
    owner_filter = request.args.get("owner", "")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20

    # Build filter params
    status_arg = status_filter if status_filter in VALID_STATUSES else None
    owner_id_arg = g.user.id if owner_filter == "me" else None

    tasks = Task.get_all(
        status=status_arg,
        owner_id=owner_id_arg,
        current_user_id=g.user.id,
        limit=per_page,
        offset=(page - 1) * per_page,
    )

    # Get counts for filter badges
    total_count = Task.count(current_user_id=g.user.id)

    status_counts = {}
    for status in VALID_STATUSES:
        status_counts[status] = Task.count(status=status, current_user_id=g.user.id)

    # Get task owners for display
    owner_ids = {t.owner_id for t in tasks}
    owners = {u.id: u for u in [User.get_by_id(oid) for oid in owner_ids] if u}

    return render_partial_or_full(
        "tasks/_list.html",
        "tasks/index.html",
        tasks=tasks,
        owners=owners,
        status_filter=status_filter,
        owner_filter=owner_filter,
        page=page,
        per_page=per_page,
        total_count=total_count,
        status_counts=status_counts,
        valid_statuses=VALID_STATUSES,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    """Create a new task."""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip()
        is_private = request.form.get("is_private") == "1"

        errors = []
        if not title:
            errors.append("Title is required.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "tasks/form.html",
                task=None,
                title=title,
                description=description,
                due_date=due_date,
                is_private=is_private,
            )

        task = Task.create(
            title=title,
            owner_id=g.user.id,
            description=description or None,
            due_date=due_date or None,
            is_private=is_private,
        )

        # Auto-watch the owner
        TaskWatcher.add(task.id, g.user.id)

        # Log activity
        activity = Activity.log(
            task_id=task.id,
            action="created",
            user_id=g.user.id,
            details={"title": title},
        )

        # Queue notifications
        notification_service.queue_notifications(activity, task, get_base_url())

        flash("Task created.", "success")

        if is_htmx_request():
            return redirect(url_for("tasks.view", task_uuid=task.uuid))

        return redirect(url_for("tasks.view", task_uuid=task.uuid))

    return render_template("tasks/form.html", task=None)


@bp.route("/<task_uuid>")
@login_required
def view(task_uuid: str):
    """View a single task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return  # unreachable but helps type checker

    # Check access for private tasks (owner, admin, or watcher)
    if not can_view_task(task, g.user):
        abort(403)

    owner = User.get_by_id(task.owner_id)
    activities = Activity.get_for_task(task.id, limit=50)

    # Get users for activity display
    activity_user_ids = {a.user_id for a in activities if a.user_id}
    users = {u.id: u for u in [User.get_by_id(uid) for uid in activity_user_ids] if u}

    # Get comments for edit checking
    comments = Comment.get_for_task(task.id)
    comments_by_uuid = {c.uuid: c for c in comments}

    # Get allowed status transitions
    allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])

    edit_window_seconds = current_app.config.get("COMMENT_EDIT_WINDOW_SECONDS", 300)

    # Get watcher info
    is_watching = TaskWatcher.is_watching(task.id, g.user.id)
    watcher_count = TaskWatcher.count(task.id)
    watchers_data = TaskWatcher.get_watchers(task.id)
    watchers = [User.get_by_id(w.user_id) for w in watchers_data]
    watchers = [w for w in watchers if w]  # Filter out None
    watcher_ids = {w.id for w in watchers}

    # Can manage watchers if owner or admin
    can_manage_watchers = task.owner_id == g.user.id or g.user.is_admin

    # Available users to add as watchers (exclude current watchers)
    available_users = []
    if can_manage_watchers:
        all_users = User.get_all()
        available_users = [u for u in all_users if u.id not in watcher_ids]

    return render_template(
        "tasks/view.html",
        task=task,
        owner=owner,
        activities=activities,
        users=users,
        comments_by_uuid=comments_by_uuid,
        allowed_transitions=allowed_transitions,
        valid_statuses=VALID_STATUSES,
        format_file_size=attachment_service.format_file_size,
        edit_window_seconds=edit_window_seconds,
        is_watching=is_watching,
        watcher_count=watcher_count,
        watchers=watchers,
        can_manage_watchers=can_manage_watchers,
        available_users=available_users,
    )


@bp.route("/<task_uuid>/edit", methods=["GET", "POST"])
@login_required
def edit(task_uuid: str):
    """Edit a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return  # unreachable but helps type checker

    # Only owner or admin can edit
    if task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip()
        is_private = request.form.get("is_private") == "1"
        skip_notification = request.form.get("skip_notification") == "1"

        errors = []
        if not title:
            errors.append("Title is required.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "tasks/form.html",
                task=task,
                title=title,
                description=description,
                due_date=due_date,
                is_private=is_private,
            )

        changes = task.update(
            title=title,
            description=description or None,
            due_date=due_date or None,
            is_private=is_private,
        )

        if changes:
            activity = Activity.log(
                task_id=task.id,
                action="updated",
                user_id=g.user.id,
                details={"changes": [{"field": c[0], "old": c[1], "new": c[2]} for c in changes]},
                skip_notification=skip_notification,
            )
            # Queue notifications
            notification_service.queue_notifications(activity, task, get_base_url())
            flash("Task updated.", "success")

        return redirect(url_for("tasks.view", task_uuid=task.uuid))

    return render_template(
        "tasks/form.html",
        task=task,
        title=task.title,
        description=task.description or "",
        due_date=task.due_date or "",
        is_private=task.is_private,
    )


@bp.route("/<task_uuid>/status", methods=["POST"])
@login_required
def change_status(task_uuid: str):
    """Change task status."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return  # unreachable but helps type checker

    # Only owner or admin can change status
    if task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    new_status = request.form.get("status", "")

    if not task.can_transition_to(new_status):
        flash(f"Cannot change status from {task.status} to {new_status}.", "error")
    else:
        old_status = task.status
        if task.set_status(new_status):
            activity = Activity.log(
                task_id=task.id,
                action="status_changed",
                user_id=g.user.id,
                details={"old": old_status, "new": new_status},
            )
            # Queue notifications
            notification_service.queue_notifications(activity, task, get_base_url())
            flash(f"Status changed to {new_status}.", "success")

    if is_htmx_request():
        # Return updated status section with OOB activity update
        allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])
        return render_with_activity_oob(
            "tasks/_status.html",
            task=task,
            allowed_transitions=allowed_transitions,
        )

    return redirect(url_for("tasks.view", task_uuid=task.uuid))


@bp.route("/<task_uuid>/delete", methods=["POST"])
@login_required
def delete(task_uuid: str):
    """Delete a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return  # unreachable but helps type checker

    # Only owner or admin can delete
    if task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    task.delete()
    flash("Task deleted.", "success")

    return redirect(url_for("tasks.index"))


# --- Comments ---


@bp.route("/<task_uuid>/comments", methods=["POST"])
@login_required
def add_comment(task_uuid: str):
    """Add a comment to a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    content = request.form.get("content", "").strip()
    skip_notification = request.form.get("skip_notification") == "1"

    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    comment = Comment.create(task_id=task.id, user_id=g.user.id, content=content)

    # Auto-watch the commenter
    TaskWatcher.add(task.id, g.user.id)

    activity = Activity.log(
        task_id=task.id,
        action="commented",
        user_id=g.user.id,
        details={"comment_uuid": comment.uuid, "content": content},
        skip_notification=skip_notification,
    )

    # Queue notifications
    notification_service.queue_notifications(activity, task, get_base_url())

    if is_htmx_request():
        return render_activity_with_watchers_oob(task)

    flash("Comment added.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/comments/<comment_uuid>/delete", methods=["POST"])
@login_required
def delete_comment(task_uuid: str, comment_uuid: str):
    """Delete a comment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    comment = Comment.get_by_uuid(comment_uuid)
    if comment is None or comment.task_id != task.id:
        abort(404)
        return

    # Only comment author, task owner, or admin can delete
    if comment.user_id != g.user.id and task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    comment.delete()

    Activity.log(
        task_id=task.id,
        action="comment_deleted",
        user_id=g.user.id,
    )

    if is_htmx_request():
        return render_activity(task)

    flash("Comment deleted.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/comments/<comment_uuid>/edit", methods=["POST"])
@login_required
def edit_comment(task_uuid: str, comment_uuid: str):
    """Edit a comment (within edit window)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    comment = Comment.get_by_uuid(comment_uuid)
    if comment is None or comment.task_id != task.id:
        abort(404)
        return

    # Only comment author can edit
    if comment.user_id != g.user.id:
        abort(403)

    # Check edit window
    edit_window_seconds = current_app.config.get("COMMENT_EDIT_WINDOW_SECONDS", 300)
    if not comment.is_editable(edit_window_seconds):
        flash("Edit window has expired.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    content = request.form.get("content", "").strip()
    skip_notification = request.form.get("skip_notification") == "1"

    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    comment.update(content)

    # Update activity log with new content
    Activity.update_comment_content(comment_uuid, content)

    # Log the edit and queue notifications
    activity = Activity.log(
        task_id=task.id,
        action="comment_edited",
        user_id=g.user.id,
        details={"comment_uuid": comment.uuid, "content": content},
        skip_notification=skip_notification,
    )
    notification_service.queue_notifications(activity, task, get_base_url())

    if is_htmx_request():
        return render_activity(task)

    flash("Comment updated.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


# --- Attachments ---


@bp.route("/<task_uuid>/attachments", methods=["POST"])
@login_required
def upload_attachment(task_uuid: str):
    """Upload an attachment to a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    if "file" not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    # Check file size
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset to beginning

    max_size = current_app.config.get("MAX_UPLOAD_SIZE", 10 * 1024 * 1024)
    if size > max_size:
        flash(f"File too large. Maximum size is {max_size // (1024 * 1024)}MB.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    skip_notification = request.form.get("skip_notification") == "1"

    attachment = attachment_service.save_uploaded_file(
        file=file,
        task_id=task.id,
        uploaded_by=g.user.id,
    )

    # Auto-watch the uploader
    TaskWatcher.add(task.id, g.user.id)

    blob = attachment.get_blob()
    activity = Activity.log(
        task_id=task.id,
        action="attachment_added",
        user_id=g.user.id,
        details={
            "attachment_uuid": attachment.uuid,
            "filename": attachment.original_filename,
            "file_size": blob.file_size if blob else 0,
        },
        skip_notification=skip_notification,
    )

    # Queue notifications
    notification_service.queue_notifications(activity, task, get_base_url())

    if is_htmx_request():
        return render_activity_with_watchers_oob(task)

    flash("File uploaded.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/attachments/<attachment_uuid>")
@login_required
def download_attachment(task_uuid: str, attachment_uuid: str):
    """Download an attachment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    attachment = Attachment.get_by_uuid(attachment_uuid)
    if attachment is None or attachment.task_id != task.id:
        abort(404)
        return

    blob = attachment.get_blob()
    if blob is None:
        abort(404)
        return

    content = attachment_service.get_blob_content(blob)
    if content is None:
        abort(404)
        return

    return Response(
        content,
        mimetype=blob.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.original_filename}"',
            "Content-Length": str(blob.file_size),
        },
    )


@bp.route("/<task_uuid>/attachments/<attachment_uuid>/delete", methods=["POST"])
@login_required
def delete_attachment(task_uuid: str, attachment_uuid: str):
    """Delete an attachment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    attachment = Attachment.get_by_uuid(attachment_uuid)
    if attachment is None or attachment.task_id != task.id:
        abort(404)
        return

    # Only uploader, task owner, or admin can delete
    if attachment.uploaded_by != g.user.id and task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    filename = attachment.original_filename
    attachment_service.delete_attachment(attachment)

    Activity.log(
        task_id=task.id,
        action="attachment_deleted",
        user_id=g.user.id,
        details={"filename": filename},
    )

    if is_htmx_request():
        return render_activity(task)

    flash("Attachment deleted.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


# --- Watching ---


@bp.route("/<task_uuid>/watch", methods=["POST"])
@login_required
def watch(task_uuid: str):
    """Start watching a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    TaskWatcher.add(task.id, g.user.id)

    if is_htmx_request():
        button_html = render_template(
            "tasks/_watch_button.html",
            task=task,
            is_watching=True,
        )
        watchers_html = render_watchers_section(task)
        oob_html = f'<div id="watchers-section" hx-swap-oob="innerHTML">{watchers_html}</div>'
        return button_html + oob_html

    flash("You are now watching this task.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/unwatch", methods=["POST"])
@login_required
def unwatch(task_uuid: str):
    """Stop watching a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    TaskWatcher.remove(task.id, g.user.id)

    if is_htmx_request():
        button_html = render_template(
            "tasks/_watch_button.html",
            task=task,
            is_watching=False,
        )
        watchers_html = render_watchers_section(task)
        oob_html = f'<div id="watchers-section" hx-swap-oob="innerHTML">{watchers_html}</div>'
        return button_html + oob_html

    flash("You are no longer watching this task.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/watchers", methods=["POST"])
@login_required
def add_watcher(task_uuid: str):
    """Add a user as a watcher (owner/admin only)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Only owner or admin can manage watchers
    if task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    user_id = request.form.get("user_id", type=int)
    if not user_id:
        flash("No user selected.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    user = User.get_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    TaskWatcher.add(task.id, user_id)

    if is_htmx_request():
        return render_watchers_section(task)

    flash(f"{user.display_name or user.email} is now watching this task.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/watchers/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_watcher(task_uuid: str, user_id: int):
    """Remove a user from watchers (owner/admin only)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
        return

    # Only owner or admin can manage watchers
    if task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    # Can't remove the owner
    if user_id == task.owner_id:
        flash("Cannot remove the task owner from watchers.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    TaskWatcher.remove(task.id, user_id)

    if is_htmx_request():
        return render_watchers_section(task)

    flash("Watcher removed.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))
