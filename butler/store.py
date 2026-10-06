"""SQLite: Butler's private state. Never talks to the network.

The Calendar event is the source of truth for who's coming (D13); the guest table keeps only
what the calendar can't: email answers, Plus-ones, Dietary needs, Guest notes, threads, and the
last calendar snapshot to diff against. A Guest's status is derived, never stored.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dinner (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft / draft_shown / active / confirming_cancel / canceled / closed
    title TEXT,
    host_email TEXT,
    host_name TEXT,  -- display name from the Host's first email, if any
    start_at TEXT,  -- ISO 8601 with offset
    place TEXT,
    group_threshold INTEGER NOT NULL DEFAULT 2,
    calendar_event_id TEXT,
    host_thread_id TEXT,
    group_thread_id TEXT,
    cancel_asked_in TEXT  -- the Host email in which Butler asked them to confirm canceling (D9)
);
CREATE TABLE IF NOT EXISTS guest (
    id INTEGER PRIMARY KEY,
    dinner_id INTEGER NOT NULL REFERENCES dinner(id),
    email TEXT NOT NULL,
    name TEXT,  -- display name from the Guest's emails, if any
    email_answer TEXT NOT NULL DEFAULT 'none',  -- none / yes / no
    on_calendar INTEGER NOT NULL DEFAULT 0,
    calendar_answer TEXT,  -- last snapshot
    plus_ones INTEGER NOT NULL DEFAULT 0,
    dietary_needs TEXT,
    guest_note TEXT,
    guest_thread_id TEXT,
    group_joined_at TEXT,
    UNIQUE (dinner_id, email)
);
CREATE TABLE IF NOT EXISTS host_note (
    id INTEGER PRIMARY KEY,
    dinner_id INTEGER NOT NULL REFERENCES dinner(id),
    text TEXT NOT NULL,
    shareable INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS change (
    id INTEGER PRIMARY KEY,
    dinner_id INTEGER NOT NULL REFERENCES dinner(id),
    kind TEXT NOT NULL,  -- approve / rsvp / group_start / group_join / change / cancel
    payload TEXT NOT NULL DEFAULT '{}'
);
-- Every email and calendar write Butler makes, queued in the same transaction as the state it reflects (D5).
-- A row belongs to a Change, or answers one inbound email (Butler's reply).
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    change_id INTEGER REFERENCES change(id),
    message_id TEXT,  -- the inbound email this row replies to
    channel TEXT NOT NULL,  -- calendar / host / guest / group
    recipient TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / sent
    sent_message_id TEXT,
    CHECK ((change_id IS NULL) != (message_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS outbox_change ON outbox (change_id, channel, recipient) WHERE change_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS outbox_reply ON outbox (message_id, channel, recipient) WHERE message_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS trace (
    id INTEGER PRIMARY KEY,
    gmail_message_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    kind TEXT NOT NULL,  -- claude / tool / gate
    input TEXT NOT NULL,
    output TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message (
    gmail_message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    dinner_id INTEGER REFERENCES dinner(id),
    channel TEXT,
    role TEXT,
    skipped TEXT,  -- why Butler didn't act on it, if it didn't
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

OVER = ("canceled", "closed")
LIVE = ("active", "confirming_cancel")  # approved and not over


def status(guest) -> str:
    """invited / attending / declined, derived from the calendar snapshot and the email answer (D13)."""
    if guest["on_calendar"]:
        return "declined" if guest["calendar_answer"] == "declined" else "attending"
    return "declined" if guest["email_answer"] == "no" else "invited"


def headcount(guests) -> int:
    """Attending Guests plus their Plus-ones. The Host isn't counted."""
    coming = [guest for guest in guests if status(guest) == "attending"]
    return len(coming) + sum(guest["plus_ones"] for guest in coming)


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        with self.db:
            yield

    # Inbound

    def is_processed(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM message WHERE gmail_message_id = ?", (message_id,)).fetchone() is not None

    def mark_processed(self, email, route, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO message (gmail_message_id, thread_id, sender, dinner_id, channel, role, skipped, processed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (email.message_id, email.thread_id, email.sender, route.dinner_id, route.channel, route.role,
             route.skipped, now.isoformat()),
        )

    def poll_cursor(self) -> int | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = 'poll_cursor'").fetchone()
        return int(row["value"]) if row else None

    def set_poll_cursor(self, epoch: int) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES ('poll_cursor', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (str(epoch),),
        )

    # Dinners and Guests

    def create_dinner(self, **fields) -> int:
        columns = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self.db.execute(f"INSERT INTO dinner ({columns}) VALUES ({marks})", tuple(fields.values())).lastrowid

    def update_dinner(self, dinner_id: int, **fields) -> None:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self.db.execute(f"UPDATE dinner SET {assignments} WHERE id = ?", (*fields.values(), dinner_id))

    def add_guest(self, dinner_id: int, email: str, **fields) -> int:
        fields = {"dinner_id": dinner_id, "email": email.lower(), **fields}
        columns = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self.db.execute(f"INSERT INTO guest ({columns}) VALUES ({marks})", tuple(fields.values())).lastrowid

    def dinner(self, dinner_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM dinner WHERE id = ?", (dinner_id,)).fetchone()

    def live_dinners(self) -> list[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM dinner WHERE status IN {LIVE} ORDER BY id").fetchall()

    def current_dinner(self) -> sqlite3.Row | None:
        """The one Dinner that isn't over (D14: one at a time)."""
        return self.db.execute(
            f"SELECT * FROM dinner WHERE status NOT IN {OVER} ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def guests(self, dinner_id: int) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM guest WHERE dinner_id = ? ORDER BY id", (dinner_id,)).fetchall()

    def remove_guest(self, dinner_id: int, email: str) -> None:
        self.db.execute("DELETE FROM guest WHERE dinner_id = ? AND email = ?", (dinner_id, email.lower()))

    def update_guest(self, dinner_id: int, email: str, **fields) -> None:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self.db.execute(
            f"UPDATE guest SET {assignments} WHERE dinner_id = ? AND email = ?", (*fields.values(), dinner_id, email.lower())
        )

    def guest(self, dinner_id: int, email: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM guest WHERE dinner_id = ? AND email = ?", (dinner_id, email.lower())
        ).fetchone()

    def last_from(self, thread_id: str, sender: str) -> str | None:
        """The newest email Butler processed from `sender` in a thread: what Butler replies to when it posts there."""
        row = self.db.execute(
            "SELECT gmail_message_id FROM message WHERE thread_id = ? AND sender = ? ORDER BY rowid DESC LIMIT 1",
            (thread_id, sender),
        ).fetchone()
        return row["gmail_message_id"] if row else None

    def members(self, dinner_id: int) -> list[str]:
        """Who's in the Group thread: the Host, then Guests in the order they joined. Nobody ever leaves (D6)."""
        joined = self.db.execute(
            "SELECT email FROM guest WHERE dinner_id = ? AND group_joined_at IS NOT NULL ORDER BY group_joined_at, id",
            (dinner_id,),
        ).fetchall()
        return [self.dinner(dinner_id)["host_email"], *(row["email"] for row in joined)]

    def newest_group_post(self, thread_id: str, senders: list[str]) -> sqlite3.Row | None:
        """The newest Group thread post Butler processed from any of `senders`: (gmail_message_id, sender).
        An email in the thread sent only to Butler was routed as private and doesn't count."""
        marks = ", ".join("?" for _ in senders)
        return self.db.execute(
            f"SELECT gmail_message_id, sender FROM message WHERE thread_id = ? AND channel = 'group_thread'"
            f" AND sender IN ({marks}) ORDER BY rowid DESC LIMIT 1",
            (thread_id, *senders),
        ).fetchone()

    def last_group_post(self, dinner_id: int) -> str | None:
        """Butler's newest sent email in a Dinner's Group thread."""
        row = self.db.execute(
            "SELECT sent_message_id FROM outbox WHERE channel = 'group' AND status = 'sent'"
            " AND sent_message_id IS NOT NULL AND json_extract(payload, '$.dinner_id') = ? ORDER BY id DESC LIMIT 1",
            (dinner_id,),
        ).fetchone()
        return row["sent_message_id"] if row else None

    def find_thread(self, thread_id: str) -> tuple[sqlite3.Row, str, str | None] | None:
        """(Dinner, channel, the Guest's email for a Guest thread) for a thread Butler knows, any Dinner."""
        row = self.db.execute(
            "SELECT * FROM dinner WHERE host_thread_id = ? OR group_thread_id = ? ORDER BY id DESC LIMIT 1",
            (thread_id, thread_id),
        ).fetchone()
        if row:
            return row, "host_thread" if row["host_thread_id"] == thread_id else "group_thread", None
        guest = self.db.execute(
            "SELECT dinner_id, email FROM guest WHERE guest_thread_id = ? ORDER BY id DESC LIMIT 1", (thread_id,)
        ).fetchone()
        if guest:
            return self.dinner(guest["dinner_id"]), "guest_thread", guest["email"]
        return None

    # Host notes

    def add_note(self, dinner_id: int, text: str, shareable: bool) -> int:
        return self.db.execute(
            "INSERT INTO host_note (dinner_id, text, shareable) VALUES (?, ?, ?)", (dinner_id, text, int(shareable))
        ).lastrowid

    def notes(self, dinner_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM host_note WHERE dinner_id = ? AND deleted = 0 ORDER BY id", (dinner_id,)
        ).fetchall()

    def set_note_shareable(self, dinner_id: int, note_id: int, shareable: bool) -> None:
        self.db.execute("UPDATE host_note SET shareable = ? WHERE dinner_id = ? AND id = ?",
                        (int(shareable), dinner_id, note_id))

    def delete_note(self, dinner_id: int, note_id: int) -> bool:
        cursor = self.db.execute(
            "UPDATE host_note SET deleted = 1 WHERE dinner_id = ? AND id = ? AND deleted = 0", (dinner_id, note_id)
        )
        return cursor.rowcount == 1

    # Changes, outbox, traces

    def add_change(self, dinner_id: int, kind: str, payload: dict | None = None) -> int:
        return self.db.execute(
            "INSERT INTO change (dinner_id, kind, payload) VALUES (?, ?, ?)", (dinner_id, kind, json.dumps(payload or {}))
        ).lastrowid

    def changes(self, dinner_id: int, kind: str) -> list[dict]:
        rows = self.db.execute("SELECT payload FROM change WHERE dinner_id = ? AND kind = ? ORDER BY id",
                               (dinner_id, kind)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def queue(self, channel: str, recipient: str, payload: dict, change_id: int | None = None,
              message_id: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO outbox (change_id, message_id, channel, recipient, payload) VALUES (?, ?, ?, ?, ?)",
            (change_id, message_id, channel, recipient, json.dumps(payload)),
        )

    def pending(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM outbox WHERE status = 'pending' ORDER BY id").fetchall()

    def mark_sent(self, outbox_id: int, sent_message_id: str | None) -> None:
        self.db.execute(
            "UPDATE outbox SET status = 'sent', sent_message_id = ? WHERE id = ?", (sent_message_id, outbox_id)
        )

    def add_trace(self, message_id: str, step: int, kind: str, input, output) -> None:
        self.db.execute(
            "INSERT INTO trace (gmail_message_id, step, kind, input, output) VALUES (?, ?, ?, ?, ?)",
            (message_id, step, kind, json.dumps(input, default=str), json.dumps(output, default=str)),
        )

    def close_finished(self, now: datetime) -> list[int]:
        """Close approved Dinners that started more than an hour ago. Returns the closed ids."""
        rows = self.db.execute(f"SELECT id, start_at FROM dinner WHERE status IN {LIVE}").fetchall()
        done = [r["id"] for r in rows if r["start_at"] and datetime.fromisoformat(r["start_at"]) + timedelta(hours=1) <= now]
        for dinner_id in done:
            self.update_dinner(dinner_id, status="closed")
        return done
