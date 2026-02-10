"""Attachment and FileBlob models."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cadence.db import get_db, transaction


@dataclass
class FileBlob:
    """Deduplicated file storage. Path derived from hash: {BLOBS_DIR}/{hash[:2]}/{hash}"""

    id: int
    sha256_hash: str
    file_size: int
    mime_type: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> FileBlob:
        """Create FileBlob from database row."""
        return FileBlob(
            id=int(row[0]),
            sha256_hash=str(row[1]),
            file_size=int(row[2]),
            mime_type=str(row[3]),
            created_at=str(row[4]),
        )

    @staticmethod
    def get_by_id(blob_id: int) -> FileBlob | None:
        """Get blob by ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, sha256_hash, file_size, mime_type, created_at FROM file_blob WHERE id = ?",
            (blob_id,),
        )
        row = cursor.fetchone()
        if row:
            return FileBlob._from_row(row)
        return None

    @staticmethod
    def get_by_hash(sha256_hash: str) -> FileBlob | None:
        """Get blob by hash (for deduplication check)."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, sha256_hash, file_size, mime_type, created_at "
            "FROM file_blob WHERE sha256_hash = ?",
            (sha256_hash,),
        )
        row = cursor.fetchone()
        if row:
            return FileBlob._from_row(row)
        return None

    @staticmethod
    def create(sha256_hash: str, file_size: int, mime_type: str) -> FileBlob:
        """Create a new file blob record."""
        now = datetime.now(UTC).isoformat()

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO file_blob (sha256_hash, file_size, mime_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (sha256_hash, file_size, mime_type, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            blob_id = int(row[0]) if row else 0

        return FileBlob(
            id=blob_id,
            sha256_hash=sha256_hash,
            file_size=file_size,
            mime_type=mime_type,
            created_at=now,
        )

    @staticmethod
    def get_or_create(sha256_hash: str, file_size: int, mime_type: str) -> tuple[FileBlob, bool]:
        """Get existing blob or create new one. Returns (blob, created)."""
        existing = FileBlob.get_by_hash(sha256_hash)
        if existing:
            return existing, False
        return FileBlob.create(sha256_hash, file_size, mime_type), True


@dataclass
class Attachment:
    """Per-upload attachment metadata, linked to a deduplicated FileBlob."""

    id: int
    uuid: str
    task_id: int
    file_blob_id: int
    original_filename: str
    uploaded_by: str
    uploaded_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Attachment:
        """Create Attachment from database row."""
        return Attachment(
            id=int(row[0]),
            uuid=str(row[1]),
            task_id=int(row[2]),
            file_blob_id=int(row[3]),
            original_filename=str(row[4]),
            uploaded_by=str(row[5]),
            uploaded_at=str(row[6]),
        )

    @staticmethod
    def get_by_id(attachment_id: int) -> Attachment | None:
        """Get attachment by ID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, file_blob_id, original_filename, uploaded_by, uploaded_at "
            "FROM attachment WHERE id = ?",
            (attachment_id,),
        )
        row = cursor.fetchone()
        if row:
            return Attachment._from_row(row)
        return None

    @staticmethod
    def get_by_uuid(attachment_uuid: str) -> Attachment | None:
        """Get attachment by UUID."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, file_blob_id, original_filename, uploaded_by, uploaded_at "
            "FROM attachment WHERE uuid = ?",
            (attachment_uuid,),
        )
        row = cursor.fetchone()
        if row:
            return Attachment._from_row(row)
        return None

    @staticmethod
    def create(
        task_id: int,
        file_blob_id: int,
        original_filename: str,
        uploaded_by: str,
    ) -> Attachment:
        """Create a new attachment."""
        now = datetime.now(UTC).isoformat()
        attachment_uuid = str(uuid.uuid4())

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO attachment (uuid, task_id, file_blob_id, original_filename, "
                "uploaded_by, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (attachment_uuid, task_id, file_blob_id, original_filename, uploaded_by, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            attachment_id = int(row[0]) if row else 0

        return Attachment(
            id=attachment_id,
            uuid=attachment_uuid,
            task_id=task_id,
            file_blob_id=file_blob_id,
            original_filename=original_filename,
            uploaded_by=uploaded_by,
            uploaded_at=now,
        )

    @staticmethod
    def get_for_task(task_id: int) -> list[Attachment]:
        """Get all attachments for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT id, uuid, task_id, file_blob_id, original_filename, uploaded_by, uploaded_at "
            "FROM attachment WHERE task_id = ? ORDER BY uploaded_at ASC",
            (task_id,),
        )
        return [Attachment._from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def count_for_task(task_id: int) -> int:
        """Count attachments for a task."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM attachment WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def get_blob(self) -> FileBlob | None:
        """Get the associated FileBlob."""
        return FileBlob.get_by_id(self.file_blob_id)

    def delete(self) -> None:
        """Delete the attachment (does not delete the blob)."""
        with transaction() as cursor:
            cursor.execute("DELETE FROM attachment WHERE id = ?", (self.id,))
