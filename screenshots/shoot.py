#!/usr/bin/env python3
"""Regenerate the PNGs in this directory from synthetic data.

    python3 screenshots/shoot.py                     # all views, both schemes
    python3 screenshots/shoot.py --scheme light
    python3 screenshots/shoot.py --src /tmp/old/src --out /tmp/before

Needs a graphical session: it opens the real window briefly, then renders
it through the widget's own paintable rather than grabbing the screen, so
the output is identical under X11 and Wayland and never captures whatever
else is on the desktop.

XDG_STATE_HOME and XDG_CONFIG_HOME are redirected to a temp directory that
seed.py fills, so this reads none of your real messages, contacts, or
config, and leaves nothing behind.

Run it with the system interpreter (/usr/bin/python3): PyGObject and
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

# (ViewStack child, output basename, force the link pill to a bad link)
VIEWS = [
    ("conversations", "messages", False),
    ("conversations", "messages-reconnecting", True),
    ("notifications", "notifications", False),
    ("calls", "calls", False),
    ("status", "setup", False),
]

SETTLE_MS = 700        # after switching view, before capturing
SCHEME_SETTLE_MS = 900  # after switching colour scheme: a restyle is slower


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(REPO / "src"),
                    help="package root to import from (default: ./src)")
    ap.add_argument("--out", default=str(HERE),
                    help="directory to write PNGs into (default: this one)")
    ap.add_argument("--scheme", choices=("light", "dark", "both"),
                    default="both")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    schemes = ["light", "dark"] if args.scheme == "both" else [args.scheme]

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
        return _render(out, schemes)


def _render(out: pathlib.Path, schemes: list[str]) -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Graphene, Gtk

    from iphonebridge.ui import app as uiapp
    from iphonebridge.ui.client import DaemonClient
    from iphonebridge.ui.window import MainWindow

    SCHEMES = {"light": Adw.ColorScheme.FORCE_LIGHT,
               "dark": Adw.ColorScheme.FORCE_DARK}

    def capture(win, path: pathlib.Path) -> bool:
        w, h = win.get_width(), win.get_height()
        if not w or not h:
            print(f"  !! {path.name}: window not allocated", file=sys.stderr)
            return False
        paintable = Gtk.WidgetPaintable.new(win)
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, w, h)
        node = snapshot.to_node()
        if node is None:
            print(f"  !! {path.name}: empty render node", file=sys.stderr)
            return False
        renderer = win.get_native().get_renderer()
        texture = renderer.render_texture(
            node, Graphene.Rect().init(0, 0, w, h))
        texture.save_to_png(str(path))
        print(f"  {path.name}  {w}x{h}")
        return True

    class Shooter(uiapp.IphonebridgeApp):
        """The real application, minus the single-instance behaviour.

        Subclassing keeps the stylesheet and icon-path setup in do_startup
        as the only copy; a distinct id plus NON_UNIQUE stops this from
        merely waking an already-running iphonebridge-ui and exiting.
        """

        def __init__(self) -> None:
            super().__init__()
            self.set_application_id("me.santisbon.iphonebridge.Screenshots")
            self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
            self.failures = 0
            self._jobs = [(s, v) for s in schemes for v in VIEWS]
            self._scheme = None

        def do_activate(self) -> None:
            self.win = MainWindow(application=self, client=DaemonClient())
            self.win.present()
            GLib.timeout_add(SETTLE_MS, self._step, 0)

        def _step(self, i: int) -> bool:
            if i >= len(self._jobs):
                self.quit()
                return False
            scheme, (child, label, degraded) = self._jobs[i]
            delay = SETTLE_MS
            if scheme != self._scheme:
                Adw.StyleManager.get_default().set_color_scheme(
                    SCHEMES[scheme])
                self._scheme = scheme
                delay = SCHEME_SETTLE_MS
            self.win._stack.set_visible_child_name(child)
            if child == "conversations":
                page = self.win._stack.get_child_by_name("conversations")
                row = page._thread_list.get_row_at_index(0)
                if row is not None:
                    page._thread_list.select_row(row)
                # The pre-redesign page has no link pill, so skip that
                # variant rather than writing a duplicate of the healthy one.
                if not hasattr(page, "_update_link_pill"):
                    if degraded:
                        return self._step(i + 1)
                else:
                    page._update_link_pill(alive=not degraded)
            GLib.timeout_add(delay, self._shoot, (i, f"{label}-{scheme}"))
            return False

        def _shoot(self, job: tuple[int, str]) -> bool:
            i, name = job
            if not capture(self.win, out / f"{name}.png"):
                self.failures += 1
            GLib.timeout_add(150, self._step, i + 1)
            return False

    shooter = Shooter()
    shooter.run([])
    return 1 if shooter.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
