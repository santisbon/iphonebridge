

def test_set_cod_starts_the_root_unit(monkeypatch):
    """The daemon sets the CoD by starting iphonebridge-cod.service over
    D-Bus, never by running sudo, and succeeds once the adapter reports
    A/V Hands-Free."""
    from iphonebridge import bluez_setup

    started = []

    class Manager:
        def StartUnit(self, unit, mode):
            started.append((unit, mode))

    monkeypatch.setattr(bluez_setup.dbus, "Interface",
                        lambda obj, iface: Manager())
    monkeypatch.setattr(bluez_setup.system_bus, "get_object",
                        lambda *a: object(), raising=False)
    cods = iter([0x0c010c, 0x240408])
    monkeypatch.setattr(bluez_setup, "current_cod", lambda: next(cods))
    monkeypatch.setattr(bluez_setup.time, "sleep", lambda s: None)
    assert bluez_setup.set_cod() is True
    assert started == [("iphonebridge-cod.service", "replace")]


DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
ANCS_SVC = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"


def _chars_under(dev_path):
    from iphonebridge.ancs.constants import ANCS_CHAR_UUIDS
    return {
        f"{dev_path}/service0010/char{i:04x}":
            {"org.bluez.GattCharacteristic1": {"UUID": u.upper()}}
        for i, u in enumerate(sorted(ANCS_CHAR_UUIDS))
    }


def _install_fake_bluez(monkeypatch, *, uuids, connected, managed,
                        missing=False):
    import dbus.exceptions

    from iphonebridge import bluez_setup

    class Props:
        def Get(self, iface, prop):
            if missing:
                raise dbus.exceptions.DBusException("UnknownObject")
            return {"UUIDs": uuids, "Connected": connected}[prop]

    class ObjectManager:
        def GetManagedObjects(self):
            return managed

    def fake_bluez(path, iface):
        if iface == "org.freedesktop.DBus.ObjectManager":
            return ObjectManager()
        return Props()

    monkeypatch.setattr(bluez_setup, "bluez", fake_bluez)
    monkeypatch.setattr(bluez_setup.config, "device_path", lambda bus=None: DEV)


def test_ancs_state_cached_uuid_without_le_link_is_not_live(monkeypatch):
    """BlueZ keeps the ANCS service UUID from the last LE session, so the
    UUID alone reads granted with the phone back over BR/EDR and no GATT
    objects present — the state the app's Status tab calls Not detected.
    doctor must not call that available."""
    from iphonebridge import bluez_setup

    _install_fake_bluez(monkeypatch, uuids=[ANCS_SVC], connected=True,
                        managed={})
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_NO_LE


def test_ancs_state_live_needs_all_three_chars_under_this_device(monkeypatch):
    from iphonebridge import bluez_setup

    _install_fake_bluez(monkeypatch, uuids=[ANCS_SVC], connected=True,
                        managed=_chars_under(DEV))
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_LIVE

    other = _chars_under("/org/bluez/hci0/dev_11_22_33_44_55_66")
    _install_fake_bluez(monkeypatch, uuids=[ANCS_SVC], connected=True,
                        managed=other)
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_NO_LE

    partial = dict(list(_chars_under(DEV).items())[:2])
    _install_fake_bluez(monkeypatch, uuids=[ANCS_SVC], connected=True,
                        managed=partial)
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_NO_LE


def test_ancs_state_earlier_failures_take_precedence(monkeypatch):
    from iphonebridge import bluez_setup

    _install_fake_bluez(monkeypatch, uuids=[ANCS_SVC], connected=False,
                        managed=_chars_under(DEV))
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_DISCONNECTED

    _install_fake_bluez(monkeypatch, uuids=["0000110e-0000-1000-8000-00805f9b34fb"],
                        connected=True, managed=_chars_under(DEV))
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_NO_BOND

    _install_fake_bluez(monkeypatch, uuids=[], connected=True, managed={},
                        missing=True)
    assert bluez_setup.ancs_state() == bluez_setup.ANCS_NO_DEVICE
