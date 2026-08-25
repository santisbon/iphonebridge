"""Small shared helpers for the UI pages."""
from __future__ import annotations

from datetime import datetime, timezone


def _parse(value: str | None) -> datetime | None:
    """Parse an ISO timestamp from an event dict into local time."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt.astimezone() if dt.tzinfo is not None else dt


def _fmt(dt: datetime, fmt: str) -> str:
    try:
        return dt.strftime(fmt)
    except ValueError:  # %-d is glibc-only; fall back if unsupported
        return dt.strftime(fmt.replace("%-d", "%d"))


def format_ts(value: str | None, *, fmt: str = "%b %-d · %H:%M") -> str:
    """Format an ISO timestamp from an event dict, in local time."""
    if not value:
        return ""
    dt = _parse(value)
    if dt is None:
        return str(value)[:16]
    return _fmt(dt, fmt)


#: Sorts before any real event, for entries with no usable timestamp.
_BEGINNING = datetime.min.replace(tzinfo=timezone.utc)


def ts_key(value: str | None) -> datetime:
    """Comparable instant for ordering events.

    The daemon writes UTC, so its own stamps do sort correctly as text.
    This exists for everything else: entries logged before the move to
    UTC carry a local offset, and "09:30-05:00" sorts before
    "14:30+00:00" despite being the same instant or later. Parsing rather
    than comparing keeps a log that mixes both readable, and costs
    nothing once the log is uniform.

    Always returns an aware datetime, so results are safe to compare with
    each other; a naive stamp is read as local time.
    """
    dt = _parse(value)
    if dt is None:
        return _BEGINNING
    return dt if dt.tzinfo is not None else dt.astimezone()


def _days_ago(dt: datetime) -> int:
    return (datetime.now().astimezone().date() - dt.date()).days


def daystamp(value: str | None) -> str:
    """Pango markup for the centred rule between message groups.

    Messages prints the day in bold with the time beside it, and switches
    to relative wording for the last two days.
    """
    from gi.repository import GLib
    dt = _parse(value)
    if dt is None:
        return ""
    delta = _days_ago(dt)
    if delta == 0:
        day = "Today"
    elif delta == 1:
        day = "Yesterday"
    elif 0 < delta < 7:
        day = _fmt(dt, "%A")
    else:
        day = _fmt(dt, "%b %-d")
    return (f"<b>{GLib.markup_escape_text(day)}</b>  "
            f"{GLib.markup_escape_text(_fmt(dt, '%H:%M'))}")


def relative_stamp(value: str | None) -> str:
    """Short stamp for the right edge of a conversation row."""
    dt = _parse(value)
    if dt is None:
        return ""
    delta = _days_ago(dt)
    if delta == 0:
        return _fmt(dt, "%H:%M")
    if delta == 1:
        return "Yesterday"
    if 0 < delta < 7:
        return _fmt(dt, "%a")
    return _fmt(dt, "%b %-d")


def event_ts(ev: dict) -> str:
    """Best timestamp string for an event dict (message timestamp or seen_at)."""
    return ev.get("timestamp") or ev.get("seen_at") or ""


def same_group(prev_ts: str | None, ts: str, *, gap_seconds: int = 15 * 60) -> bool:
    """True when `ts` belongs under the same day rule as `prev_ts`.

    A new rule goes in when the calendar day changes or more than
    `gap_seconds` has passed, which is what makes a long thread readable
    without a timestamp on every bubble.
    """
    a, b = _parse(prev_ts), _parse(ts)
    if a is None or b is None:
        return False
    if a.date() != b.date():
        return False
    return abs((b - a).total_seconds()) <= gap_seconds


_PHONE_RE = __import__("re").compile(r"^\+?[\d\s()\-.]{7,}$")


def resolve_recipient(contacts, raw: str) -> str | None:
    """Shared by the dialer and the new-conversation composer.

    A phone number passes through; letters translate as a vanity number
    when a digit is present; otherwise it's a contact-name lookup.
    Returns None when nothing matches.
    """
    from iphonebridge.events import vanity_to_digits
    if _PHONE_RE.match(raw):
        return raw
    if any(ch.isdigit() for ch in raw):
        translated = vanity_to_digits(raw)
        if _PHONE_RE.match(translated):
            return translated
    matches = contacts.find_by_name(raw)
    if not matches:
        return None
    return matches[0][1]


def pin_popover_height(listbox, scroll, cap: int = 320) -> None:
    """Size a suggestion popover to its content on every rebuild.

    GTK popovers grow with content but don't renegotiate smaller when it
    shrinks, so a narrowed match list leaves dead space. Pinning the
    ScrolledWindow's min and max content height to the list's measured
    natural height (capped) forces the popover to follow in both
    directions; past the cap it scrolls.
    """
    from gi.repository import Gtk
    _, nat, _, _ = listbox.measure(Gtk.Orientation.VERTICAL, -1)
    h = min(nat, cap)
    scroll.set_min_content_height(h)
    scroll.set_max_content_height(h)
    # The vertical scrollbar imposes its own minimum height (~58px) on
    # the scrolled window even when unused, leaving blank space under a
    # short list — only enable it when the content actually overflows.
    scroll.set_policy(Gtk.PolicyType.NEVER,
                      Gtk.PolicyType.AUTOMATIC if nat > cap
                      else Gtk.PolicyType.NEVER)
    # A mapped popover never applies a shrink on its own (a fresh map
    # does, which is why programmatic set_text — delete+insert, closing
    # and reopening the popover per step — masked this). present() asks
    # the popover to renegotiate its surface size in place.
    popover = scroll.get_ancestor(Gtk.Popover)
    if popover is not None and popover.get_visible():
        popover.present()


_PREFERRED_FONTS = ("SF Pro Text", "SF Pro Display", "Inter", "Adwaita Sans",
                    "Cantarell")


def has_preferred_font() -> bool:
    """True when one of the Apple-adjacent UI faces is installed.

    style.css only applies its font stack behind the `ib-font` class,
    gated on this: setting font-family unconditionally would swap the
    desktop's chosen UI font for fontconfig's generic sans on machines
    that have none of these installed.
    """
    from gi.repository import PangoCairo
    try:
        families = PangoCairo.FontMap.get_default().list_families()
    except Exception:
        return False
    installed = {f.get_name() for f in families}
    return any(name in installed for name in _PREFERRED_FONTS)
