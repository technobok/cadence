"""Tasks blueprint for task management."""

from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.wrappers import Response

from cadence.blueprints.auth import login_required
from cadence.models import (
    VALID_STATUSES,
    Activity,
    Attachment,
    Comment,
    Tag,
    Task,
    TaskTag,
    TaskWatcher,
    user_helpers,
)
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


def _gk() -> Any:
    """Get the gatekeeper client from app config."""
    return current_app.config.get("GATEKEEPER_CLIENT")


def _is_admin(username: str) -> bool:
    """Check if a user is a cadence admin."""
    return user_helpers.is_admin(_gk(), username)


def _display_name(username: str, fallback_fullname: str = "") -> str:
    """Get a display name for a username."""
    return user_helpers.get_display_name(_gk(), username, fallback_fullname)


def _display_name_via_gk(username: str) -> str:
    """Look up a username via gatekeeper and return a display name."""
    gk = _gk()
    gk_user = gk.get_user(username)
    return user_helpers.get_display_name(gk, username, gk_user.fullname if gk_user else "")


def can_view_task(task: Task, user: Any) -> bool:
    """Check if a user can view a task."""
    if not task.is_private:
        return True
    if task.owner == user.username:
        return True
    if _is_admin(user.username):
        return True
    # Watchers can view private tasks
    if TaskWatcher.is_watching(task.id, user.username):
        return True
    return False


def render_partial_or_full(partial: str, full: str, **context: Any) -> str:
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


def render_activity(task: Task) -> str:
    """Render the activity/timeline section for a task."""
    gk = _gk()
    activities = Activity.get_for_task(task.id, limit=50)
    activity_usernames = {a.username for a in activities if a.username}

    # Build username -> display_name mapping
    users: dict[str, str] = {}
    for username in activity_usernames:
        gk_user = gk.get_user(username)
        users[username] = user_helpers.get_display_name(
            gk, username, gk_user.fullname if gk_user else ""
        )

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


def render_with_activity_oob(primary_template: str, task: Task, **context: Any) -> str:
    """Render primary template plus out-of-band activity update for HTMX."""
    primary_html = render_template(primary_template, task=task, **context)
    activity_html = render_activity(task)

    # Wrap activity in OOB swap div
    oob_html = f'<div id="activity-section" hx-swap-oob="innerHTML">{activity_html}</div>'

    return primary_html + oob_html


def get_watchers_context(task: Task) -> dict[str, Any]:
    """Get watchers context data for a task."""
    gk = _gk()
    watcher_count = TaskWatcher.count(task.id)
    watchers_data = TaskWatcher.get_watchers(task.id)

    # Build watcher dicts with display info from gatekeeper
    watchers: list[dict[str, str]] = []
    watcher_usernames: set[str] = set()
    for w in watchers_data:
        watcher_usernames.add(w.username)
        gk_user = gk.get_user(w.username)
        watchers.append({
            "username": w.username,
            "display_name": user_helpers.get_display_name(
                gk, w.username, gk_user.fullname if gk_user else ""
            ),
            "email": gk_user.email if gk_user else "",
        })

    # Can manage watchers if owner or admin
    can_manage_watchers = task.owner == g.user.username or _is_admin(g.user.username)

    # Available users to add as watchers -- no longer have a User.get_all();
    # the search_users endpoint handles lookup instead
    available_users: list[dict[str, str]] = []

    return {
        "task": task,
        "watcher_count": watcher_count,
        "watchers": watchers,
        "can_manage_watchers": can_manage_watchers,
        "available_users": available_users,
    }


def render_watchers_section(task: Task) -> str:
    """Render the watchers section for a task."""
    return render_template("tasks/_watchers.html", **get_watchers_context(task))


def render_activity_with_watchers_oob(task: Task) -> str:
    """Render activity section plus out-of-band watchers update for HTMX."""
    activity_html = render_activity(task)
    watchers_html = render_watchers_section(task)

    # Wrap watchers in OOB swap div
    oob_html = f'<div id="watchers-section" hx-swap-oob="innerHTML">{watchers_html}</div>'

    return activity_html + oob_html


def get_tags_context(task: Task) -> dict[str, Any]:
    """Get tags context data for a task."""
    tag_ids = TaskTag.get_tag_ids_for_task(task.id)
    tags = [t for t in [Tag.get_by_id(tid) for tid in tag_ids] if t]

    # Can manage tags if owner or admin
    can_manage_tags = task.owner == g.user.username or _is_admin(g.user.username)

    return {
        "task": task,
        "tags": tags,
        "can_manage_tags": can_manage_tags,
    }


def render_tags_section(task: Task) -> str:
    """Render the tags section for a task."""
    return render_template("tasks/_tags.html", **get_tags_context(task))


