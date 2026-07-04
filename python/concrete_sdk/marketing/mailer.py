"""Outreach email delivery for the marketing pipeline.

Testing phase: everything sends to/from mf@concrete.ch, never a real lead's
address. TEST_MAILBOX is the single place that defines that address.
"""

from google.cloud import secretmanager

import resend

TEST_MAILBOX = "mf@concrete.ch"


class MarketingMailer:
    def __init__(self, project_id: str, secret_id: str = "RESEND_API_KEY"):
        self._project_id = project_id
        self._secret_id = secret_id
        self._api_key: str | None = None

    @property
    def api_key(self) -> str:
        """Cached Resend API key."""
        if self._api_key is None:
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{self._project_id}/secrets/{self._secret_id}/versions/latest"
            self._api_key = client.access_secret_version(request={"name": name}).payload.data.decode().strip()
        return self._api_key

    def send(self, subject: str, html: str, to: str = TEST_MAILBOX, from_: str = TEST_MAILBOX) -> None:
        resend.api_key = self.api_key
        resend.Emails.send({"from": from_, "to": to, "subject": subject, "html": html})
