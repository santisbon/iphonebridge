"""config.device_path finds the iPhone's BlueZ object by its address."""
import dbus.exceptions

from iphonebridge import config

ADDRESS = "AA:BB:CC:DD:EE:FF"
# A resolvable private address: the top two bits of the first byte are 01.
RANDOM_PATH = "/org/bluez/hci0/dev_5A_11_22_33_44_55"


class Bus:
    def __init__(self, objects=None, error=False):
        self.objects, self.error = objects or {}, error

    def get_object(self, name, path):
        bus = self

        class Manager:
            def GetManagedObjects(self, dbus_interface):
                if bus.error:
                    raise dbus.exceptions.DBusException("no bluetoothd")
                return bus.objects
        return Manager()


def test_finds_a_device_named_after_its_random_address(monkeypatch):
    monkeypatch.setattr(config, "IPHONE_MAC", ADDRESS.lower())
    bus = Bus({RANDOM_PATH: {"org.bluez.Device1": {"Address": ADDRESS}},
               "/org/bluez/hci0": {"org.bluez.Adapter1": {}}})
    assert config.device_path(bus) == RANDOM_PATH


def test_falls_back_to_the_public_address_path(monkeypatch):
    monkeypatch.setattr(config, "IPHONE_MAC", ADDRESS)
    expected = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
    assert config.device_path() == expected
    assert config.device_path(Bus()) == expected
    assert config.device_path(Bus(error=True)) == expected


def test_ignores_a_device_on_another_adapter(monkeypatch):
    monkeypatch.setattr(config, "IPHONE_MAC", ADDRESS)
    bus = Bus({"/org/bluez/hci1/dev_5A_11_22_33_44_55": {"org.bluez.Device1": {"Address": ADDRESS}}})
    assert config.device_path(bus) == "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
