"""Tags blueprint for tag management (admin only)."""

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from cadence.blueprints.auth import admin_required
from cadence.models import TAG_COLORS, Tag

bp = Blueprint("tags", __name__, url_prefix="/tags")


def is_htmx_request() -> bool:
    """Check if this is an HTMX request."""
    return request.headers.get("HX-Request") == "true"


def render_partial_or_full(partial: str, full: str, **context):
    """Render partial template for HTMX, full page otherwise."""
    template = partial if is_htmx_request() else full
    return render_template(template, **context)


@bp.route("/")
@admin_required
def index():
    """List all tags with usage count."""
    tags = Tag.get_all()

    # Add usage count to each tag
    tags_with_count = []
    for tag in tags:
        tags_with_count.append(
            {
                "tag": tag,
                "usage_count": tag.usage_count(),
            }
        )

    return render_partial_or_full(
        "tags/_list.html",
        "tags/index.html",
        tags=tags_with_count,
    )


@bp.route("/<tag_uuid>/edit", methods=["GET", "POST"])
@admin_required
def edit(tag_uuid: str):
    """Edit a tag."""
    tag = Tag.get_by_uuid(tag_uuid)
    if tag is None:
        abort(404)
        return

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "").strip()

        errors = []
        if not name:
            errors.append("Name is required.")

        # Check for duplicate name (case-insensitive)
        existing = Tag.get_by_name(name)
        if existing and existing.id != tag.id:
            errors.append("A tag with this name already exists.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "tags/edit.html",
                tag=tag,
                tag_colors=TAG_COLORS,
                name=name,
                color=color,
            )

        tag.update(name=name, color=color if color in TAG_COLORS else None)
        flash(f"Tag '{tag.name}' updated.", "success")

        return redirect(url_for("tags.index"))

    return render_template(
        "tags/edit.html",
        tag=tag,
        tag_colors=TAG_COLORS,
        name=tag.name,
        color=tag.color,
    )


@bp.route("/<tag_uuid>/delete", methods=["POST"])
@admin_required
def delete(tag_uuid: str):
    """Delete a tag."""
    tag = Tag.get_by_uuid(tag_uuid)
    if tag is None:
        abort(404)
        return

    usage_count = tag.usage_count()

    # Check if force delete is requested
    force = request.form.get("force") == "1"

    if usage_count > 0 and not force:
        flash(
            f"Tag '{tag.name}' is used by {usage_count} task(s). "
            "Use the confirm dialog to delete it anyway.",
            "error",
        )
        return redirect(url_for("tags.index"))

    tag_name = tag.name
    tag.delete()
    flash(f"Tag '{tag_name}' deleted.", "success")

    return redirect(url_for("tags.index"))
