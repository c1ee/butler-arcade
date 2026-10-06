"""Domain tools for the tool loop, and which ones exist for each email: toolset(role, channel, phase).

Claude never sees Gmail or Calendar tools and never chooses recipients (D2). A tool missing from the
toolset doesn't exist for that email, so who may do what is enforced here, not in a prompt (D4, D9).
Tools write to the store and queue outbox rows; nothing is sent until the email's transaction commits (D5).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

from butler import effects, render
from butler.config import Settings
from butler.store import Store

SETUP = ("draft", "draft_shown")  # phases before the Host approves

HOST_THREAD = ["get_event", "get_group_thread", "get_guest_details", "change_event", "add_note", "invite_guest",
               "update_note"]
HOST_IN_GROUP = ["get_event", "get_group_thread", "change_event", "add_note", "invite_guest"]
GUEST_IN_GROUP = ["get_event", "get_group_thread", "get_my_rsvp", "record_rsvp"]
GUEST_THREAD = ["get_event", "get_my_rsvp", "record_rsvp"]


def toolset(role: str, channel: str, phase: str, attending: bool = False) -> list[str]:
    """Tool names for one email. `phase` is the Dinner's status; `attending` is the sending Guest's status."""
    if role == "host" and channel == "host_thread":
        if phase == "draft":
            return ["update_draft"]
        if phase == "draft_shown":  # send_invites only once the complete draft was shown (D9)
            return ["update_draft", "send_invites"]
        return HOST_THREAD + (["cancel_dinner"] if phase == "confirming_cancel" else [])
    if phase in SETUP:
        return []
    if role == "host" and channel == "group_thread":
        return HOST_IN_GROUP
    if role == "guest" and (channel == "group_thread" or channel == "guest_thread" and attending):
        return GUEST_IN_GROUP
    if role == "guest" and channel == "guest_thread":
        return GUEST_THREAD
    return []


@dataclass(frozen=True)
class Ctx:
    """What a tool knows about the email it's acting on. The sender is bound here, never a tool argument (D4)."""

    store: Store
    settings: Settings
    dinner_id: int
    sender: str
    now: datetime


class ToolError(Exception):
    """Shown to Claude as a failed tool call. Raised before any write, so nothing changed."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[Ctx, BaseModel], dict]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.args.model_json_schema()}

    def call(self, ctx: Ctx, raw: dict) -> dict:
        try:
            args = self.args.model_validate(raw)
        except ValidationError as error:
            raise ToolError(str(error)) from error
        return self.run(ctx, args)


class NoArgs(BaseModel):
    pass


# Setup (H1, H2)

EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


class NoteIn(BaseModel):
    text: str = Field(
        min_length=1, description="The fact itself, close to the Host's words. Leave out who may know it: that's `shareable`."
    )
    shareable: bool = Field(
        description="True only if the Host said Guests may know it ('tell guests', 'put it in the invite'). "
        "Otherwise false: private, only the Host sees it."
    )


class UpdateDraft(BaseModel):
    start: datetime | None = Field(
        None, description="When dinner starts, local time (America/Los_Angeles), ISO 8601, e.g. 2026-10-24T19:00"
    )
    place: str | None = Field(
        None, description="The address or venue exactly as Guests should read it, e.g. '482 Linden Ave'. No commentary."
    )
    add_guests: list[str] = Field(default_factory=list, description="Guest email addresses to invite")
    remove_guests: list[str] = Field(default_factory=list, description="Guest email addresses to take off the draft")
    add_notes: list[NoteIn] = Field(default_factory=list, description="Host notes, e.g. what to bring, parking")
    remove_notes: list[int] = Field(default_factory=list, description="ids of Host notes to drop")
    group_threshold: int | None = Field(
        None, ge=1, description="How many Guests must say yes before Butler starts a group email thread (default 2)"
    )


def draft_state(store: Store, dinner_id: int) -> dict:
    """The draft as Claude sees it in the Host thread (private scope)."""
    dinner = store.dinner(dinner_id)
    start = datetime.fromisoformat(dinner["start_at"]) if dinner["start_at"] else None
    guests = [guest["email"] for guest in store.guests(dinner_id)]
    return {
        "start": f"{start.astimezone(render.ZONE):%Y-%m-%dT%H:%M} ({render.when(start)})" if start else None,
        "place": dinner["place"],
        "guests": guests,
        "notes": [{"id": n["id"], "text": n["text"], "shareable": bool(n["shareable"])} for n in store.notes(dinner_id)],
        "group_threshold": dinner["group_threshold"],
        "missing": missing(dinner, guests),
        "shown_to_host": dinner["status"] == "draft_shown",
    }


def missing(dinner, guests: list) -> list[str]:
    return [label for label, value in [("start time", dinner["start_at"]), ("place", dinner["place"]),
                                       ("guest emails", guests)] if not value]


def show_draft(store: Store, dinner_id: int) -> str | None:
    """The preview to attach below Butler's reply when the draft is complete and the Host hasn't seen this
    version. Marks it shown, which gives the Host's next email send_invites (D9)."""
    dinner, guests = store.dinner(dinner_id), store.guests(dinner_id)
    if dinner["status"] != "draft" or missing(dinner, guests):
        return None
    store.update_dinner(dinner_id, status="draft_shown")
    return render.draft_preview(dinner, store.notes(dinner_id), guests)


