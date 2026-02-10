"""Comment model."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class Comment:
    id: int
    uuid: str
    task_id: int
    username: str
    content: str
    created_at: str
    updated_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Comment:
        """Create Comment from database row."""
        return Comment(
            id=int(row[0]),
            uuid=str(row[1]),
            task_id=int(row[2]),
            username=str(row[3]),
            content=str(row[4]),
            created_at=str(row[5]),
            updated_at=str(row[6]),
        )

    @staticmethod
    def get_by_id(comment_id: int) -> Comment | None:
        """Get comment by ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, username, content, created_at, updated_at "
            "FROM comment WHERE id = ?",
            (comment_id,),
        )
        row = cursor.fetchone()
        if row:
            return Comment._from_row(row)
        return None

    @staticmethod
    def get_by_uuid(comment_uuid: str) -> Comment | None:
        """Get comment by UUID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, username, content, created_at, updated_at "
            "FROM comment WHERE uuid = ?",
            (comment_uuid,),
        )
        row = cursor.fetchone()
        if row:
            return Comment._from_row(row)
        return None

    @staticmethod
    def create(task_id: int, username: str, content: str) -> Comment:
        """Create a new comment."""
        now = datetime.now(UTC).isoformat()
        comment_uuid = str(uuid.uuid4())

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO comment (uuid, task_id, username, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (comment_uuid, task_id, username, content, now, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            comment_id = int(row[0]) if row else 0

        return Comment(
            id=comment_id,
            uuid=comment_uuid,
            task_id=task_id,
            username=username,
            content=content,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def get_for_task(task_id: int) -> list[Comment]:
        """Get all comments for a task, oldest first."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, username, content, created_at, updated_at "
            "FROM comment WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        )
        return [Comment._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def count_for_task(task_id: int) -> int:
        """Count comments for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM comment WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def delete(self) -> None:
        """Delete the comment."""
        with transaction() as cursor:
            cursor.execute("DELETE FROM comment WHERE id = ?", (self.id,))

    def update(self, content: str) -> None:
        """Update the comment content."""
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "UPDATE comment SET content = ?, updated_at = ? WHERE id = ?",
                (content, now, self.id),
            )
        self.content = content
        self.updated_at = now

    def is_editable(self, edit_window_seconds: int = 300) -> bool:
        """Check if comment is within the edit window."""
        try:
            updated = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            elapsed = (now - updated).total_seconds()
            return elapsed < edit_window_seconds
        except Exception:
            return False

    def seconds_until_edit_expires(self, edit_window_seconds: int = 300) -> int:
        """Get seconds remaining in edit window, or 0 if expired."""
        try:
            updated = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            elapsed = (now - updated).total_seconds()
            remaining = edit_window_seconds - elapsed
            return max(0, int(remaining))
        except Exception:
            return 0
