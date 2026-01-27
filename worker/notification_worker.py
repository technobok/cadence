"""Background worker for sending notifications."""

import configparser
import logging
import sys
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import apsw
from cadence.services.ntfy_service import send_ntfy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_config() -> configparser.ConfigParser:
    """Load config from config.ini."""
    config = configparser.ConfigParser()
    config_path = Path(__file__).parent.parent / "instance" / "config.ini"
    if config_path.exists():
        config.read(config_path)
    return config


def get_db_connection(config: configparser.ConfigParser) -> apsw.Connection:
    """Get database connection."""
    db_path = config.get("database", "PATH", fallback="instance/cadence.sqlite3")
    # Make path relative to project root
    if not Path(db_path).is_absolute():
        db_path = str(Path(__file__).parent.parent / db_path)

    conn = apsw.Connection(db_path)
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def send_email_notification(
    config: configparser.ConfigParser,
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

    smtp_server = config.get("mail", "SMTP_SERVER", fallback="")
    smtp_port = config.getint("mail", "SMTP_PORT", fallback=587)
    smtp_use_tls = config.getboolean("mail", "SMTP_USE_TLS", fallback=True)
    smtp_username = config.get("mail", "SMTP_USERNAME", fallback="")
    smtp_password = config.get("mail", "SMTP_PASSWORD", fallback="")
    mail_sender = config.get("mail", "MAIL_SENDER", fallback="")

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
    config: configparser.ConfigParser,
    batch_size: int = 50,
    max_retries: int = 3,
) -> int:
    """Process pending notifications. Returns count processed."""
    cursor = conn.cursor()

    # Get pending notifications with user info
    cursor.execute(
        """
        SELECT n.id, n.uuid, n.user_id, n.task_id, n.channel, n.subject, n.body,
               n.body_html, n.status, n.retries, u.email, u.ntfy_topic
        FROM notification_queue n
        JOIN user u ON n.user_id = u.id
        WHERE n.status = 'pending' AND u.is_active = 1
        ORDER BY n.created_at ASC
        LIMIT ?
        """,
        (batch_size,),
    )

    notifications = cursor.fetchall()
    processed = 0
    ntfy_server = config.get("ntfy", "SERVER", fallback="https://ntfy.sh")

    for row in notifications:
        (
            notif_id,
            notif_uuid,
            user_id,
            task_id,
            channel,
            subject,
            body,
            body_html,
            status,
            retries,
            user_email,
            user_ntfy_topic,
        ) = row

        success = False

        try:
            if channel == "email":
                success = send_email_notification(config, user_email, subject, body, body_html)
            elif channel == "ntfy":
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
                    # No ntfy topic configured, mark as failed permanently
                    logger.warning(f"User {user_id} has no ntfy topic configured")
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


def run_worker():
    """Main worker loop."""
    config = get_config()
    poll_interval = config.getint("worker", "POLL_INTERVAL", fallback=5)
    batch_size = config.getint("worker", "BATCH_SIZE", fallback=50)
    max_retries = config.getint("worker", "MAX_RETRIES", fallback=3)

    logger.info(
        f"Starting notification worker (poll_interval={poll_interval}s, "
        f"batch_size={batch_size}, max_retries={max_retries})"
    )

    while True:
        try:
            conn = get_db_connection(config)
            processed = process_notifications(conn, config, batch_size, max_retries)
            if processed > 0:
                logger.info(f"Processed {processed} notifications")
            conn.close()
        except Exception as e:
            logger.error(f"Worker error: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()
