"""Omi's notification API: a short message on the student's phone, from our private Omi app.

POST {OMI_API_BASE}/v2/integrations/{OMI_APP_ID}/notification?uid=<uid>&message=<text>
with "Authorization: Bearer <OMI_APP_SECRET>" (docs.omi.me, apps/Notifications; uid and
message are query parameters in Omi's backend too). The student must have the app installed.
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger("dayline.omi")

TIMEOUT_SECONDS = 10
MAX_MESSAGE = 300
DEMO_UID_PREFIX = "demo-omi-"

# Plain explanations of Omi's answers, for the activity log and the simulator.
_STATUS = {
    401: "Omi rejected the app secret (check OMI_APP_SECRET)",
    403: "Omi refused: the Dayline app isn't installed for this Omi account, or the app secret is wrong",
    404: "Omi doesn't know this app or user (check OMI_APP_ID and the Omi user id)",
    429: "Omi's notification limit was reached; try again later",
}


@dataclass
class Notified:
    sent: bool
    detail: str  # plain words, e.g. "Sent to Omi" or why not


def configured() -> bool:
    return bool(settings.omi_app_id and settings.omi_app_secret)


def is_demo_uid(uid: str | None) -> bool:
    return bool(uid) and uid.startswith(DEMO_UID_PREFIX)


def notify(uid: str, message: str, transport: httpx.BaseTransport | None = None) -> Notified:
    """Send one notification. Never raises: the reply is also in the app either way."""
    if is_demo_uid(uid):
        return Notified(False, "Simulated device: shown in Dayline instead of sent to a phone")
    if not configured():
        return Notified(False, "Omi notifications aren't set up (OMI_APP_ID and OMI_APP_SECRET)")
    text = message.strip()
    if len(text) > MAX_MESSAGE:
        text = text[: MAX_MESSAGE - 1].rstrip() + "…"
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = client.post(
                f"{settings.omi_api_base}/v2/integrations/{settings.omi_app_id}/notification",
                params={"uid": uid, "message": text},
                headers={"Authorization": f"Bearer {settings.omi_app_secret}"},
            )
    except httpx.HTTPError as exc:
        log.warning("Omi notification failed: %r", exc)
        return Notified(False, "Couldn't reach Omi to send the notification")
    if response.status_code == 200:
        return Notified(True, "Sent to Omi")
    log.warning("Omi notification answered HTTP %s", response.status_code)
    return Notified(False, _STATUS.get(response.status_code, f"Omi answered HTTP {response.status_code}"))
