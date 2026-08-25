"""Tests for daemon.sweep_inbox — seeding history from the MAP listing."""
from __future__ import annotations

from iphonebridge.daemon import sweep_inbox


class _Sessions:
    map_path = "/org/bluez/obex/client/session0"


class _Listener:
    def __init__(self, seen=()):
        self.seen_keys = set(seen)


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
    from iphonebridge.events import message_key
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