def update_draft(ctx: Ctx, args: UpdateDraft) -> dict:
    store, dinner_id = ctx.store, ctx.dinner_id
    dinner = store.dinner(dinner_id)
    if dinner["status"] not in SETUP:
        raise ToolError("The invites already went out, so the draft can't change.")

    fields = {}
    if args.start is not None:
        start = (args.start if args.start.tzinfo else args.start.replace(tzinfo=render.ZONE)).astimezone(render.ZONE)
        if start <= ctx.now:
            raise ToolError(f"{render.when(start)} is in the past (today is {render.when(ctx.now)}).")
        if start.isoformat() != dinner["start_at"]:
            fields["start_at"] = start.isoformat()
    if args.place and args.place.strip() != dinner["place"]:
        fields["place"] = args.place.strip()
    if args.group_threshold is not None and args.group_threshold != dinner["group_threshold"]:
        fields["group_threshold"] = args.group_threshold

    current = {guest["email"] for guest in store.guests(dinner_id)}
    add = list(dict.fromkeys(address.strip().lower() for address in args.add_guests))
    remove = {address.strip().lower() for address in args.remove_guests}
    for address in add:
        if not EMAIL.match(address):
            raise ToolError(f"{address!r} isn't an email address. Ask the Host for it.")
        if address in (dinner["host_email"], ctx.settings.butler_email):
            raise ToolError(f"{address} is the {'Host' if address == dinner['host_email'] else 'Butler'}, not a Guest.")
    if unknown := remove - current:
        raise ToolError(f"Not on the draft: {', '.join(sorted(unknown))}.")
    note_ids = {note["id"] for note in store.notes(dinner_id)}
    if unknown_notes := set(args.remove_notes) - note_ids:
        raise ToolError(f"No Host note with id {', '.join(map(str, sorted(unknown_notes)))}.")

    add = [address for address in add if address not in current]
    for address in add:
        store.add_guest(dinner_id, address)
    for address in remove:
        store.remove_guest(dinner_id, address)
    for note in args.add_notes:
        store.add_note(dinner_id, note.text.strip(), note.shareable)
    for note_id in args.remove_notes:
        store.delete_note(dinner_id, note_id)
    if fields or add or remove or args.add_notes or args.remove_notes:
        if dinner["status"] == "draft_shown":
            fields["status"] = "draft"  # the Host must see this version before approving it (D9)
    if fields:
        store.update_dinner(dinner_id, **fields)
    return draft_state(store, dinner_id)


def send_invites(ctx: Ctx, args: NoArgs) -> dict:
    dinner = ctx.store.dinner(ctx.dinner_id)
    if dinner["status"] == "draft":
        raise ToolError("Nothing was sent: the Host hasn't seen this version of the draft. "
                        "If it's complete, the new draft is shown below your reply for them to approve.")
    if dinner["status"] != "draft_shown":
        raise ToolError("The invites already went out.")
    guests = effects.approve(ctx.store, ctx.settings, ctx.dinner_id)
    return {
        "sent": True,
        "invited": guests,
        "calendar": "Event on Butler's calendar; the Host gets the calendar invite. Guests are added when they say yes.",
    }


TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            "update_draft",
            "Record dinner details from the Host: start time, place, Guests, Host notes, group threshold. "
            "Pass only what this email adds or changes. Returns the whole draft, including what's still missing.",
            UpdateDraft,
            update_draft,
        ),
        Tool(
            "send_invites",
            "Approve the draft: puts the dinner on the calendar (the Host gets the calendar invite) and emails "
            "each Guest a private invite. Only when the Host approved the draft shown to them, with no changes.",
            NoArgs,
            send_invites,
        ),
    ]
}
