"""Tests for daemon.sweep_inbox — seeding history from the MAP listing."""
from __future__ import annotations

from iphonebridge.daemon import sweep_inbox
from iphonebridge.events import SeenMessages, message_key


class _Sessions:
    map_path = "/org/bluez/obex/client/session0"


class _Listener:
    def __init__(self, seen=()):
        self.seen_keys = SeenMessages(seen)


class _Contacts:
    def resolve(self, raw):
        return "A Contact" if raw == "+15551234567" else None


class _Jsonl:
    name = "jsonl"
    def __init__(self):
        self.events = []
    def handle(self, event):
        self.events.append(event)


def _listing(monkeypatch, msgs):
    monkeypatch.setattr(
        "iphonebridge.obex.map_query.list_recent_messages",
        lambda path, limit=50: msgs)


def test_sweep_logs_unseen_and_marks_seen(monkeypatch):
    _listing(monkeypatch, [
        {"handle": "message1", "sender": "+15551234567", "body": "hi",
         "timestamp": "2026-08-24T10:00:00", "read": True,
         "status": "complete", "type": "sms-gsm", "sender_phone_norm": "15551234567"},
        {"handle": "message2", "sender": "friend@icloud.com", "body": "yo",
         "timestamp": "", "read": False, "status": "", "type": "sms-gsm",
         "sender_phone_norm": ""},
    ])
    lst, sink = _Listener(), _Jsonl()
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 2
    assert len(lst.seen_keys) == 2
    # MAP listings are newest-first; the log must be chronological, so
    # the listing's second entry is written first.
    ev2, ev1 = sink.events
    assert ev1.contact_name == "A Contact" and ev1.sender_phone == "+15551234567"
    assert ev2.sender_email == "friend@icloud.com" and ev2.sender_phone is None


def test_sweep_skips_already_seen(monkeypatch):
    """Identity is content, not handle: the same message re-listed under a
    fresh handle (as happens after a delete renumbers them) is skipped."""
    _listing(monkeypatch, [
        {"handle": "message1", "sender": "+15551234567", "body": "hi",
         "timestamp": "", "read": True, "status": "", "type": "",
         "sender_phone_norm": ""},
    ])
    seen = {message_key(None, "+15551234567", "hi")}
    lst, sink = _Listener(seen=seen), _Jsonl()
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 0
    assert sink.events == []


def test_sweep_skips_after_handles_renumber(monkeypatch):
    """A delete on the iPhone renumbers every handle; the same messages
    must not be re-logged under their new ones."""
    msg = {"handle": "OLD", "sender": "+15551234567", "body": "hi",
           "timestamp": "", "read": True, "status": "", "type": "",
           "sender_phone_norm": ""}
    _listing(monkeypatch, [msg])
    lst, sink = _Listener(), _Jsonl()
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 1
    msg["handle"] = "RENUMBERED"
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 0
    assert len(sink.events) == 1


def test_sweep_skips_a_message_already_pushed_live(monkeypatch):
    """The duplicate this guard exists for.

    A live MNS push is announced as a Message1 with Status="notification",
    which BlueZ exports with no Timestamp, so the pushed copy keys on an
    empty timestamp. The listing carries the real send time. Their exact
    keys differ, so before the loose match the sweep re-logged every
    message that had already arrived live.
    """
    pushed_at = "2026-08-25T15:57:51+00:00"       # our clock, on arrival
    sent_at = "2026-08-25T15:57:49+00:00"         # the phone's clock
    seen = SeenMessages()
    seen.note(message_key(None, "+15551234567", "hi"), pushed_at)

    _listing(monkeypatch, [
        {"handle": "message1", "sender": "+15551234567", "body": "hi",
         "timestamp": sent_at, "read": True, "status": "complete",
         "type": "sms-gsm", "sender_phone_norm": "15551234567"},
    ])
    lst, sink = _Listener(), _Jsonl()
    lst.seen_keys = seen
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 0
    assert sink.events == []


def test_sweep_still_logs_an_identical_message_sent_much_later(monkeypatch):
    """The loose match must not swallow a genuine repeat. Same sender and
    same text, but hours apart, so it is a different message."""
    seen = SeenMessages()
    seen.note(message_key(None, "+15551234567", "ok"),
              "2026-08-25T09:00:00+00:00")
    _listing(monkeypatch, [
        {"handle": "message1", "sender": "+15551234567", "body": "ok",
         "timestamp": "2026-08-25T17:00:00+00:00", "read": True,
         "status": "complete", "type": "sms-gsm",
         "sender_phone_norm": "15551234567"},
    ])
    lst, sink = _Listener(), _Jsonl()
    lst.seen_keys = seen
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 1


