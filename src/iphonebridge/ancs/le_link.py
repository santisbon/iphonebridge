"""Bring the iPhone's LE link back when the phone is on BR/EDR only.

ANCS is a GATT service iOS serves over LE. After a reboot or a Bluetooth
restart the iPhone reconnects over BR/EDR alone and stays there, so
per-app notifications stop until the LE link comes back.

Linux does not dial an LE device on demand. The kernel puts the device's
identity address on the controller's accept list and connects when it
hears that device advertise; an iPhone advertises from a rotating
resolvable private address, which the controller matches to the identity
address only if the iPhone's IRK is on the controller's resolving list.
The kernel programs the resolving list only for a device that bluetoothd
has added to the kernel's LE auto-connect list and flagged for address
resolution (adapter_set_device_flags, src/adapter.c in BlueZ 5.87).
bluetoothd does that when Device1.PreferredBearer changes to "le"
(dev_property_set_prefer_bearer, src/device.c); setting the property to
the value it already holds does nothing.

On 2026-10-29 the iPhone had fallen off the auto-connect list while its
PreferredBearer stayed "le". Every LE connect then waited on the accept
list for the iPhone's identity address, which an iPhone never advertises
from, and timed out with le-connection-abort-by-local; Device1.Connect()
fell back to BR/EDR and returned success. Setting PreferredBearer to
"bredr" and back to "le" put the iPhone back on both lists, and the
kernel brought LE up next to BR/EDR at the iPhone's next advertisement,
with no disconnect: ANCS was subscribed 5 seconds later.

So this re-arms the iPhone that way when it is on BR/EDR only. Re-arming
changes no link, so it runs during calls too. It repeats every
LE_REARM_SEC while the phone stays on BR/EDR only, because bluetoothd
takes a device off the auto-connect list again after three LE
authentication failures (device_remove_connection, src/device.c), and
because the iPhone advertises little while its screen is off.
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
# Time between re-arms while the phone stays on BR/EDR only.
LE_REARM_SEC = 10 * 60

DEVICE = "org.bluez.Device1"
BEARER_LE = "org.bluez.Bearer.LE1"
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


def rearm_le(props: dbus.Interface) -> None:
    """Put the device back on the kernel's LE auto-connect list, with
    address resolution, through the device's Properties interface.

    bluetoothd acts only on a change of PreferredBearer: "bredr" takes
    the device off the list and "le" adds it back. The second write runs
    even if the first fails, so the property never stays "bredr". Raises
    DBusException when BlueZ refuses either write.
    """
    try:
        props.Set(DEVICE, "PreferredBearer", "bredr")
    finally:
        props.Set(DEVICE, "PreferredBearer", "le")


def should_rearm(*, bredr_only_checks: int,
                 since_rearm: float | None) -> bool:
    """Whether to re-arm the iPhone's LE auto-connect now.

    `bredr_only_checks` is how many checks in a row found the phone on
    BR/EDR only, `since_rearm` how long ago the last re-arm in this
    stretch on BR/EDR only ran (None if none has).
    """
    if bredr_only_checks < LE_GRACE_CHECKS:
        return False
    return since_rearm is None or since_rearm >= LE_REARM_SEC


class LeLinkKeeper:
    """Polls the iPhone's links and re-arms LE auto-connect when needed."""

    def __init__(self, device_path: str, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.device_path = device_path
        self._clock = clock
        self._timer_id: int | None = None
        self._bredr_only_checks = 0
        self._last_rearm: float | None = None
        # A re-arm ran and LE has not been seen up since.
        self._rearmed = False
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
        state = self._link_state()
        if state == LINK_UNSUPPORTED and not self._said_unsupported:
            self._said_unsupported = True
            log.info("BlueZ offers no bearer control (bluetoothd runs "
                     "without -E), so the iPhone's LE link is not "
                     "restored automatically")
        if state == LINK_LE:
            if self._rearmed:
                log.info("iPhone's LE link is up")
                self._rearmed = False
            self._last_rearm = None
        if state != LINK_BREDR_ONLY:
            self._bredr_only_checks = 0
            return True
        self._bredr_only_checks += 1
        now = self._clock()
        since_rearm = (None if self._last_rearm is None
                       else now - self._last_rearm)
        if should_rearm(bredr_only_checks=self._bredr_only_checks,
                        since_rearm=since_rearm):
            self._last_rearm = now
            self._rearm()
        return True

    def _rearm(self) -> None:
        log.info("iPhone is connected over classic Bluetooth only; "
                 "re-arming LE auto-connect so LE comes up at its next "
                 "advertisement")
        try:
            rearm_le(self._props())
        except dbus.exceptions.DBusException as e:
            log.warning("re-arming LE auto-connect failed: %s",
                        e.get_dbus_message() or e.get_dbus_name())
            return
        self._rearmed = True
