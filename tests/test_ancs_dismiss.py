"""Dismissal, both directions — the toolkit-free pieces.

The wire format and the log rewrite are what CI can hold: the negative
action command sent to the phone, the removal event coming back, and the
notification leaving the history file. The D-Bus and Qt plumbing between
them runs only on a machine with a bus.
"""
from __future__ import annotations

import json
import struct

from iphonebridge.ancs.constants import ActionID, CommandID, EventFlag, EventID
from iphonebridge.ancs.parsers import Notification, build_perform_action
from iphonebridge.events import drop_ancs_by_seen_at


class TestNegativeActionPacket:
    """What we write to the Control Point to dismiss on the iPhone."""

    def test_shape(self):
        pkt = build_perform_action(0x0A0B0C0D, is_positive=False)
        assert len(pkt) == 6
        assert pkt[0] == CommandID.PerformNotificationAction
        assert struct.unpack("<I", pkt[1:5])[0] == 0x0A0B0C0D
        assert pkt[5] == ActionID.Negative

    def test_positive_differs_only_in_the_action(self):
        neg = build_perform_action(7, is_positive=False)
        pos = build_perform_action(7, is_positive=True)
        assert neg[:5] == pos[:5]
        assert pos[5] == ActionID.Positive


class TestRemovalEvent:
    """What the phone sends when a notification is dismissed there."""

    @staticmethod
    def packet(event_id, flags, uid):
        return struct.pack("<BBBBI", event_id, flags, 4, 1, uid)

    def test_removed_parses(self):
        n = Notification.parse(self.packet(EventID.NotificationRemoved, 0, 42))
        assert n.type == EventID.NotificationRemoved
        assert n.id == 42

    def test_removed_with_preexisting_flag_is_still_a_removal(self):
        """The client must handle removals before its preexisting skip: a
        dismissal has to reach the app however the notification first
        arrived."""
        n = Notification.parse(
            self.packet(EventID.NotificationRemoved, EventFlag.PreExisting, 9))
        assert n.type == EventID.NotificationRemoved
        assert n.is_preexisting  # both true at once — order in the client decides


class TestLogRemoval:
    """Dismissal must survive an app restart, so it rewrites the log."""

    @staticmethod
    def write(path, events):
        path.write_text("".join(json.dumps(e) + "\n" for e in events))

    @staticmethod
    def kinds(path):
        return [json.loads(line)["kind"] for line in path.read_text().splitlines()]

    def test_drops_only_the_named_notification(self, tmp_path):
        log = tmp_path / "events.jsonl"
        self.write(log, [
            {"kind": "sms_received", "seen_at": "T1", "body": "keep"},
            {"kind": "ancs_notification", "seen_at": "T2", "title": "drop me"},
            {"kind": "ancs_notification", "seen_at": "T3", "title": "keep"},
        ])
        assert drop_ancs_by_seen_at(log, {"T2"}) == 1
        assert self.kinds(log) == ["sms_received", "ancs_notification"]

    def test_message_sharing_the_stamp_survives(self, tmp_path):
        """Addressing is by kind AND stamp, so a dismissal can never take
        an SMS with it."""
        log = tmp_path / "events.jsonl"
        self.write(log, [
            {"kind": "sms_received", "seen_at": "T9"},
            {"kind": "ancs_notification", "seen_at": "T9"},
        ])
        assert drop_ancs_by_seen_at(log, {"T9"}) == 1
        assert self.kinds(log) == ["sms_received"]

    def test_unknown_stamp_leaves_the_file_alone(self, tmp_path):
        log = tmp_path / "events.jsonl"
        self.write(log, [{"kind": "ancs_notification", "seen_at": "T1"}])
        before = log.read_text()
        assert drop_ancs_by_seen_at(log, {"nope"}) == 0
        assert log.read_text() == before

    def test_malformed_lines_are_preserved(self, tmp_path):
        log = tmp_path / "events.jsonl"
        log.write_text('not json\n'
                       '{"kind": "ancs_notification", "seen_at": "T1"}\n')
        assert drop_ancs_by_seen_at(log, {"T1"}) == 1
        assert log.read_text() == "not json\n"
