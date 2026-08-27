"""PhoneMonitor — battery, cellular and identity read off the iPhone.

Three sources feed one flat status dict:

- BlueZ's ``org.bluez.Battery1`` on the device (exact percentage, backed
  by the phone's GATT battery service, updated by notification);
- oFono's HFP modem: ``NetworkRegistration`` for cellular signal,
  carrier and registration, ``Handsfree`` for a coarse 0-5 battery level
  used only when Battery1 is absent;
- the GATT Device Information service for the model identifier (Apple
  exposes model and manufacturer only — no software revision, so no iOS
  version travels over Bluetooth at all).

The pure helpers live at the top so CI can test the mapping without a
phone. Only ``PhoneMonitor`` touches D-Bus.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import dbus
import dbus.exceptions

from iphonebridge.bus import system_bus

log = logging.getLogger(__name__)

BATTERY_IFACE = "org.bluez.Battery1"
_DIS_UUIDS = {
    "00002a24-0000-1000-8000-00805f9b34fb": "model",
    "00002a29-0000-1000-8000-00805f9b34fb": "manufacturer",
}
_OFONO = "org.ofono"


# ---- pure helpers (CI-tested) -------------------------------------------

def hfp_level_to_pct(level) -> int:
    """HFP's 0-5 battery indicator as a rough percentage; -1 unknown."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return -1
    if not 0 <= level <= 5:
        return -1
    return level * 20


def build_phone_status(battery_pct=-1, hfp_level=-1, signal_pct=-1,
                       network="", reg="", model="",
                       manufacturer="") -> dict:
    """The flat wire dict. Battery1's exact reading wins; the HFP level
    fills in as an estimate when that is all there is."""
    try:
        pct = int(battery_pct)
    except (TypeError, ValueError):
        pct = -1
    estimated = False
    if pct < 0:
        pct = hfp_level_to_pct(hfp_level)
        estimated = pct >= 0
    try:
        sig = int(signal_pct)
    except (TypeError, ValueError):
        sig = -1
    return {
        "battery_pct": pct,
        "battery_estimated": estimated,
        "signal_pct": max(-1, min(100, sig)),
        "network": "" if network is None else str(network),
        "reg": "" if reg is None else str(reg),
        "model": "" if model is None else str(model),
        "manufacturer": "" if manufacturer is None else str(manufacturer),
    }


class BatteryAlarm:
    """Fires once per dip below the threshold, with hysteresis.

    Re-arms only after the battery climbs 5 points clear, so a reading
    that hovers at the threshold cannot ring on every update. A
    threshold of 0 (or less) disables it.
    """

    def __init__(self, threshold: int) -> None:
        self.threshold = int(threshold)
        self._armed = True

    def update(self, pct: int) -> bool:
        if self.threshold <= 0 or pct < 0:
            return False
        if self._armed and pct <= self.threshold:
            self._armed = False
            return True
        if not self._armed and pct >= self.threshold + 5:
            self._armed = True
        return False


# ---- the D-Bus watcher --------------------------------------------------

