"""Tasks blueprint for task management."""

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from cadence.blueprints.auth import login_required
from cadence.models import VALID_STATUSES, Activity, Task, User
from cadence.models.task import STATUS_TRANSITIONS

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def render_partial_or_full(partial: str, full: str, **context):
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


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
    activities = Activity.get_for_task(task.id, limit=20)

    # Get users for activity display
    activity_user_ids = {a.user_id for a in activities if a.user_id}
    activity_users = {u.id: u for u in [User.get_by_id(uid) for uid in activity_user_ids] if u}

    # Get allowed status transitions
    allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])

    return render_template(
        "tasks/view.html",
        task=task,
        owner=owner,
        activities=activities,
        activity_users=activity_users,
        allowed_transitions=allowed_transitions,
        valid_statuses=VALID_STATUSES,
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
        # Return updated status section
        allowed_transitions = STATUS_TRANSITIONS.get(task.status, [])
        return render_template(
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
