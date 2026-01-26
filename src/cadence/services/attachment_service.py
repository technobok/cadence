"""Attachment service for file handling."""

import hashlib
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from cadence.models.attachment import Attachment, FileBlob


def get_blob_path(sha256_hash: str) -> Path:
    """Get the storage path for a blob based on its hash."""
    blobs_dir = Path(current_app.config["BLOBS_DIRECTORY"])
    return blobs_dir / sha256_hash[:2] / sha256_hash


def save_uploaded_file(
    file: FileStorage,
    task_id: int,
    uploaded_by: int,
) -> Attachment:
    """
    Save an uploaded file with deduplication.
    Returns the created Attachment.
    """
    # Read file content and compute hash
    content = file.read()
    sha256_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)

    # Detect mime type
    mime_type = file.content_type or "application/octet-stream"

    # Get or create the blob record
    blob, created = FileBlob.get_or_create(sha256_hash, file_size, mime_type)

    # If this is a new blob, save the file to disk
    if created:
        blob_path = get_blob_path(sha256_hash)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(content)

    # Create the attachment record
    original_filename = file.filename or "unnamed"
    attachment = Attachment.create(
        task_id=task_id,
        file_blob_id=blob.id,
        original_filename=original_filename,
        uploaded_by=uploaded_by,
    )

    return attachment


def get_blob_content(blob: FileBlob) -> bytes | None:
    """Get the content of a blob from disk."""
    blob_path = get_blob_path(blob.sha256_hash)
    if blob_path.exists():
        return blob_path.read_bytes()
    return None


def delete_attachment(attachment: Attachment) -> None:
    """
    Delete an attachment.
    Only deletes the blob file if no other attachments reference it.
    """
    blob = attachment.get_blob()
    attachment.delete()

    # Check if any other attachments reference this blob
    if blob:
        from cadence.db import get_db

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM attachment WHERE file_blob_id = ?",
            (blob.id,),
        )
        row = cursor.fetchone()
        count = int(row[0]) if row else 0

        # If no more references, delete the blob file and record
        if count == 0:
            blob_path = get_blob_path(blob.sha256_hash)
            if blob_path.exists():
                blob_path.unlink()
            # Delete the blob record
            cursor.execute("DELETE FROM file_blob WHERE id = ?", (blob.id,))


def format_file_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