class PhoneMonitor:
    """Follows the three sources and reports one dict on every change."""

    def __init__(self, device_path: str,
                 on_change: Callable[[dict], None]) -> None:
        self.device_path = device_path
        self.on_change = on_change
        # oFono's HFP modem path embeds the BlueZ device path.
        self._dev_leaf = device_path.rsplit("/", 1)[1]

        self._battery_pct = -1
        self._hfp_level = -1
        self._signal = -1
        self._network = ""
        self._reg = ""
        self._identity: dict[str, str] = {}   # "model"/"manufacturer"
        self._dis_paths: dict[str, str] = {}  # key -> char path
        self._modem_path: str | None = None
        self._matches: list = []

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        log.info("phone monitor starting; watching %s", self.device_path)
        om = dbus.Interface(system_bus.get_object("org.bluez", "/"),
                            "org.freedesktop.DBus.ObjectManager")
        self._matches.append(
            om.connect_to_signal("InterfacesAdded", self._on_bluez_added))
        self._matches.append(
            om.connect_to_signal("InterfacesRemoved",
                                 self._on_bluez_removed))
        self._matches.append(system_bus.add_signal_receiver(
            self._on_device_props,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged", path=self.device_path))
        try:
            for path, ifaces in om.GetManagedObjects().items():
                self._on_bluez_added(path, ifaces, sweep=True)
        except dbus.exceptions.DBusException:
            log.exception("phone monitor BlueZ sweep failed")

        # oFono may not be running at all; the phone works without calls.
        self._matches.append(system_bus.add_signal_receiver(
            self._on_modem_added, dbus_interface="org.ofono.Manager",
            signal_name="ModemAdded"))
        self._matches.append(system_bus.add_signal_receiver(
            self._on_netreg_prop, dbus_interface="org.ofono.NetworkRegistration",
            signal_name="PropertyChanged", path_keyword="opath"))
        self._matches.append(system_bus.add_signal_receiver(
            self._on_hf_prop, dbus_interface="org.ofono.Handsfree",
            signal_name="PropertyChanged", path_keyword="opath"))
        try:
            mgr = dbus.Interface(system_bus.get_object(_OFONO, "/"),
                                 "org.ofono.Manager")
            for path, _props in mgr.GetModems():
                self._on_modem_added(path, _props)
        except dbus.exceptions.DBusException:
            log.info("oFono not reachable; no cellular status")
        self._emit()

    def stop(self) -> None:
        log.info("phone monitor stopping")
        for m in self._matches:
            try:
                m.remove()
            except Exception:
                pass
        self._matches = []

    # ---- BlueZ side -----------------------------------------------------

    def _on_bluez_added(self, path, ifaces, sweep: bool = False) -> None:
        path_s = str(path)
        if BATTERY_IFACE in ifaces and path_s == self.device_path:
            pct = ifaces[BATTERY_IFACE].get("Percentage")
            self._battery_pct = -1 if pct is None else int(pct)
            if not sweep:
                self._emit()
        ch = ifaces.get("org.bluez.GattCharacteristic1")
        if ch is not None and path_s.startswith(self.device_path + "/"):
            key = _DIS_UUIDS.get(str(ch.get("UUID", "")).lower())
            if key is not None:
                self._dis_paths[key] = path_s
                self._read_identity()

    def _on_bluez_removed(self, path, ifaces) -> None:
        if BATTERY_IFACE in ifaces and str(path) == self.device_path:
            self._battery_pct = -1
            self._emit()

    def _on_device_props(self, iface, changed, _invalidated) -> None:
        if str(iface) != BATTERY_IFACE:
            return
        if "Percentage" in changed:
            self._battery_pct = int(changed["Percentage"])
            self._emit()

    def _read_identity(self) -> None:
        """Model and manufacturer never change; read until they stick.
        The read reaches the phone, so it fails while disconnected and
        is simply retried on the next battery/cellular activity."""
        for key, path in self._dis_paths.items():
            if key in self._identity:
                continue
            try:
                val = dbus.Interface(
                    system_bus.get_object("org.bluez", path),
                    "org.bluez.GattCharacteristic1").ReadValue({})
                self._identity[key] = bytes(val).decode(errors="replace")
            except dbus.exceptions.DBusException:
                pass

    # ---- oFono side -----------------------------------------------------

    def _on_modem_added(self, path, _props) -> None:
        path_s = str(path)
        if self._dev_leaf not in path_s:
            return
        self._modem_path = path_s
        for iface_name, handler in (
                ("org.ofono.NetworkRegistration", self._apply_netreg),
                ("org.ofono.Handsfree", self._apply_hf)):
            try:
                props = dbus.Interface(
                    system_bus.get_object(_OFONO, path_s),
                    iface_name).GetProperties()
            except dbus.exceptions.DBusException:
                continue
            for k, v in props.items():
                handler(str(k), v)
        self._emit()

    def _on_netreg_prop(self, name, value, opath=None) -> None:
        if self._modem_path is None or str(opath) != self._modem_path:
            return
        if self._apply_netreg(str(name), value):
            self._emit()

    def _on_hf_prop(self, name, value, opath=None) -> None:
        if self._modem_path is None or str(opath) != self._modem_path:
            return
        if self._apply_hf(str(name), value):
            self._emit()

    def _apply_netreg(self, name, value) -> bool:
        if name == "Strength":
            self._signal = int(value)
        elif name == "Name":
            self._network = str(value)
        elif name == "Status":
            self._reg = str(value)
        else:
            return False
        return True

    def _apply_hf(self, name, value) -> bool:
        if name != "BatteryChargeLevel":
            return False
        self._hfp_level = int(value)
        return True

    # ---- state ----------------------------------------------------------

    def snapshot(self) -> dict:
        if len(self._identity) < len(self._dis_paths):
            self._read_identity()
        return build_phone_status(
            battery_pct=self._battery_pct, hfp_level=self._hfp_level,
            signal_pct=self._signal, network=self._network, reg=self._reg,
            model=self._identity.get("model", ""),
            manufacturer=self._identity.get("manufacturer", ""))

    def _emit(self) -> None:
        try:
            self.on_change(self.snapshot())
        except Exception:
            log.exception("phone status fan-out failed")
