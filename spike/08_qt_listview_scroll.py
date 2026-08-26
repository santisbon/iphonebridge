#!/usr/bin/env python3
"""Does a QML ListView follow a growing list? — the gate for the Qt port.

The GTK message view reports a correct scroll position at every layer
reachable from Python while painting stale content. This spike answers
whether Qt has the same problem on this machine, measured two ways:

  * numerically, via ListView.contentY, which in Qt genuinely drives what
    is drawn (unlike GtkAdjustment, which agreed with itself while the
    view disagreed);
  * visually, via QQuickWindow.grabWindow(), which captures real rendered
    pixels (unlike Gtk.WidgetPaintable, which cannot see scroll offset).

Exit 0 means the view followed every append. Run it with the system
interpreter: PyQt6 comes from apt.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import (QAbstractListModel, QModelIndex, Qt, QTimer,
                          QUrl)
from PyQt6.QtGui import QGuiApplication
from PyQt6 import sip
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow

APPENDS = 12
QML = """
import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: win
    width: 640; height: 320; visible: true
    title: "listview scroll spike"
    property alias view: list
    ListView {
        id: list
        objectName: "list"
        anchors.fill: parent
        model: msgs
        spacing: 4
        delegate: Rectangle {
            width: list.width - 16; height: 44; x: 8
            radius: 10; color: "#E9E9EB"
            Text { anchors.centerIn: parent; text: model.display }
        }
        // The idiomatic way to pin a chat view to its newest item.
        onCountChanged: Qt.callLater(list.positionViewAtEnd)
    }
}
"""


class Messages(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[str] = [f"seed row {i}" for i in range(6)]

    def rowCount(self, parent=QModelIndex()) -> int:      # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rows[index.row()]
        return None

    def append(self, text: str) -> None:
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self._rows.append(text)
        self.endInsertRows()


def main() -> int:
    app = QGuiApplication(sys.argv)
    model = Messages()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("msgs", model)
    engine.loadData(QML.encode(), QUrl("qrc:/spike.qml"))
    if not engine.rootObjects():
        print("  QML failed to load", file=sys.stderr, flush=True)
        return 2
    # rootObjects() hands back a QWindow; grabWindow lives on
    # QQuickWindow, so cast to reach the real rendered pixels.
    win = sip.cast(engine.rootObjects()[0], QQuickWindow)
    view = win.findChild(object, "list")

    state = {"n": 0, "worst": 0.0, "fails": 0}

    def measure(label: str) -> float:
        content_h = view.property("contentHeight")
        y = view.property("contentY")
        h = view.property("height")
        # contentY is relative to originY, which ListView is free to move.
        # Leaving it out makes a perfectly-following view look 240px short.
        origin = view.property("originY")
        bottom = max(origin, origin + content_h - h)
        gap = bottom - y
        overflows = content_h > h
        print(f"  {label:14} contentY={y:7.0f} contentHeight={content_h:7.0f} "
              f"height={h:6.0f} originY={origin:6.0f} bottom={bottom:7.0f} gap={gap:6.0f} "
              f"overflows={overflows}", flush=True)
        return abs(gap) if overflows else 0.0

    def tick() -> None:
        if state["n"] >= APPENDS:
            img = win.grabWindow()
            img.save("/tmp/qt_spike.png")
            print(f"\n  worst gap across {APPENDS} appends: {state['worst']:.0f}px", flush=True)
            print(f"  followed every append: {state['worst'] < 2}", flush=True)
            print("  rendered frame written to /tmp/qt_spike.png", flush=True)
            app.exit(0 if state["worst"] < 2 else 1)
            return
        state["n"] += 1
        model.append(f"appended message number {state['n']}")
        QTimer.singleShot(250, check)

    def check() -> None:
        gap = measure(f"append {state['n']}")
        state["worst"] = max(state["worst"], gap)
        QTimer.singleShot(150, tick)

    QTimer.singleShot(900, lambda: (measure("on open"), tick()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
