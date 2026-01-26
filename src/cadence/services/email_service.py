"""Email service for sending magic links and notifications."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app


def send_email(to_email: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    """
    Send an email via SMTP.

    Returns True if sent successfully, False otherwise.
    """
    smtp_server = current_app.config.get("SMTP_SERVER")
    smtp_port = current_app.config.get("SMTP_PORT", 587)
    smtp_use_tls = current_app.config.get("SMTP_USE_TLS", True)
    smtp_username = current_app.config.get("SMTP_USERNAME")
    smtp_password = current_app.config.get("SMTP_PASSWORD")
    mail_sender = current_app.config.get("MAIL_SENDER")

    if not smtp_server or not mail_sender:
        current_app.logger.warning("SMTP not configured, skipping email send")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_sender
    msg["To"] = to_email

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        if smtp_port == 465:
            # SSL connection
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.sendmail(mail_sender, to_email, msg.as_string())
        else:
            # STARTTLS connection
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.sendmail(mail_sender, to_email, msg.as_string())

        current_app.logger.info(f"Email sent to {to_email}: {subject}")
        return True

    except Exception as e:
        current_app.logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_magic_link(to_email: str, magic_link: str) -> bool:
    """Send a magic link login email."""
    subject = "Cadence - Login Link"

    body_text = f"""You requested to log in to Cadence.

Click the link below to log in:
{magic_link}

This link will expire in 1 hour.

If you didn't request this, you can safely ignore this email.
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
</head>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2>Login to Cadence</h2>
    <p>You requested to log in to Cadence.</p>
    <p>
        <a href="{magic_link}"
           style="display: inline-block; padding: 12px 24px; background: #1095c1;
                  color: white; text-decoration: none; border-radius: 4px;">
            Log In
        </a>
    </p>
    <p style="color: #666; font-size: 14px;">
        Or copy this link: {magic_link}
    </p>
    <p style="color: #666; font-size: 14px;">
        This link will expire in 1 hour.
    </p>
    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
    <p style="color: #999; font-size: 12px;">
        If you didn't request this, you can safely ignore this email.
    </p>
</body>
</html>
"""

    return send_email(to_email, subject, body_text, body_html)
