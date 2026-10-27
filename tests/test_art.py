"""ArtFetcher's fallback when another client holds the image channel."""
from __future__ import annotations

ADDR = "AA:BB:CC:DD:EE:FF"
BIP = "0000111a-0000-1000-8000-00805f9b34fb"


def _fetcher(monkeypatch, tmp_path, objects):
    from iphonebridge.media import art

    class ObjectManager:
        def GetManagedObjects(self):
            return objects

    monkeypatch.setattr(art.session_bus, "watch_name_owner",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr(art.session_bus, "get_object",
                        lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(art.dbus, "Interface", lambda obj, iface: ObjectManager())
    monkeypatch.setattr(art.config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(art.tempfile, "gettempdir", lambda: str(tmp_path))
    return art, art.ArtFetcher(ADDR)


def _session(target, dest):
    return {"org.bluez.obex.Session1": {"Target": target, "Destination": dest}}


def test_foreign_session_matches_image_target_and_address(monkeypatch, tmp_path):
    objects = {
        "/org/bluez/obex/client/session1": _session(
            "00001132-0000-1000-8000-00805f9b34fb", ADDR),
        "/org/bluez/obex/client/session2": _session(BIP, "11:22:33:44:55:66"),
        "/org/bluez/obex/client/session3": _session(BIP.upper(), ADDR.lower()),
    }
    _, fetcher = _fetcher(monkeypatch, tmp_path, objects)
    assert fetcher._foreign_session() == "/org/bluez/obex/client/session3"


def test_borrow_copies_the_other_clients_cover(monkeypatch, tmp_path):
    objects = {"/org/bluez/obex/client/session3": _session(BIP, ADDR)}
    art, fetcher = _fetcher(monkeypatch, tmp_path, objects)
    (tmp_path / "session3-1000010").write_bytes(b"\xff\xd8jpeg")
    target = art._art_file("1000010")
    done = []
    fetcher._busy = True
    fetcher._borrow("1000010", target, lambda h, p: done.append((h, p)))
    assert done == [("1000010", str(target))]
    assert target.read_bytes() == b"\xff\xd8jpeg"
    assert fetcher._busy is False


def test_borrow_waits_for_a_cover_that_arrives_later(monkeypatch, tmp_path):
    """The other client downloads on its own schedule; the wait has no
    deadline and ends when the file appears."""
    objects = {"/org/bluez/obex/client/session0": _session(BIP, ADDR)}
    art, fetcher = _fetcher(monkeypatch, tmp_path, objects)
    timers = []
    from gi.repository import GLib
    monkeypatch.setattr(GLib, "timeout_add_seconds",
                        lambda s, fn: timers.append(fn))
    target = art._art_file("1000010")
    done = []
    fetcher._borrow("1000010", target, lambda h, p: done.append((h, p)))
    assert done == [] and len(timers) == 1
    assert timers[0]() is True          # still waiting
    (tmp_path / "session0-1000010").write_bytes(b"cover")
    assert timers[0]() is False
    assert done == [("1000010", str(target))]


def test_a_new_handle_ends_the_wait(monkeypatch, tmp_path):
    objects = {"/org/bluez/obex/client/session0": _session(BIP, ADDR)}
    art, fetcher = _fetcher(monkeypatch, tmp_path, objects)
    timers = []
    from gi.repository import GLib
    monkeypatch.setattr(GLib, "timeout_add_seconds",
                        lambda s, fn: timers.append(fn))
    done = []
    fetcher._borrow("1", art._art_file("1"), lambda h, p: done.append((h, p)))
    fetcher._borrowing = "2"            # what fetch() does for a new track
    (tmp_path / "session0-1").write_bytes(b"cover")
    assert timers[0]() is False
    assert done == []


def test_borrow_without_another_session_reports_no_cover(monkeypatch, tmp_path):
    art, fetcher = _fetcher(monkeypatch, tmp_path, {})
    done = []
    fetcher._borrow("1", art._art_file("1"), lambda h, p: done.append((h, p)))
    assert done == [("1", None)]
