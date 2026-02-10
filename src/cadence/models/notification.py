"""Notification queue model."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class Notification:
    id: int
    uuid: str
    username: str
    task_id: int | None
    channel: str  # 'email' or 'ntfy'
    subject: str
    body: str
    body_html: str | None
    status: str  # 'pending', 'sent', 'failed'
    retries: int
    created_at: str
    sent_at: str | None

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Notification:
        """Create Notification from database row."""
        return Notification(
            id=int(row[0]),
            uuid=str(row[1]),
            username=str(row[2]),
            task_id=int(row[3]) if row[3] is not None else None,
            channel=str(row[4]),
            subject=str(row[5]),
            body=str(row[6]),
            body_html=str(row[7]) if row[7] else None,
            status=str(row[8]),
            retries=int(row[9]),
            created_at=str(row[10]),
            sent_at=str(row[11]) if row[11] else None,
        )

    @staticmethod
    def create(
        username: str,
        channel: str,
        subject: str,
        body: str,
        body_html: str | None = None,
        task_id: int | None = None,
    ) -> Notification:
        """Create a new notification in the queue."""
        now = datetime.now(UTC).isoformat()
        notification_uuid = str(uuid.uuid4())

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO notification_queue "
                "(uuid, username, task_id, channel, subject, body, body_html, status, retries, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)",
                (notification_uuid, username, task_id, channel, subject, body, body_html, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            notification_id = int(row[0]) if row else 0

        return Notification(
            id=notification_id,
            uuid=notification_uuid,
            username=username,
            task_id=task_id,
            channel=channel,
            subject=subject,
            body=body,
            body_html=body_html,
            status="pending",
            retries=0,
            created_at=now,
            sent_at=None,
        )

    @staticmethod
    def get_pending(limit: int = 50) -> list[Notification]:
        """Get pending notifications ready to be sent."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, username, task_id, channel, subject, body, body_html, "
            "status, retries, created_at, sent_at "
            "FROM notification_queue "
            "WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        return [Notification._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(notification_id: int) -> Notification | None:
        """Get notification by ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, username, task_id, channel, subject, body, body_html, "
            "status, retries, created_at, sent_at "
            "FROM notification_queue WHERE id = ?",
            (notification_id,),
        )
        row = cursor.fetchone()
        if row:
            return Notification._from_row(row)
        return None

    def mark_sent(self) -> None:
        """Mark notification as successfully sent."""
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "UPDATE notification_queue SET status = 'sent', sent_at = ? WHERE id = ?",
                (now, self.id),
            )
        self.status = "sent"
        self.sent_at = now

    def mark_failed(self, max_retries: int = 3) -> None:
        """
        Mark notification as failed and increment retry count.
        If max retries exceeded, marks as permanently failed.
        """
        new_retries = self.retries + 1
        new_status = "pending" if new_retries < max_retries else "failed"

        with transaction() as cursor:
            cursor.execute(
                "UPDATE notification_queue SET status = ?, retries = ? WHERE id = ?",
                (new_status, new_retries, self.id),
            )

        self.retries = new_retries
        self.status = new_status

    @staticmethod
    def count_pending() -> int:
        """Count pending notifications."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM notification_queue WHERE status = 'pending'")
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def cleanup_old(days: int = 30) -> int:
        """
        Delete notifications older than specified days that are sent or failed.
        Returns number deleted.
        """
        cutoff = datetime.now(UTC).isoformat()
        # Simple approach: delete all sent/failed older than N days
        with transaction() as cursor:
            cursor.execute(
                "DELETE FROM notification_queue "
                "WHERE status IN ('sent', 'failed') "
                "AND datetime(created_at) < datetime(?, '-' || ? || ' days')",
                (cutoff, days),
            )
            row = cursor.execute("SELECT changes()").fetchone()
            return int(row[0]) if row else 0
