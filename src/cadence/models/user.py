"""User model."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cadence.db import get_db, transaction


@dataclass
class User:
    id: int
    uuid: str
    email: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    ntfy_topic: str | None
    created_at: str
    updated_at: str

    @staticmethod
    def get_by_id(user_id: int) -> User | None:
        """Get user by internal ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, email, display_name, is_active, is_admin, "
            "ntfy_topic, created_at, updated_at FROM user WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            return User(*row)
        return None

    @staticmethod
    def get_by_uuid(user_uuid: str) -> User | None:
        """Get user by UUID (for external references)."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, email, display_name, is_active, is_admin, "
            "ntfy_topic, created_at, updated_at FROM user WHERE uuid = ?",
            (user_uuid,),
        )
        row = cursor.fetchone()
        if row:
            return User(*row)
        return None

    @staticmethod
    def get_by_email(email: str) -> User | None:
        """Get user by email address."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, email, display_name, is_active, is_admin, "
            "ntfy_topic, created_at, updated_at FROM user WHERE email = ?",
            (email.lower(),),
        )
        row = cursor.fetchone()
        if row:
            return User(*row)
        return None

    @staticmethod
    def create(email: str, display_name: str | None = None, is_admin: bool = False) -> User:
        """Create a new user."""
        now = datetime.now(UTC).isoformat()
        user_uuid = str(uuid.uuid4())

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO user (uuid, email, display_name, is_active, is_admin, "
                "created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                (user_uuid, email.lower(), display_name, int(is_admin), now, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            user_id = int(row[0]) if row else 0

        return User(
            id=user_id,
            uuid=user_uuid,
            email=email.lower(),
            display_name=display_name,
            is_active=True,
            is_admin=is_admin,
            ntfy_topic=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def get_or_create(email: str) -> tuple[User, bool]:
        """Get existing user or create new one. Returns (user, created)."""
        user = User.get_by_email(email)
        if user:
            return user, False
        return User.create(email), True

    def update(
        self,
        display_name: str | None = None,
        ntfy_topic: str | None = None,
        is_active: bool | None = None,
        is_admin: bool | None = None,
    ) -> None:
        """Update user fields."""
        now = datetime.now(UTC).isoformat()

        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
            self.display_name = display_name

        if ntfy_topic is not None:
            updates.append("ntfy_topic = ?")
            params.append(ntfy_topic)
            self.ntfy_topic = ntfy_topic

        if is_active is not None:
            updates.append("is_active = ?")
            params.append(int(is_active))
            self.is_active = is_active

        if is_admin is not None:
            updates.append("is_admin = ?")
            params.append(int(is_admin))
            self.is_admin = is_admin

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(self.id)

            with transaction() as cursor:
                cursor.execute(
                    f"UPDATE user SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
            self.updated_at = now

    @staticmethod
    def get_all(include_inactive: bool = False) -> list[User]:
        """Get all users."""
        db = get_db()
        cursor = db.cursor()

        if include_inactive:
            cursor.execute(
                "SELECT id, uuid, email, display_name, is_active, is_admin, "
                "ntfy_topic, created_at, updated_at FROM user ORDER BY email"
            )
        else:
            cursor.execute(
                "SELECT id, uuid, email, display_name, is_active, is_admin, "
                "ntfy_topic, created_at, updated_at FROM user "
                "WHERE is_active = 1 ORDER BY email"
            )

        return [User(*row) for row in cursor.fetchall()]  # type: ignore[arg-type]

    @staticmethod
    def count() -> int:
        """Count total users."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM user")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
