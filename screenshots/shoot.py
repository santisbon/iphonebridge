#!/usr/bin/env python3
"""Regenerate the PNGs in this directory from synthetic data.

    python3 screenshots/shoot.py                     # every view
    python3 screenshots/shoot.py --src /tmp/old/src --out /tmp/before

Runs the real QML, driven by a stub daemon client, and grabs the window
with `QQuickWindow.grabWindow()`. That returns the scene graph's own
composited output, so it captures exactly what is on screen — including
scroll position, which the GTK version's `WidgetPaintable` could not see.

Defaults to the `offscreen` platform, so nothing appears on your desktop
and it works over SSH. Pass `--onscreen` to watch it happen.

XDG_STATE_HOME and XDG_CONFIG_HOME are redirected to a temp directory that
seed.py fills, so this reads none of your real messages, contacts, or
config, and leaves nothing behind. The daemon is stubbed rather than
called, so the images do not depend on whether it is running, and a real
message arriving mid-capture cannot land in one.

Captures are light because the offscreen platform loads no platform theme,
so the default light palette applies. The app itself does follow the
desktop's light/dark setting when run normally; there is no way to force
the other scheme offscreen (setColorScheme and setPalette both make no
difference to what is drawn). Use --onscreen to capture in your own scheme.

Run it with the system interpreter (/usr/bin/python3): PyQt6 and
dbus-python come from apt, and a conda or pyenv interpreter cannot see
them.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

# (tab index, output basename, variant)
#   "offline" — daemon off the bus, so the warning banner shows
VIEWS = [
    (0, "messages", None),
    (0, "messages-daemon-down", "offline"),
    (1, "notifications", None),
    (2, "calls", None),
    (3, "music", None),
    (4, "status", None),
]

SETTLE_MS = 400   # after switching tab or scheme, before grabbing


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(REPO / "src"),
                    help="package root to import from (default: ./src)")
    ap.add_argument("--out", default=str(HERE),
                    help="directory to write PNGs into (default: this one)")
    ap.add_argument("--onscreen", action="store_true",
                    help="use the real display instead of the offscreen "
                         "platform (a window will appear briefly)")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not args.onscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # The offscreen platform has no GPU surface to render into; the
        # software rasteriser produces the same pixels without one.
        os.environ.setdefault("QT_QUICK_BACKEND", "software")

    with tempfile.TemporaryDirectory(prefix="iphonebridge-shots-") as tmp:
        state = pathlib.Path(tmp) / "state"
        os.environ["XDG_STATE_HOME"] = str(state)
        os.environ["XDG_CONFIG_HOME"] = str(pathlib.Path(tmp) / "config")
        # Both paths have to be set before iphonebridge.config is imported:
        # it resolves them once, at module import.
        sys.path.insert(0, str(HERE))
        sys.path.insert(0, args.src)
        from seed import seed
        seed(state)
        return _render(out)


def _render(out: pathlib.Path) -> int:
    from PyQt6 import sip
    from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtQuick import QQuickWindow

    class StubClient(QObject):
        """Everything Bridge asks of DaemonClient, answered locally.

        Same signals and the same call shapes — every method takes the
        callbacks the async client takes and invokes them straight away.
        Nothing here touches D-Bus, which is what keeps the images
        reproducible and free of real data.
        """

        messageReceived = pyqtSignal(object)
        messageSent = pyqtSignal(object)
        messageSeen = pyqtSignal(object)
        ancsNotification = pyqtSignal(object)
        ancsDismissed = pyqtSignal(object)
        callStateChanged = pyqtSignal(object)
        mediaStateChanged = pyqtSignal(object)
        availabilityChanged = pyqtSignal(bool)

        def __init__(self) -> None:
            super().__init__()
            self.available = True
            self.healthy = True

        def set_available(self, ok: bool) -> None:
            self.available = self.healthy = ok
            self.availabilityChanged.emit(ok)

        @staticmethod
        def read_events(kinds=None, limit=None):
            from iphonebridge.ui.protocol import read_events
            return read_events(kinds=kinds, limit=limit)

        def refresh_availability(self) -> None:
            pass

        def profile_status(self, on_ok, on_err=None) -> None:
            on_ok({"map": self.available, "pbap": self.available,
                   "ancs": self.available})

        def list_calls(self, on_ok, on_err=None) -> None:
            # A ringing call and a connected one, so the capture shows
            # both Answer and Hang up rather than an empty pane.
            on_ok([
                {"contact_name": "Dana Whitfield", "call_path": "/call/1",
                 "direction": "incoming", "state": "incoming"},
                {"peer_phone": "+1 (555) 010-0172", "call_path": "/call/2",
                 "direction": "outgoing", "state": "active"},
            ])

        def mark_read(self, keys, on_ok=None, on_err=None) -> None:
            pass

        def dismiss_notification(self, eid, on_ok=None, on_err=None) -> None:
            pass

        def get_media_state(self, on_ok, on_err=None) -> None:
            # Mid-song, so the capture shows the bar and both time labels.
            on_ok({
                "available": self.available, "status": "playing",
                "title": "Golden Hour", "artist": "The Marigolds",
                "album": "Field Notes", "duration_ms": 214_000,
                "position_ms": 83_000, "shuffle": "off",
                "repeat": "alltracks", "volume": 55,
            })

        def media_play(self, on_err=None) -> None:
            pass

        def media_pause(self, on_err=None) -> None:
            pass

        def media_next(self, on_err=None) -> None:
            pass

        def media_previous(self, on_err=None) -> None:
            pass

        def set_media_volume(self, volume, on_err=None) -> None:
            pass

        def set_media_shuffle(self, value, on_err=None) -> None:
            pass

        def set_media_repeat(self, value, on_err=None) -> None:
            pass

        def answer_call(self, call_path, on_err=None) -> None:
            pass

        def hangup_call(self, call_path, on_err=None) -> None:
            pass

        def hangup_all(self, on_err=None) -> None:
            pass

        def delete_local(self, keys, on_ok=None, on_err=None) -> None:
            pass

        def send_message(self, recipient, body, on_ok, on_err) -> None:
            pass

        def dial(self, number, on_ok, on_err) -> None:
            pass

    from iphonebridge.ui.qtapp import QML_DIR, Bridge, install_context

    app = QGuiApplication([])
    client = StubClient()
    bridge = Bridge(client)

    engine = QQmlApplicationEngine()
    # The same helper the app uses, so a model added to one is never
    # missing from the other.
    install_context(engine, bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        print("!! QML failed to load", file=sys.stderr)
        return 1
    # The engine hands back a plain QWindow; grabWindow lives on
    # QQuickWindow, which is what an ApplicationWindow actually is.
    win = sip.cast(roots[0], QQuickWindow)
    tabs = win.findChild(QObject, "tabs")

    # Newest-first, so row 0 is the thread with the most recent message —
    # the back-and-forth seed.py writes to show the bubble rhythm.
    bridge.openThread(bridge.threads.key_at(0))

    state = {"i": 0, "failures": 0}

    def step() -> None:
        i = state["i"]
        if i >= len(VIEWS):
            app.quit()
            return
        tab, label, variant = VIEWS[i]
        tabs.setProperty("currentIndex", tab)
        client.set_available(variant != "offline")
        QTimer.singleShot(SETTLE_MS, lambda: shoot(label))

    def shoot(name: str) -> None:
        path = out / f"{name}.png"
        image = win.grabWindow()
        if image.isNull() or not image.save(str(path)):
            print(f"  !! {path.name}: grab failed", file=sys.stderr)
            state["failures"] += 1
        else:
            print(f"  {path.name}  {image.width()}x{image.height()}")
        state["i"] += 1
        QTimer.singleShot(80, step)

    QTimer.singleShot(SETTLE_MS, step)
    app.exec()
    return 1 if state["failures"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
