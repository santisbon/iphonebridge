"""Qt list models over the toolkit-free ThreadStore.

These are adapters, not logic: `iphonebridge.ui.model` decides what a
conversation is, how messages order, and what counts as unread. Anything
that would be a behaviour decision belongs there, where it can be tested
without a display.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, pyqtSignal

from iphonebridge.ui.model import ThreadStore, unread_keys
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

    ROLES = _roles("body", "outgoing", "dayText", "newRun", "msgKey")
    countChanged = pyqtSignal()

    def __init__(self, store: ThreadStore) -> None:
        super().__init__()
        self._store = store
        self._key: str | None = None
        self._rows: list[dict] = []

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


class NotificationListModel(QAbstractListModel):
    """Per-app ANCS notifications, newest first."""

    ROLES = _roles("app", "preview", "stamp")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

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
