"""phone.py's pure mapping layer — battery, cellular, and the alarm."""
import json

from iphonebridge.phone import (
    BatteryAlarm,
    build_phone_status,
    hfp_level_to_pct,
)


class TestLevelToPct:
    def test_scale(self):
        assert hfp_level_to_pct(0) == 0
        assert hfp_level_to_pct(3) == 60
        assert hfp_level_to_pct(5) == 100

    def test_out_of_range_and_garbage(self):
        assert hfp_level_to_pct(6) == -1
        assert hfp_level_to_pct(-1) == -1
        assert hfp_level_to_pct(None) == -1
        assert hfp_level_to_pct("x") == -1


class TestBuilder:
    def test_exact_battery_wins(self):
        st = build_phone_status(battery_pct=76, hfp_level=4)
        assert st["battery_pct"] == 76
        assert st["battery_estimated"] is False

    def test_hfp_fallback_is_marked_estimated(self):
        st = build_phone_status(battery_pct=-1, hfp_level=4)
        assert st["battery_pct"] == 80
        assert st["battery_estimated"] is True

    def test_nothing_known(self):
        st = build_phone_status()
        assert st["battery_pct"] == -1
        assert st["battery_estimated"] is False
        assert st["signal_pct"] == -1
        assert st["network"] == ""
        assert st["model"] == ""

    def test_signal_clamped(self):
        assert build_phone_status(signal_pct=150)["signal_pct"] == 100
        assert build_phone_status(signal_pct=-7)["signal_pct"] == -1

    def test_flat_scalars_and_json_safe(self):
        st = build_phone_status(battery_pct=76, signal_pct=60,
                                network="Carrier", reg="registered",
                                model="iPhone18,1", manufacturer="Apple")
        for key, value in st.items():
            assert isinstance(value, (bool, int, str)), (key, value)
        json.dumps(st)

    def test_none_inputs_coerce(self):
        st = build_phone_status(network=None, reg=None, model=None,
                                manufacturer=None)
        assert st["network"] == "" and st["model"] == ""


class TestBatteryAlarm:
    def test_fires_once_per_dip(self):
        a = BatteryAlarm(20)
        assert a.update(50) is False
        assert a.update(20) is True     # crossing fires
        assert a.update(15) is False    # still low: silent
        assert a.update(10) is False

    def test_rearms_with_hysteresis(self):
        a = BatteryAlarm(20)
        assert a.update(18) is True
        assert a.update(22) is False    # above threshold but inside band
        assert a.update(24) is False
        assert a.update(25) is False    # reaches threshold+5: re-arms
        assert a.update(19) is True     # next dip fires again

    def test_first_reading_already_low_fires(self):
        assert BatteryAlarm(20).update(5) is True

    def test_disabled_and_unknown(self):
        assert BatteryAlarm(0).update(1) is False
        assert BatteryAlarm(-3).update(1) is False
        assert BatteryAlarm(20).update(-1) is False
