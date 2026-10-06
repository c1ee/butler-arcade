from datetime import UTC, datetime

import pytest

from butler.config import Settings
from butler.gateway import Email
from butler.router import Route, route
from butler.store import Store

BUTLER = "butler@example.com"
HOST = "host@example.com"
A = "a@example.com"
B = "b@example.com"
SETTINGS = Settings(arcade_api_key="", anthropic_api_key="", butler_user_id="Butler@example.com", host_email=HOST)


def email(sender, thread_id="new-thread", subject="hi"):
    return Email("m1", thread_id, sender, (BUTLER,), (), subject, "body", datetime.now(UTC))


@pytest.fixture
def store():
    store = Store(":memory:")
    dinner = store.create_dinner(status="active", title="Dinner at Host's", host_thread_id="host-thread",
                                 group_thread_id="group-thread")
    store.add_guest(dinner, A, guest_thread_id="a-thread")
    store.add_guest(dinner, B, guest_thread_id="b-thread")
    return store


@pytest.mark.parametrize(
    "mail, expected",
    [
        (email(HOST, "host-thread"), Route(1, "host_thread", "host")),
        (email(A, "a-thread"), Route(1, "guest_thread", "guest")),
        (email(B, "group-thread"), Route(1, "group_thread", "guest")),
        (email(HOST, "group-thread"), Route(1, "group_thread", "host")),
        # New threads route by sender: a fresh email, or a reply to Google's calendar invite.
        (email(HOST), Route(1, "host_thread", "host")),
        (email("A@Example.com", subject="Re: Invitation: Dinner at Host's"), Route(1, "guest_thread", "guest")),
        (email(A, "b-thread"), Route(1, "guest_thread", "guest", skipped="not this Guest's thread")),
        (email(A, "host-thread"), Route(1, "host_thread", "guest", skipped="not the Host")),
        (email(B, subject="Declined: Dinner at Host's @ Sat Oct 24, 2026 7pm"), Route(1, None, "guest", skipped="calendar reply")),
        (email(A, subject="Accepted: Dinner at Host's"), Route(1, None, "guest", skipped="calendar reply")),
        (email("stranger@example.com", "group-thread"), Route(1, None, "stranger", skipped="unknown sender")),
        (email(BUTLER, "group-thread"), Route(None, None, "butler", skipped="Butler's own email")),
    ],
)
def test_route(store, mail, expected):
    assert route(mail, store, SETTINGS) == expected


def test_host_with_no_dinner_starts_one():
    assert route(email(HOST), Store(":memory:"), SETTINGS) == Route(None, "host_thread", "host")


def test_guest_with_no_dinner_is_unknown():
    assert route(email(A), Store(":memory:"), SETTINGS).skipped == "unknown sender"


def test_over_dinner_ignores_its_threads_and_host_starts_fresh(store):
    store.update_dinner(1, status="canceled")
    assert route(email(A, "a-thread"), store, SETTINGS).skipped == "Dinner canceled"
    assert route(email(HOST, "host-thread"), store, SETTINGS).skipped == "Dinner canceled"
    assert route(email(HOST), store, SETTINGS) == Route(None, "host_thread", "host")
