"""HfpManager follows oFono's bus name: attach on appear, detach on vanish."""
from iphonebridge.hfp import ofono_client


class Match:
    def __init__(self):
        self.removed = False

    def remove(self):
        self.removed = True


class Watch:
    def __init__(self, callback):
        self.callback, self.cancelled = callback, False

    def cancel(self):
        self.cancelled = True


class Proxy:
    def __init__(self, modems):
        self.modems = modems

    def GetModems(self, dbus_interface=None):
        return self.modems

    def get_dbus_method(self, member, dbus_interface=None):
        return getattr(self, member)

    def connect_to_signal(self, name, handler, dbus_interface=None):
        return Match()


class Bus:
    def __init__(self, modems=()):
        self.watch = None
        self.proxy = Proxy(list(modems))

    def watch_name_owner(self, name, callback):
        assert name == ofono_client.OFONO
        self.watch = Watch(callback)
        return self.watch

    def get_object(self, name, path):
        return self.proxy


def manager(monkeypatch, bus):
    monkeypatch.setattr(ofono_client, "system_bus", bus)
    events = []
    hfp = ofono_client.HfpManager(on_event=events.append)
    hfp.start()
    return hfp, events


def test_attaches_only_once_ofono_is_running(monkeypatch):
    bus = Bus()
    hfp, _ = manager(monkeypatch, bus)
    bus.watch.callback("")
    assert hfp._mgr_matches == []
    bus.watch.callback(":1.42")
    assert len(hfp._mgr_matches) == 2


def test_a_restarted_ofono_gets_fresh_signal_matches(monkeypatch):
    bus = Bus()
    hfp, _ = manager(monkeypatch, bus)
    bus.watch.callback(":1.42")
    first = list(hfp._mgr_matches)
    bus.watch.callback("")
    assert all(m.removed for m in first) and hfp._mgr_matches == []
    bus.watch.callback(":1.43")
    assert len(hfp._mgr_matches) == 2 and hfp._mgr_matches[0] is not first[0]


def test_ofono_going_away_drops_the_modem(monkeypatch):
    bus = Bus()
    hfp, _ = manager(monkeypatch, bus)
    hfp._modem_path = "/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
    hfp._vcm_hooked = True
    assert hfp.ready
    bus.watch.callback("")
    assert not hfp.ready and hfp._modem_path is None


def test_stop_cancels_the_watch(monkeypatch):
    bus = Bus()
    hfp, _ = manager(monkeypatch, bus)
    hfp.stop()
    assert bus.watch.cancelled and hfp._name_watch is None
