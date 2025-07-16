"""Notification handling via ntfy."""

import requests
from typing import List, Dict, Optional
import logging

from . import config

log = logging.getLogger(__name__)


class NotificationClient:
    def __init__(self):
        self.topic = config.NTFY_TOPIC
        self.token = config.NTFY_TOKEN

    def send_release_notification(
        self,
        artist_name: str,
        title: str,
        release_date: str,
        release_type: Optional[str] = None,
    ):
        """Send a notification for a new release."""
        if release_type:
            message = f"{release_date}: {artist_name} - {title} ({release_type})"
        else:
            message = f"{release_date}: {artist_name} - {title}"

        self.send_notification(message)

    def send_notification(self, message: str):
        """Send a notification via ntfy."""
        try:
            response = requests.post(
                self.topic,
                data=message,
                headers={
                    "Authorization": self.token,
                    "Tags": "tada",
                },
                timeout=10,
            )

            if response.status_code == 200:
                log.info(f"Notification sent successfully: {message}")
            else:
                log.error(
                    f"Failed to send notification. Status: {response.status_code}"
                )

        except requests.RequestException as e:
            log.error(f"Error sending notification: {e}")

    def send_summary_notification(self, releases: List[Dict]):
        """Send a summary notification for multiple releases."""
        if not releases:
            return

        if len(releases) == 1:
            release = releases[0]
            self.send_release_notification(
                release["artist_name"],
                release["title"],
                release["release_date"],
                release.get("release_type", None),
            )
        else:
            # Send a summary for multiple releases
            message = f"🎵 {len(releases)} new releases found:\n"
            for release in releases[:5]:  # Limit to first 5 to avoid long messages
                message += f"• {release['artist_name']} - {release['title']}\n"

            if len(releases) > 5:
                message += f"... and {len(releases) - 5} more"

            self.send_notification(message)


class HealthCheck:
    def __init__(self):
        self.url = config.HEALTHCHECK_URL
        self.timeout = config.HEALTHCHECK_TIMEOUT

    def ping(self, success: bool = True):
        """Send a health check ping."""
        try:
            if success:
                response = requests.get(self.url, timeout=self.timeout)
            else:
                # Send failure ping
                response = requests.get(f"{self.url}/fail", timeout=self.timeout)

            if response.status_code == 200:
                log.debug("Health check ping sent successfully")
            else:
                log.warning(
                    f"Health check ping failed with status: {response.status_code}"
                )

        except requests.RequestException as e:
            log.error(f"Error sending health check ping: {e}")

    def ping_start(self):
        """Send a start ping."""
        try:
            response = requests.get(f"{self.url}/start", timeout=self.timeout)
            log.debug("Health check start ping sent")
        except requests.RequestException as e:
            log.error(f"Error sending health check start ping: {e}")
