"""LeLinkKeeper reconnects an iPhone stuck on BR/EDR only, with guards."""
from iphonebridge.ancs import le_link
from iphonebridge.ancs.le_link import (
    BREDR_POLL_SEC,
    BREDR_WAIT_SEC,
    LE_GRACE_CHECKS,
    LE_RETRY_SEC,
    LINK_BREDR_ONLY,
    LINK_GONE,
    LINK_LE,
    LeLinkKeeper,
    should_reconnect,
)


def test_waits_out_the_grace_period():
    assert not should_reconnect(bredr_only_checks=LE_GRACE_CHECKS - 1,
                                since_attempt=None, call_active=False)
    assert should_reconnect(bredr_only_checks=LE_GRACE_CHECKS,
                            since_attempt=None, call_active=False)


def test_never_while_on_le_or_during_a_call():
    assert not should_reconnect(bredr_only_checks=0,
                                since_attempt=None, call_active=False)
    assert not should_reconnect(bredr_only_checks=LE_GRACE_CHECKS * 10,
                                since_attempt=None, call_active=True)


def test_spaces_attempts():
    assert not should_reconnect(bredr_only_checks=LE_GRACE_CHECKS,
                                since_attempt=LE_RETRY_SEC - 1,
                                call_active=False)
    assert should_reconnect(bredr_only_checks=LE_GRACE_CHECKS,
                            since_attempt=LE_RETRY_SEC, call_active=False)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def keeper(states, clock, calls=False):
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", call_active=lambda: calls,
                     clock=clock)
    k.attempts = 0
    k._link_state = lambda: states[0]

    def reconnect():
        k.attempts += 1
    k._reconnect = reconnect
    return k


def ticks(k, n, clock, step=29.9):
    # GLib's seconds timers can fire early, so a check can land just
    # short of LE_CHECK_SEC after the previous one.
    for _ in range(n):
        clock.now += step
        assert k._tick() is True


def test_tick_reconnects_after_grace_then_spaces_retries():
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = keeper(states, clock)
    ticks(k, LE_GRACE_CHECKS - 1, clock)
    assert k.attempts == 0
    ticks(k, 1, clock)
    assert k.attempts == 1
    ticks(k, int(LE_RETRY_SEC // 29.9), clock)
    assert k.attempts == 1
    ticks(k, 1, clock)
    assert k.attempts == 2


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
    assert k.attempts == 0


def test_tick_holds_off_during_a_call_and_while_busy():
    clock, states = Clock(), [LINK_BREDR_ONLY]
    k = keeper(states, clock, calls=True)
    ticks(k, LE_GRACE_CHECKS, clock)
    assert k.attempts == 0
    k._call_active = lambda: False
    k._busy = True
    ticks(k, 1, clock)
    assert k.attempts == 0
    k._busy = False
    ticks(k, 1, clock)
    assert k.attempts == 1


class Props:
    def __init__(self, answers):
        self.answers = answers

    def Get(self, iface, prop):
        return self.answers.pop(0)


def test_profiles_wait_for_bredr_to_come_back():
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", call_active=lambda: False)
    restored = []
    k._restore_profiles = lambda: restored.append(k._bredr_waited)
    props = Props([False, False, True])
    k._props = lambda: props
    k._bredr_waited = 0
    assert k._await_bredr() is True
    assert k._await_bredr() is True
    assert k._await_bredr() is False
    assert restored == [3 * BREDR_POLL_SEC]


def test_profiles_reconnect_anyway_after_the_wait():
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", call_active=lambda: False)
    restored = []
    k._restore_profiles = lambda: restored.append(True)
    polls = BREDR_WAIT_SEC // BREDR_POLL_SEC
    props = Props([False] * polls)
    k._props = lambda: props
    k._bredr_waited = 0
    results = [k._await_bredr() for _ in range(polls)]
    assert results == [True] * (polls - 1) + [False]
    assert restored == [True]


class E:
    def __init__(self, name, message=""):
        self.name, self.message = name, message

    def get_dbus_name(self):
        return self.name

    def get_dbus_message(self):
        return self.message


def test_profile_already_connected_is_quiet(caplog):
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", call_active=lambda: False)
    k._on_profile_error(le_link.HFP_AG_UUID, le_link.PROFILE_TRIES,
                        E("org.bluez.Error.AlreadyConnected"))
    assert not caplog.records


def test_busy_profile_is_asked_again_then_reported(monkeypatch, caplog):
    timers = []
    monkeypatch.setattr(le_link.GLib, "timeout_add_seconds",
                        lambda sec, fn, *args: timers.append(args))
    k = LeLinkKeeper("/org/bluez/hci0/dev_X", call_active=lambda: False)
    busy = E("org.bluez.Error.Failed", "br-connection-busy")
    tries = le_link.PROFILE_TRIES
    while tries > 1:
        k._on_profile_error(le_link.AVRCP_UUID, tries, busy)
        tries -= 1
    assert timers == [(le_link.AVRCP_UUID, n)
                      for n in range(le_link.PROFILE_TRIES - 1, 0, -1)]
    assert not caplog.records
    k._on_profile_error(le_link.AVRCP_UUID, 1, busy)
    assert len(timers) == le_link.PROFILE_TRIES - 1
    assert "br-connection-busy" in caplog.text


class BearerProps:
    """Device1.Connected and, unless None, Bearer.LE1.Connected."""

    def __init__(self, connected, le):
        self.connected, self.le = connected, le

    def Get(self, iface, prop):
        import dbus.exceptions
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
