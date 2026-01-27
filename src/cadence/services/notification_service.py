"""Notification service for queuing task notifications."""

import mistune

from cadence.models import Activity, Notification, Task, TaskWatcher, User

# Markdown renderer for notifications
_md = mistune.create_markdown(escape=True, plugins=["strikethrough"])


def get_recipients(task: Task, actor_id: int | None) -> list[User]:
    """
    Get users who should be notified about a task change.

    Recipients are:
    - Task owner
    - All watchers
    Excluding:
    - The actor (person who made the change)
    - Inactive users
    """
    recipient_ids: set[int] = set()

    # Add task owner
    recipient_ids.add(task.owner_id)

    # Add watchers
    watcher_ids = TaskWatcher.get_watcher_user_ids(task.id)
    recipient_ids.update(watcher_ids)

    # Remove actor
    if actor_id is not None:
        recipient_ids.discard(actor_id)

    # Fetch users and filter out inactive
    recipients = []
    for user_id in recipient_ids:
        user = User.get_by_id(user_id)
        if user and user.is_active:
            recipients.append(user)

    return recipients


def _render_markdown(text: str) -> str:
    """Render markdown to HTML."""
    return str(_md(text))


def _wrap_html_email(content: str, task_url: str) -> str:
    """Wrap content in a styled HTML email template."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
             max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
    {content}
    <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
    <p style="margin: 0;">
        <a href="{task_url}" style="color: #1095c1; text-decoration: none;">View task in Cadence</a>
    </p>
</body>
</html>"""


def format_notification(
    activity: Activity,
    task: Task,
    actor: User | None,
    base_url: str,
) -> tuple[str, str, str]:
    """
    Format notification subject, body, and HTML body based on activity type.

    Returns:
        (subject, body_text, body_html) tuple
    """
    task_url = f"{base_url.rstrip('/')}/tasks/{task.uuid}"
    actor_name = actor.display_name or actor.email if actor else "Someone"

    action = activity.action
    details = activity.details or {}

    if action == "created":
        subject = f"[Cadence] New task: {task.title}"
        body = f"{actor_name} created a new task.\n\n{task_url}"
        html_content = f"<p><strong>{actor_name}</strong> created a new task.</p>"

    elif action == "updated":
        changes = details.get("changes", [])
        change_summary = ", ".join(c.get("field", "") for c in changes)
        subject = f"[Cadence] Task updated: {task.title}"
        body = f"{actor_name} updated {change_summary}.\n\n{task_url}"
        html_content = f"<p><strong>{actor_name}</strong> updated {change_summary}.</p>"

    elif action == "status_changed":
        old_status = details.get("old", "")
        new_status = details.get("new", "")
        subject = f"[Cadence] Status changed: {task.title}"
        body = f"{actor_name} changed status from {old_status} to {new_status}.\n\n{task_url}"
        html_content = (
            f"<p><strong>{actor_name}</strong> changed status from "
            f"<code>{old_status}</code> to <code>{new_status}</code>.</p>"
        )

    elif action == "commented":
        content = details.get("content", "")
        # Plain text: truncate long comments
        content_truncated = content[:200] + "..." if len(content) > 200 else content
        subject = f"[Cadence] Comment on: {task.title}"
        body = f"{actor_name} commented:\n\n{content_truncated}\n\n{task_url}"
        # HTML: render full markdown
        html_content = (
            f"<p><strong>{actor_name}</strong> commented:</p>"
            f'<blockquote style="margin: 16px 0; padding: 12px 16px; '
            f'background: #f5f5f5; border-left: 4px solid #1095c1;">'
            f"{_render_markdown(content)}</blockquote>"
        )

    elif action == "comment_edited":
        content = details.get("content", "")
        # Plain text: truncate long comments
        content_truncated = content[:200] + "..." if len(content) > 200 else content
        subject = f"[Cadence] Comment edited: {task.title}"
        body = f"{actor_name} edited their comment:\n\n{content_truncated}\n\n{task_url}"
        # HTML: render full markdown
        html_content = (
            f"<p><strong>{actor_name}</strong> edited their comment:</p>"
            f'<blockquote style="margin: 16px 0; padding: 12px 16px; '
            f'background: #f5f5f5; border-left: 4px solid #1095c1;">'
            f"{_render_markdown(content)}</blockquote>"
        )

    elif action == "attachment_added":
        filename = details.get("filename", "file")
        subject = f"[Cadence] Attachment added: {task.title}"
        body = f"{actor_name} uploaded {filename}.\n\n{task_url}"
        html_content = f"<p><strong>{actor_name}</strong> uploaded <code>{filename}</code>.</p>"

    else:
        subject = f"[Cadence] Activity on: {task.title}"
        body = f"{actor_name} performed action: {action}.\n\n{task_url}"
        html_content = f"<p><strong>{actor_name}</strong> performed action: {action}.</p>"

    # Add task title header to HTML
    html_header = f'<h2 style="margin: 0 0 16px 0; color: #333;">{task.title}</h2>'
    body_html = _wrap_html_email(html_header + html_content, task_url)

    return subject, body, body_html


def queue_notifications(
    activity: Activity,
    task: Task,
    base_url: str,
) -> int:
    """
    Queue notifications for an activity.

    Args:
        activity: The activity that triggered the notification
        task: The task involved
        base_url: Base URL for generating links

    Returns:
        Number of notifications queued
    """
    if activity.skip_notification:
        return 0

    # Get actor
    actor = User.get_by_id(activity.user_id) if activity.user_id else None

    # Get recipients
    recipients = get_recipients(task, activity.user_id)

    if not recipients:
        return 0

    # Format notification
    subject, body, body_html = format_notification(activity, task, actor, base_url)

    count = 0
    for user in recipients:
        # Queue email notification if user has it enabled
        if user.email_notifications:
            Notification.create(
                user_id=user.id,
                channel="email",
                subject=subject,
                body=body,
                body_html=body_html,
                task_id=task.id,
            )
            count += 1

        # Queue ntfy notification if user has a topic configured
        if user.ntfy_topic:
            Notification.create(
                user_id=user.id,
                channel="ntfy",
                subject=subject,
                body=body,
                task_id=task.id,
            )
            count += 1

    return count
