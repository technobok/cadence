"""Activity log model."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class Activity:
    id: int
    uuid: str
    task_id: int
    username: str | None
    action: str
    details: dict[str, Any] | None
    logged_at: str
    skip_notification: bool

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Activity:
        """Create Activity from database row."""
        return Activity(
            id=int(row[0]),
            uuid=str(row[1]),
            task_id=int(row[2]),
            username=str(row[3]) if row[3] is not None else None,
            action=str(row[4]),
            details=json.loads(str(row[5])) if row[5] else None,
            logged_at=str(row[6]),
            skip_notification=bool(row[7]),
        )

    @staticmethod
    def get_by_id(activity_id: int) -> Activity | None:
        """Get activity by ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, username, action, details, logged_at, "
            "skip_notification FROM activity_log WHERE id = ?",
            (activity_id,),
        )
        row = cursor.fetchone()
        if row:
            return Activity._from_row(row)
        return None

    @staticmethod
    def log(
        task_id: int,
        action: str,
        username: str | None = None,
        details: dict[str, Any] | None = None,
        skip_notification: bool = False,
    ) -> Activity:
        """Log an activity for a task."""
        now = datetime.now(UTC).isoformat()
        activity_uuid = str(uuid.uuid4())
        details_json = json.dumps(details) if details else None

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO activity_log (uuid, task_id, username, action, details, "
                "logged_at, skip_notification) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    activity_uuid,
                    task_id,
                    username,
                    action,
                    details_json,
                    now,
                    int(skip_notification),
                ),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            activity_id = int(row[0]) if row else 0

        return Activity(
            id=activity_id,
            uuid=activity_uuid,
            task_id=task_id,
            username=username,
            action=action,
            details=details,
            logged_at=now,
            skip_notification=skip_notification,
        )

    @staticmethod
    def get_for_task(task_id: int, limit: int = 50, offset: int = 0) -> list[Activity]:
        """Get activity log entries for a task, newest first."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, username, action, details, logged_at, "
            "skip_notification FROM activity_log WHERE task_id = ? "
            "ORDER BY logged_at DESC LIMIT ? OFFSET ?",
            (task_id, limit, offset),
        )
        return [Activity._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def get_recent(
        limit: int = 50, username: str | None = None, hours: int | None = None
    ) -> list[Activity]:
        """Get recent activity across all tasks."""
        from datetime import timedelta

        db = get_db()
        cursor = db.cursor()

        if hours:
            since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
            if username:
                cursor.execute(
                    "SELECT id, uuid, task_id, username, action, details, logged_at, "
                    "skip_notification FROM activity_log WHERE username = ? "
                    "AND logged_at >= ? ORDER BY logged_at DESC LIMIT ?",
                    (username, since, limit),
                )
            else:
                cursor.execute(
                    "SELECT id, uuid, task_id, username, action, details, logged_at, "
                    "skip_notification FROM activity_log WHERE logged_at >= ? "
                    "ORDER BY logged_at DESC LIMIT ?",
                    (since, limit),
                )
        elif username:
            cursor.execute(
                "SELECT id, uuid, task_id, username, action, details, logged_at, "
                "skip_notification FROM activity_log WHERE username = ? "
                "ORDER BY logged_at DESC LIMIT ?",
                (username, limit),
            )
        else:
            cursor.execute(
                "SELECT id, uuid, task_id, username, action, details, logged_at, "
                "skip_notification FROM activity_log ORDER BY logged_at DESC LIMIT ?",
                (limit,),
            )

        return [Activity._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def get_in_date_range(start_date: str, end_date: str, limit: int = 1000) -> list[Activity]:
        """Get activity within a date range (inclusive)."""
        db = get_db()
        cursor = db.cursor()

        # Add time component to make end_date inclusive
        start = f"{start_date}T00:00:00"
        end = f"{end_date}T23:59:59"

        cursor.execute(
            "SELECT id, uuid, task_id, username, action, details, logged_at, "
            "skip_notification FROM activity_log "
            "WHERE logged_at >= ? AND logged_at <= ? "
            "ORDER BY logged_at DESC LIMIT ?",
            (start, end, limit),
        )

        return [Activity._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def update_comment_content(comment_uuid: str, new_content: str) -> bool:
        """Update the content in activity details for a comment."""
        db = get_db()
        cursor = db.cursor()
        # Find activity with this comment_uuid in details
        cursor.execute(
            "SELECT id, details FROM activity_log WHERE action = 'commented' "
            "AND json_extract(details, '$.comment_uuid') = ?",
            (comment_uuid,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        activity_id = int(row[0])
        details = json.loads(str(row[1])) if row[1] else {}
        details["content"] = new_content

        with transaction() as tx_cursor:
            tx_cursor.execute(
                "UPDATE activity_log SET details = ? WHERE id = ?",
                (json.dumps(details), activity_id),
            )
        return True
