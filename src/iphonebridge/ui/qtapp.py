"""iphonebridge-ui on Qt — entry point and the bridge QML talks to.

A separate process from the daemon, as before: its application id is
`me.santisbon.iphonebridge.UI` and it reaches the daemon over D-Bus.

Ordering matters here. The QApplication must exist before the D-Bus
connection, because the Qt main-loop integration installs QSocketNotifiers
which need an application object — see `iphonebridge.ui.qtbus`.
"""
from __future__ import annotations

import logging
import os
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

#: Set IPHONEBRIDGE_UI_DIAG=1 to log which conversation is open, where it
#: sits in the list, which rows would draw an unread dot, and whether an
#: arriving message keys to the open thread. Thread keys are logged as
#: SHA-256 prefixes, never as names, numbers, or message text, so the
#: output is safe to hand to anyone. Off by default and free when off.
DIAG = bool(os.environ.get("IPHONEBRIDGE_UI_DIAG"))


def _key_digest(value) -> str:
    if not value:
        return "-"
    import hashlib
    return "id:" + hashlib.sha256(str(value).encode()).hexdigest()[:6]

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
        self._current_key: str | None = None
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

    @pyqtProperty(int, notify=changed)
    def currentIndex(self) -> int:
        """Where the open conversation currently sits in the list.

        Derived on every read rather than stored: a new message re-sorts
        the list, so the row that held this thread a moment ago may now
        hold a different one.
        """
        return self.threads.index_of(self._current_key)

    @pyqtProperty(str, notify=changed)
    def statusText(self) -> str:
        return self._status

    @pyqtProperty(str, notify=changed)
    def callSummary(self) -> str:
        return self._calls

    def _refresh_threads(self) -> None:
        """Re-read the conversation list, then tell QML.

        `currentIndex` is derived from the open thread's key rather than
        stored, so a refresh alone is not enough: refreshing re-sorts the
        rows, and the binding has no other way to learn its row moved.
        Every refresh goes through here for that reason.
        """
        self.threads.refresh()
        self.changed.emit()

    def _diag(self, tag: str, arriving: str | None = None) -> None:
        """Log the selection/unread state. See DIAG above."""
        if not DIAG:
            return
        from iphonebridge.ui.model import unread_keys
        rows = []
        for i in range(self.threads.rowCount()):
            k = self.threads.key_at(i)
            rows.append(_key_digest(k)
                        + ("*" if unread_keys(self.store.get(k)) else ""))
        log.info("DIAG %-9s open=%s idx=%d rows=%s%s", tag,
                 _key_digest(self._current_key),
                 self.threads.index_of(self._current_key), rows,
                 "" if arriving is None else
                 f" arriving={_key_digest(arriving)}"
                 f" match={arriving == self._current_key}")

    # ---- what QML calls -------------------------------------------------

    @pyqtSlot(str)
    def openThread(self, key: str) -> None:
        self._current_key = key
        self._thread_name = (self.store.get(key) or {}).get("name", "")
        self.messages.show(key)
        self.changed.emit()
        keys = self.store.mark_thread_read(key)
        if keys:
            self._refresh_threads()
            self._client.mark_read(keys)
        self._diag("opened")

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
        # Arriving into the conversation already on screen counts as read:
        # otherwise the unread dot lights up on the thread you are sitting
        # in and never clears, because nothing opens it again — and the
        # phone is never told you saw it either.
        self._diag("arrived", key)
        if key == self._current_key:
            seen = self.store.mark_thread_read(key)
            if seen:
                self._client.mark_read(seen)
        self._refresh_threads()
        if key == self.messages.thread_key:
            self.messages.reload()
        self._diag("settled")

    def _on_seen(self, ev: dict) -> None:
        if self.store.mark_read(ev.get("keys") or ()):
            self._refresh_threads()
            self._diag("seen")

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


def _diag_to_file() -> None:
    """Mirror the DIAG lines to a file as well as stderr, so a session can
    be read back after the fact instead of scrolled away."""
    from iphonebridge import config
    path = config.STATE_DIR / "ui-diag.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, mode="w")
    except OSError as e:
        log.warning("could not open %s: %s", path, e)
        return
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    log.info("DIAG writing to %s", path)


def main() -> int:
    # Qt caches compiled QML under ~/.cache/qmlcache and decides a cache
    # entry is still good from the source file's path and timestamp. dpkg
    # installs with a build-normalised mtime, so every rebuild of the same
    # version lands Main.qml with an identical timestamp and the stale
    # entry keeps winning: the package ships new QML and the app runs the
    # previous version's. That cost a long evening of chasing a selection
    # bug that had already been fixed. Compiling ~200 lines at startup is
    # not worth a cache that can lie.
    os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        stream=sys.stderr)
    if DIAG:
        _diag_to_file()

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
