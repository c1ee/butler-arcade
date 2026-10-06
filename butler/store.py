"""SQLite: Butler's private state. Never talks to the network.

The Calendar event is the source of truth for who's coming (D13); the guest table keeps only
what the calendar can't: email answers, Plus-ones, Dietary needs, Guest notes, threads, and the
last calendar snapshot to diff against. A Guest's status is derived, never stored.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dinner (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft / draft_shown / active / confirming_cancel / canceled / closed
    title TEXT,
    start_at TEXT,  -- ISO 8601 with offset
    place TEXT,
    group_threshold INTEGER NOT NULL DEFAULT 2,
    calendar_event_id TEXT,
    host_thread_id TEXT,
    group_thread_id TEXT
);
CREATE TABLE IF NOT EXISTS guest (
    id INTEGER PRIMARY KEY,
    dinner_id INTEGER NOT NULL REFERENCES dinner(id),
    email TEXT NOT NULL,
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

    def current_dinner(self) -> sqlite3.Row | None:
        """The one Dinner that isn't over (D14: one at a time)."""
        return self.db.execute(
            f"SELECT * FROM dinner WHERE status NOT IN {OVER} ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def guest(self, dinner_id: int, email: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM guest WHERE dinner_id = ? AND email = ?", (dinner_id, email.lower())
        ).fetchone()

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

    def close_finished(self, now: datetime) -> list[int]:
        """Close approved Dinners that started more than an hour ago. Returns the closed ids."""
        rows = self.db.execute(f"SELECT id, start_at FROM dinner WHERE status IN {LIVE}").fetchall()
        done = [r["id"] for r in rows if r["start_at"] and datetime.fromisoformat(r["start_at"]) + timedelta(hours=1) <= now]
        for dinner_id in done:
            self.update_dinner(dinner_id, status="closed")
        return done
