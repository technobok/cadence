"""Background worker for sending notifications."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import apsw
from cadence.config import parse_value, resolve_entry
from cadence.db import get_standalone_db
from cadence.services.ntfy_service import send_ntfy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Gatekeeper client singleton for user lookups
_gk_client: Any = None


def _get_gk() -> Any:
    """Get or create the GatekeeperClient instance for user lookups."""
    global _gk_client
    if _gk_client is not None:
        return _gk_client

    gk_db_path = os.environ.get("GATEKEEPER_DB")
    if not gk_db_path:
        logger.warning("GATEKEEPER_DB not set, cannot look up user emails")
        return None

    try:
        from gatekeeper.client import GatekeeperClient

        _gk_client = GatekeeperClient(db_path=gk_db_path)
        logger.info("Gatekeeper client initialized for worker")
        return _gk_client
    except Exception as e:
        logger.error(f"Failed to initialize Gatekeeper client: {e}")
        return None


def _get_config_value(key: str) -> str | int | bool | list[str]:
    """Read a config value from the database, falling back to registry default."""
    entry = resolve_entry(key)
    if not entry:
        raise ValueError(f"Unknown config key: {key}")
    db = get_standalone_db()
    row = db.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    if row:
        return parse_value(entry, str(row[0]))
    return entry.default


def send_email_notification(
    to_email: str,
    subject: str,
    body: str,
    body_html: str | None = None,
) -> bool:
    """Send email notification using SMTP."""
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_server = _get_config_value("mail.smtp_server")
    smtp_port = _get_config_value("mail.smtp_port")
    smtp_use_tls = _get_config_value("mail.smtp_use_tls")
    smtp_username = _get_config_value("mail.smtp_username")
    smtp_password = _get_config_value("mail.smtp_password")
    mail_sender = _get_config_value("mail.mail_sender")

    if not smtp_server or not mail_sender:
        logger.warning("SMTP not configured, skipping email send")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_sender
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.sendmail(mail_sender, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.sendmail(mail_sender, to_email, msg.as_string())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def process_notifications(
    conn: apsw.Connection,
    batch_size: int = 50,
    max_retries: int = 3,
) -> int:
    """Process pending notifications. Returns count processed."""
    cursor = conn.cursor()
    gk = _get_gk()

    # Get pending notifications
    cursor.execute(
        """
        SELECT id, uuid, username, task_id, channel, subject, body,
               body_html, status, retries
        FROM notification_queue
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (batch_size,),
    )

    notifications = cursor.fetchall()
    processed = 0
    ntfy_server = _get_config_value("ntfy.server")

    for row in notifications:
        (
            notif_id,
            notif_uuid,
            username,
            task_id,
            channel,
            subject,
            body,
            body_html,
            status,
            retries,
        ) = row

        # Look up user info from gatekeeper
        if not gk:
            logger.warning(f"Cannot process notification {notif_id}: no gatekeeper client")
            break

        gk_user = gk.get_user(username)
        if not gk_user or not gk_user.enabled:
            logger.info(f"Skipping notification for disabled/unknown user: {username}")
            # Mark as failed
            now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            cursor.execute(
                "UPDATE notification_queue SET status = 'failed', sent_at = ? WHERE id = ?",
                (now, notif_id),
            )
            processed += 1
            continue

        success = False

        try:
            if channel == "email":
                user_email = gk_user.email
                if user_email:
                    success = send_email_notification(user_email, subject, body, body_html)
                else:
                    logger.warning(f"User {username} has no email address")
                    success = False
            elif channel == "ntfy":
                user_ntfy_topic = gk.get_user_property(username, "cadence", "ntfy_topic")
                if user_ntfy_topic:
                    # Extract click URL from body if present
                    click_url = None
                    lines = body.strip().split("\n")
                    for line in lines:
                        if line.startswith("http"):
                            click_url = line.strip()
                            break

                    success = send_ntfy(
                        server=ntfy_server,
                        topic=user_ntfy_topic,
                        title=subject.replace("[Cadence] ", ""),
                        message=body.split("\n\n")[0] if "\n\n" in body else body,
                        click_url=click_url,
                    )
                else:
                    logger.warning(f"User {username} has no ntfy topic configured")
                    success = False

            # Update notification status
            now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            if success:
                cursor.execute(
                    "UPDATE notification_queue SET status = 'sent', sent_at = ? WHERE id = ?",
                    (now, notif_id),
                )
            else:
                new_retries = retries + 1
                new_status = "pending" if new_retries < max_retries else "failed"
                cursor.execute(
                    "UPDATE notification_queue SET status = ?, retries = ? WHERE id = ?",
                    (new_status, new_retries, notif_id),
                )

            processed += 1

        except Exception as e:
            logger.error(f"Error processing notification {notif_id}: {e}")
            # Mark as retry
            new_retries = retries + 1
            new_status = "pending" if new_retries < max_retries else "failed"
            cursor.execute(
                "UPDATE notification_queue SET status = ?, retries = ? WHERE id = ?",
                (new_status, new_retries, notif_id),
            )

    return processed


def run_worker() -> None:
    """Main worker loop."""
    poll_interval = _get_config_value("worker.poll_interval")
    batch_size = _get_config_value("worker.batch_size")
    max_retries = _get_config_value("worker.max_retries")

    logger.info(
        f"Starting notification worker (poll_interval={poll_interval}s, "
        f"batch_size={batch_size}, max_retries={max_retries})"
    )

    while True:
        try:
            db = get_standalone_db()
            processed = process_notifications(db, batch_size, max_retries)
            if processed > 0:
                logger.info(f"Processed {processed} notifications")
        except Exception as e:
            logger.error(f"Worker error: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()
