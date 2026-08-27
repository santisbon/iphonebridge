"""ArtFetcher — pulls AVRCP cover art over a bip-avrcp OBEX session.

The image handle arrives with the track metadata (BlueZ's `ImgHandle`);
the bytes come over a separate OBEX image service the iPhone advertises
inside its AVRCP record, whose L2CAP PSM BlueZ surfaces as the player's
`ObexPort`. obexd speaks the protocol; this class only drives its client
API: one session, `Image1.Get` per handle, a small on-disk cache.

Everything is asynchronous. Fetches are triggered from BlueZ signal
callbacks on the daemon's GLib loop, and an OBEX transfer takes long
enough that blocking there would stall every other subsystem.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import dbus
import dbus.exceptions

from iphonebridge import config
from iphonebridge.bus import session_bus

log = logging.getLogger(__name__)

OBEX_BUS = "org.bluez.obex"
_CACHE_KEEP = 8  # covers kept on disk; enough to flip between tracks

#: Fetch outcome callback: (handle, path-or-None).
DoneCb = Callable[[str, str | None], None]


def _art_dir() -> Path:
    d = config.STATE_DIR / "art"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _art_file(handle: str) -> Path:
    safe = "".join(ch for ch in handle if ch.isalnum()) or "0"
    return _art_dir() / f"cover_{safe}.img"


def _prune(keep: Path) -> None:
    files = sorted(_art_dir().glob("cover_*.img"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[_CACHE_KEEP:]:
        if p != keep:
            try:
                p.unlink()
            except OSError:
                pass


class ArtFetcher:
    """One bip-avrcp session, created lazily and dropped on any error so
    the next fetch starts fresh — the session dies with the audio link
    and there is no signal telling us when."""

    def __init__(self, address: str) -> None:
        self.address = address
        self._session_path: str | None = None
        self._connecting = False
        self._busy = False
        self._psm = 0
        self._retry_armed = False
        # The daemon restarts obexd whenever it rebuilds its MAP/PBAP
        # sessions, which kills this session with no signal to us — and
        # iOS stops offering image handles the moment the channel drops.
        # Follow the bus name so every obexd comes back with a session.
        self._name_watch = session_bus.watch_name_owner(
            OBEX_BUS, self._on_obex_owner)

    # ---- public ---------------------------------------------------------

    def connect(self, psm: int) -> None:
        """Bring the bip-avrcp session up ahead of any fetch.

        Not an optimisation: iOS only includes the image handle in track
        metadata while the controller holds this OBEX channel open
        (measured live — the handle appeared on the first track change
        after connecting, and never without). Waiting for a handle
        before connecting therefore waits forever.
        """
        self._psm = int(psm)
        if self._session_path is not None or self._connecting:
            return
        self._connecting = True
        self._create_session(self._psm,
                             lambda: None, lambda: None)

    def fetch(self, handle: str, psm: int, on_done: DoneCb) -> None:
        """Get the cover for `handle`, from cache or the phone."""
        self._psm = int(psm)
        target = _art_file(handle)
        if target.is_file() and target.stat().st_size > 0:
            on_done(handle, str(target))
            return
        if self._busy:
            # One transfer at a time; the caller re-triggers on the next
            # track change, and stale art is worse than late art.
            log.info("art fetch busy; skipping handle request")
            return
        self._busy = True
        if self._session_path is None:
            self._create_session(psm,
                                 lambda: self._get(handle, target, on_done),
                                 lambda: self._done(on_done, handle, None))
        else:
            self._get(handle, target, on_done)

    def close(self) -> None:
        self._psm = 0   # no reconnect behind a deliberate close
        path, self._session_path = self._session_path, None
        if path is None:
            return
        try:
            dbus.Interface(
                session_bus.get_object(OBEX_BUS, "/org/bluez/obex"),
                "org.bluez.obex.Client1",
            ).RemoveSession(path, timeout=10)
        except dbus.exceptions.DBusException:
            pass

    # ---- plumbing -------------------------------------------------------

    def _done(self, on_done: DoneCb, handle: str, path: str | None) -> None:
        self._busy = False
        on_done(handle, path)

    def _on_obex_owner(self, owner: str) -> None:
        # Any owner change means our session object is gone.
        self._session_path = None
        if owner and self._psm > 0:
            self.connect(self._psm)

    def _arm_retry(self) -> None:
        if self._retry_armed:
            return
        self._retry_armed = True
        from gi.repository import GLib

        def retry() -> bool:
            self._retry_armed = False
            if self._session_path is None and self._psm > 0:
                self.connect(self._psm)
            return False

        GLib.timeout_add_seconds(10, retry)

    def _drop_session(self) -> None:
        self._session_path = None
        # An obexd restart kills the session behind our back, and iOS
        # stops offering image handles the moment the channel is gone —
        # re-establish eagerly rather than waiting for a fetch that will
        # never be asked for.
        if self._psm > 0:
            self.connect(self._psm)

    def _create_session(self, psm: int, ok: Callable[[], None],
                        err: Callable[[], None]) -> None:
        def created(path) -> None:
            self._connecting = False
            self._session_path = str(path)
            log.info("bip-avrcp session up")
            ok()

        def failed(e) -> None:
            self._connecting = False
            log.warning("bip-avrcp CreateSession failed: %s", e)
            self._arm_retry()
            err()

        dbus.Interface(
            session_bus.get_object(OBEX_BUS, "/org/bluez/obex"),
            "org.bluez.obex.Client1",
        ).CreateSession(
            self.address,
            {"Target": "bip-avrcp", "PSM": dbus.UInt16(psm)},
            timeout=30, reply_handler=created, error_handler=failed)

    def _get(self, handle: str, target: Path, on_done: DoneCb) -> None:
        tmp = target.with_suffix(".part")

        def started(*ret) -> None:
            transfer = str(ret[0])
            self._watch_transfer(transfer, handle, tmp, target, on_done)

        def failed(e) -> None:
            log.warning("Image1.Get failed: %s", e)
            # The session outlives the link silently; a fresh one next
            # time is the only recovery there is.
            self._drop_session()
            self._done(on_done, handle, None)

        dbus.Interface(
            session_bus.get_object(OBEX_BUS, self._session_path),
            "org.bluez.obex.Image1",
        ).Get(str(tmp), handle, {}, timeout=30,
              reply_handler=started, error_handler=failed)

    def _watch_transfer(self, transfer: str, handle: str, tmp: Path,
                        target: Path, on_done: DoneCb) -> None:
        from gi.repository import GLib
        match: dict = {}

        def finish(path: str | None) -> None:
            m = match.pop("m", None)
            if m is not None:
                try:
                    m.remove()
                except Exception:
                    pass
            self._done(on_done, handle, path)

        def on_props(iface, changed, _inv) -> None:
            if str(iface) != "org.bluez.obex.Transfer1":
                return
            status = str(changed.get("Status", ""))
            if status == "complete":
                try:
                    os.replace(tmp, target)
                except OSError:
                    finish(None)
                    return
                _prune(target)
                finish(str(target))
            elif status == "error":
                tmp.unlink(missing_ok=True)
                self._drop_session()
                finish(None)

        match["m"] = session_bus.add_signal_receiver(
            on_props, dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged", bus_name=OBEX_BUS,
            path=transfer)

        def timed_out() -> bool:
            if match.get("m") is not None:
                log.warning("cover art transfer timed out")
                tmp.unlink(missing_ok=True)
                self._drop_session()
                finish(None)
            return False

        GLib.timeout_add_seconds(30, timed_out)