@bp.route("/")
@login_required
def index() -> str:
    """List all tasks with optional filtering."""
    gk = _gk()
    status_filter = request.args.get("status", "")
    owner_filter = request.args.get("owner", "")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20

    # Build filter params
    status_arg = status_filter if status_filter in VALID_STATUSES else None
    owner_arg = g.user.username if owner_filter == "me" else None

    # Admins can see all tasks including private ones
    include_private = _is_admin(g.user.username)

    tasks = Task.get_all(
        status=status_arg,
        owner=owner_arg,
        current_username=g.user.username,
        include_private=include_private,
        limit=per_page,
        offset=(page - 1) * per_page,
    )

    # Get counts for filter badges
    total_count = Task.count(current_username=g.user.username, include_private=include_private)

    status_counts: dict[str, int] = {}
    for status in VALID_STATUSES:
        status_counts[status] = Task.count(
            status=status, current_username=g.user.username, include_private=include_private
        )

    # Get task owners for display -- map owner username -> display name string
    owner_usernames = {t.owner for t in tasks}
    owners: dict[str, str] = {}
    for username in owner_usernames:
        gk_user = gk.get_user(username)
        owners[username] = user_helpers.get_display_name(
            gk, username, gk_user.fullname if gk_user else ""
        )

    # Get tags for each task
    task_tags: dict[int, list[Tag]] = {}
    for task in tasks:
        tag_ids = TaskTag.get_tag_ids_for_task(task.id)
        task_tags[task.id] = [t for t in [Tag.get_by_id(tid) for tid in tag_ids] if t]

    return render_partial_or_full(
        "tasks/_list.html",
        "tasks/index.html",
        tasks=tasks,
        owners=owners,
        task_tags=task_tags,
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
def create() -> str | Response:
    """Create a new task."""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip()
        is_private = request.form.get("is_private") == "1"

        errors: list[str] = []
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
            owner=g.user.username,
            description=description or None,
            due_date=due_date or None,
            is_private=is_private,
        )

        # Auto-watch the owner
        TaskWatcher.add(task.id, g.user.username)

        # Log activity
        activity = Activity.log(
            task_id=task.id,
            action="created",
            username=g.user.username,
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
def view(task_uuid: str) -> str:
    """View a single task."""
    gk = _gk()
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Check access for private tasks (owner, admin, or watcher)
    if not can_view_task(task, g.user):
        abort(403)

    # Owner display name
    owner_gk = gk.get_user(task.owner)
    owner_display_name = user_helpers.get_display_name(
        gk, task.owner, owner_gk.fullname if owner_gk else ""
    )

    activities = Activity.get_for_task(task.id, limit=50)

    # Get users for activity display -- username -> display_name mapping
    activity_usernames = {a.username for a in activities if a.username}
    users: dict[str, str] = {}
    for username in activity_usernames:
        gk_user = gk.get_user(username)
        users[username] = user_helpers.get_display_name(
            gk, username, gk_user.fullname if gk_user else ""
        )

    # Get comments for edit checking
    comments = Comment.get_for_task(task.id)
    comments_by_uuid = {c.uuid: c for c in comments}

    # Get allowed status transitions
    allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])

    edit_window_seconds = current_app.config.get("COMMENT_EDIT_WINDOW_SECONDS", 300)

    # Get watcher info
    is_watching = TaskWatcher.is_watching(task.id, g.user.username)
    watcher_count = TaskWatcher.count(task.id)
    watchers_data = TaskWatcher.get_watchers(task.id)

    watchers: list[dict[str, str]] = []
    watcher_usernames: set[str] = set()
    for w in watchers_data:
        watcher_usernames.add(w.username)
        gk_user = gk.get_user(w.username)
        watchers.append({
            "username": w.username,
            "display_name": user_helpers.get_display_name(
                gk, w.username, gk_user.fullname if gk_user else ""
            ),
            "email": gk_user.email if gk_user else "",
        })

    # Can manage watchers if owner or admin
    can_manage_watchers = task.owner == g.user.username or _is_admin(g.user.username)

    # Available users to add as watchers -- handled via search_users endpoint
    available_users: list[dict[str, str]] = []

    # Get tags for this task
    tag_ids = TaskTag.get_tag_ids_for_task(task.id)
    tags = [t for t in [Tag.get_by_id(tid) for tid in tag_ids] if t]
    can_manage_tags = task.owner == g.user.username or _is_admin(g.user.username)

    return render_template(
        "tasks/view.html",
        task=task,
        owner_display_name=owner_display_name,
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
        tags=tags,
        can_manage_tags=can_manage_tags,
    )


