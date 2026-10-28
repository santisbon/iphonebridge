"""The libnotify sink comes up with no notification server running yet."""
from iphonebridge.sinks import libnotify


class Proxy:
    def connect_to_signal(self, name, handler, dbus_interface=None,
                          **kwargs):
        return object()


class Bus:
    def __init__(self):
        self.kwargs = None

    def get_object(self, name, path, introspect=True,
                   follow_name_owner_changes=False):
        # dbus-python resolves the owner here unless told to follow it,
        # which fails with ServiceUnknown while nobody owns the name.
        if not follow_name_owner_changes:
            raise RuntimeError("org.freedesktop.Notifications has no owner")
        self.kwargs = {"follow_name_owner_changes": True}
        return Proxy()


def test_sink_follows_the_name_instead_of_its_owner(monkeypatch):
    bus = Bus()
    monkeypatch.setattr(libnotify, "session_bus", bus)
    sink = libnotify.LibnotifySink()
    assert sink.name == "libnotify"
    assert bus.kwargs == {"follow_name_owner_changes": True}
