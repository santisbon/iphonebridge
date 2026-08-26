"""The daemon's D-Bus surface, and the parts of talking to it that do not
depend on which main loop is running.

Split out so a second front end can reuse it: `iphonebridge.ui.client`
binds this to GLib for the GTK app, and a Qt front end binds it to Qt's
loop, but the bus names, the dbus-type coercion and the event-log reader
are identical either way. Nothing here imports a main-loop integration,
so importing it can never fix the wrong loop as default.
"""
from __future__ import annotations

import json
import logging

import dbus
import dbus.exceptions

from iphonebridge import config

log = logging.getLogger(__name__)

BUS_NAME = "me.santisbon.iphonebridge"
OBJECT_PATH = "/me/santisbon/iphonebridge"
MESSAGES_IFACE = "me.santisbon.iphonebridge.Messages1"
CALLS_IFACE = "me.santisbon.iphonebridge.Calls1"
EVENTS_IFACE = "me.santisbon.iphonebridge.Events1"

#: Everything the QML expects to find in its root context. Kept here, and
#: away from any toolkit import, so a test can check the QML against it
#: without a display: a name missing from the context is not a crash, it
#: is a view with no model and a binding that quietly reads null, which is
#: how the Calls tab once shipped permanently empty.
QML_CONTEXT_NAMES = ("bridge", "threads", "messages", "notifications", "calls")

#: Events1 signal name -> the name a front end re-emits it under.
EVENT_SIGNALS = (
    ("MessageReceived", "message-received"),
    ("MessageSent", "message-sent"),
    ("MessageSeen", "message-seen"),
    ("AncsNotification", "ancs-notification"),
)


def plain(value):
    """Recursively convert dbus-python types into plain Python values."""
    if isinstance(value, dbus.Dictionary):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, dbus.Array):
        return [plain(v) for v in value]
    if isinstance(value, dbus.String):
        return str(value)
    if isinstance(value, dbus.Boolean):
        return bool(value)
    if isinstance(value, (dbus.Int16, dbus.Int32, dbus.Int64,
                          dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
        return int(value)
    if isinstance(value, dbus.Double):
        return float(value)
    return value


def dbus_error_text(e: Exception) -> str:
    if isinstance(e, dbus.exceptions.DBusException):
        return e.get_dbus_message() or e.get_dbus_name() or str(e)
    return str(e)


def read_events(kinds: set[str] | None = None,
                limit: int | None = None) -> list[dict]:
    """Parse events.jsonl, oldest-first. Optionally filter by `kind`.

    Reads the daemon's state file directly rather than going over D-Bus:
    cheaper than a round-trip, and it works while the daemon is
    mid-restart.
    """
    path = config.EVENTS_JSONL
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kinds and ev.get("kind") not in kinds:
                continue
            out.append(ev)
    except OSError as e:
        log.warning("could not read %s: %s", path, e)
    if limit is not None:
        out = out[-limit:]
    return out