def test_repeated_identical_messages_pair_off_one_for_one(monkeypatch):
    """Two identical texts really sent a minute apart, each already pushed
    live. Both listing entries must be recognised, not just one, and
    neither may be logged twice."""
    seen = SeenMessages()
    seen.note(message_key(None, "+15551234567", "ok"),
              "2026-08-25T15:00:02+00:00")
    seen.note(message_key(None, "+15551234567", "ok"),
              "2026-08-25T15:01:02+00:00")
    _listing(monkeypatch, [
        {"handle": "m2", "sender": "+15551234567", "body": "ok",
         "timestamp": "2026-08-25T15:01:00+00:00", "read": True,
         "status": "complete", "type": "sms-gsm",
         "sender_phone_norm": "15551234567"},
        {"handle": "m1", "sender": "+15551234567", "body": "ok",
         "timestamp": "2026-08-25T15:00:00+00:00", "read": True,
         "status": "complete", "type": "sms-gsm",
         "sender_phone_norm": "15551234567"},
    ])
    lst, sink = _Listener(), _Jsonl()
    lst.seen_keys = seen
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 0
    assert sink.events == []


def test_listing_seen_twice_in_one_startup_logs_once(monkeypatch):
    """ListMessages makes obexd export Message1 objects, so InterfacesAdded
    fires for every listed message and the MNS listener sees it too. The
    signals queue behind the synchronous sweep, so each message is offered
    to the guard twice in one startup. The second offer must still be
    recognised, even though the first consumed the loose entry."""
    seen = SeenMessages()
    seen.note(message_key(None, "+15551234567", "hi"),
              "2026-08-25T15:57:51+00:00")
    listing = {"handle": "message1", "sender": "+15551234567", "body": "hi",
               "timestamp": "2026-08-25T15:57:49+00:00", "read": True,
               "status": "complete", "type": "sms-gsm",
               "sender_phone_norm": "15551234567"}
    _listing(monkeypatch, [listing])
    lst, sink = _Listener(), _Jsonl()
    lst.seen_keys = seen

    # First pass: the sweep itself.
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink) == 0
    # Second pass: the same message arriving via InterfacesAdded, which is
    # what the listener does with the very same key.
    key = message_key("2026-08-25T15:57:49+00:00", "+15551234567", "hi")
    assert seen.matches(key, "2026-08-25T15:57:49+00:00") is True
    assert sink.events == []


def test_sweep_files_the_path_under_the_logged_key(monkeypatch):
    """Read-state can only be written back through an object path, and a
    listing is the only place one comes from. A message logged from a live
    push is keyed on its arrival time, so filing the path under the
    sweep's own key would leave it unreachable."""
    pushed_at = "2026-08-25T15:57:51+00:00"
    sent_at = "2026-08-25T15:57:49+00:00"
    logged_key = message_key(pushed_at, "+15551234567", "hi")
    seen = SeenMessages()
    seen.note(logged_key, pushed_at, has_timestamp=False)

    filed = {}
    _listing(monkeypatch, [
        {"handle": "message1", "path": "/org/bluez/obex/client/session0/message1",
         "sender": "+15551234567", "body": "hi", "timestamp": sent_at,
         "read": True, "status": "complete", "type": "sms-gsm",
         "sender_phone_norm": "15551234567"},
    ])
    lst, sink = _Listener(), _Jsonl()
    lst.seen_keys = seen
    assert sweep_inbox(_Sessions(), lst, _Contacts(), sink,
                       remember_path=lambda k, p: filed.__setitem__(k, p)) == 0
    assert logged_key in filed, "path must be reachable by the logged key"
    assert filed[logged_key].endswith("message1")


def test_find_reports_the_matched_key(monkeypatch):
    """The sweep needs to know which key a message is already filed
    under, not merely that it is."""
    pushed_at = "2026-08-25T15:57:51+00:00"
    logged_key = message_key(pushed_at, "+15551234567", "hi")
    seen = SeenMessages()
    seen.note(logged_key, pushed_at, has_timestamp=False)
    listing_key = message_key("2026-08-25T15:57:49+00:00", "+15551234567", "hi")
    assert seen.find(listing_key, "2026-08-25T16:26:02+00:00",
                     has_timestamp=True) == logged_key


def test_find_returns_none_for_an_unknown_message(monkeypatch):
    seen = SeenMessages()
    assert seen.find(message_key(None, "+15551234567", "hi"),
                     "2026-08-25T15:57:51+00:00", has_timestamp=False) is None
