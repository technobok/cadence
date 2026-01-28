"""Task model."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction

# Valid status transitions
VALID_STATUSES = ["new", "in_progress", "on_hold", "complete"]
STATUS_TRANSITIONS = {
    "new": ["in_progress", "on_hold", "complete"],
    "in_progress": ["on_hold", "complete"],
    "on_hold": ["in_progress", "complete"],
    "complete": ["in_progress"],  # Allow reopening
}


@dataclass
class Task:
    id: int
    uuid: str
    title: str
    description: str | None
    status: str
    owner_id: int
    due_date: str | None
    is_private: bool
    created_at: str
    updated_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Task:
        """Create Task from database row."""
        return Task(
            id=int(row[0]),
            uuid=str(row[1]),
            title=str(row[2]),
            description=str(row[3]) if row[3] else None,
            status=str(row[4]),
            owner_id=int(row[5]),
            due_date=str(row[6]) if row[6] else None,
            is_private=bool(row[7]),
            created_at=str(row[8]),
            updated_at=str(row[9]),
        )

    @staticmethod
    def get_by_id(task_id: int) -> Task | None:
        """Get task by internal ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, title, description, status, owner_id, "
            "due_date, is_private, created_at, updated_at FROM task WHERE id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        if row:
            return Task._from_row(row)
        return None

    @staticmethod
    def get_by_uuid(task_uuid: str) -> Task | None:
        """Get task by UUID (for external references)."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, title, description, status, owner_id, "
            "due_date, is_private, created_at, updated_at FROM task WHERE uuid = ?",
            (task_uuid,),
        )
        row = cursor.fetchone()
        if row:
            return Task._from_row(row)
        return None

    @staticmethod
    def create(
        title: str,
        owner_id: int,
        description: str | None = None,
        due_date: str | None = None,
        is_private: bool = False,
    ) -> Task:
        """Create a new task."""
        now = datetime.now(UTC).isoformat()
        task_uuid = str(uuid.uuid4())

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO task (uuid, title, description, status, owner_id, "
                "due_date, is_private, created_at, updated_at) "
                "VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?)",
                (task_uuid, title, description, owner_id, due_date, int(is_private), now, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            task_id = int(row[0]) if row else 0

        return Task(
            id=task_id,
            uuid=task_uuid,
            title=title,
            description=description,
            status="new",
            owner_id=owner_id,
            due_date=due_date,
            is_private=is_private,
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        title: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        is_private: bool | None = None,
        owner_id: int | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Update task fields. Returns list of changes as (field, old_value, new_value).
        Does not update status - use set_status() for that.
        """
        now = datetime.now(UTC).isoformat()
        changes: list[tuple[str, str, str]] = []
        updates = []
        params = []

        if title is not None and title != self.title:
            changes.append(("title", self.title, title))
            updates.append("title = ?")
            params.append(title)
            self.title = title

        if description is not None and description != self.description:
            changes.append(("description", self.description or "", description))
            updates.append("description = ?")
            params.append(description)
            self.description = description

        if due_date is not None and due_date != self.due_date:
            changes.append(("due_date", self.due_date or "", due_date))
            updates.append("due_date = ?")
            params.append(due_date if due_date else None)
            self.due_date = due_date if due_date else None

        if is_private is not None and is_private != self.is_private:
            changes.append(("is_private", str(self.is_private), str(is_private)))
            updates.append("is_private = ?")
            params.append(int(is_private))
            self.is_private = is_private

        if owner_id is not None and owner_id != self.owner_id:
            updates.append("owner_id = ?")
            params.append(owner_id)
            self.owner_id = owner_id

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(self.id)

            with transaction() as cursor:
                cursor.execute(
                    f"UPDATE task SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
            self.updated_at = now

        return changes

    def set_status(self, new_status: str) -> bool:
        """
        Change task status if transition is valid.
        Returns True if status was changed, False if transition not allowed.
        """
        if new_status not in VALID_STATUSES:
            return False

        if new_status == self.status:
            return False

        allowed = STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            return False

        now = datetime.now(UTC).isoformat()

        with transaction() as cursor:
            cursor.execute(
                "UPDATE task SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, self.id),
            )

        self.status = new_status
        self.updated_at = now
        return True

    def can_transition_to(self, new_status: str) -> bool:
        """Check if transition to new_status is allowed."""
        if new_status not in VALID_STATUSES:
            return False
        if new_status == self.status:
            return False
        return new_status in STATUS_TRANSITIONS.get(self.status, [])

    @staticmethod
    def get_all(
        status: str | None = None,
        owner_id: int | None = None,
        include_private: bool = False,
        current_user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """Get tasks with optional filtering."""
        db = get_db()
        cursor = db.cursor()

        conditions = []
        params: list[int | str] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if owner_id:
            conditions.append("owner_id = ?")
            params.append(owner_id)

        if not include_private and current_user_id:
            # Show public tasks OR private tasks owned by/watched by current user
            conditions.append("""
                (is_private = 0
                 OR owner_id = ?
                 OR id IN (SELECT task_id FROM task_watcher WHERE user_id = ?))
            """)
            params.append(current_user_id)
            params.append(current_user_id)
        elif not include_private:
            conditions.append("is_private = 0")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.append(limit)
        params.append(offset)

        cursor.execute(
            f"SELECT id, uuid, title, description, status, owner_id, "
            f"due_date, is_private, created_at, updated_at FROM task "
            f"{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )

        return [Task._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def count(
        status: str | None = None,
        owner_id: int | None = None,
        include_private: bool = False,
        current_user_id: int | None = None,
    ) -> int:
        """Count tasks with optional filtering."""
        db = get_db()
        cursor = db.cursor()

        conditions = []
        params: list[int | str] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if owner_id:
            conditions.append("owner_id = ?")
            params.append(owner_id)

        if not include_private and current_user_id:
            conditions.append("""
                (is_private = 0
                 OR owner_id = ?
                 OR id IN (SELECT task_id FROM task_watcher WHERE user_id = ?))
            """)
            params.append(current_user_id)
            params.append(current_user_id)
        elif not include_private:
            conditions.append("is_private = 0")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"SELECT COUNT(*) FROM task {where_clause}", params)
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def delete(self) -> None:
        """Delete the task."""
        with transaction() as cursor:
            cursor.execute("DELETE FROM task WHERE id = ?", (self.id,))
