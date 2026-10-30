"""LeLinkKeeper re-arms LE auto-connect for an iPhone stuck on BR/EDR."""
import dbus.exceptions

from iphonebridge.ancs import le_link
from iphonebridge.ancs.le_link import (
    LE_GRACE_CHECKS,
    LE_REARM_SEC,
    LINK_BREDR_ONLY,
    LINK_GONE,
    LINK_LE,
    LeLinkKeeper,
    rearm_le,
    should_rearm,
)


def test_waits_out_the_grace_period():
    assert not should_rearm(bredr_only_checks=LE_GRACE_CHECKS - 1,
                            since_rearm=None)
    assert should_rearm(bredr_only_checks=LE_GRACE_CHECKS, since_rearm=None)


def test_never_while_on_le():
    assert not should_rearm(bredr_only_checks=0, since_rearm=None)


def test_spaces_rearms():
    assert not should_rearm(bredr_only_checks=LE_GRACE_CHECKS,
                            since_rearm=LE_REARM_SEC - 1)
    assert should_rearm(bredr_only_checks=LE_GRACE_CHECKS,
                        since_rearm=LE_REARM_SEC)


class SetProps:
    """Records PreferredBearer writes; fails the writes listed in fail."""

    def __init__(self, fail=()):
        self.writes, self.fail = [], set(fail)

    def Set(self, iface, prop, value):
        assert (iface, prop) == (le_link.DEVICE, "PreferredBearer")
        self.writes.append(value)
        if value in self.fail:
            raise dbus.exceptions.DBusException("org.bluez.Error.Failed")


def test_rearm_changes_the_bearer_so_bluez_acts():
    # bluetoothd ignores a write of the value it already holds, so the
    # property has to change: away from "le", then back.
    props = SetProps()
    rearm_le(props)
    assert props.writes == ["bredr", "le"]


def test_rearm_never_leaves_the_bearer_on_bredr():
    props = SetProps(fail={"bredr"})
    try:
        rearm_le(props)
    except dbus.exceptions.DBusException:
        pass
    assert props.writes[-1] == "le"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def keeper(states, clock):
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", clock=clock)
    k.rearms = 0
    k._link_state = lambda: states[0]

    def rearm():
        k.rearms += 1
        k._rearmed = True
    k._rearm = rearm
    return k


def ticks(k, n, clock, step=29.9):
    # GLib's seconds timers can fire early, so a check can land just
    # short of LE_CHECK_SEC after the previous one.
    for _ in range(n):
        clock.now += step
        assert k._tick() is True


def test_tick_rearms_after_grace_then_spaces_rearms():
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = keeper(states, clock)
    ticks(k, LE_GRACE_CHECKS - 1, clock)
    assert k.rearms == 0
    ticks(k, 1, clock)
    assert k.rearms == 1
    ticks(k, int(LE_REARM_SEC // 29.9), clock)
    assert k.rearms == 1
    ticks(k, 1, clock)
    assert k.rearms == 2


def test_tick_rearms_after_grace_when_le_drops_again(caplog):
    caplog.set_level("INFO")
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = keeper(states, clock)
    ticks(k, LE_GRACE_CHECKS, clock)
    assert k.rearms == 1
    states[0] = LINK_LE
    ticks(k, 1, clock)
    assert "LE link is up" in caplog.text
    # LE dropped well inside LE_REARM_SEC of the last re-arm: the next
    # re-arm waits only for the grace period.
    states[0] = LINK_BREDR_ONLY
    ticks(k, LE_GRACE_CHECKS, clock)
    assert k.rearms == 2


def test_tick_restarts_the_grace_period_when_le_comes_back():
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = keeper(states, clock)
    ticks(k, LE_GRACE_CHECKS - 1, clock)
    states[0] = LINK_LE
    ticks(k, 1, clock)
    states[0] = LINK_BREDR_ONLY
    ticks(k, LE_GRACE_CHECKS - 1, clock)
    states[0] = LINK_GONE
    ticks(k, 1, clock)
    assert k.rearms == 0


def test_failed_rearm_is_reported_and_retried(caplog):
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", clock=clock)
    k._link_state = lambda: states[0]
    props = SetProps(fail={"le"})
    k._props = lambda: props
    ticks(k, LE_GRACE_CHECKS, clock)
    assert "re-arming LE auto-connect failed" in caplog.text
    assert not k._rearmed
    ticks(k, int(LE_REARM_SEC // 29.9) + 1, clock)
    assert props.writes == ["bredr", "le", "bredr", "le"]


class BearerProps:
    """Device1.Connected and, unless None, Bearer.LE1.Connected."""

    def __init__(self, connected, le):
        self.connected, self.le = connected, le

    def Get(self, iface, prop):
        if iface == le_link.BEARER_LE:
            if self.le is None:
                raise dbus.exceptions.DBusException("UnknownInterface")
            return self.le
        return self.connected


def test_le_connected_reads_the_le_bearer():
    assert le_link.le_connected(BearerProps(True, True)) is True
    assert le_link.le_connected(BearerProps(True, False)) is False
    assert le_link.le_connected(BearerProps(True, None)) is None


def test_ancs_active_needs_the_le_link(monkeypatch):
    from iphonebridge.ancs import client

    k = client.AncsClient("/org/bluez/hci0/dev_X", on_event=lambda e: None)
    k._notify_started = True
    for connected, le, want in ((True, True, True),
                                (True, False, False),  # BR/EDR only
                                (False, False, False),
                                (True, None, True)):   # no bearer state
        props = BearerProps(connected, le)
        monkeypatch.setattr(client.dbus, "Interface",
                            lambda obj, iface, props=props: props)
        monkeypatch.setattr(client.system_bus, "get_object",
                            lambda *a, **kw: object())
        assert k.active is want, (connected, le)
