from datetime import UTC, datetime, timedelta

from butler.config import Settings
from butler.gateway import Email
from butler.main import OVERLAP_SECONDS, poll_once, tick
from butler.store import Store

HOST = "host@example.com"
SETTINGS = Settings(arcade_api_key="", anthropic_api_key="", butler_user_id="butler@example.com", host_email=HOST)
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class FakeInbox:
    def __init__(self, emails):
        self.emails = emails
        self.searches = []

    def search_inbox(self, after):
        self.searches.append(after)
        return self.emails


def mail(message_id):
    return Email(message_id, "t-" + message_id, HOST, ("butler@example.com",), (), "dinner?", "body", NOW)


def test_each_email_is_handled_once_and_the_cursor_advances(caplog):
    caplog.set_level("INFO")
    store, inbox = Store(":memory:"), FakeInbox([mail("m1")])
    poll_once(inbox, store, SETTINGS, NOW)
    inbox.emails = [mail("m1"), mail("m2")]
    poll_once(inbox, store, SETTINGS, NOW + timedelta(seconds=30))

    routed = [r.message for r in caplog.records if "→" in r.message]
    assert [line.split()[0] for line in routed] == ["m1", "m2"]
    assert "new Dinner, host_thread, host" in routed[0]
    assert inbox.searches == [int(NOW.timestamp()) - OVERLAP_SECONDS] * 2
    assert store.poll_cursor() == int(NOW.timestamp()) + 30


def test_tick_closes_a_dinner_an_hour_after_it_starts():
    store = Store(":memory:")
    start = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
    with store.transaction():
        store.create_dinner(status="active", start_at=start.isoformat())
        store.create_dinner(status="draft", start_at=start.isoformat())
    tick(None, store, start + timedelta(minutes=59))
    assert store.dinner(1)["status"] == "active"
    tick(None, store, start + timedelta(hours=1))
    assert [store.dinner(1)["status"], store.dinner(2)["status"]] == ["closed", "draft"]
