"""One notification, one row — across BLE reconnections and in the log.

Versions up to 0.18.2 subscribed to the ANCS Notification Source and
Data Source again on every reconnection without removing the previous
PropertiesChanged receivers. BlueZ re-creates the characteristics at
the same object paths, so the old receivers kept matching, and N
stacked subscriptions turned one notification into N^2 rows. Two things
guard against that now: the client drops a session's receivers when it
ends, and the daemon compacts a log an older version wrote.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from iphonebridge.events import drop_duplicate_ancs

# ---- the client, against a fake system bus ---------------------------------

NS_UUID = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
DS_UUID = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"
CP_UUID = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
NS_PATH = DEV + "/service0010/char0011"
DS_PATH = DEV + "/service0010/char0013"
CP_PATH = DEV + "/service0010/char0015"


class FakeMatch:
    def __init__(self, bus, handler, path):
        self.bus, self.handler, self.path = bus, handler, path
        self.removed = False

    def remove(self):
        self.removed = True
        self.bus.live.discard(self)


class FakeProxy:
    """Enough of a dbus ProxyObject for dbus.Interface to wrap."""

    def __init__(self, bus):
        self.bus = bus

    def get_dbus_method(self, name, dbus_interface=None):
        if name == "GetManagedObjects":
            return lambda: {}
        return lambda *a, **k: None

    def connect_to_signal(self, signal_name, handler, dbus_interface=None,
                          **kw):
        return FakeMatch(self.bus, handler, "/")


class FakeBus:
    def __init__(self):
        self.live: set[FakeMatch] = set()
        self.added: list[FakeMatch] = []

    def get_object(self, name, path):
        return FakeProxy(self)

    def add_signal_receiver(self, handler, dbus_interface=None,
                            signal_name=None, path=None, **kw):
        m = FakeMatch(self, handler, path)
        self.live.add(m)
        self.added.append(m)
        return m

    def fire(self, path, value):
        """A PropertiesChanged on `path`, delivered to every live receiver
        matching it, the way the bus daemon would."""
        for m in list(self.live):
            if m.path == path:
                m.handler("org.bluez.GattCharacteristic1",
                          {"Value": value}, [])


@pytest.fixture
def client(monkeypatch):
    bus = FakeBus()
    fake_mod = types.ModuleType("iphonebridge.bus")
    fake_mod.system_bus = bus
    monkeypatch.setitem(sys.modules, "iphonebridge.bus", fake_mod)
    monkeypatch.delitem(sys.modules, "iphonebridge.ancs.client",
                        raising=False)
    from iphonebridge.ancs.client import AncsClient
    c = AncsClient(DEV, on_event=lambda e: None)
    c.start()
    return c, bus


def chars_added(c):
    for path, uuid in ((NS_PATH, NS_UUID), (DS_PATH, DS_UUID),
                       (CP_PATH, CP_UUID)):
        c._on_iface_added(path, {"org.bluez.GattCharacteristic1":
                                 {"UUID": uuid}})


def chars_removed(c):
    for path in (NS_PATH, DS_PATH, CP_PATH):
        c._on_iface_removed(path, ["org.bluez.GattCharacteristic1"])


def receivers_on(bus, path):
    return [m for m in bus.live if m.path == path]


class TestResubscribe:
    def test_first_session_has_one_receiver_per_characteristic(self, client):
        c, bus = client
        chars_added(c)
        assert len(receivers_on(bus, NS_PATH)) == 1
        assert len(receivers_on(bus, DS_PATH)) == 1

    def test_reconnection_does_not_stack_receivers(self, client):
        """The reported fault: after three reconnections a notification
        was logged nine times."""
        c, bus = client
        for _ in range(4):
            chars_added(c)
            chars_removed(c)
            chars_added(c)
        assert len(receivers_on(bus, NS_PATH)) == 1
        assert len(receivers_on(bus, DS_PATH)) == 1
        assert c._notify_started

    def test_removed_session_leaves_no_receiver(self, client):
        c, bus = client
        chars_added(c)
        chars_removed(c)
        assert receivers_on(bus, NS_PATH) == []
        assert receivers_on(bus, DS_PATH) == []
        assert not c._notify_started

    def test_resubscribe_without_a_removal_still_does_not_stack(self, client):
        """BlueZ may keep the characteristic objects across a drop, in
        which case no InterfacesRemoved ever arrives."""
        c, bus = client
        chars_added(c)
        c._notify_started = False       # what a silent drop looks like
        c._try_subscribe()
        assert len(receivers_on(bus, NS_PATH)) == 1
        assert len(receivers_on(bus, DS_PATH)) == 1

    def test_one_notification_requests_attributes_once(self, client, monkeypatch):
        """End to end on the bus: one Notification Source packet after
        three reconnections writes one GetNotificationAttributes."""
        import struct

        from iphonebridge.ancs.constants import EventID
        c, bus = client
        requests = []
        monkeypatch.setattr(c, "_request_attrs", lambda n: requests.append(n.id))
        for _ in range(3):
            chars_added(c)
            chars_removed(c)
        chars_added(c)
        bus.fire(NS_PATH, struct.pack("<BBBBI", EventID.NotificationAdded,
                                      0, 4, 1, 77))
        assert requests == [77]

    def test_stop_removes_everything(self, client):
        c, bus = client
        chars_added(c)
        c.stop()
        assert bus.live == set()


# ---- the daemon, when the phone re-sends a uid -------------------------------


def _bare_daemon():
    """A Daemon with only the ANCS fan-out state, no bus or sessions."""
    from iphonebridge.daemon import Daemon
    d = Daemon.__new__(Daemon)
    d._ancs_uid_map = {}
    d._ancs_uid_content = {}
    d.sinks = []
    d._dbus_service = None
    return d


def _ancs_event(uid=5, title="t", body="b"):
    from iphonebridge.ancs.events import AncsEvent
    return AncsEvent(notification_id=uid, device_path=DEV,
                     app_id="com.example.app", app_name="Example",
                     title=title, subtitle="", body=body, category="Other",
                     is_silent=False, is_preexisting=False,
                     positive_action=None, negative_action=None)


class _Sink:
    name = "probe"

    def __init__(self):
        self.got = []

    def handle_ancs(self, event):
        self.got.append(event)


class TestResend:
    def test_unchanged_resend_is_delivered_once(self):
        d = _bare_daemon()
        sink = _Sink()
        d.sinks.append(sink)
        d._fanout_ancs(_ancs_event())
        d._fanout_ancs(_ancs_event())
        assert len(sink.got) == 1

    def test_changed_content_on_the_uid_is_delivered(self):
        d = _bare_daemon()
        sink = _Sink()
        d.sinks.append(sink)
        d._fanout_ancs(_ancs_event(body="one"))
        d._fanout_ancs(_ancs_event(body="two"))
        assert len(sink.got) == 2

    def test_new_session_forgets_the_uid(self):
        """uids restart per connection: the same number with the same
        words after a reset is a notification the user has not seen."""
        d = _bare_daemon()
        sink = _Sink()
        d.sinks.append(sink)
        d._fanout_ancs(_ancs_event())
        d._ancs_session_reset()
        d._fanout_ancs(_ancs_event())
        assert len(sink.got) == 2

    def test_dismissed_then_resent_is_delivered(self):
        d = _bare_daemon()
        sink = _Sink()
        d.sinks.append(sink)
        d._fanout_ancs(_ancs_event())
        d._ancs_uid_map.pop(5)          # what a dismissal leaves behind
        d._fanout_ancs(_ancs_event())
        assert len(sink.got) == 2


# ---- the log, written by an older version ------------------------------------

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def row(uid=1, at=T0, title="t", body="b", app="com.example.app", **extra):
    return {"kind": "ancs_notification", "device_path": DEV,
            "notification_id": uid, "app_id": app, "title": title,
            "subtitle": "", "body": body, "seen_at": at.isoformat(), **extra}


def write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def stamps(path):
    return [json.loads(line)["seen_at"]
            for line in path.read_text().splitlines()]


class TestCompaction:
    def test_copies_within_a_second_collapse_to_the_first(self, tmp_path):
        log = tmp_path / "events.jsonl"
        copies = [row(at=T0 + timedelta(milliseconds=i * 10)) for i in range(9)]
        write(log, copies)
        assert drop_duplicate_ancs(log) == 8
        assert stamps(log) == [T0.isoformat()]

    def test_different_uids_are_different_notifications(self, tmp_path):
        """Same app, same words, new uid: a genuine re-notification."""
        log = tmp_path / "events.jsonl"
        write(log, [row(uid=1), row(uid=2, at=T0 + timedelta(seconds=1))])
        assert drop_duplicate_ancs(log) == 0

    def test_different_content_on_one_uid_is_kept(self, tmp_path):
        log = tmp_path / "events.jsonl"
        write(log, [row(body="first"), row(body="second",
                                             at=T0 + timedelta(seconds=1))])
        assert drop_duplicate_ancs(log) == 0

    def test_same_uid_in_a_later_session_is_kept(self, tmp_path):
        """uids restart with every BLE connection, so the same number an
        hour later is a new notification. Only the window ties copies."""
        log = tmp_path / "events.jsonl"
        write(log, [row(), row(at=T0 + timedelta(hours=1))])
        assert drop_duplicate_ancs(log) == 0

    def test_messages_and_unreadable_lines_are_untouched(self, tmp_path):
        log = tmp_path / "events.jsonl"
        log.write_text(
            json.dumps({"kind": "sms_received", "seen_at": T0.isoformat(),
                        "body": "x"}) + "\n"
            + "not json\n"
            + json.dumps(row()) + "\n"
            + json.dumps(row(at=T0 + timedelta(seconds=2))) + "\n"
            + json.dumps({"kind": "sms_received", "seen_at": T0.isoformat(),
                          "body": "x"}) + "\n")
        assert drop_duplicate_ancs(log) == 1
        assert log.read_text().count("sms_received") == 2
        assert "not json" in log.read_text()

    def test_missing_stamp_is_never_dropped(self, tmp_path):
        log = tmp_path / "events.jsonl"
        a, b = row(), row()
        del a["seen_at"], b["seen_at"]
        write(log, [a, b])
        assert drop_duplicate_ancs(log) == 0

    def test_clean_log_is_not_rewritten(self, tmp_path):
        log = tmp_path / "events.jsonl"
        write(log, [row(uid=1), row(uid=2)])
        before = log.stat().st_mtime_ns
        assert drop_duplicate_ancs(log) == 0
        assert log.stat().st_mtime_ns == before

    def test_missing_log_is_fine(self, tmp_path):
        assert drop_duplicate_ancs(tmp_path / "nope.jsonl") == 0
