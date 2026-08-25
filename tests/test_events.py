"""Tests for iphonebridge.events — phone normalization, timestamp parsing,
SmsEvent construction from MAP Message1 properties."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from iphonebridge.events import (
    SmsEvent,
    message_key,
    normalize_key,
    normalize_phone,
    parse_map_timestamp,
    sms_event_from_message1_props,
    sms_sent_event,
)


class TestNormalizePhone:
    @pytest.mark.parametrize("raw,expected", [
        ("+1 (555) 123-4567", "15551234567"),
        ("+15551234567",      "15551234567"),
        ("5551234567",        "5551234567"),
        ("(555) 123-4567",    "5551234567"),
        ("555.123.4567",      "5551234567"),
        ("555 123 4567",      "5551234567"),
        ("+1-555-123-4567",   "15551234567"),
    ])
    def test_real_numbers_pass(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "Mom", "123", "abcdef"])
    def test_non_phones_return_none(self, raw):
        assert normalize_phone(raw) is None

    def test_short_digit_string_returns_none(self):
        # 6 digits is below threshold
        assert normalize_phone("555-1234") == "5551234"  # 7 digits is the boundary
        assert normalize_phone("12345") is None          # 5 digits is too short


class TestParseMapTimestamp:
    def test_basic_format(self):
        """A bare MAP stamp is the phone's local time, and comes back as
        the same instant expressed in UTC."""
        result = parse_map_timestamp("20260519T181423")
        assert isinstance(result, datetime)
        assert result.utcoffset() == timedelta(0)
        assert result == datetime(2026, 5, 19, 18, 14, 23).astimezone(
            timezone.utc)

    def test_with_tz_suffix(self):
        """An explicit offset is applied rather than discarded: 18:14:23
        at +0500 is 13:14:23 UTC."""
        assert parse_map_timestamp("20260519T181423+0500") == datetime(
            2026, 5, 19, 13, 14, 23, tzinfo=timezone.utc)

    @pytest.mark.parametrize("bad", ["", None, "not a date", "20260", "abcdef"])
    def test_invalid_returns_none(self, bad):
        assert parse_map_timestamp(bad) is None


class TestSmsEventFromProps:
    def test_full_payload(self):
        props = {
            "Sender": "+15551234567",
            "Subject": "hello world",
            "Timestamp": "20260519T120000",
            "Type": "SMS_GSM",
            "Status": "complete",
            "Read": False,
        }
        e = sms_event_from_message1_props("message123", props,
                                          contact_name="Test Contact")
        assert e.handle == "message123"
        assert e.sender_phone == "+15551234567"
        assert e.sender_phone_norm == "15551234567"
        assert e.contact_name == "Test Contact"
        assert e.body == "hello world"
        assert e.is_read is False
        assert e.raw_type == "SMS_GSM"
        assert e.timestamp is not None
        assert e.timestamp.day == 19

    def test_no_contact_resolves_to_phone(self):
        props = {"Sender": "+15551234567", "Subject": "hi"}
        e = sms_event_from_message1_props("h1", props, contact_name=None)
        assert e.display_sender == "+15551234567"

    def test_no_sender_at_all(self):
        e = sms_event_from_message1_props("h2", {}, contact_name=None)
        assert e.display_sender == "(unknown)"
        assert e.sender_phone is None
        assert e.sender_phone_norm is None

    def test_to_dict_is_json_serializable(self):
        import json
        props = {"Sender": "+15551234567", "Subject": "hi",
                 "Timestamp": "20260519T120000"}
        e = sms_event_from_message1_props("h3", props,
                                          contact_name="Alice")
        d = e.to_dict()
        # Round-trips through JSON cleanly
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["body"] == "hi"
        assert parsed["contact_name"] == "Alice"
        assert parsed["sender_phone_norm"] == "15551234567"

    def test_sender_address_used_if_sender_missing(self):
        props = {"SenderAddress": "+15551234567", "Subject": "hi"}
        e = sms_event_from_message1_props("h4", props)
        assert e.sender_phone == "+15551234567"


class TestSmsSentEvent:
    def test_recipient_lands_in_sender_fields(self):
        # A sent event carries the recipient in sender_* so it threads with
        # incoming messages from the same person.
        e = sms_sent_event("+15551234567", "on my way",
                           contact_name="Maddie",
                           transfer_path="/org/bluez/obex/client/session0/transfer3")
        assert e.kind == "sms_sent"
        assert e.sender_phone == "+15551234567"
        assert e.sender_phone_norm == "15551234567"
        assert e.contact_name == "Maddie"
        assert e.body == "on my way"
        assert e.is_read is True
        assert e.handle == "transfer3"
        assert e.timestamp is not None
        assert e.display_sender == "Maddie"

    def test_handle_synthesized_without_transfer_path(self):
        e = sms_sent_event("+15551234567", "hi")
        assert e.handle.startswith("sent-")

    def test_to_dict_is_json_serializable(self):
        import json
        e = sms_sent_event("+15551234567", "hi", contact_name="Alice")
        parsed = json.loads(json.dumps(e.to_dict()))
        assert parsed["kind"] == "sms_sent"
        assert parsed["contact_name"] == "Alice"
        assert parsed["body"] == "hi"


class TestSmsEventDisplay:
    def test_prefers_contact_over_phone(self):
        e = SmsEvent(
            kind="sms_received", handle="h", sender_phone="+15551234567",
            sender_phone_norm="15551234567", contact_name="Alice",
            body="hi", timestamp=None, is_read=False,
            raw_status=None, raw_type=None,
        )
        assert e.display_sender == "Alice"

    def test_falls_back_to_phone(self):
        e = SmsEvent(
            kind="sms_received", handle="h", sender_phone="+15551234567",
            sender_phone_norm="15551234567", contact_name=None,
            body="hi", timestamp=None, is_read=False,
            raw_status=None, raw_type=None,
        )
        assert e.display_sender == "+15551234567"

    def test_unknown_fallback(self):
        e = SmsEvent(
            kind="sms_received", handle="h", sender_phone=None,
            sender_phone_norm=None, contact_name=None,
            body=None, timestamp=None, is_read=False,
            raw_status=None, raw_type=None,
        )
        assert e.display_sender == "(unknown)"


def test_logged_sms_keys(tmp_path):
    from iphonebridge.events import logged_sms_keys, message_key
    log = tmp_path / "events.jsonl"
    log.write_text(
        '{"kind": "sms_received", "timestamp": "t1", "sender_phone": "+1", "body": "a"}\n'
        '{"kind": "sms_received", "timestamp": "t1", "sender_phone": "+1", "body": "a"}\n'
        '{"kind": "sms_received", "timestamp": "t2", "sender_email": "x@y", "body": "b"}\n'
        '{"kind": "sms_sent", "timestamp": "t3", "sender_phone": "+9", "body": "c"}\n'
        'not json\n'
    )
    assert logged_sms_keys(log) == {
        message_key("t1", "+1", "a"), message_key("t2", "x@y", "b")}


def test_logged_sms_keys_missing_file(tmp_path):
    from iphonebridge.events import logged_sms_keys
    assert logged_sms_keys(tmp_path / "absent.jsonl") == set()


def test_message_key_ignores_handle_and_normalizes():
    from iphonebridge.events import message_key
    assert message_key("t", " +15551234567 ", " hi ") == message_key("t", "+15551234567", "hi")
    assert message_key("t", "A@B.com", "hi") == message_key("t", "a@b.com", "hi")
    assert message_key("t1", "+1", "hi") != message_key("t2", "+1", "hi")


def test_vanity_to_digits():
    from iphonebridge.events import vanity_to_digits
    assert vanity_to_digits("1 (800) MYAPPLE") == "1 (800) 6927753"
    assert vanity_to_digits("1-800-flowers") == "1-800-3569377"
    assert vanity_to_digits("+1 800 GO FEDEX") == "+1 800 46 33339"
    # No letters — unchanged
    assert vanity_to_digits("+15551234567") == "+15551234567"


def test_vanity_resolve_rule():
    """The Calls-tab rule: translate only when a digit is present, so a
    contact name is never turned into keypad digits."""
    import re

    from iphonebridge.events import vanity_to_digits
    phone_re = re.compile(r"^\+?[\d\s()\-.]{7,}$")

    def resolves_as_number(raw: str) -> str | None:
        if phone_re.match(raw):
            return raw
        if any(ch.isdigit() for ch in raw):
            t = vanity_to_digits(raw)
            if phone_re.match(t):
                return t
        return None  # falls through to contact lookup

    assert resolves_as_number("1 (800) MYAPPLE") == "1 (800) 6927753"
    assert resolves_as_number("Maddie") is None
    assert resolves_as_number("MYAPPLE") is None   # no digit -> not a number


def test_dialable():
    from iphonebridge.events import dialable
    assert dialable("1 (800) 6927753") == "18006927753"
    assert dialable("+1 555-123-4567") == "+15551234567"
    assert dialable("*67 555 1234") == "*675551234"
    assert dialable("+15551234567") == "+15551234567"
    # + only survives at the front
    assert dialable("555+123") == "555123"
    # formatting-only input reduces to nothing dialable
    assert dialable("() -") == ""


def test_message_key_survives_listing_truncation():
    """The MAP listing truncates bodies (~125 chars) while a bMessage
    download carries them whole; both must produce the same key."""
    from iphonebridge.events import message_key
    full = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, " * 4
    truncated = full[:125]
    assert message_key("t", "+1", full) == message_key("t", "+1", truncated)
    # Different messages at the same timestamp stay distinct
    assert message_key("t", "+1", "Alpha message") != message_key("t", "+1", "Beta message")


def test_drop_events_by_key_and_tombstones(tmp_path):
    """Local delete removes events and remembers them, so the startup
    sweep cannot re-add a message still sitting on the phone."""
    import json

    from iphonebridge.events import (
        deleted_keys,
        drop_events_by_key,
        message_key,
        record_deleted_keys,
    )

    log = tmp_path / "events.jsonl"
    rows = [
        {"kind": "sms_received", "timestamp": "t1", "sender_phone": "+1", "body": "keep"},
        {"kind": "sms_received", "timestamp": "t2", "sender_phone": "+1", "body": "drop"},
        {"kind": "sms_sent", "timestamp": "t3", "sender_phone": "+1", "body": "keep too"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    doomed = message_key("t2", "+1", "drop")
    assert drop_events_by_key(log, {doomed}) == 1
    left = [json.loads(x) for x in log.read_text().splitlines()]
    assert [e["body"] for e in left] == ["keep", "keep too"]
    # deleting nothing rewrites nothing
    assert drop_events_by_key(log, {message_key("tX", "+9", "absent")}) == 0

    tomb = tmp_path / "deleted-keys.txt"
    record_deleted_keys(tomb, [doomed, doomed])
    assert deleted_keys(tomb) == {doomed}
    assert deleted_keys(tmp_path / "absent.txt") == set()


class TestUtcStorage:
    """Timestamps are stored in UTC so the log can be ordered as text.

    A local offset is unambiguous to a parser but wrong as storage: carry
    the machine across a timezone mid-conversation and the offset changes
    under you, so lexical order stops matching real order inside one file.
    """

    @staticmethod
    def _received(**over):
        base = dict(
            kind="sms_received", handle="h1", sender_phone="+15551234567",
            sender_phone_norm="15551234567", contact_name=None, body="hi",
            timestamp=None, is_read=False, raw_status="notification",
            raw_type="sms-gsm")
        base.update(over)
        return SmsEvent(**base)

    def test_seen_at_is_utc(self):
        d = self._received().to_dict()
        assert datetime.fromisoformat(d["seen_at"]).utcoffset() == timedelta(0)

    def test_sent_timestamp_is_utc(self):
        d = sms_sent_event("+15551234567", "hi").to_dict()
        for fieldname in ("timestamp", "seen_at"):
            assert datetime.fromisoformat(d[fieldname]).utcoffset() == \
                timedelta(0)

    def test_a_live_message_has_no_map_timestamp(self):
        """Not a defect: BlueZ exports an MNS-pushed message with a
        property set that carries no Timestamp, so consumers fall back to
        seen_at."""
        assert self._received().to_dict()["timestamp"] is None

    def test_string_order_survives_a_timezone_change(self):
        """The travelling case. Two events written either side of a zone
        change must still sort correctly as plain text; under local-offset
        storage the second would sort first."""
        original = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/Chicago"
            time.tzset()
            first = self._received().to_dict()["seen_at"]
            os.environ["TZ"] = "America/Los_Angeles"
            time.tzset()
            second = self._received().to_dict()["seen_at"]
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            time.tzset()
        assert first < second
        assert datetime.fromisoformat(first) < datetime.fromisoformat(second)


class TestKeyNormalisation:
    """Keys identify an instant, not a spelling of one, so the log's
    storage format can change without orphaning tombstones."""

    INSTANT = datetime(2026, 8, 4, 20, 54, 41,
                       tzinfo=timezone(timedelta(hours=-5)))

    def test_same_instant_spelled_three_ways_gives_one_key(self):
        as_utc = self.INSTANT.astimezone(timezone.utc).isoformat()
        as_local = self.INSTANT.isoformat()
        keys = {message_key(v, "+15551234567", "hi")
                for v in (self.INSTANT, as_utc, as_local)}
        assert len(keys) == 1

    def test_legacy_tombstone_maps_onto_the_current_key(self):
        """A key written when the log stored local offsets still matches
        the key computed from the same message today."""
        legacy = "\x1f".join((self.INSTANT.isoformat(), "+15551234567", "hi"))
        assert normalize_key(legacy) == message_key(
            self.INSTANT, "+15551234567", "hi")

    def test_missing_timestamp_keeps_an_empty_field(self):
        assert message_key(None, "+1", "x") == message_key("", "+1", "x")

    def test_unparseable_timestamp_is_passed_through(self):
        key = message_key("not a date", "+1", "x")
        assert key.split("\x1f")[0] == "not a date"

    def test_normalising_a_malformed_key_is_a_no_op(self):
        assert normalize_key("no separators here") == "no separators here"


class TestParseMapTimestampZones:
    def test_bare_is_read_as_this_machines_zone_and_stored_utc(self):
        dt = parse_map_timestamp("20260804T205441")
        assert dt.utcoffset() == timedelta(0)
        assert dt == datetime(2026, 8, 4, 20, 54, 41).astimezone(timezone.utc)

    def test_explicit_z_is_honoured(self):
        assert parse_map_timestamp("20260804T205441Z") == \
            datetime(2026, 8, 4, 20, 54, 41, tzinfo=timezone.utc)

    def test_explicit_offset_is_honoured_not_discarded(self):
        assert parse_map_timestamp("20260804T205441+0530") == \
            datetime(2026, 8, 4, 15, 24, 41, tzinfo=timezone.utc)

    def test_negative_offset(self):
        assert parse_map_timestamp("20260804T205441-0500") == \
            datetime(2026, 8, 5, 1, 54, 41, tzinfo=timezone.utc)

    def test_garbage_is_none(self):
        for bad in (None, "", "nope", "2026-08-04T20:54:41"):
            assert parse_map_timestamp(bad) is None


class TestMarkLoggedRead:
    """Read-state is persisted in the log because the Message1 objects it
    comes from are transient: obexd drops them when the OBEX session
    restarts, taking their Read property with them."""

    @staticmethod
    def _log(tmp_path, entries):
        import json
        p = tmp_path / "events.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return p

    @staticmethod
    def _msg(body, read=False, ts=None, sender="+15551234567"):
        return {"kind": "sms_received", "sender_phone": sender, "body": body,
                "timestamp": ts, "is_read": read,
                "seen_at": "2026-08-25T15:00:00+00:00"}

    def _read_back(self, path):
        import json
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_marks_the_named_message(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        log = self._log(tmp_path, [self._msg("hi"), self._msg("bye")])
        key = message_key(None, "+15551234567", "hi")
        assert mark_logged_read(log, {key}) == 1
        rows = self._read_back(log)
        assert rows[0]["is_read"] is True
        assert rows[1]["is_read"] is False

    def test_already_read_is_not_counted_again(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        log = self._log(tmp_path, [self._msg("hi", read=True)])
        key = message_key(None, "+15551234567", "hi")
        assert mark_logged_read(log, {key}) == 0

    def test_unknown_key_changes_nothing(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        log = self._log(tmp_path, [self._msg("hi")])
        before = log.read_text()
        assert mark_logged_read(log, {"nope"}) == 0
        assert log.read_text() == before

    def test_empty_key_set_is_a_no_op(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        log = self._log(tmp_path, [self._msg("hi")])
        assert mark_logged_read(log, set()) == 0

    def test_missing_file_is_survivable(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        assert mark_logged_read(tmp_path / "absent.jsonl", {"k"}) == 0

    def test_other_event_kinds_are_left_alone(self, tmp_path):
        from iphonebridge.events import mark_logged_read
        note = {"kind": "ancs_notification", "app_name": "Mail",
                "seen_at": "2026-08-25T15:00:00+00:00"}
        log = self._log(tmp_path, [note, self._msg("hi")])
        assert mark_logged_read(log, {message_key(None, "+15551234567", "hi")}) == 1
        rows = self._read_back(log)
        assert rows[0] == note
        assert len(rows) == 2

    def test_key_matching_survives_timestamp_respelling(self, tmp_path):
        """The stored timestamp is normalised into the key, so a message
        logged with a local offset is still addressable."""
        from iphonebridge.events import mark_logged_read
        log = self._log(tmp_path,
                        [self._msg("hi", ts="2026-08-25T10:00:00-05:00")])
        key = message_key("2026-08-25T15:00:00+00:00", "+15551234567", "hi")
        assert mark_logged_read(log, {key}) == 1


class TestSeenEvent:
    def test_carries_keys_and_never_looks_like_a_message(self):
        from iphonebridge.events import SeenEvent
        d = SeenEvent(("a", "b")).to_dict()
        assert d["kind"] == "sms_seen"
        assert d["keys"] == ["a", "b"]
        assert "body" not in d
