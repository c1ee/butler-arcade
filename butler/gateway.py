"""The only module that calls Arcade. Turns catalog output into plain records; tests swap in a fake.

Facts from the live check (ticket 05) live here, not in callers:
- Send to one `recipient` plus `cc`. A comma-separated recipient lands in spam or is dropped.
- `ReplyToEmail` quotes the replied-to email and takes To from it.
- `UpdateEvent` returns a string, so re-read with `get_event` when the event is needed.
- Calendar notifications: only creating the event and adding an attendee email anyone.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr

from arcadepy import Arcade

from butler.config import Settings


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class Email:
    message_id: str
    thread_id: str
    sender: str  # bare lowercase address
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    body: str  # plain text, including whatever quote the sender's mail app pasted
    sent_at: datetime | None
    sender_name: str = ""  # display name from the From header, if any


@dataclass(frozen=True)
class Sent:
    message_id: str
    thread_id: str


@dataclass(frozen=True)
class Attendee:
    email: str
    response_status: str  # accepted / declined / tentative / needsAction
    additional_guests: int


@dataclass(frozen=True)
class Event:
    event_id: str
    title: str
    start: datetime
    end: datetime
    place: str
    description: str
    attendees: tuple[Attendee, ...]


class Gateway:
    def __init__(self, settings: Settings):
        self._client = Arcade(api_key=settings.arcade_api_key)
        self._user_id = settings.butler_user_id

    def _run(self, tool: str, **inputs):
        output = self._client.tools.execute(tool_name=tool, input=inputs, user_id=self._user_id).output
        if output is None:
            raise GatewayError(f"{tool}: no output")
        if output.error:
            raise GatewayError(f"{tool}: {output.error.message}")
        return output.value

    # Gmail

    def search_inbox(self, after: int) -> list[Email]:
        """Inbox emails received after `after` (epoch seconds), oldest first. `in:inbox` leaves out Butler's sent mail."""
        emails, page_token = [], None
        while True:
            inputs = {"query": f"in:inbox after:{after}", "result_detail": "full", "max_results": 10}
            if page_token:
                inputs["page_token"] = page_token
            value = self._run("Gmail.SearchEmailsByQuery", **inputs)
            emails += [_email(e, id_key="message_id", sender_key="sender") for e in value["emails"]]
            page_token = value["pagination"]["next_page_token"]
            if not value["pagination"]["has_next_page"] or not page_token:
                break
        return sorted(reversed(emails), key=lambda e: e.sent_at or datetime.min.replace(tzinfo=UTC))

    def get_thread(self, thread_id: str) -> list[Email]:
        """Every email in the thread, Butler's own included, oldest first."""
        value = self._run("Gmail.GetThread", thread_id=thread_id)
        return [_email(m, id_key="id", sender_key="from_") for m in value["messages"]]

    def send(self, to: str, subject: str, body: str, cc: list[str] | None = None) -> Sent:
        value = self._run("Gmail.SendEmail", recipient=to, cc=cc or [], subject=subject, body=body)
        return Sent(value["id"], value["thread_id"])

    def reply(self, message_id: str, body: str, cc: list[str] | None = None, to_sender_only: bool = True) -> Sent:
        value = self._run(
            "Gmail.ReplyToEmail",
            reply_to_message_id=message_id,
            reply_to_whom="only_the_sender" if to_sender_only else "every_recipient",
            cc=cc or [],
            body=body,
        )
        return Sent(value["id"], value["thread_id"])

    # Calendar. Datetimes must be timezone-aware; Google keeps the instant whatever Butler's calendar zone is.

    def create_event(self, title: str, start: datetime, end: datetime, place: str, description: str, host: str) -> str:
        value = self._run(
            "GoogleCalendar.CreateEvent",
            summary=title,
            start_datetime=start.isoformat(),
            end_datetime=end.isoformat(),
            location=place,
            description=description,
            attendee_emails=[host],
            send_notifications_to_attendees="all",
        )
        return value["event"]["id"]

    def get_event(self, event_id: str) -> Event:
        value = self._run("GoogleCalendar.GetEvent", event_id=event_id)
        return Event(
            event_id=value["event_id"],
            title=value["title"] or "",
            start=datetime.fromisoformat(value["start"]["date_time"]),
            end=datetime.fromisoformat(value["end"]["date_time"]),
            place=value["location"] or "",
            description=value["description"] or "",
            attendees=tuple(
                Attendee(a["email"].lower(), a["response_status"], a["additional_guests"] or 0)
                for a in value["attendees"]
            ),
        )

    def update_event(
        self,
        event_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        place: str | None = None,
        description: str | None = None,
    ) -> None:
        changes = {
            "updated_start_datetime": start.isoformat() if start else None,
            "updated_end_datetime": end.isoformat() if end else None,
            "updated_location": place,
            "updated_description": description,
        }
        self._run(
            "GoogleCalendar.UpdateEvent",
            event_id=event_id,
            send_notifications_to_attendees="nobody",
            **{k: v for k, v in changes.items() if v is not None},
        )

    def add_attendee(self, event_id: str, email: str) -> None:
        """Google emails the invite to this Guest only."""
        self._run(
            "GoogleCalendar.UpdateEvent",
            event_id=event_id,
            attendee_emails_to_add=[email],
            send_notifications_to_attendees="all",
        )

    def remove_attendee(self, event_id: str, email: str) -> None:
        self._run(
            "GoogleCalendar.UpdateEvent",
            event_id=event_id,
            attendee_emails_to_remove=[email],
            send_notifications_to_attendees="nobody",
        )

    def delete_event(self, event_id: str) -> None:
        self._run("GoogleCalendar.DeleteEvent", event_id=event_id, send_updates="nobody")


def _addresses(field: str) -> tuple[str, ...]:
    return tuple(address.lower() for _, address in getaddresses([field or ""]) if address)


def _sent_at(date: str) -> datetime | None:
    # Gmail tools return a display string, e.g. "Tuesday, October 06, 2026 at 05:42:16 UTC".
    try:
        return datetime.strptime(date, "%A, %B %d, %Y at %H:%M:%S UTC").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _email(raw: dict, id_key: str, sender_key: str) -> Email:
    # SearchEmailsByQuery says `message_id`/`sender`; GetThread and GetEmail say `id`/`from_`.
    name, address = parseaddr(raw[sender_key] or "")
    return Email(
        message_id=raw[id_key],
        thread_id=raw["thread_id"],
        sender=address.lower(),
        to=_addresses(raw["to"]),
        cc=_addresses(raw["cc"]),
        subject=raw["subject"] or "",
        body=raw["body"] or "",
        sent_at=_sent_at(raw["date"]),
        sender_name=name,
    )
