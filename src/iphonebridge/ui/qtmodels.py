"""Qt list models over the toolkit-free ThreadStore.

These are adapters, not logic: `iphonebridge.ui.model` decides what a
conversation is, how messages order, and what counts as unread. Anything
that would be a behaviour decision belongs there, where it can be tested
without a display.
"""
from __future__ import annotations

from typing import ClassVar

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Qt,
    pyqtProperty,
    pyqtSignal,
)

from iphonebridge.ui.model import (
    ThreadStore,
    emoji_markup,
    emoji_only,
    unread_keys,
)
from iphonebridge.ui.util import daystamp, event_ts, format_ts, relative_stamp, same_group


def _roles(*names: str) -> dict[int, bytes]:
    return {Qt.ItemDataRole.UserRole + i: n.encode()
            for i, n in enumerate(names)}


class ThreadListModel(QAbstractListModel):
    """The conversation list, newest first."""

    ROLES = _roles("key", "name", "preview", "stamp", "unread")

    def __init__(self, store: ThreadStore) -> None:
        super().__init__()
        self._store = store
        self._rows: list[dict] = []

    def roleNames(self) -> dict[int, bytes]:
        return self.ROLES

    def rowCount(self, parent=QModelIndex()) -> int:      # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        thread = self._rows[index.row()]
        name = self.ROLES.get(role, b"").decode()
        if name == "key":
            return thread["key"]
        if name == "name":
            return thread["name"]
        if name == "preview":
            return self._store.preview(thread)
        if name == "stamp":
            return relative_stamp(thread.get("last_ts"))
        if name == "unread":
            return bool(unread_keys(thread))
        return None

    def refresh(self) -> None:
        """Re-read the store. Cheap: conversation counts are small."""
        self.beginResetModel()
        self._rows = self._store.ordered()
        self.endResetModel()

    def key_at(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]["key"]
        return None

    def index_of(self, key: str | None) -> int:
        """The row currently holding `key`, or -1.

        The list re-sorts newest-first on every arrival, so a row index is
        only meaningful until the next message. Anything that needs to
        remember a conversation must remember its key and ask again.
        """
        if key is None:
            return -1
        for i, thread in enumerate(self._rows):
            if thread["key"] == key:
                return i
        return -1


class MessageListModel(QAbstractListModel):
    """One conversation's messages, oldest first.

    Day rules and run-grouping are computed here rather than in QML so the
    rhythm stays a single decision: a rule whenever the calendar day
    changes or more than fifteen minutes pass, and tighter spacing within
    a run from one sender than across a change of speaker.
    """

    ROLES = _roles("body", "outgoing", "dayText", "newRun", "msgKey",
                   "emojiOnly", "bodyHtml")
    countChanged = pyqtSignal()
    emojiPointSizeChanged = pyqtSignal()

    def __init__(self, store: ThreadStore) -> None:
        super().__init__()
        self._store = store
        self._key: str | None = None
        self._rows: list[dict] = []
        self._emoji_pt = 0.0

    @pyqtProperty(float, notify=emojiPointSizeChanged)
    def emojiPointSize(self) -> float:
        """Point size for emoji inside a message. The view sets it from
        the type scale, because only the view knows what that is."""
        return self._emoji_pt

    @emojiPointSize.setter
    def emojiPointSize(self, value: float) -> None:
        if abs(value - self._emoji_pt) < 0.01:
            return
        self._emoji_pt = value
        self.emojiPointSizeChanged.emit()
        self.reload()

    def roleNames(self) -> dict[int, bytes]:
        return self.ROLES

    def rowCount(self, parent=QModelIndex()) -> int:      # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        name = self.ROLES.get(role, b"").decode()
        return row.get(name)

    def _build(self, messages: list[dict]) -> list[dict]:
        rows, prev = [], None
        for msg in messages:
            prev_ts = prev["ts"] if prev else None
            starts_group = not same_group(prev_ts, msg["ts"])
            rows.append({
                "body": msg["body"],
                "outgoing": msg["outgoing"],
                # Empty string, not None: QML binds it directly.
                "dayText": daystamp(msg["ts"]) if starts_group else "",
                "newRun": starts_group or prev is None
                          or prev["outgoing"] != msg["outgoing"],
                "msgKey": msg.get("key") or "",
                "emojiOnly": emoji_only(msg["body"]),
                "bodyHtml": emoji_markup(msg["body"], self._emoji_pt),
            })
            prev = msg
        return rows

    def show(self, key: str | None) -> None:
        self._key = key
        self.beginResetModel()
        self._rows = self._build(self._store.messages(key) if key else [])
        self.endResetModel()
        self.countChanged.emit()

    def reload(self) -> None:
        self.show(self._key)

    @property
    def thread_key(self) -> str | None:
        return self._key


