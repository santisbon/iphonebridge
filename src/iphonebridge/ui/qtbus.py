"""D-Bus for the Qt UI process — the same stack, a different main loop.

`iphonebridge.bus` installs the GLib main-loop integration at import time
and is shared by the daemon, the CLI and the sinks. dbus-python only
delivers signals while its integrated loop is *running*, and under
`QApplication.exec()` the GLib loop never runs — every signal would go
silently missing.

`python3-dbus.mainloop.pyqt6` provides the Qt equivalent, so the UI keeps
the exact dbus-python API the rest of the project uses: signal receivers,
async reply_handler/error_handler, and watch_name_owner all behave as
before. Only the loop underneath changes.

The two integrations are mutually exclusive within a process, because each
calls `set_as_default`. The UI must therefore never import
`iphonebridge.bus`, directly or transitively — importing this module first
and asserting below makes that failure loud instead of mysterious.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QCoreApplication

if "iphonebridge.bus" in sys.modules:      # pragma: no cover - import guard
    raise ImportError(
        "iphonebridge.bus was imported before iphonebridge.ui.qtbus. Both "
        "install a dbus-python main loop with set_as_default, so whichever "
        "lands second is ignored and D-Bus signals stop arriving. The UI "
        "must use qtbus only."
    )

import dbus
import dbus.mainloop.pyqt6

_bus: dbus.SessionBus | None = None


def session_bus() -> dbus.SessionBus:
    """The session bus, wired to Qt's event loop.

    Deliberately lazy, unlike `iphonebridge.bus`'s import-time module
    globals: the integration installs QSocketNotifiers, and those need a
    QCoreApplication to already exist. Connecting at import time earns
    "QSocketNotifier: Can only be used with threads started with QThread"
    and a socket watch that never fires. Call this after constructing the
    application object.
    """
    global _bus
    if _bus is None:
        if QCoreApplication.instance() is None:
            raise RuntimeError(
                "construct the QApplication before connecting to D-Bus: "
                "the Qt main-loop integration installs QSocketNotifiers, "
                "which need a running application object."
            )
        dbus.mainloop.pyqt6.DBusQtMainLoop(set_as_default=True)
        _bus = dbus.SessionBus()
    return _bus
