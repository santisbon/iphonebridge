"""iphonebridge-ui on Qt — entry point and the bridge QML talks to.

A separate process from the daemon, as before: its application id is
`me.santisbon.iphonebridge.UI` and it reaches the daemon over D-Bus.

Ordering matters here. The QApplication must exist before the D-Bus
connection, because the Qt main-loop integration installs QSocketNotifiers
which need an application object — see `iphonebridge.ui.qtbus`.
"""
from __future__ import annotations

import logging
import pathlib
import sys

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from iphonebridge.contacts import ContactsResolver
from iphonebridge.ui.model import ThreadStore
from iphonebridge.ui.qtmodels import MessageListModel, NotificationListModel, ThreadListModel
from iphonebridge.ui.util import resolve_recipient

log = logging.getLogger(__name__)

QML_DIR = pathlib.Path(__file__).parent / "qml"


class Bridge(QObject):
    """What QML can call, and what it watches."""

    changed = pyqtSignal()

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client
        self._contacts = ContactsResolver()
        self.store = ThreadStore()
        self.threads = ThreadListModel(self.store)
        self.messages = MessageListModel(self.store)
        self.notifications = NotificationListModel()
        self._thread_name = ""
        self._status = "Checking…"
        self._calls = "No active calls"

        for ev in client.read_events(kinds={"sms_received", "sms_sent"}):
            self.store.ingest(ev, outgoing=(ev.get("kind") == "sms_sent"))
        for ev in client.read_events(kinds={"ancs_notification"}):
            self.notifications.add(ev)
        self.threads.refresh()

        client.messageReceived.connect(lambda ev: self._ingest(ev, False))
        client.messageSent.connect(lambda ev: self._ingest(ev, True))
        client.messageSeen.connect(self._on_seen)
        client.ancsNotification.connect(self._on_ancs)
        client.availabilityChanged.connect(lambda _ok: self._refresh_status())
        client.callStateChanged.connect(lambda _ev: self.recheck())
        self.recheck()

    # ---- properties QML binds to ---------------------------------------

    @pyqtProperty(bool, notify=changed)
    def available(self) -> bool:
        return self._client.available

    @pyqtProperty(str, notify=changed)
    def threadName(self) -> str:
        return self._thread_name

    @pyqtProperty(str, notify=changed)
    def statusText(self) -> str:
        return self._status

    @pyqtProperty(str, notify=changed)
    def callSummary(self) -> str:
        return self._calls

    # ---- what QML calls -------------------------------------------------

    @pyqtSlot(str)
    def openThread(self, key: str) -> None:
        self._thread_name = (self.store.get(key) or {}).get("name", "")
        self.messages.show(key)
        self.changed.emit()
        keys = self.store.mark_thread_read(key)
        if keys:
            self.threads.refresh()
            self._client.mark_read(keys)

    @pyqtSlot(str)
    def send(self, body: str) -> None:
        body = body.strip()
        key = self.messages.thread_key
        if not body or not key:
            return
        target = (self.store.get(key) or {}).get("phone")
        if target:
            self._client.send_message(
                target, body, lambda _t: None,
                lambda err: log.warning("send failed: %s", err))

    @pyqtSlot(str)
    def dial(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        number = resolve_recipient(self._contacts, raw)
        if number is None:
            self._calls = f"No contact matches {raw!r}"
            self.changed.emit()
            return
        self._client.dial(number, lambda _p: self.recheck(),
                          lambda err: self._set_calls(f"Call failed: {err}"))

    @pyqtSlot()
    def recheck(self) -> None:
        self._client.refresh_availability()
        self._refresh_status()
        self._client.list_calls(self._on_calls)

    # ---- daemon events --------------------------------------------------

    def _ingest(self, ev: dict, outgoing: bool) -> None:
        key, _msg = self.store.ingest(ev, outgoing=outgoing)
        self.threads.refresh()
        if key == self.messages.thread_key:
            self.messages.reload()

    def _on_seen(self, ev: dict) -> None:
        if self.store.mark_read(ev.get("keys") or ()):
            self.threads.refresh()

    def _on_ancs(self, ev: dict) -> None:
        if not ev.get("is_preexisting"):
            self.notifications.add(ev)

    def _on_calls(self, calls: list) -> None:
        if not calls:
            self._set_calls("No active calls")
            return
        self._set_calls("; ".join(
            f"{c.get('contact_name') or c.get('peer_phone') or '(unknown)'} "
            f"— {c.get('direction', '')} {c.get('state', '?')}" for c in calls))

    def _set_calls(self, text: str) -> None:
        self._calls = text
        self.changed.emit()

    def _refresh_status(self) -> None:
        def show(profiles: dict) -> None:
            reachable = self._client.available
            rows = [f"<b>Daemon</b>: {'running' if reachable else 'not reachable'}",
                    f"<b>Messages (MAP)</b>: "
                    f"{'connected' if self._client.healthy else 'unavailable'}"]
            for label, code in (("Show Message Notifications", "map"),
                                ("Sync Contacts", "pbap"),
                                ("Show System Notifications", "ancs")):
                state = profiles.get(code)
                rows.append(f"<b>{label}</b>: " + (
                    "working" if state else
                    "not detected" if state is not None else "unknown"))
            try:
                rows.append(f"<b>Contacts cached</b>: {ContactsResolver().count()}")
            except Exception:
                log.exception("contact count failed")
            self._status = "<br>".join(rows)
            self.changed.emit()
        self._client.profile_status(show, lambda _e: None)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        stream=sys.stderr)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("iphonebridge")
    app.setDesktopFileName("me.santisbon.iphonebridge.UI")

    # Imported only now: the D-Bus connection needs the application first.
    from iphonebridge.ui.qtclient import DaemonClient

    client = DaemonClient()
    bridge = Bridge(client)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("bridge", bridge)
    ctx.setContextProperty("threads", bridge.threads)
    ctx.setContextProperty("messages", bridge.messages)
    ctx.setContextProperty("notifications", bridge.notifications)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        log.error("QML failed to load from %s", QML_DIR)
        return 2
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