class CallListModel(QAbstractListModel):
    """Active HFP calls, with what can be done to each.

    `canAnswer` is decided here rather than in QML so the rule — only a
    call that is still ringing can be answered — lives with the rest of
    the call state instead of in a view binding.
    """

    ROLES = _roles("peer", "detail", "path", "canAnswer")
    countChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    @pyqtProperty(int, notify=countChanged)
    def count(self) -> int:
        """Row count as a *bindable* property.

        QML cannot track rowCount(): it is a method, so a binding that
        calls it is evaluated once and never again. That is why a control
        gated on "are there any calls" stayed enabled after the last call
        ended.
        """
        return len(self._rows)

    def roleNames(self) -> dict[int, bytes]:
        return self.ROLES

    def rowCount(self, parent=QModelIndex()) -> int:      # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        return self._rows[index.row()].get(self.ROLES.get(role, b"").decode())

    #: oFono's call states, said the way a person would. The raw pair was
    #: shown before and read as "incoming · incoming", which is the
    #: telephony stack's vocabulary rather than anything the reader has a
    #: use for.
    _PHRASE: ClassVar[dict[str, str]] = {
        "incoming": "Incoming call",
        "waiting": "Call waiting",
        "dialing": "Calling…",
        "alerting": "Ringing…",
        "active": "Connected",
        "held": "On hold",
        "disconnected": "Ended",
    }

    def show(self, calls: list) -> None:
        self.beginResetModel()
        self._rows = []
        for c in calls or []:
            state = str(c.get("state") or "")
            direction = str(c.get("direction") or "")
            detail = self._PHRASE.get(state)
            if detail is None:
                # An unmapped state is still worth showing plainly rather
                # than hiding: it means oFono grew a state we do not know.
                detail = " ".join(p for p in (direction, state) if p) or "Call"
            self._rows.append({
                "peer": (c.get("contact_name") or c.get("peer_phone")
                         or "(unknown)"),
                "detail": detail,
                "path": str(c.get("call_path") or ""),
                "canAnswer": state in ("incoming", "waiting"),
            })
        self.endResetModel()
        self.countChanged.emit()


class NotificationListModel(QAbstractListModel):
    """Per-app ANCS notifications, newest first."""

    ROLES = _roles("app", "preview", "stamp")
    countChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    @pyqtProperty(int, notify=countChanged)
    def count(self) -> int:
        """Bindable row count — see CallListModel.count."""
        return len(self._rows)

    def roleNames(self) -> dict[int, bytes]:
        return self.ROLES

    def rowCount(self, parent=QModelIndex()) -> int:      # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        return self._rows[index.row()].get(self.ROLES.get(role, b"").decode())

    def add(self, ev: dict) -> None:
        title = (ev.get("title") or "").strip()
        body = (ev.get("body") or "").strip()
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._rows.insert(0, {
            "app": ev.get("app_name") or ev.get("app_id") or "Notification",
            "preview": " — ".join(p for p in (title, body) if p) or "(no preview)",
            "stamp": format_ts(event_ts(ev), fmt="%H:%M"),
        })
        self.endInsertRows()
        self.countChanged.emit()
