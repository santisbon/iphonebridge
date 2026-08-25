"""DaemonClient for the Qt front end.

Same daemon, same dbus-python calls as the GTK client — see
`iphonebridge.ui.protocol` for the shared surface. Two differences:

* signals are Qt signals on a QObject rather than GObject signals;
* the calls that used to block the UI thread are issued asynchronously.

That second point is not cosmetic. `IsHealthy` can take up to five
seconds to answer over a bad Bluetooth link, and the GTK client called it
synchronously from the main thread, which is why the connection indicator
there is driven by events and never polled. Under Qt the same call is
issued with reply/error handlers, so a dead link costs nothing.
"""
from __future__ import annotations

import json
import logging

import dbus
import dbus.exceptions
from PyQt6.QtCore import QObject, pyqtSignal

from iphonebridge.ui.protocol import (
    BUS_NAME,
    CALLS_IFACE,
    EVENT_SIGNALS,
    EVENTS_IFACE,
    MESSAGES_IFACE,
    OBJECT_PATH,
    dbus_error_text,
    plain,
    read_events,
)
from iphonebridge.ui.qtbus import session_bus

log = logging.getLogger(__name__)


class DaemonClient(QObject):
    """Live link to the daemon, as Qt signals."""

    messageReceived = pyqtSignal(object)
    messageSent = pyqtSignal(object)
    messageSeen = pyqtSignal(object)
    ancsNotification = pyqtSignal(object)
    callStateChanged = pyqtSignal(object)
    availabilityChanged = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = session_bus()
        self._matches: list = []
        self.available = False   # is the daemon reachable on D-Bus?
        self.healthy = False     # is the MAP session up?
        self._subscribe()
        self.refresh_availability()
        # Live availability: re-probe whenever the daemon's bus name
        # changes owner, so the "not reachable" banner clears by itself
        # when the daemon comes up, without anyone pressing Recheck.
        self._name_watch = self._bus.watch_name_owner(
            BUS_NAME, lambda _owner: self.refresh_availability())

    # ---- signal subscription -------------------------------------------

    def _subscribe(self) -> None:
        emitters = {
            "message-received": self.messageReceived,
            "message-sent": self.messageSent,
            "message-seen": self.messageSeen,
            "ancs-notification": self.ancsNotification,
        }
        # add_signal_receiver works even before the daemon is up — delivery
        # just starts once it claims the bus name.
        for sig, name in EVENT_SIGNALS:
            self._matches.append(self._bus.add_signal_receiver(
                lambda props, _e=emitters[name]: _e.emit(plain(props)),
                dbus_interface=EVENTS_IFACE, signal_name=sig,
                bus_name=BUS_NAME, path=OBJECT_PATH))
        self._matches.append(self._bus.add_signal_receiver(
            lambda props: self.callStateChanged.emit(plain(props)),
            dbus_interface=CALLS_IFACE, signal_name="CallStateChanged",
            bus_name=BUS_NAME, path=OBJECT_PATH))

    def stop(self) -> None:
        if self._name_watch is not None:
            try:
                self._name_watch.cancel()
            except Exception:
                pass
            self._name_watch = None
        for m in self._matches:
            try:
                m.remove()
            except Exception:
                pass
        self._matches = []

    # ---- proxy helpers --------------------------------------------------

    def _iface(self, name: str) -> dbus.Interface:
        return dbus.Interface(self._bus.get_object(BUS_NAME, OBJECT_PATH), name)

    def _set_available(self, reachable: bool, healthy: bool) -> None:
        self.healthy = healthy
        if reachable != self.available:
            self.available = reachable
            self.availabilityChanged.emit(reachable)

    def refresh_availability(self) -> None:
        """Re-probe the daemon, without blocking the UI thread.

        Emits availabilityChanged on a transition. Callers read
        `.available` for the last known answer rather than waiting.
        """
        try:
            self._iface(MESSAGES_IFACE).IsHealthy(
                timeout=5,
                reply_handler=lambda ok: self._set_available(True, bool(ok)),
                error_handler=lambda _e: self._set_available(False, False))
        except dbus.exceptions.DBusException:
            self._set_available(False, False)

    # ---- Messages1 ------------------------------------------------------

    def delete_local(self, keys: list[str], on_ok=None, on_err=None) -> None:
        """Remove messages from local history. on_ok(count)."""
        self._call(MESSAGES_IFACE, "DeleteLocal", keys,
                   on_ok=on_ok, on_err=on_err, timeout=20)

    def mark_read(self, keys: list[str], on_ok=None, on_err=None) -> None:
        """Mark messages read here and, where possible, on the iPhone."""
        self._call(MESSAGES_IFACE, "MarkRead", keys,
                   on_ok=on_ok, on_err=on_err, timeout=20)

    def profile_status(self, on_ok, on_err=None) -> None:
        """Per-profile liveness: {"map","pbap","ancs"} -> bool."""
        def parse(raw):
            try:
                on_ok(dict(json.loads(str(raw))))
            except (ValueError, TypeError):
                on_ok({})
        self._call(MESSAGES_IFACE, "GetStatus",
                   on_ok=parse, on_err=on_err, timeout=5)

    def send_message(self, recipient: str, body: str, on_ok, on_err) -> None:
        """Send asynchronously. on_ok(transfer_path) / on_err(text)."""
        self._call(MESSAGES_IFACE, "Send", recipient, body,
                   on_ok=lambda t: on_ok(str(t)), on_err=on_err, timeout=60)

    # ---- Calls1 ---------------------------------------------------------

    def dial(self, number: str, on_ok, on_err) -> None:
        self._call(CALLS_IFACE, "Dial", number,
                   on_ok=lambda p: on_ok(str(p)), on_err=on_err, timeout=45)

    def answer_call(self, call_path: str, on_err=None) -> None:
        self._call(CALLS_IFACE, "AnswerCall", call_path, on_err=on_err)

    def hangup_call(self, call_path: str, on_err=None) -> None:
        self._call(CALLS_IFACE, "HangupCall", call_path, on_err=on_err)

    def hangup_all(self, on_err=None) -> None:
        self._call(CALLS_IFACE, "HangupAll", on_err=on_err)

    def list_calls(self, on_ok, on_err=None) -> None:
        def parse(raw):
            try:
                on_ok(json.loads(str(raw)))
            except ValueError:
                on_ok([])
        self._call(CALLS_IFACE, "ListCalls", on_ok=parse, on_err=on_err,
                   timeout=15)

    # ---- the one call path ----------------------------------------------

    def _call(self, iface: str, method: str, *args,
              on_ok=None, on_err=None, timeout: int = 20) -> None:
        """Every daemon method goes out asynchronously.

        Nothing here may block: a wedged Bluetooth link must not freeze
        the window.
        """
        def failed(e) -> None:
            text = dbus_error_text(e)
            log.warning("%s failed: %s", method, text)
            if on_err is not None:
                on_err(text)
        try:
            getattr(self._iface(iface), method)(
                *args, timeout=timeout,
                reply_handler=(on_ok if on_ok is not None else lambda *_: None),
                error_handler=failed)
        except dbus.exceptions.DBusException as e:
            failed(e)

    # ---- history --------------------------------------------------------

    read_events = staticmethod(read_events)
