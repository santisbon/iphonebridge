"""BlueZ adapter prep — the toggle-dance from spike/RESULTS.md §1.

For MAP/PBAP to be reachable on iOS 26.5, three things must be true on
the Linux side:

1. Adapter Class-of-Device set to A/V Hands-Free (Major=4 Minor=8).
2. A BLE peripheral advert is active with SolicitUUIDs containing the
   ANCS UUID. Without this, the iPhone never surfaces the per-device
   "Show Message Notifications" / "Sync Contacts" toggles.
3. Adapter is powered.

This module owns those three concerns. Re-run safely on startup.

Setting the CoD requires CAP_NET_ADMIN (essentially root), so the daemon
asks systemd on the system bus to start iphonebridge-cod.service, a root
unit that runs `btmgmt class 4 8`. A polkit rule lets any local user start
that one unit and nothing else, so the daemon never runs sudo. The BLE
advert is user-bus DBus and needs no privileges.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import dbus
import dbus.exceptions
import dbus.service

from iphonebridge import config
from iphonebridge.ancs.constants import ANCS_CHAR_UUIDS
from iphonebridge.bus import bluez, system_bus

log = logging.getLogger(__name__)


# ---- Class-of-Device ----------------------------------------------------

def current_cod() -> int | None:
    """Return adapter Class field, or None if unavailable."""
    try:
        v = bluez(f"/org/bluez/{config.ADAPTER}",
                  "org.freedesktop.DBus.Properties").Get(
            "org.bluez.Adapter1", "Class")
        return int(v)
    except dbus.exceptions.DBusException:
        return None


def desired_cod_matches(cod: int | None) -> bool:
    """Major & Minor match what we want? Service-class bits are derived
    by BlueZ from registered profiles, so we only compare the low 16 bits
    of (Major<<8 | Minor<<2)."""
    if cod is None:
        return False
    major = (cod >> 8) & 0x1F
    minor = (cod >> 2) & 0x3F
    return major == config.COD_MAJOR and (minor << 2) == config.COD_MINOR


COD_UNIT = "iphonebridge-cod.service"


def set_cod(*, wait: float = 5.0) -> bool:
    """Start the root unit that sets A/V Hands-Free CoD, then wait for the
    adapter to report it. Returns True once the CoD matches."""
    log.info("starting %s to set the adapter CoD", COD_UNIT)
    try:
        manager = dbus.Interface(
            system_bus.get_object("org.freedesktop.systemd1",
                                  "/org/freedesktop/systemd1"),
            "org.freedesktop.systemd1.Manager")
        manager.StartUnit(COD_UNIT, "replace")
    except dbus.exceptions.DBusException as e:
        log.error("could not start %s: %s", COD_UNIT, e.get_dbus_message())
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if desired_cod_matches(current_cod()):
            log.info("CoD set to A/V Hands-Free")
            return True
        time.sleep(0.25)
    log.error("%s ran, but the adapter CoD is still 0x%06x "
              "(journalctl -u %s)", COD_UNIT, current_cod() or 0, COD_UNIT)
    return False


# ---- BLE advertisement (SolicitUUIDs = ANCS) ----------------------------

class _AncsAdvert(dbus.service.Object):
    """Minimal LEAdvertisement1 object so iOS shows our toggles."""

    PATH = config.BLE_ADVERT_DBUS_PATH

    @dbus.service.method("org.bluez.LEAdvertisement1",
                         in_signature="", out_signature="")
    def Release(self) -> None:
        return None

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface: str) -> dict[str, Any]:
        if iface != "org.bluez.LEAdvertisement1":
            raise dbus.exceptions.DBusException(
                f"Unknown interface {iface}",
                name="org.freedesktop.DBus.Error.InvalidArgs")
        return {
            "Type": dbus.String("peripheral"),
            "SolicitUUIDs": dbus.Array([config.ANCS_SOLICIT_UUID], signature="s"),
            "LocalName": dbus.String(config.BLE_ADVERT_LOCAL_NAME),
            "Includes": dbus.Array(["tx-power"], signature="s"),
        }

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="ss", out_signature="v")
    def Get(self, iface: str, prop: str):
        return self.GetAll(iface)[prop]


_advert_instance: _AncsAdvert | None = None
_advert_registered = False


def advert_registered() -> bool:
    """True only if BlueZ confirmed *our* advertisement."""
    return _advert_registered


def _on_advert_registered() -> None:
    global _advert_registered
    _advert_registered = True
    log.info("BLE advert registered: %s", _AncsAdvert.PATH)


def _on_advert_error(e: dbus.exceptions.DBusException) -> None:
    global _advert_registered
    name = e.get_dbus_name()
    if name == "org.bluez.Error.AlreadyExists":
        _advert_registered = True
        log.info("BLE advert already registered")
        return
    _advert_registered = False
    log.error("RegisterAdvertisement failed: %s: %s", name, e.get_dbus_message())
    log.error("  → Without this advertisement iOS won't offer the "
              "'Share System Notifications' toggle, so ANCS stays dark.")
    log.error("  → MAP and PBAP are unaffected; messages and contacts "
              "still work.")


def register_advert() -> bool:
    """Ask BlueZ to advertise ANCS solicitation. Returns whether the call was
    dispatched, not whether it succeeded — the outcome arrives on a callback.

    Deliberately asynchronous. RegisterAdvertisement makes BlueZ call back
    into our LEAdvertisement1 object to read its properties, so a blocking
    call deadlocks: we sit inside the outbound call with no main loop to
    service the inbound one, and both time out. That NoReply used to be
    reported as probable success by checking ActiveInstances > 0 — but that
    property is adapter-wide and counts every other application's
    advertisements, so the check could never fail and masked a registration
    that never happened.
    """
    global _advert_instance, _advert_registered
    if _advert_instance is None:
        _advert_instance = _AncsAdvert(system_bus, _AncsAdvert.PATH)
    _advert_registered = False

    ad_mgr = bluez(f"/org/bluez/{config.ADAPTER}",
                   "org.bluez.LEAdvertisingManager1")
    try:
        ad_mgr.RegisterAdvertisement(
            _AncsAdvert.PATH, {},
            reply_handler=_on_advert_registered,
            error_handler=_on_advert_error,
        )
    except dbus.exceptions.DBusException as e:
        log.error("RegisterAdvertisement could not be dispatched: %s",
                  e.get_dbus_name())
        return False
    log.info("BLE advert registration dispatched; awaiting BlueZ")
    return True


def unregister_advert() -> None:
    """Best-effort unregister; safe to call on shutdown."""
    global _advert_registered
    if not _advert_registered:
        return
    try:
        ad_mgr = bluez(f"/org/bluez/{config.ADAPTER}",
                       "org.bluez.LEAdvertisingManager1")
        ad_mgr.UnregisterAdvertisement(_AncsAdvert.PATH)
        log.info("BLE advert unregistered")
    except dbus.exceptions.DBusException as e:
        log.debug("UnregisterAdvertisement: %s", e.get_dbus_name())
    _advert_registered = False


def probe_advert(timeout_s: int = 10) -> tuple[bool, str]:
    """Register a throwaway advertisement and report BlueZ's verdict.

    Diagnostic (doctor), not part of daemon startup. Registration is
    asynchronous for the same reason register_advert's docstring gives —
    BlueZ calls back into the advertisement object to read its properties,
    so a blocking call deadlocks — hence the private main loop here.

    Returns (ok, detail). detail carries the D-Bus error name on failure,
    or "timeout" if BlueZ never answered.
    """
    from gi.repository import GLib

    path = config.BLE_ADVERT_DBUS_PATH + "_probe"
    ad = _AncsAdvert(system_bus, path)
    loop = GLib.MainLoop()
    outcome: dict[str, str] = {}

    def done() -> None:
        outcome["result"] = "ok"
        loop.quit()

    def failed(e: dbus.exceptions.DBusException) -> None:
        outcome["result"] = e.get_dbus_name() or "unknown"
        loop.quit()

    ad_mgr = bluez(f"/org/bluez/{config.ADAPTER}",
                   "org.bluez.LEAdvertisingManager1")
    try:
        ad_mgr.RegisterAdvertisement(path, {}, reply_handler=done,
                                     error_handler=failed)
    except dbus.exceptions.DBusException as e:
        ad.remove_from_connection()
        return False, e.get_dbus_name() or "dispatch failed"

    GLib.timeout_add_seconds(timeout_s, loop.quit)
    loop.run()

    result = outcome.get("result", "timeout")
    if result == "ok":
        try:
            ad_mgr.UnregisterAdvertisement(path)
        except dbus.exceptions.DBusException:
            pass
    ad.remove_from_connection()
    return result == "ok", "" if result == "ok" else result


# Where ANCS stands for the paired iPhone, as ancs_state() reports it.
ANCS_NO_DEVICE = "no-device"        # device object not found
ANCS_NO_BOND = "no-bond"            # bond never exposed the ANCS service
ANCS_DISCONNECTED = "disconnected"  # granted, but the phone is not connected
ANCS_NO_LE = "no-le"                # granted and connected, but not over LE
ANCS_LIVE = "live"                  # the three characteristics exist now


def ancs_state() -> str:
    """Report ANCS for the paired iPhone as one of the ANCS_* values.

    The device's UUID list says whether iOS ever granted ANCS to this
    bond, but BlueZ keeps it from the last LE session, so it reads the
    same with the phone on LE now as with the phone reconnected over
    BR/EDR only. ANCS is a GATT service, so what matters is whether its
    three characteristic objects exist under the device right now — the
    same thing the daemon's ANCS client waits for, which is why this
    agrees with the app's Status tab where the UUID check did not.
    """
    dev_path = config.device_path()
    try:
        props = bluez(dev_path, "org.freedesktop.DBus.Properties")
        uuids = props.Get("org.bluez.Device1", "UUIDs")
        connected = bool(props.Get("org.bluez.Device1", "Connected"))
    except dbus.exceptions.DBusException:
        return ANCS_NO_DEVICE
    wanted = config.ANCS_SOLICIT_UUID.lower()
    if not any(str(u).lower() == wanted for u in uuids):
        return ANCS_NO_BOND
    if not connected:
        return ANCS_DISCONNECTED
    return ANCS_LIVE if _ancs_chars_present(dev_path) else ANCS_NO_LE


def _ancs_chars_present(dev_path: str) -> bool:
    """True when all three ANCS characteristics exist under dev_path."""
    try:
        managed = bluez("/", "org.freedesktop.DBus.ObjectManager"
                        ).GetManagedObjects()
    except dbus.exceptions.DBusException:
        return False
    prefix = dev_path + "/"
    found = set()
    for path, ifaces in managed.items():
        char = ifaces.get("org.bluez.GattCharacteristic1")
        if char is None or not str(path).startswith(prefix):
            continue
        found.add(str(char.get("UUID", "")).lower())
    return ANCS_CHAR_UUIDS <= found


# ---- one-shot startup ---------------------------------------------------

def prepare() -> bool:
    """Run all the prerequisites. Returns False if anything critical failed.

    Idempotent. Safe to call on every daemon start.
    """
    ok = True
    cod = current_cod()
    log.info("current adapter Class = 0x%06x", cod or 0)
    if desired_cod_matches(cod):
        log.info("CoD already matches A/V Hands-Free, leaving as-is")
    else:
        ok &= set_cod()

    # Dispatch only — the real outcome is logged from the callback, and it
    # must not gate `ok`, which the daemon uses to decide whether MAP/PBAP
    # are likely to work. ANCS is independent of those.
    register_advert()
    return ok
