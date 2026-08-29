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
import time

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from iphonebridge import config
from iphonebridge.contacts import ContactsResolver
from iphonebridge.media.events import (
    extrapolate_position,
    format_ms,
    next_repeat,
    next_shuffle,
    repeat_display,
    shuffle_display,
)
from iphonebridge.models import marketing_name
from iphonebridge.ui.emoji import (
    apply_tone,
    build_groups,
    build_name_map,
    build_tone_map,
    emoji_name,
    load_emoji_db,
    load_recents,
    load_tone,
    note_recent,
    save_recents,
    save_tone,
    search_emoji,
    tone_swatches,
)
from iphonebridge.ui.model import ThreadStore
from iphonebridge.ui.protocol import QML_CONTEXT_NAMES
from iphonebridge.ui.qtmodels import (
    CallListModel,
    MessageListModel,
    NotificationListModel,
    ThreadListModel,
)
from iphonebridge.ui.util import contact_suggestions, resolve_recipient

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
    #: Emoji data only. Separate from `changed` deliberately: that one
    #: fires on every status tick, and re-marshalling thousands of
    #: emoji strings into QML each time would be pure waste.
    emojiChanged = pyqtSignal()
    #: Transient feedback for the user — the Qt equivalent of the GTK
    #: toast overlay. Every action that can fail says so through this.
    toast = pyqtSignal(str)
    #: An incoming call wants the window in front, on the Calls tab.
    callArrived = pyqtSignal()
    #: A composed message has been confirmed and its conversation is now
    #: open. The view leaves compose mode on this and nothing else: it used
    #: to infer the moment from `changed` plus a non-empty thread name, and
    #: both were already true of the conversation you were last in, so that
    #: one flashed up for a frame before the new one replaced it.
    composeFinished = pyqtSignal()

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client
        self._contacts = ContactsResolver()
        self.store = ThreadStore()
        self.threads = ThreadListModel(self.store)
        self.messages = MessageListModel(self.store)
        self.notifications = NotificationListModel()
        self.calls = CallListModel()
        self._thread_name = ""
        self._current_key: str | None = None
        # Set while a composed message is in flight, so the thread it
        # lands in can be opened once the daemon confirms the send.
        self._pending_open: str | None = None
        self._compose_error = ""
        self._link_ok = False
        self._status_groups: list = []
        self._status = "Checking…"
        self._calls = "No active calls"
        # Now-playing snapshot from the daemon, plus the monotonic instant
        # it landed — the position bar extrapolates from that pair rather
        # than trusting any clock that could skew between processes.
        self._media: dict = {}
        self._media_at = time.monotonic()
        self._phone: dict = {}
        # Emoji database, loaded from the system dictionary on first
        # use (the picker's first open), never shipped with the app.
        self._emoji_db: list | None = None
        self._emoji_groups: list = []
        self._emoji_recents_path = config.STATE_DIR / "emoji-recents.json"
        self._emoji_recents = load_recents(self._emoji_recents_path)
        self._emoji_tone_path = config.STATE_DIR / "emoji-tone.json"
        self._emoji_tone = load_tone(self._emoji_tone_path)
        self._tone_map: dict = {}
        self._emoji_names: dict = {}

        for ev in client.read_events(kinds={"sms_received", "sms_sent"}):
            self.store.ingest(ev, outgoing=(ev.get("kind") == "sms_sent"))
        for ev in client.read_events(kinds={"ancs_notification"}):
            self.notifications.add(ev)
        self.threads.refresh()

        client.messageReceived.connect(lambda ev: self._ingest(ev, False))
        client.messageSent.connect(lambda ev: self._ingest(ev, True))
        client.messageSeen.connect(self._on_seen)
        client.ancsNotification.connect(self._on_ancs)
        client.ancsDismissed.connect(
            lambda ev: self.notifications.remove_eid(str((ev or {}).get("eid", ""))))
        client.availabilityChanged.connect(lambda _ok: self._refresh_status())
        client.callStateChanged.connect(self._on_call_state)
        client.mediaStateChanged.connect(self._on_media_state)
        client.phoneStatusChanged.connect(self._on_phone_status)
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

    @pyqtProperty(str, notify=changed)
    def composeError(self) -> str:
        return self._compose_error

    @pyqtProperty(bool, notify=changed)
    def linkOk(self) -> bool:
        return self._link_ok

    @pyqtProperty(str, notify=changed)
    def linkText(self) -> str:
        """The Bluetooth link, stated where a conversation can see it.

        Driven by availability changes and by message traffic, which
        proves the link — never polled, because the daemon's IsHealthy
        call can block for five seconds on a bad link.
        """
        return "iPhone connected" if self._link_ok else "Reconnecting…"

    @pyqtProperty(int, notify=changed)
    def eventsLogged(self) -> int:
        return len(self._client.read_events())

    @pyqtProperty(list, notify=changed)
    def statusGroups(self) -> list:
        """The Status tab as grouped data.

        Shaped for a settings-style list: each row is a label and a short
        value, and anything that needs explaining is a footer under its
        group rather than a sentence trailing every row. `state` is "ok",
        "warn" or "idle", and only "warn" is coloured — a screen where
        everything is marked is a screen nobody reads.

        The iPhone toggles are inferred from what is actually working
        rather than read from the phone: a live session proves its toggle
        is on, and nothing else can.
        """
        return self._status_groups

    # ---- now playing (Music tab) ----------------------------------------

    @pyqtProperty(bool, notify=changed)
    def mediaAvailable(self) -> bool:
        return bool(self._media.get("available"))

    @pyqtProperty(str, notify=changed)
    def mediaStatus(self) -> str:
        return str(self._media.get("status", ""))

    @pyqtProperty(str, notify=changed)
    def mediaTitle(self) -> str:
        return str(self._media.get("title", ""))

    @pyqtProperty(str, notify=changed)
    def mediaArtist(self) -> str:
        return str(self._media.get("artist", ""))

    @pyqtProperty(str, notify=changed)
    def mediaAlbum(self) -> str:
        return str(self._media.get("album", ""))

    @pyqtProperty(int, notify=changed)
    def mediaDurationMs(self) -> int:
        try:
            return int(self._media.get("duration_ms", 0))
        except (TypeError, ValueError):
            return 0

    @pyqtProperty(int, notify=changed)
    def mediaVolume(self) -> int:
        try:
            return int(self._media.get("volume", -1))
        except (TypeError, ValueError):
            return -1

    @pyqtProperty(str, notify=changed)
    def mediaArtPath(self) -> str:
        return str(self._media.get("art_path", ""))

    @pyqtProperty(str, notify=changed)
    def mediaShuffleText(self) -> str:
        return shuffle_display(str(self._media.get("shuffle", "")))

    @pyqtProperty(str, notify=changed)
    def mediaRepeatText(self) -> str:
        return repeat_display(str(self._media.get("repeat", "")))

    # ---- emoji picker ----------------------------------------------------

    def _emoji(self) -> list:
        if self._emoji_db is None:
            self._emoji_db = load_emoji_db()
            self._emoji_groups = build_groups(self._emoji_db)
            self._tone_map = build_tone_map(self._emoji_db)
            self._emoji_names = build_name_map(self._emoji_db)
        return self._emoji_db

    def _toned(self, emoji: list) -> list:
        """A list of emoji in the chosen tone. Anything without a form in
        that tone, which is most of them, comes back unchanged."""
        if self._emoji_tone < 0:
            return list(emoji)
        return [apply_tone(e, self._emoji_tone, self._tone_map)
                for e in emoji]

    @pyqtProperty(list, notify=emojiChanged)
    def emojiGroups(self) -> list:
        self._emoji()
        return [{"name": g["name"],
                 "icon": g["icon"],
                 "emoji": self._toned(g["emoji"])}
                for g in self._emoji_groups]

    @pyqtProperty(list, notify=emojiChanged)
    def emojiRecents(self) -> list:
        # Stored as they were inserted, tone and all, so a tone change
        # does not rewrite what you actually sent.
        return list(self._emoji_recents)

    @pyqtProperty(int, notify=emojiChanged)
    def emojiTone(self) -> int:
        return self._emoji_tone

    @pyqtProperty(list, notify=emojiChanged)
    def emojiToneSwatches(self) -> list:
        """The six choices the tone selector shows: neutral, then each
        tone, drawn on one sample emoji.

        Deliberately does not touch the dictionary. The picker's tone
        button binds to this and exists from startup, so loading here
        would undo the point of only reading the dictionary when the
        picker is first opened.
        """
        return tone_swatches()

    @pyqtSlot(int)
    def setEmojiTone(self, tone: int) -> None:
        tone = int(tone)
        if tone == self._emoji_tone:
            return
        self._emoji_tone = tone
        save_tone(self._emoji_tone_path, tone)
        self.emojiChanged.emit()

    @pyqtSlot(str, result=str)
    def emojiName(self, emoji: str) -> str:
        """What the picker names under the cursor.

        Two cells can hold the same picture and still be different
        emoji: Norway, Bouvet Island and Svalbard fly one flag between
        them, as do France, Clipperton Island and St. Martin. The name
        is the only thing that separates them.

        Only ever called while the picker is open, which has already
        paid for the dictionary.
        """
        self._emoji()
        return emoji_name(str(emoji), self._emoji_names)

    @pyqtSlot(str, result=list)
    def searchEmoji(self, query: str) -> list:
        return self._toned(search_emoji(self._emoji(), query))

    @pyqtSlot(str)
    def noteEmojiUsed(self, emoji: str) -> None:
        self._emoji_recents = note_recent(self._emoji_recents, emoji)
        save_recents(self._emoji_recents_path, self._emoji_recents)
        self.emojiChanged.emit()

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

    @pyqtSlot(str, result=list)
    def suggest(self, text: str) -> list:
        """Contacts to offer for `text`, as rows QML can bind to."""
        return [{"name": name, "phone": phone}
                for name, phone in contact_suggestions(self._contacts, text)]

    @pyqtSlot(str, str)
    def sendTo(self, recipient: str, body: str) -> None:
        """Start a conversation: resolve who `recipient` means, then send.

        Takes a contact name, a number, or a vanity number, the same three
        the dialer takes.
        """
        recipient, body = recipient.strip(), body.strip()
        if not recipient or not body:
            return
        number = resolve_recipient(self._contacts, recipient)
        if number is None:
            self._compose_error = f"No contact matches {recipient!r}"
            self.changed.emit()
            return
        self._compose_error = ""
        self._pending_open = number
        self.changed.emit()
        self._client.send_message(
            number, body, lambda _t: None,
            lambda err: self._set_compose_error(f"Send failed: {err}"))

    def _set_compose_error(self, text: str) -> None:
        self._pending_open = None
        self._compose_error = text
        self.changed.emit()

    @pyqtSlot()
    def clearCompose(self) -> None:
        self._compose_error = ""
        self.changed.emit()

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

    @pyqtSlot(str)
    def answer(self, path: str) -> None:
        self._client.answer_call(
            path, lambda err: self.toast.emit(f"Answer failed: {err}"))

    @pyqtSlot(str)
    def hangup(self, path: str) -> None:
        self._client.hangup_call(
            path, lambda err: self.toast.emit(f"Hang up failed: {err}"))

    @pyqtSlot()
    def hangupAll(self) -> None:
        self._client.hangup_all(
            lambda err: self.toast.emit(f"Hang up failed: {err}"))

    @pyqtSlot(str)
    def dismissNotification(self, eid: str) -> None:
        """Dismiss a notification here and, when it is from the live BLE
        session and carries a negative action, on the iPhone too. The
        card leaves the feed when the daemon's AncsDismissed comes back,
        so both ends stay on one removal path."""
        if not eid:
            return
        self._client.dismiss_notification(
            eid, None,
            lambda err: self.toast.emit(f"Dismiss failed: {err}"))

    # ---- media controls --------------------------------------------------

    def _media_err(self, err: str) -> None:
        self.toast.emit(f"Playback control failed: {err}")

    @pyqtSlot()
    def mediaPlayPause(self) -> None:
        if str(self._media.get("status", "")) == "playing":
            self._client.media_pause(self._media_err)
        else:
            self._client.media_play(self._media_err)

    @pyqtSlot()
    def mediaNext(self) -> None:
        self._client.media_next(self._media_err)

    @pyqtSlot()
    def mediaPrevious(self) -> None:
        self._client.media_previous(self._media_err)

    @pyqtSlot(int)
    def setMediaVolume(self, volume: int) -> None:
        self._client.set_media_volume(max(0, min(127, int(volume))),
                                      self._media_err)

    @pyqtSlot()
    def toggleShuffle(self) -> None:
        # The row's value only advances when the daemon echoes the write
        # back — the honest rendering when an app ignores the setting.
        self._client.set_media_shuffle(
            next_shuffle(str(self._media.get("shuffle", ""))),
            self._media_err)

    @pyqtSlot()
    def toggleRepeat(self) -> None:
        self._client.set_media_repeat(
            next_repeat(str(self._media.get("repeat", ""))),
            self._media_err)

    @pyqtSlot(result=int)
    def mediaPositionMs(self) -> int:
        elapsed_ms = int((time.monotonic() - self._media_at) * 1000)
        try:
            pos = int(self._media.get("position_ms", 0))
        except (TypeError, ValueError):
            pos = 0
        return extrapolate_position(pos, str(self._media.get("status", "")),
                                    elapsed_ms, self.mediaDurationMs)

    @pyqtSlot(int, result=str)
    def formatMs(self, ms: int) -> str:
        return format_ms(ms)

    @pyqtSlot(str)
    def deleteThread(self, key: str) -> None:
        """Delete a whole conversation from local history.

        The phone is never touched: iOS ignores MAP deletes, so this is
        explicitly a local-history operation and the toast says so.
        """
        self._delete(self.store.message_keys(key))

    @pyqtSlot(str)
    def deleteMessage(self, msg_key: str) -> None:
        self._delete([msg_key] if msg_key else [])

    def _delete(self, keys: list) -> None:
        if not keys:
            return

        def done(removed) -> None:
            emptied = self.store.remove(keys)
            if self._current_key in emptied:
                self._current_key = None
                self._thread_name = ""
                self.messages.show(None)
            self._refresh_threads()
            if self._current_key:
                self.messages.reload()
            noun = "message" if removed == 1 else "messages"
            self.toast.emit(f"Deleted {removed} {noun} from this computer")

        self._client.delete_local(
            keys, done, lambda err: self.toast.emit(f"Delete failed: {err}"))

    @pyqtSlot()
    def recheck(self) -> None:
        self._client.refresh_availability()
        self._refresh_status()
        self._client.list_calls(self._on_calls)
        self._client.get_media_state(self._on_media_state)
        self._client.get_phone_status(self._on_phone_status)

    # ---- daemon events --------------------------------------------------

    def _ingest(self, ev: dict, outgoing: bool) -> None:
        # Traffic proves the link is up, which is cheaper and more honest
        # than asking: IsHealthy can block for five seconds on a bad one.
        self._set_link(True)
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
        # A message composed to a new recipient has just been confirmed:
        # open the thread it created rather than leaving the compose form
        # up with no sign of where it went.
        if outgoing and self._pending_open is not None:
            self._pending_open = None
            self.openThread(key)
            self.composeFinished.emit()
        self._diag("settled")

    def _on_seen(self, ev: dict) -> None:
        if self.store.mark_read(ev.get("keys") or ()):
            self._refresh_threads()
            self._diag("seen")

    def _on_call_state(self, ev: dict) -> None:
        self.recheck()
        if (ev or {}).get("kind") == "call_incoming":
            peer = (ev.get("contact_name") or ev.get("peer_phone")
                    or "someone")
            self.toast.emit(f"Incoming call from {peer}")
            # The GTK window switched to Calls and presented itself; a
            # ringing phone is the one event worth interrupting for.
            self.callArrived.emit()

    def _on_media_state(self, state) -> None:
        self._media = dict(state or {})
        self._media_at = time.monotonic()
        self.changed.emit()

    def _on_phone_status(self, state) -> None:
        self._phone = dict(state or {})
        self._refresh_status()

    def _phone_rows(self) -> list:
        p = self._phone
        rows = []
        pct = int(p.get("battery_pct", -1))
        if pct < 0:
            rows.append({"label": "Battery", "value": "Unknown",
                         "state": "idle"})
        else:
            low = config.LOW_BATTERY_PCT > 0 \
                and pct <= config.LOW_BATTERY_PCT
            prefix = "~" if p.get("battery_estimated") else ""
            rows.append({"label": "Battery", "value": f"{prefix}{pct}%",
                         "state": "warn" if low else "ok"})
        sig = int(p.get("signal_pct", -1))
        net = str(p.get("network", ""))
        reg = str(p.get("reg", ""))
        if sig < 0 and not net:
            rows.append({"label": "Cellular", "value": "Unknown",
                         "state": "idle"})
        else:
            # oFono scales the HFP signal indicator to a percentage;
            # undo it. iOS sends its displayed bar count (0-4) even
            # though the indicator allows 0-5, so cap at four bars and
            # the row reads exactly like the phone's own status bar.
            value = net + (" (roaming)" if reg == "roaming" else "")
            rows.append({"label": "Cellular", "value": value,
                         "state": "ok" if reg in ("registered", "roaming")
                         else "warn",
                         "bars": min(round(sig / 20), 4) if sig >= 0
                         else -1})
        model = marketing_name(str(p.get("model", "")))
        rows.append({"label": "Model", "value": model or "Unknown",
                     "state": "ok" if model else "idle"})
        return rows

    def _on_ancs(self, ev: dict) -> None:
        if not ev.get("is_preexisting"):
            self.notifications.add(ev)

    def _on_calls(self, calls: list) -> None:
        self.calls.show(calls)
        self._set_calls("No active calls" if not calls else "")

    def _set_calls(self, text: str) -> None:
        self._calls = text
        self.changed.emit()

    def _set_link(self, ok: bool) -> None:
        if ok != self._link_ok:
            self._link_ok = ok
            self.changed.emit()

    def _refresh_status(self) -> None:
        reachable = self._client.available
        healthy = reachable and self._client.healthy
        self._set_link(healthy)

        def show(profiles: dict) -> None:
            service = {
                "title": "Service",
                "rows": [
                    {"label": "Background service",
                     "value": "Running" if reachable else "Not reachable",
                     "state": "ok" if reachable else "warn"},
                    {"label": "Messages",
                     "value": "Connected" if healthy else "Unavailable",
                     "state": "ok" if healthy else "warn"},
                ],
                "footer": "" if reachable else "Start it with",
                "code": "" if reachable else
                        "systemctl --user start iphonebridge",
            }

            toggles = {"title": "On your phone", "rows": [], "code": "",
                       "footer": "Settings → Bluetooth → tap ⓘ next to this "
                                 "computer. Each one is marked from what is "
                                 "working now, not read from the phone."}
            for label, code in (("Show Message Notifications", "map"),
                                ("Sync Contacts", "pbap"),
                                ("Show System Notifications", "ancs")):
                if not reachable or code not in profiles:
                    value, state = "Unknown", "idle"
                elif profiles[code]:
                    value, state = "Working", "ok"
                else:
                    value, state = "Not detected", "warn"
                toggles["rows"].append({"label": label, "value": value,
                                        "state": state})

            phone = {"title": "Phone", "code": "",
                     "footer": "Read over Bluetooth. Battery and signal "
                               "update live.",
                     "rows": self._phone_rows()}

            try:
                cached = ContactsResolver().count()
            except Exception:
                log.exception("contact count failed")
                cached = 0
            stored = {
                "title": "Stored on this computer",
                "footer": "", "code": "",
                "rows": [
                    {"label": "Contacts", "value": f"{cached:,}",
                     "state": "ok" if cached else "idle"},
                    {"label": "Messages and notifications",
                     "value": f"{len(self._client.read_events()):,}",
                     "state": "ok"},
                ],
            }

            self._status_groups = [service, toggles, phone, stored]
            self._status = ""
            self.changed.emit()
        self._client.profile_status(show, lambda _e: show({}))


