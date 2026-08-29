"""media/events.py — the tested contract behind the Now Playing tab.

The dict built here is what the daemon's Media1 signal carries, and the
D-Bus variant coercion can hold neither nested containers nor None, so
the flatness/scalar checks are load-bearing, not pedantry.
"""
import json

from iphonebridge.media.events import (
    MediaState,
    extrapolate_position,
    format_ms,
    is_position_jump,
    media_state_from_bluez,
    next_repeat,
    next_shuffle,
    repeat_display,
    shuffle_display,
)

FULL_PROPS = {
    "Status": "playing",
    "Position": 42_000,
    "Shuffle": "off",
    "Repeat": "alltracks",
    "Track": {
        "Title": "Song",
        "Artist": "Artist",
        "Album": "Album",
        "Duration": 180_000,
        "Genre": "Pop",
        "TrackNumber": 3,
        "NumberOfTracks": 12,
    },
}


class TestBuilder:
    def test_full_props(self):
        st = media_state_from_bluez(FULL_PROPS, 55)
        assert st.available is True
        assert st.status == "playing"
        assert st.title == "Song"
        assert st.artist == "Artist"
        assert st.album == "Album"
        assert st.duration_ms == 180_000
        assert st.position_ms == 42_000
        assert st.shuffle == "off"
        assert st.repeat == "alltracks"
        assert st.volume == 55

    def test_missing_track_keys_default_cleanly(self):
        st = media_state_from_bluez({"Status": "paused", "Track": {}}, None)
        assert (st.title, st.artist, st.album) == ("", "", "")
        assert st.duration_ms == 0
        assert st.volume == -1

    def test_no_track_at_all(self):
        st = media_state_from_bluez({"Status": "stopped"}, 10)
        assert st.available is True
        assert st.title == ""

    def test_no_player_is_unavailable(self):
        st = media_state_from_bluez(None, None)
        assert st.available is False
        assert st.volume == -1
        assert st.status == ""

    def test_explicit_position_overrides_cached_property(self):
        st = media_state_from_bluez(FULL_PROPS, 55, position_ms=99_000)
        assert st.position_ms == 99_000

    def test_art_path_rides_the_payload(self):
        st = media_state_from_bluez(FULL_PROPS, 55,
                                    art_path="/tmp/cover_1.img")
        assert st.art_path == "/tmp/cover_1.img"
        assert media_state_from_bluez(FULL_PROPS, 55).art_path == ""
        assert media_state_from_bluez(FULL_PROPS, 55,
                                      art_path=None).art_path == ""

    def test_dbus_like_string_coercion(self):
        props = {"Status": "playing", "Position": "42000",
                 "Track": {"Duration": "180000", "Title": 7}}
        st = media_state_from_bluez(props, "55")
        assert st.position_ms == 42_000
        assert st.duration_ms == 180_000
        assert st.title == "7"
        assert st.volume == 55

    def test_dict_is_flat_scalars_and_json_safe(self):
        for st in (media_state_from_bluez(FULL_PROPS, 55),
                   media_state_from_bluez(None, None),
                   MediaState()):
            d = st.to_dict()
            for key, value in d.items():
                assert isinstance(value, (bool, int, str)), (key, value)
            json.dumps(d)


class TestCycles:
    def test_shuffle_cycle(self):
        assert next_shuffle("off") == "alltracks"
        assert next_shuffle("alltracks") == "off"
        # "group" and garbage always land somewhere nameable
        assert next_shuffle("group") == "off"
        assert next_shuffle("") == "off"

    def test_repeat_cycle(self):
        assert next_repeat("off") == "alltracks"
        assert next_repeat("alltracks") == "singletrack"
        assert next_repeat("singletrack") == "off"
        assert next_repeat("group") == "off"
        assert next_repeat("") == "off"


class TestPosition:
    def test_playing_advances(self):
        assert extrapolate_position(10_000, "playing", 5_000, 180_000) \
            == 15_000

    def test_paused_and_stopped_hold(self):
        assert extrapolate_position(10_000, "paused", 5_000, 180_000) \
            == 10_000
        assert extrapolate_position(10_000, "stopped", 5_000, 0) == 10_000

    def test_clamped_to_duration(self):
        assert extrapolate_position(179_000, "playing", 60_000, 180_000) \
            == 180_000

    def test_unknown_duration_does_not_clamp(self):
        assert extrapolate_position(179_000, "playing", 60_000, 0) \
            == 239_000

    def test_never_negative(self):
        assert extrapolate_position(-5, "paused", -10, 0) == 0

    def test_jump_threshold(self):
        assert is_position_jump(10_000, 13_000)
        assert not is_position_jump(10_000, 11_500)
        assert is_position_jump(10_000, 7_000)
        assert not is_position_jump(10_000, 10_000)


class TestFormatting:
    def test_format_ms(self):
        assert format_ms(0) == "0:00"
        assert format_ms(61_000) == "1:01"
        assert format_ms(3_661_000) == "1:01:01"
        assert format_ms(-500) == "0:00"

    def test_display_labels(self):
        assert shuffle_display("off") == "Off"
        assert shuffle_display("alltracks") == "On"
        assert repeat_display("off") == "Off"
        assert repeat_display("alltracks") == "All"
        assert repeat_display("singletrack") == "One"
