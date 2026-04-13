"""
pushover_notify.py
──────────────────
Send push notifications via the Pushover API.
"""

import requests

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier:
    """Send notifications through Pushover."""

    def __init__(self, api_token: str, user_key: str):
        self.api_token = api_token
        self.user_key = user_key

    def send(self, title: str, message: str, html: bool = False,
             priority: int = 0, url: str | None = None,
             url_title: str | None = None) -> bool:
        """
        Send a push notification.

        Args:
            title:     Notification title
            message:   Notification body
            html:      Whether the message contains HTML
            priority:  -2 (lowest) to 2 (emergency)
            url:       Optional URL to attach
            url_title: Optional title for the URL

        Returns:
            True if the notification was sent successfully.
        """
        payload = {
            "token": self.api_token,
            "user": self.user_key,
            "title": title,
            "message": message,
            "priority": priority,
            "html": 1 if html else 0,
        }

        if url:
            payload["url"] = url
        if url_title:
            payload["url_title"] = url_title

        try:
            resp = requests.post(PUSHOVER_API_URL, data=payload, timeout=15)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"[pushover] Failed to send notification: {e}")
            return False

    # ── Convenience methods ───────────────────────────────────────────

    def notify_success(self, merchant_name: str, total: float,
                       account_name: str, skipped: bool = False):
        """Send a notification for a successfully processed receipt."""
        status = "⚠️ DUPLICATE - not imported" if skipped else "✅ Added"
        self.send(
            title="👍 Receipt Processed",
            message=(
                f"Receipt Processed: {merchant_name} - "
                f"Amt: ${total:.2f} - Account: {account_name} {status}"
            ),
        )

    def notify_exception(self, merchant_name: str, total: float,
                         cardnumber: str | None, receipt_link: str | None = None):
        """Send a notification when account matching fails."""
        card_display = cardnumber or "Unknown"
        msg = (
            f"Account Not found: {merchant_name} - "
            f"${total:.2f} - Card: {card_display}"
        )
        if receipt_link:
            msg += f'\n<a href="{receipt_link}">View Receipt</a>'

        self.send(
            title="⚠️ Account matching Exception",
            message=msg,
            html=bool(receipt_link),
        )

    def notify_error(self, error_message: str):
        """Send a notification for an unexpected error."""
        self.send(
            title="❌ Receipt Processing Error",
            message=error_message,
            priority=1,
        )