@bp.route("/<task_uuid>/edit", methods=["GET", "POST"])
@login_required
def edit(task_uuid: str) -> str | Response:
    """Edit a task."""
    gk = _gk()
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can edit
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    # For admin owner-change: we no longer have User.get_all() so pass empty list;
    # the template can use a text input for the new owner username instead.
    all_users: list[Any] = []

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip()
        is_private = request.form.get("is_private") == "1"
        skip_notification = request.form.get("skip_notification") == "1"

        # Admin can change owner
        new_owner: str | None = None
        if _is_admin(g.user.username):
            owner_str = request.form.get("owner", "").strip()
            if owner_str:
                new_owner = owner_str

        errors: list[str] = []
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
                all_users=all_users,
            )

        changes = task.update(
            title=title,
            description=description or None,
            due_date=due_date or None,
            is_private=is_private,
        )

        # Handle owner change separately (admin only)
        if new_owner and new_owner != task.owner and _is_admin(g.user.username):
            new_owner_gk = gk.get_user(new_owner)
            if new_owner_gk:
                old_owner_display = _display_name_via_gk(task.owner)
                task.update(owner=new_owner)
                new_owner_display = _display_name_via_gk(new_owner)
                changes.append(("owner", old_owner_display, new_owner_display))
                # Auto-watch new owner
                TaskWatcher.add(task.id, new_owner)
            else:
                flash(f"User '{new_owner}' not found.", "error")

        if changes:
            activity = Activity.log(
                task_id=task.id,
                action="updated",
                username=g.user.username,
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
        all_users=all_users,
    )


@bp.route("/<task_uuid>/status", methods=["POST"])
@login_required
def change_status(task_uuid: str) -> str | Response:
    """Change task status."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can change status
    if task.owner != g.user.username and not _is_admin(g.user.username):
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
                username=g.user.username,
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
def delete(task_uuid: str) -> Response:
    """Delete a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only admin can delete tasks
    if not _is_admin(g.user.username):
        abort(403)

    task.delete()
    flash("Task deleted.", "success")

    return redirect(url_for("tasks.index"))


# --- Comments ---


@bp.route("/<task_uuid>/comments", methods=["POST"])
@login_required
def add_comment(task_uuid: str) -> str | Response:
    """Add a comment to a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    content = request.form.get("content", "").strip()
    skip_notification = request.form.get("skip_notification") == "1"

    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    comment = Comment.create(task_id=task.id, username=g.user.username, content=content)

    # Auto-watch the commenter
    TaskWatcher.add(task.id, g.user.username)

    activity = Activity.log(
        task_id=task.id,
        action="commented",
        username=g.user.username,
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
def delete_comment(task_uuid: str, comment_uuid: str) -> str | Response:
    """Delete a comment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    comment = Comment.get_by_uuid(comment_uuid)
    if comment is None or comment.task_id != task.id:
        abort(404)
    assert comment is not None

    # Only admin can delete comments
    if not _is_admin(g.user.username):
        abort(403)

    comment.delete()

    Activity.log(
        task_id=task.id,
        action="comment_deleted",
        username=g.user.username,
    )

    if is_htmx_request():
        return render_activity(task)

    flash("Comment deleted.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/comments/<comment_uuid>/edit", methods=["POST"])
