"""Bring the iPhone's LE link back when the phone is on BR/EDR only.

ANCS is a GATT service iOS serves over LE. After a reboot or a Bluetooth
restart the iPhone reconnects over BR/EDR alone and stays there, so
per-app notifications stop until something reconnects it over LE. On
2026-10-28, with BlueZ 5.87, the phone held BR/EDR without LE
for the whole minute after BlueZ dropped only its LE link, and for the
whole boot after a reboot.

Bearer.LE1.Connect cannot add the LE link next to the BR/EDR one: iOS
also serves GATT over BR/EDR, and while that ATT channel is up BlueZ's
device_connect_le() refuses with EALREADY ("There is one connection
attempt going on", src/device.c in 5.87). So this does what
`iphonebridge ancs-enable` does: disconnect the device, then connect it
with Device1.PreferredBearer = "le". The phone brings BR/EDR back by
itself, sometimes without the Hands-Free or AV Remote Control profile,
so those are reconnected once BR/EDR is back. The disconnect interrupts
messages, calls and media, which is why should_reconnect() waits out a
grace period, never runs during a call, and spaces attempts apart.

iOS does not always take the LE link back: on 2026-10-28, from 22:45 on,
every attempt either failed with le-connection-abort-by-local or brought
LE up without ANCS, and the phone was on BR/EDR only again by the next
attempt. Each such attempt is still a disconnect, so the wait doubles
after every attempt that no ANCS subscription follows, from LE_RETRY_SEC
up to LE_RETRY_MAX_SEC, and starts over once ANCS is subscribed.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import dbus
import dbus.exceptions
from gi.repository import GLib

from iphonebridge import config
from iphonebridge.bus import system_bus

log = logging.getLogger(__name__)

# How often to look at the iPhone's links.
LE_CHECK_SEC = 30
# How many checks in a row must find the phone on BR/EDR only before we
# act: right after a connection BlueZ and iOS may still be bringing LE up
# themselves. Counted in checks, not seconds, because GLib's seconds
# timers can fire a little early and a 30 s check would then measure
# 29.9 s and wait a whole extra interval.
LE_GRACE_CHECKS = 2
# Time between the first reconnect and the second; it doubles after each
# attempt without ANCS, up to LE_RETRY_MAX_SEC, so a phone that keeps
# refusing LE is not knocked off BR/EDR over and over.
LE_RETRY_SEC = 10 * 60
LE_RETRY_MAX_SEC = 4 * 60 * 60
# After the LE connect, poll this often, at most this long, for iOS to
# bring BR/EDR back. Connecting a profile before then races iOS's own
# reconnect and fails with br-connection-busy.
BREDR_POLL_SEC = 5
BREDR_WAIT_SEC = 60
# A profile that BlueZ reports busy is asked for again this many times,
# this far apart.
PROFILE_TRIES = 3
PROFILE_RETRY_SEC = 10

# BR/EDR profiles iOS can leave out when it comes back after the
# disconnect: Hands-Free Audio Gateway (calls) and AV Remote Control
# (media controls).
HFP_AG_UUID = "0000111f-0000-1000-8000-00805f9b34fb"
AVRCP_UUID = "0000110e-0000-1000-8000-00805f9b34fb"

DEVICE = "org.bluez.Device1"
BEARER_LE = "org.bluez.Bearer.LE1"
BEARER_BREDR = "org.bluez.Bearer.BREDR1"
PROPS = "org.freedesktop.DBus.Properties"

# _link_state() values
LINK_GONE = "gone"            # no device object, or not connected at all
LINK_UNSUPPORTED = "unsupported"  # BlueZ offers no bearer control
LINK_NO_GRANT = "no-grant"    # the bond never exposed ANCS
LINK_LE = "le"                # the LE link is up
LINK_BREDR_ONLY = "bredr-only"


def le_connected(props: dbus.Interface) -> bool | None:
    """Whether the device's LE link is up, read from Bearer.LE1 through
    the device's Properties interface. None when BlueZ offers no
    per-bearer state (bluetoothd without -E): Device1.Connected is then
    all there is, and it reads true over either bearer."""
    try:
        return bool(props.Get(BEARER_LE, "Connected"))
    except dbus.exceptions.DBusException:
        return None


def retry_delay(attempts: int) -> float:
    """The wait after `attempts` reconnects in a row that no ANCS
    subscription followed: LE_RETRY_SEC after the first, doubling after
    each one, at most LE_RETRY_MAX_SEC."""
    return min(LE_RETRY_SEC * 2 ** max(attempts - 1, 0), LE_RETRY_MAX_SEC)


def should_reconnect(*, bredr_only_checks: int,
                     since_attempt: float | None,
                     attempts: int,
                     call_active: bool) -> bool:
    """Whether to reconnect the iPhone over LE now.

    `bredr_only_checks` is how many checks in a row found the phone on
    BR/EDR only, `since_attempt` how long ago the last reconnect began
    (None if never), `attempts` how many reconnects no ANCS subscription
    has followed.
    """
    if bredr_only_checks < LE_GRACE_CHECKS:
        return False
    if call_active:
        return False
    return since_attempt is None or since_attempt >= retry_delay(attempts)


class LeLinkKeeper:
    """Polls the iPhone's links and reconnects it over LE when needed."""

    def __init__(self, device_path: str, *,
                 call_active: Callable[[], bool],
                 ancs_active: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.device_path = device_path
        self._call_active = call_active
        self._ancs_active = ancs_active
        self._clock = clock
        self._timer_id: int | None = None
        self._bredr_only_checks = 0
        self._last_attempt: float | None = None
        # Reconnects since ANCS was last subscribed.
        self._attempts = 0
        self._bredr_waited = 0
        self._busy = False
        self._said_unsupported = False

    def start(self) -> None:
        if self._timer_id is None:
            self._timer_id = GLib.timeout_add_seconds(LE_CHECK_SEC,
                                                      self._tick)

    def stop(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    # ---- polling --------------------------------------------------------

    def _props(self) -> dbus.Interface:
        return dbus.Interface(
            system_bus.get_object("org.bluez", self.device_path), PROPS)

    def _link_state(self) -> str:
        props = self._props()
        try:
            dev = props.GetAll(DEVICE)
        except dbus.exceptions.DBusException:
            return LINK_GONE
        if not bool(dev.get("Connected", False)):
            return LINK_GONE
        wanted = config.ANCS_SOLICIT_UUID.lower()
        if not any(str(u).lower() == wanted for u in dev.get("UUIDs", [])):
            return LINK_NO_GRANT
        # PreferredBearer and Bearer.LE1 exist only with bluetoothd -E.
        if "PreferredBearer" not in dev:
            return LINK_UNSUPPORTED
        le = le_connected(props)
        if le is None:
            return LINK_UNSUPPORTED
        return LINK_LE if le else LINK_BREDR_ONLY

    def _tick(self) -> bool:
        """GLib timer callback. Return True to keep the timer running."""
        if self._busy:
            return True
        if self._attempts and self._ancs_active():
            self._attempts = 0
        state = self._link_state()
        if state == LINK_UNSUPPORTED and not self._said_unsupported:
            self._said_unsupported = True
            log.info("BlueZ offers no bearer control (bluetoothd runs "
                     "without -E), so the iPhone's LE link is not "
                     "restored automatically")
        if state != LINK_BREDR_ONLY:
            self._bredr_only_checks = 0
            return True
        self._bredr_only_checks += 1
        now = self._clock()
        since_attempt = (None if self._last_attempt is None
                         else now - self._last_attempt)
        if should_reconnect(bredr_only_checks=self._bredr_only_checks,
                            since_attempt=since_attempt,
                            attempts=self._attempts,
                            call_active=self._call_active()):
            self._last_attempt = now
            self._attempts += 1
            self._reconnect()
        return True

    # ---- the reconnect ----------------------------------------------------

    def _device(self) -> dbus.Interface:
        return dbus.Interface(
            system_bus.get_object("org.bluez", self.device_path), DEVICE)

    def _reconnect(self) -> None:
        log.info("iPhone is connected over classic Bluetooth only; "
                 "reconnecting it over LE for per-app notifications")
        self._busy = True
        # PreferredBearer only takes effect while disconnected. A
        # NotConnected error means the phone already went: carry on.
        self._device().Disconnect(
            reply_handler=self._connect_le,
            error_handler=lambda _e: self._connect_le(),
            timeout=20)

    def _connect_le(self) -> None:
        try:
            self._props().Set(DEVICE, "PreferredBearer", "le")
            self._device().Connect(
                reply_handler=self._on_le_connected,
                error_handler=self._on_le_failed,
                timeout=60)
        except dbus.exceptions.DBusException as e:
            self._on_le_failed(e)

    def _on_le_failed(self, e: dbus.exceptions.DBusException) -> None:
        self._busy = False
        log.warning("LE reconnect failed: %s — next try in %d min at "
                    "the earliest",
                    e.get_dbus_message() or e.get_dbus_name(),
                    retry_delay(self._attempts) // 60)

    def _on_le_connected(self) -> None:
        log.info("iPhone reconnected over LE")
        self._bredr_waited = 0
        GLib.timeout_add_seconds(BREDR_POLL_SEC, self._await_bredr)

    def _await_bredr(self) -> bool:
        """GLib timer callback: wait for iOS to bring BR/EDR back, then
        restore the profiles. Past BREDR_WAIT_SEC, connecting the
        profiles brings BR/EDR up from this side instead."""
        self._bredr_waited += BREDR_POLL_SEC
        try:
            back = bool(self._props().Get(BEARER_BREDR, "Connected"))
        except dbus.exceptions.DBusException:
            back = False
        if not back and self._bredr_waited < BREDR_WAIT_SEC:
            return True
        self._restore_profiles()
        return False

    def _restore_profiles(self) -> None:
        """Reconnect calls and media controls if iOS came back without
        them."""
        self._busy = False
        for uuid in (HFP_AG_UUID, AVRCP_UUID):
            self._connect_profile(uuid, PROFILE_TRIES)

    def _connect_profile(self, uuid: str, tries: int) -> bool:
        self._device().ConnectProfile(
            uuid,
            reply_handler=lambda: None,
            error_handler=lambda e: self._on_profile_error(uuid, tries, e),
            timeout=30)
        return False  # one-shot when run as a GLib timer callback

    def _on_profile_error(self, uuid: str, tries: int,
                          e: dbus.exceptions.DBusException) -> None:
        if e.get_dbus_name() == "org.bluez.Error.AlreadyConnected":
            return
        message = e.get_dbus_message() or e.get_dbus_name()
        # iOS is still connecting its own profiles on the fresh BR/EDR
        # link, often the very one asked for: ask again shortly.
        if message == "br-connection-busy" and tries > 1:
            GLib.timeout_add_seconds(PROFILE_RETRY_SEC,
                                     self._connect_profile, uuid, tries - 1)
            return
        log.warning("reconnecting profile %s after the LE reconnect "
                    "failed: %s", uuid, message)