def install_context(engine, bridge) -> None:
    """Publish the bridge and its models under the names the QML uses.

    One place, because anything that loads Main.qml needs exactly the same
    set and they drift otherwise — the screenshot renderer had `calls` and
    the app did not, so the Calls tab was empty in the app and populated
    in every test.
    """
    ctx = engine.rootContext()
    models = {
        "bridge": bridge,
        "threads": bridge.threads,
        "messages": bridge.messages,
        "notifications": bridge.notifications,
        "calls": bridge.calls,
    }
    missing = set(QML_CONTEXT_NAMES) - set(models)
    if missing:
        raise RuntimeError(f"no object for QML context name(s): {sorted(missing)}")
    for name, obj in models.items():
        ctx.setContextProperty(name, obj)


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
    install_context(engine, bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        log.error("QML failed to load from %s", QML_DIR)
        return 2

    # Which screen Qt believes the window is on, and at what scale,
    # logged on every change. The compositor rescales the buffer when
    # that belief and the actual placement disagree, and rescaled text
    # is what reads as uneven stems on a mixed-scale desktop; this line
    # is how to tell the two apart.
    from PyQt6 import sip
    from PyQt6.QtQuick import QQuickWindow
    win = sip.cast(engine.rootObjects()[0], QQuickWindow)

    def _log_screen(*_):
        scr = win.screen()
        log.debug("window on screen %s at scale %.2f",
                  scr.name() if scr else "?", win.devicePixelRatio())
    win.screenChanged.connect(_log_screen)
    _log_screen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
