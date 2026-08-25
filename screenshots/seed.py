"""Synthetic conversation data for the screenshots in this directory.

Every name, number, and message here is invented, and the numbers are all
in the 555 range. Screenshots are rendered against a throwaway state dir
seeded from this file rather than against a real events.jsonl, so no real
contact or message can end up in a committed image.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Fixed so re-running produces byte-identical images: the day rules in a
# thread read "Today" / "Yesterday" relative to this, not to the clock.
BASE = datetime(2026, 8, 25, 9, 12)


def _local(minutes: int) -> datetime:
    """A wall-clock instant, made timezone-aware in the local zone.

    Anchoring to local wall time keeps the rendered images identical on
    any machine: the file contents differ by zone, but the UI converts
    back to local for display.
    """
    return (BASE + timedelta(minutes=minutes)).astimezone()


def _at(minutes: int) -> str:
    """UTC, which is how the daemon writes `seen_at`."""
    return _local(minutes).astimezone(timezone.utc).isoformat()


def _sms(kind: str, name: str | None, phone: str, body: str,
         minutes: int) -> dict:
    ev = {"kind": kind, "contact_name": name, "sender_phone": phone,
          "sender_phone_norm": phone.lstrip("+"), "body": body,
          "seen_at": _at(minutes)}
    # Only a sent message gets a `timestamp`, mirroring the daemon: BlueZ
    # exports an MNS-pushed message with a property set carrying no
    # Timestamp, so an incoming one falls back to seen_at. Both are UTC,
    # as the log is. Ordering across the two fields is covered by
    # tests/test_ui_util.py, including the legacy mixed-zone case.
    if kind == "sms_sent":
        ev["timestamp"] = _at(minutes)
    return ev


def events() -> list[dict]:
    rows = [
        # A back-and-forth with consecutive same-sender runs, so the
        # 2px-within-a-run vs 8px-on-speaker-change rhythm is visible.
        _sms("sms_received", "Dana Whitfield", "+15550138",
             "landed early, cab line is a mess", -1440),
        _sms("sms_received", "Dana Whitfield", "+15550138",
             "might be 20 late", -1439),
        _sms("sms_sent", "Dana Whitfield", "+15550138",
             "no rush, the table is held until 8", -1435),
        _sms("sms_received", "Dana Whitfield", "+15550138",
             "you are a saint", -1430),
        _sms("sms_received", "Dana Whitfield", "+15550138",
             "ok moving now", 0),
        _sms("sms_sent", "Dana Whitfield", "+15550138",
             "see you there", 3),
        # A long single message, to exercise wrapping and the width cap.
        _sms("sms_received", "Margaret Ellison", "+15550172",
             "Reminder that the quarterly numbers are due Thursday morning, "
             "and I still need the revised figures from your side before I "
             "can close the deck.", -220),
        # An unnamed number, the case sidebar avatars would break on.
        _sms("sms_received", None, "+15550196",
             "Your verification code is 481502.", -90),
    ]
    notes = [
        ("Slack", "Design channel",
         "Susan: pushed the new bubble radius, take a look"),
        ("Mail", "Ana Beltran",
         "Re: Thursday deck — one more pass and it ships"),
        ("Calendar", "Standup", "in 10 minutes"),
        ("WhatsApp", "Climbing crew", "Marta: gym at 7 or are we outside?"),
    ]
    rows += [{"kind": "ancs_notification", "app_name": app, "title": title,
              "body": body, "seen_at": _at(-30 + i * 7)}
             for i, (app, title, body) in enumerate(notes)]
    return rows


def seed(state_home: pathlib.Path) -> pathlib.Path:
    """Write events.jsonl under `state_home`, the way the daemon would.

    `state_home` is an XDG_STATE_HOME, so the file lands in the
    `iphonebridge/` subdirectory that config.py looks in.
    """
    out = state_home / "iphonebridge" / "events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r) for r in events()) + "\n")
    return out


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    path = seed(target)
    print(f"seeded {path} ({len(events())} events)")
