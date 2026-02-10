"""Task watcher model for tracking users watching tasks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class TaskWatcher:
    task_id: int
    username: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> TaskWatcher:
        """Create TaskWatcher from database row."""
        return TaskWatcher(
            task_id=int(row[0]),
            username=str(row[1]),
            created_at=str(row[2]),
        )

    @staticmethod
    def add(task_id: int, username: str) -> bool:
        """
        Add a user as a watcher of a task.
        Returns True if added, False if already watching.
        """
        now = datetime.now(UTC).isoformat()

        try:
            with transaction() as cursor:
                cursor.execute(
                    "INSERT INTO task_watcher (task_id, username, created_at) VALUES (?, ?, ?)",
                    (task_id, username, now),
                )
            return True
        except Exception:
            # Already watching (UNIQUE constraint) or other error
            return False

    @staticmethod
    def remove(task_id: int, username: str) -> bool:
        """
        Remove a user from watching a task.
        Returns True if removed, False if wasn't watching.
        """
        with transaction() as cursor:
            cursor.execute(
                "DELETE FROM task_watcher WHERE task_id = ? AND username = ?",
                (task_id, username),
            )
            return cursor.execute("SELECT changes()").fetchone()[0] > 0  # type: ignore[index]

    @staticmethod
    def is_watching(task_id: int, username: str) -> bool:
        """Check if a user is watching a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT 1 FROM task_watcher WHERE task_id = ? AND username = ?",
            (task_id, username),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def get_watchers(task_id: int) -> list[TaskWatcher]:
        """Get all watchers for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT task_id, username, created_at FROM task_watcher "
            "WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )
        return [TaskWatcher._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def get_watcher_usernames(task_id: int) -> list[str]:
        """Get usernames of all watchers for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT username FROM task_watcher WHERE task_id = ?",
            (task_id,),
        )
        # username is NOT NULL in schema, so row[0] is always a str
        return [str(row[0]) for row in cursor.fetchall() if row[0] is not None]

    @staticmethod
    def count(task_id: int) -> int:
        """Count watchers for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM task_watcher WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
