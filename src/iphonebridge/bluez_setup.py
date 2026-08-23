"""BlueZ adapter prep — the toggle-dance from spike/RESULTS.md §1.

For MAP/PBAP to be reachable on iOS 26.5, three things must be true on
the Linux side:

1. Adapter Class-of-Device set to A/V Hands-Free (Major=4 Minor=8).
2. A BLE peripheral advert is active with SolicitUUIDs containing the
   ANCS UUID. Without this, the iPhone never surfaces the per-device
   "Show Message Notifications" / "Sync Contacts" toggles.
3. Adapter is powered.

This module owns those three concerns. Re-run safely on startup.

CoD setting requires CAP_NET_ADMIN (essentially root), so we shell out to
sudo btmgmt unless we detect we already have it. The BLE advert is
user-bus DBus and needs no privileges.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

import dbus
import dbus.exceptions
import dbus.service

from iphonebridge import config
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


def set_cod(*, dry_run: bool = False) -> bool:
    """Apply A/V Hands-Free CoD via btmgmt. Returns True on success."""
    cmd = ["btmgmt", "class", str(config.COD_MAJOR), str(config.COD_MINOR)]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd  # non-interactive sudo; user pre-grants
    log.info("setting adapter CoD via: %s", " ".join(cmd))
    if dry_run:
        return True
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.error("btmgmt failed: %s", e)
        return False
    if r.returncode != 0:
        log.error("btmgmt class %d %d failed (rc=%d): %s",
                  config.COD_MAJOR, config.COD_MINOR, r.returncode,
                  r.stderr.strip() or r.stdout.strip())
        return False
    log.info("CoD set ok: %s", r.stdout.strip())
    return True


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
              "'Show System Notifications' toggle, so ANCS stays dark.")
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


# ---- one-shot startup ---------------------------------------------------

def prepare(*, allow_sudo: bool = True) -> bool:
    """Run all the prerequisites. Returns False if anything critical failed.

    Idempotent. Safe to call on every daemon start.
    """
    ok = True
    cod = current_cod()
    log.info("current adapter Class = 0x%06x", cod or 0)
    if not desired_cod_matches(cod):
        if not allow_sudo and os.geteuid() != 0:
            log.warning("CoD wrong but sudo disabled — skipping CoD set")
        else:
            ok &= set_cod()
    else:
        log.info("CoD already matches A/V Hands-Free, leaving as-is")

    # Dispatch only — the real outcome is logged from the callback, and it
    # must not gate `ok`, which the daemon uses to decide whether MAP/PBAP
    # are likely to work. ANCS is independent of those.
    register_advert()
    return ok
