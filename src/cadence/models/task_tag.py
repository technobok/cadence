"""Task-Tag junction model for managing tags on tasks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class TaskTag:
    task_id: int
    tag_id: int
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> TaskTag:
        """Create TaskTag from database row."""
        return TaskTag(
            task_id=int(row[0]),
            tag_id=int(row[1]),
            created_at=str(row[2]),
        )

    @staticmethod
    def add(task_id: int, tag_id: int) -> bool:
        """
        Add a tag to a task.
        Returns True if added, False if already tagged.
        """
        now = datetime.now(UTC).isoformat()

        try:
            with transaction() as cursor:
                cursor.execute(
                    "INSERT INTO task_tag (task_id, tag_id, created_at) VALUES (?, ?, ?)",
                    (task_id, tag_id, now),
                )
            return True
        except Exception:
            # Already tagged (UNIQUE constraint) or other error
            return False

    @staticmethod
    def remove(task_id: int, tag_id: int) -> bool:
        """
        Remove a tag from a task.
        Returns True if removed, False if wasn't tagged.
        """
        with transaction() as cursor:
            cursor.execute(
                "DELETE FROM task_tag WHERE task_id = ? AND tag_id = ?",
                (task_id, tag_id),
            )
            return cursor.execute("SELECT changes()").fetchone()[0] > 0  # type: ignore[index]

    @staticmethod
    def has_tag(task_id: int, tag_id: int) -> bool:
        """Check if a task has a specific tag."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT 1 FROM task_tag WHERE task_id = ? AND tag_id = ?",
            (task_id, tag_id),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def get_tags_for_task(task_id: int) -> list[TaskTag]:
        """Get all tag associations for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT task_id, tag_id, created_at FROM task_tag "
            "WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )
        return [TaskTag._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def get_tag_ids_for_task(task_id: int) -> list[int]:
        """Get tag IDs for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT tag_id FROM task_tag WHERE task_id = ?",
            (task_id,),
        )
        return [int(row[0]) for row in cursor.fetchall() if row[0] is not None]

    @staticmethod
    def set_tags_for_task(task_id: int, tag_ids: list[int]) -> None:
        """Set the complete list of tags for a task (replaces existing)."""
        now = datetime.now(UTC).isoformat()

        with transaction() as cursor:
            # Remove all existing tags
            cursor.execute("DELETE FROM task_tag WHERE task_id = ?", (task_id,))

            # Add new tags
            for tag_id in tag_ids:
                cursor.execute(
                    "INSERT OR IGNORE INTO task_tag (task_id, tag_id, created_at) VALUES (?, ?, ?)",
                    (task_id, tag_id, now),
                )

    @staticmethod
    def count_for_task(task_id: int) -> int:
        """Count tags for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM task_tag WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
