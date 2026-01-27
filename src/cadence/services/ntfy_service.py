"""Ntfy notification service for sending push notifications."""

import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def send_ntfy(
    server: str,
    topic: str,
    title: str,
    message: str,
    click_url: str | None = None,
    priority: int = 3,
) -> bool:
    """
    Send a notification via ntfy.

    Args:
        server: ntfy server URL (e.g., https://ntfy.sh)
        topic: ntfy topic to publish to
        title: notification title
        message: notification body
        click_url: URL to open when notification is clicked
        priority: notification priority (1-5, default 3)

    Returns:
        True if sent successfully, False otherwise.
    """
    if not server or not topic:
        logger.warning("ntfy not configured, skipping notification")
        return False

    url = f"{server.rstrip('/')}/{topic}"

    headers = {
        "Title": title,
        "Priority": str(priority),
    }

    if click_url:
        headers["Click"] = click_url

    try:
        data = message.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                logger.info(f"ntfy notification sent to {topic}: {title}")
                return True
            else:
                logger.error(f"ntfy returned status {response.status}")
                return False

    except urllib.error.HTTPError as e:
        logger.error(f"ntfy HTTP error: {e.code} - {e.reason}")
        return False
    except urllib.error.URLError as e:
        logger.error(f"ntfy URL error: {e.reason}")
        return False
    except Exception as e:
        logger.error(f"ntfy error: {e}")
        return False