@login_required
def edit_comment(task_uuid: str, comment_uuid: str) -> str | Response:
    """Edit a comment (admin can always edit, author within edit window)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    comment = Comment.get_by_uuid(comment_uuid)
    if comment is None or comment.task_id != task.id:
        abort(404)
    assert comment is not None

    # Admin can always edit; author can edit within window
    if not _is_admin(g.user.username):
        if comment.username != g.user.username:
            abort(403)

        # Check edit window for non-admin
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
        username=g.user.username,
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
def upload_attachment(task_uuid: str) -> str | Response:
    """Upload an attachment to a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

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
        uploaded_by=g.user.username,
    )

    # Auto-watch the uploader
    TaskWatcher.add(task.id, g.user.username)

    blob = attachment.get_blob()
    activity = Activity.log(
        task_id=task.id,
        action="attachment_added",
        username=g.user.username,
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
def download_attachment(task_uuid: str, attachment_uuid: str) -> Response:
    """Download an attachment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    attachment = Attachment.get_by_uuid(attachment_uuid)
    if attachment is None or attachment.task_id != task.id:
        abort(404)
    assert attachment is not None

    blob = attachment.get_blob()
    if blob is None:
        abort(404)
    assert blob is not None

    content = attachment_service.get_blob_content(blob)
    if content is None:
        abort(404)
    assert content is not None

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
def delete_attachment(task_uuid: str, attachment_uuid: str) -> str | Response:
    """Delete an attachment."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    attachment = Attachment.get_by_uuid(attachment_uuid)
    if attachment is None or attachment.task_id != task.id:
        abort(404)
    assert attachment is not None

    # Only admin can delete attachments
    if not _is_admin(g.user.username):
        abort(403)

    filename = attachment.original_filename
    attachment_service.delete_attachment(attachment)

    Activity.log(
        task_id=task.id,
        action="attachment_deleted",
        username=g.user.username,
        details={"filename": filename},
    )

    if is_htmx_request():
        return render_activity(task)

    flash("Attachment deleted.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


# --- Watching ---


@bp.route("/<task_uuid>/watch", methods=["POST"])
@login_required
def watch(task_uuid: str) -> str | Response:
    """Start watching a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    TaskWatcher.add(task.id, g.user.username)

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
def unwatch(task_uuid: str) -> str | Response:
    """Stop watching a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Check access for private tasks
    if not can_view_task(task, g.user):
        abort(403)

    TaskWatcher.remove(task.id, g.user.username)

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
def add_watcher(task_uuid: str) -> str | Response:
    """Add a user as a watcher (owner/admin only)."""
    gk = _gk()
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage watchers
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    username = request.form.get("username", "").strip()
    if not username:
        flash("No user selected.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    gk_user = gk.get_user(username)
    if not gk_user:
        flash("User not found.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    TaskWatcher.add(task.id, username)

    if is_htmx_request():
        return render_watchers_section(task)

    display_name = user_helpers.get_display_name(gk, username, gk_user.fullname)
    flash(f"{display_name} is now watching this task.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/watchers/<username>/remove", methods=["POST"])
@login_required
def remove_watcher(task_uuid: str, username: str) -> str | Response:
    """Remove a user from watchers (owner/admin only)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage watchers
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    # Can't remove the owner
    if username == task.owner:
        flash("Cannot remove the task owner from watchers.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    TaskWatcher.remove(task.id, username)

    if is_htmx_request():
        return render_watchers_section(task)

    flash("Watcher removed.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/users/search")
@login_required
def search_users(task_uuid: str) -> Response:
    """Search users for adding as watchers (returns JSON for Tom Select)."""
    gk = _gk()
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage watchers
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    query = request.args.get("q", "").strip()

    # Get current watcher usernames to exclude
    watcher_usernames = set(TaskWatcher.get_watcher_usernames(task.id))

    # Since we don't have a "list all users" API on the gatekeeper client,
    # we check if the query matches an exact username via gk.get_user().
    results: list[dict[str, str]] = []
    if query:
        gk_user = gk.get_user(query)
        if gk_user and gk_user.username not in watcher_usernames:
            results.append({
                "id": gk_user.username,
                "text": user_helpers.get_display_name(gk, gk_user.username, gk_user.fullname),
                "email": gk_user.email,
            })

    return jsonify(results)


# --- Tags ---


@bp.route("/<task_uuid>/tags/search")
@login_required
def search_tags(task_uuid: str) -> Response:
    """Search tags for adding to task (returns JSON for Tom Select)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage tags
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    query = request.args.get("q", "").strip()

    # Get current tag IDs to exclude
    current_tag_ids = set(TaskTag.get_tag_ids_for_task(task.id))

    # Search all tags
    if query:
        all_tags = Tag.search(query)
    else:
        all_tags = Tag.get_all()

    results: list[dict[str, Any]] = []
    for tag in all_tags:
        if tag.id in current_tag_ids:
            continue
        results.append(
            {
                "id": tag.id,
                "text": tag.name,
                "color": tag.color,
                "light": tag.is_light(),
            }
        )
        if len(results) >= 20:
            break

    return jsonify(results)


@bp.route("/<task_uuid>/tags", methods=["POST"])
@login_required
def add_tag(task_uuid: str) -> str | Response:
    """Add a tag to a task (supports tag_id or tag_name for inline creation)."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage tags
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    tag_id = request.form.get("tag_id", type=int)
    tag_name = request.form.get("tag_name", "").strip()

    tag: Tag | None = None

    if tag_id:
        tag = Tag.get_by_id(tag_id)
    elif tag_name:
        # Get or create tag by name
        tag = Tag.get_or_create(tag_name)

    if tag is None:
        flash("Tag not found.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    TaskTag.add(task.id, tag.id)

    if is_htmx_request():
        return render_tags_section(task)

    flash(f"Tag '{tag.name}' added.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))


@bp.route("/<task_uuid>/tags/<int:tag_id>/remove", methods=["POST"])
@login_required
def remove_tag(task_uuid: str, tag_id: int) -> str | Response:
    """Remove a tag from a task."""
    task = Task.get_by_uuid(task_uuid)
    if task is None:
        abort(404)
    assert task is not None

    # Only owner or admin can manage tags
    if task.owner != g.user.username and not _is_admin(g.user.username):
        abort(403)

    TaskTag.remove(task.id, tag_id)

    if is_htmx_request():
        return render_tags_section(task)

    flash("Tag removed.", "success")
    return redirect(url_for("tasks.view", task_uuid=task_uuid))
