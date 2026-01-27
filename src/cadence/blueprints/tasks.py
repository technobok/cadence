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
from cadence.models import VALID_STATUSES, Activity, Attachment, Comment, Task, User
from cadence.models.task import STATUS_TRANSITIONS
from cadence.services import attachment_service

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def render_partial_or_full(partial: str, full: str, **context):
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


def render_activity(task: Task) -> str:
    """Render the activity/timeline section for a task."""
    activities = Activity.get_for_task(task.id, limit=50)
    activity_user_ids = {a.user_id for a in activities if a.user_id}
    users = {u.id: u for u in [User.get_by_id(uid) for uid in activity_user_ids] if u}

    return render_template(
        "tasks/_activity.html",
        task=task,
        activities=activities,
        users=users,
        format_file_size=attachment_service.format_file_size,
    )


def render_with_activity_oob(primary_template: str, task: Task, **context) -> str:
    """Render primary template plus out-of-band activity update for HTMX."""
    primary_html = render_template(primary_template, task=task, **context)
    activity_html = render_activity(task)

    # Wrap activity in OOB swap div
    oob_html = f'<div id="activity-section" hx-swap-oob="innerHTML">{activity_html}</div>'

    return primary_html + oob_html


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

        # Log activity
        Activity.log(
            task_id=task.id,
            action="created",
            user_id=g.user.id,
            details={"title": title},
        )

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

    # Check access for private tasks
    if task.is_private and task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    owner = User.get_by_id(task.owner_id)
    activities = Activity.get_for_task(task.id, limit=50)

    # Get users for activity display
    activity_user_ids = {a.user_id for a in activities if a.user_id}
    users = {u.id: u for u in [User.get_by_id(uid) for uid in activity_user_ids] if u}

    # Get allowed status transitions
    allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])

    return render_template(
        "tasks/view.html",
        task=task,
        owner=owner,
        activities=activities,
        users=users,
        allowed_transitions=allowed_transitions,
        valid_statuses=VALID_STATUSES,
        format_file_size=attachment_service.format_file_size,
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
            Activity.log(
                task_id=task.id,
                action="updated",
                user_id=g.user.id,
                details={"changes": [{"field": c[0], "old": c[1], "new": c[2]} for c in changes]},
            )
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
            Activity.log(
                task_id=task.id,
                action="status_changed",
                user_id=g.user.id,
                details={"old": old_status, "new": new_status},
            )
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
    if task.is_private and task.owner_id != g.user.id and not g.user.is_admin:
        abort(403)

    content = request.form.get("content", "").strip()
    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("tasks.view", task_uuid=task_uuid))

    comment = Comment.create(task_id=task.id, user_id=g.user.id, content=content)

    Activity.log(
        task_id=task.id,
        action="commented",
        user_id=g.user.id,
        details={"comment_uuid": comment.uuid, "content": content},
    )

    if is_htmx_request():
        return render_activity(task)

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
    if task.is_private and task.owner_id != g.user.id and not g.user.is_admin:
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

    attachment = attachment_service.save_uploaded_file(
        file=file,
        task_id=task.id,
        uploaded_by=g.user.id,
    )

    blob = attachment.get_blob()
    Activity.log(
        task_id=task.id,
        action="attachment_added",
        user_id=g.user.id,
        details={
            "attachment_uuid": attachment.uuid,
            "filename": attachment.original_filename,
            "file_size": blob.file_size if blob else 0,
        },
    )

    if is_htmx_request():
        return render_activity(task)

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
    if task.is_private and task.owner_id != g.user.id and not g.user.is_admin:
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
