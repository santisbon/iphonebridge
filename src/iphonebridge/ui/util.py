"""Small shared helpers for the UI pages."""
from __future__ import annotations

from datetime import datetime


def format_ts(value: str | None, *, fmt: str = "%b %-d · %H:%M") -> str:
    """Format an ISO timestamp from an event dict, in local time."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return str(value)[:16]
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    try:
        return dt.strftime(fmt)
    except ValueError:  # %-d is glibc-only; fall back if unsupported
        return dt.strftime("%b %d · %H:%M")


def event_ts(ev: dict) -> str:
    """Best timestamp string for an event dict (message timestamp or seen_at)."""
    return ev.get("timestamp") or ev.get("seen_at") or ""


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
    return "+" + matches[0][1]
