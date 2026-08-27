"""MediaManager — tracks the iPhone's AVRCP player and transport in BlueZ.

BlueZ does the whole protocol; this class only watches the two objects it
publishes under the device (`.../avrcp/playerN` with MediaPlayer1, the
transport with MediaTransport1) and proxies commands at them. Like the
HFP manager it has no retry loop: ObjectManager signals drive everything,
and with no player present it sits dormant. The deprecated MediaControl1
interface on the device root is ignored.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import dbus
import dbus.exceptions

from iphonebridge.bus import system_bus
from iphonebridge.media.events import (
    extrapolate_position,
    is_position_jump,
    media_state_from_bluez,
)

log = logging.getLogger(__name__)

PLAYER_IFACE = "org.bluez.MediaPlayer1"
TRANSPORT_IFACE = "org.bluez.MediaTransport1"

#: Player property changes worth a state broadcast. Position is handled
#: separately: iOS reports it sporadically and re-broadcasting each report
#: would be noise, so it only forces an emit when it disagrees with what a
#: listener would have extrapolated (a seek, or a transition we missed).
_EMIT_KEYS = frozenset({"Status", "Track", "Shuffle", "Repeat"})

SHUFFLE_VALUES = frozenset({"off", "alltracks", "group"})
REPEAT_VALUES = frozenset({"off", "singletrack", "alltracks", "group"})


class MediaError(RuntimeError):
    """No usable player/transport for the requested command."""


class MediaManager:
    """Follows one MediaPlayer1 and one MediaTransport1 under one device."""

    def __init__(self, device_path: str,
                 on_state: Callable[[dict], None]) -> None:
        self.device_path = device_path
        self.on_state = on_state

        self._player_path: str | None = None
        self._player_props: dict = {}
        self._transport_path: str | None = None
        self._volume: int | None = None

        # Base for position extrapolation and seek detection.
        self._pos_ms = 0
        self._pos_at = time.monotonic()

        self._om_matches: list = []
        self._player_match = None
        self._transport_match = None

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        log.info("media manager starting; watching %s", self.device_path)
        om = dbus.Interface(
            system_bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager",
        )
        self._om_matches.append(
            om.connect_to_signal("InterfacesAdded", self._on_iface_added)
        )
        self._om_matches.append(
            om.connect_to_signal("InterfacesRemoved", self._on_iface_removed)
        )
        self._sweep(om)

    def stop(self) -> None:
        log.info("media manager stopping")
        for m in self._om_matches:
            self._safe_remove(m)
        self._om_matches = []
        self._drop_player(emit=False)
        self._drop_transport(emit=False)

    @staticmethod
    def _safe_remove(match) -> None:
        try:
            if match is not None:
                match.remove()
        except Exception:
            pass

    def _sweep(self, om=None) -> None:
        """Adopt whatever already exists — same idempotency trick as the
        ANCS client: replay current objects through the added-handler."""
        if om is None:
            om = dbus.Interface(
                system_bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
        try:
            managed = om.GetManagedObjects()
        except dbus.exceptions.DBusException:
            log.exception("media sweep failed")
            return
        for path, ifaces in managed.items():
            self._on_iface_added(path, ifaces)

    # ---- ObjectManager handlers -----------------------------------------

    def _under_device(self, path: str) -> bool:
        return path.startswith(self.device_path + "/")

    def _on_iface_added(self, path, ifaces) -> None:
        path_s = str(path)
        if not self._under_device(path_s):
            return
        if PLAYER_IFACE in ifaces and self._player_path is None:
            self._player_path = path_s
            self._player_props = dict(ifaces[PLAYER_IFACE])
            self._rebase_position(self._player_props.get("Position"))
            self._player_match = system_bus.add_signal_receiver(
                self._on_player_props,
                dbus_interface="org.freedesktop.DBus.Properties",
                signal_name="PropertiesChanged",
                path=path_s,
            )
            log.info("AVRCP player appeared: .../%s",
                     path_s.rsplit("/", 2)[-1])
            self._emit()
        if TRANSPORT_IFACE in ifaces and self._transport_path is None:
            self._transport_path = path_s
            vol = ifaces[TRANSPORT_IFACE].get("Volume")
            self._volume = None if vol is None else int(vol)
            self._transport_match = system_bus.add_signal_receiver(
                self._on_transport_props,
                dbus_interface="org.freedesktop.DBus.Properties",
                signal_name="PropertiesChanged",
                path=path_s,
            )
            self._emit()

    def _on_iface_removed(self, path, ifaces) -> None:
        path_s = str(path)
        if path_s == self._player_path and PLAYER_IFACE in ifaces:
            log.info("AVRCP player gone")
            self._drop_player(emit=True)
            # iOS can leave a sibling player behind when the fronting app
            # changes; adopt a survivor rather than going dark.
            self._sweep()
        if path_s == self._transport_path and TRANSPORT_IFACE in ifaces:
            self._drop_transport(emit=True)
            self._sweep()

    def _drop_player(self, *, emit: bool) -> None:
        self._safe_remove(self._player_match)
        self._player_match = None
        self._player_path = None
        self._player_props = {}
        self._rebase_position(0)
        if emit:
            self._emit()

    def _drop_transport(self, *, emit: bool) -> None:
        self._safe_remove(self._transport_match)
        self._transport_match = None
        self._transport_path = None
        self._volume = None
        if emit:
            self._emit()

    # ---- property change handlers ---------------------------------------

    def _on_player_props(self, iface, changed, _invalidated) -> None:
        if str(iface) != PLAYER_IFACE:
            return
        keys = {str(k) for k in changed}
        self._player_props.update(changed)
        if "Track" in keys and "Position" not in keys:
            # New track, no position report yet: playback restarted at 0
            # and waiting for iOS's next report would show the old spot.
            self._rebase_position(0)
        if "Position" in keys:
            reported = int(changed["Position"])
            jump = is_position_jump(self._position_estimate(), reported)
            self._rebase_position(reported)
            if not (keys & _EMIT_KEYS) and not jump:
                return  # silent cache update
        elif "Status" in keys:
            # A transition re-bases the estimate at the current spot so
            # pause/resume doesn't jump.
            self._rebase_position(self._position_estimate())
        if keys & _EMIT_KEYS or "Position" in keys:
            self._emit()

    def _on_transport_props(self, iface, changed, _invalidated) -> None:
        if str(iface) != TRANSPORT_IFACE:
            return
        if "Volume" in changed:
            self._volume = int(changed["Volume"])
            self._emit()

    # ---- state ----------------------------------------------------------

    def _rebase_position(self, position_ms) -> None:
        try:
            self._pos_ms = max(0, int(position_ms))
        except (TypeError, ValueError):
            self._pos_ms = 0
        self._pos_at = time.monotonic()

    def _position_estimate(self) -> int:
        track = self._player_props.get("Track") or {}
        try:
            duration = int(track.get("Duration", 0))
        except (TypeError, ValueError):
            duration = 0
        elapsed_ms = int((time.monotonic() - self._pos_at) * 1000)
        return extrapolate_position(
            self._pos_ms, str(self._player_props.get("Status", "")),
            elapsed_ms, duration)

    def snapshot(self) -> dict:
        """Current state as the flat wire dict."""
        props = self._player_props if self._player_path else None
        pos = self._position_estimate() if props is not None else None
        return media_state_from_bluez(props, self._volume,
                                      position_ms=pos).to_dict()

    def _emit(self) -> None:
        try:
            self.on_state(self.snapshot())
        except Exception:
            log.exception("media state fan-out failed")

    # ---- commands -------------------------------------------------------

    def _player(self) -> dbus.Interface:
        if self._player_path is None:
            raise MediaError("no media player connected")
        return dbus.Interface(
            system_bus.get_object("org.bluez", self._player_path),
            PLAYER_IFACE)

    def _player_set(self, prop: str, value) -> None:
        if self._player_path is None:
            raise MediaError("no media player connected")
        dbus.Interface(
            system_bus.get_object("org.bluez", self._player_path),
            "org.freedesktop.DBus.Properties",
        ).Set(PLAYER_IFACE, prop, value)

    def play(self) -> None:
        self._player().Play()

    def pause(self) -> None:
        self._player().Pause()

    def next(self) -> None:
        self._player().Next()

    def previous(self) -> None:
        self._player().Previous()

    def set_volume(self, volume: int) -> None:
        if self._transport_path is None:
            raise MediaError("no media transport connected")
        volume = max(0, min(127, int(volume)))
        # BlueZ's Volume is type q; a plain int marshals as i and is
        # rejected, hence the explicit UInt16.
        dbus.Interface(
            system_bus.get_object("org.bluez", self._transport_path),
            "org.freedesktop.DBus.Properties",
        ).Set(TRANSPORT_IFACE, "Volume", dbus.UInt16(volume))

    def set_shuffle(self, value: str) -> None:
        self._player_set("Shuffle", value)

    def set_repeat(self, value: str) -> None:
        self._player_set("Repeat", value)
