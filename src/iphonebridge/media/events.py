"""MediaState — the now-playing snapshot relayed from BlueZ to the app.

Everything here is pure data mapping so it runs under CI, which has no
dbus or Qt. The dict this produces is the wire format of the daemon's
MediaStateChanged signal and GetMediaState reply, and the D-Bus layer's
variant coercion cannot carry nested containers or None — so `to_dict`
is flat and every value is a scalar with a real default.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class MediaState:
    """One flat snapshot of the AVRCP player and transport."""

    available: bool = False
    status: str = ""          # BlueZ MediaPlayer1.Status, verbatim
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    position_ms: int = 0
    shuffle: str = ""         # "off" / "alltracks" / "group"
    repeat: str = ""          # "off" / "singletrack" / "alltracks" / "group"
    volume: int = -1          # 0-127; -1 while no transport offers one

    def to_dict(self) -> dict:
        return asdict(self)


def _text(value) -> str:
    return "" if value is None else str(value)


def _ms(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def media_state_from_bluez(player_props: dict | None,
                           transport_volume: int | None,
                           position_ms: int | None = None) -> MediaState:
    """Build a snapshot from BlueZ property dicts.

    Coerces through str()/int() so dbus types and plain types both work,
    and reads `Track` defensively — mid-track-change BlueZ can hand over
    a dict missing any key.
    """
    if player_props is None:
        return MediaState(
            volume=-1 if transport_volume is None else _ms(transport_volume))
    track = player_props.get("Track") or {}
    pos = position_ms if position_ms is not None \
        else player_props.get("Position")
    try:
        volume = -1 if transport_volume is None else int(transport_volume)
    except (TypeError, ValueError):
        volume = -1
    return MediaState(
        available=True,
        status=_text(player_props.get("Status")),
        title=_text(track.get("Title")),
        artist=_text(track.get("Artist")),
        album=_text(track.get("Album")),
        duration_ms=_ms(track.get("Duration")),
        position_ms=_ms(pos),
        shuffle=_text(player_props.get("Shuffle")),
        repeat=_text(player_props.get("Repeat")),
        volume=volume,
    )


def next_shuffle(current: str) -> str:
    """Value a tap on the Shuffle row should write: off ↔ alltracks.

    "group" and anything unrecognised land on "off" — the tap always
    reaches a state the row can name.
    """
    return "alltracks" if current == "off" else "off"


def next_repeat(current: str) -> str:
    """Value a tap on the Repeat row should write.

    Cycles off → alltracks → singletrack → off, matching how the
    Music app's own repeat button advances; unknowns land on "off".
    """
    return {"off": "alltracks", "alltracks": "singletrack"}.get(current,
                                                                "off")


def extrapolate_position(position_ms: int, status: str, elapsed_ms: int,
                         duration_ms: int) -> int:
    """Where playback is now, given the last report and time since it.

    Only "playing" advances. Clamped to the track when its length is
    known; an unknown length (0) leaves the estimate unclamped rather
    than freezing it at zero.
    """
    pos = max(0, int(position_ms))
    if status == "playing":
        pos += max(0, int(elapsed_ms))
    if duration_ms > 0:
        pos = min(pos, int(duration_ms))
    return pos


def is_position_jump(expected_ms: int, reported_ms: int,
                     threshold_ms: int = 2000) -> bool:
    """True when a Position report disagrees with extrapolation enough
    to mean a seek or a missed transition, so listeners must resync."""
    return abs(int(reported_ms) - int(expected_ms)) > threshold_ms


def format_ms(ms: int) -> str:
    """Clock text for the position row: m:ss, h:mm:ss past an hour."""
    total = max(0, int(ms)) // 1000
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


_SHUFFLE_DISPLAY = {"off": "Off", "alltracks": "On", "group": "On"}
_REPEAT_DISPLAY = {"off": "Off", "alltracks": "All", "singletrack": "One",
                   "group": "All"}


def shuffle_display(value: str) -> str:
    """Row value for the Shuffle setting."""
    return _SHUFFLE_DISPLAY.get(value, "Off" if value else "—")


def repeat_display(value: str) -> str:
    """Row value for the Repeat setting."""
    return _REPEAT_DISPLAY.get(value, "Off" if value else "—")
