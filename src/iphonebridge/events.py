"""Normalized event types emitted by the OBEX layer.

The iPhone's MAP server speaks bMessages and proprietary metadata;
the rest of the daemon shouldn't have to care. Everything upstream
sees these simple dataclasses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# ---- helpers ------------------------------------------------------------

_PHONE_KEEP = re.compile(r"\D")

# The MAP folder listing truncates message text (measured at ~125 chars
# on iOS 26.6.1) while a bMessage download carries it in full, so the two
# acquisition paths report different bodies for the same message. Key on
# a prefix short enough to survive that cut but long enough to keep
# distinct messages apart.
_KEY_BODY_CHARS = 40


def message_key(timestamp, sender: str | None, body: str | None) -> str:
    """Stable identity for a message, independent of its MAP handle.

    Handles are only stable while the iPhone's message set is: deleting
    one message renumbers the rest (measured — zero of eleven handles
    survived a single delete), so a handle cannot say "already seen"
    across that. Timestamp, sender, and the start of the body can.
    """
    ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or "")
    head = " ".join((body or "").split())[:_KEY_BODY_CHARS]
    return "\x1f".join((ts, (sender or "").strip().lower(), head))


def deleted_keys(path) -> set[str]:
    """Keys the user deleted from local history.

    Seeds the same guard as logged_sms_keys so a deleted message is not
    re-added by the startup inbox sweep while it is still on the phone.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return {line.rstrip("\n") for line in f if line.strip()}
    except OSError:
        return set()


def record_deleted_keys(path, keys) -> None:
    """Append tombstones. Idempotent; duplicates are harmless."""
    keys = [k for k in keys if k]
    if not keys:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k in keys:
            f.write(k + "\n")


def drop_events_by_key(path, keys: set[str]) -> int:
    """Rewrite the event log without the given messages. Returns the count
    removed.

    The log is append-only in normal operation, so this is the one place
    that rewrites it. Events appended while the rewrite runs are carried
    over, and the swap is atomic.
    """
    import json
    import os
    if not keys:
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0
    kept, removed = [], 0
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if e.get("kind") in ("sms_received", "sms_sent") and message_key(
                e.get("timestamp"),
                e.get("sender_phone") or e.get("sender_email"),
                e.get("body")) in keys:
            removed += 1
            continue
        kept.append(line)
    if not removed:
        return 0
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(kept)
    with open(path, encoding="utf-8") as f:
        now = f.readlines()
    if len(now) > len(lines):          # appended mid-rewrite
        with open(tmp, "a", encoding="utf-8") as f:
            f.writelines(now[len(lines):])
    os.replace(tmp, path)
    return removed


def logged_sms_keys(path) -> set[str]:
    """Identities of every sms_received event already in the JSONL log.

    Seeds the dedupe guard shared by the MNS listener and the startup
    inbox sweep: obexd re-announces the inbox after every restart, and
    the sweep lists it deliberately, so without this both would re-log
    (and the listener would re-notify) messages already in history.
    """
    import json
    keys: set[str] = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("kind") != "sms_received":
                    continue
                keys.add(message_key(
                    e.get("timestamp"),
                    e.get("sender_phone") or e.get("sender_email"),
                    e.get("body")))
    except OSError:
        pass
    return keys


_KEYPAD = {c: d for d, letters in {
    "2": "ABC", "3": "DEF", "4": "GHI", "5": "JKL",
    "6": "MNO", "7": "PQRS", "8": "TUV", "9": "WXYZ",
}.items() for c in letters}


def vanity_to_digits(raw: str) -> str:
    """Translate vanity-number letters to keypad digits (E.161).

    "1 (800) MYAPPLE" -> "1 (800) 6927753". Formatting characters pass
    through untouched; only A-Z map. Callers decide when to apply this —
    a bare word like a contact name must not be fed through it.
    """
    return "".join(_KEYPAD.get(ch.upper(), ch) for ch in raw)


def dialable(raw: str) -> str:
    """Reduce a number to what oFono's Dial accepts: digits, * and #, with
    at most a leading +. Formatting ("1 (800) 692-7753") is rejected by
    oFono as InvalidFormat, so it must be stripped before dialing.
    """
    kept = "".join(ch for ch in raw if ch.isdigit() or ch in "*#+")
    if kept.startswith("+"):
        return "+" + kept[1:].replace("+", "")
    return kept.replace("+", "")


def normalize_phone(raw: str | None) -> str | None:
    """Reduce a phone string to digits only (E.164-ish minus the +).

    "+1 (561) 235-1044" → "15551234567"
    "5612351044"        → "5612351044"
    "Mom"               → None  (looked like a name)
    """
    if not raw:
        return None
    digits = _PHONE_KEEP.sub("", raw)
    # 7+ digits is plausibly a phone number
    return digits if len(digits) >= 7 else None


def parse_map_timestamp(ts: str | None) -> datetime | None:
    """Parse MAP's timestamp format: '20260519T181423' or with timezone suffix."""
    if not ts:
        return None
    # MAP timestamps: YYYYMMDDTHHMMSS, optionally followed by a TZ offset
    base = ts[:15]
    try:
        dt = datetime.strptime(base, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    # MAP timestamps are local-time on the iPhone; we'll treat as local
    return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)


# ---- event types --------------------------------------------------------

EventKind = Literal["sms_received", "sms_seen", "sms_sent"]


@dataclass(slots=True)
class SmsEvent:
    """A single SMS message event from the iPhone via MAP."""

    kind: EventKind
    handle: str                 # BlueZ obex Message1 path tail, e.g. "message93446842893444124"
    sender_phone: str | None    # raw, as given by MAP
    sender_phone_norm: str | None  # digits-only, for contacts lookup
    contact_name: str | None    # resolved from contacts cache, may be None
    body: str | None            # MAP puts the SMS text in `Subject`
    timestamp: datetime | None
    is_read: bool
    raw_status: str | None
    raw_type: str | None
    # Full BlueZ obex DBus path to the Message1 object, so downstream
    # code (e.g. libnotify sink) can write back read-state.
    message_path: str | None = None
    # iMessage senders addressed by Apple ID arrive with an email, no phone.
    sender_email: str | None = None
    seen_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def display_sender(self) -> str:
        """Best name we have for the sender."""
        return (self.contact_name or self.sender_phone
                or self.sender_email or "(unknown)")

    def to_dict(self) -> dict:
        """Serializable form for JSONL log."""
        return {
            "kind": self.kind,
            "handle": self.handle,
            "sender_phone": self.sender_phone,
            "sender_phone_norm": self.sender_phone_norm,
            "sender_email": self.sender_email,
            "contact_name": self.contact_name,
            "body": self.body,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "is_read": self.is_read,
            "raw_status": self.raw_status,
            "raw_type": self.raw_type,
            "seen_at": self.seen_at.isoformat(),
        }


def sms_sent_event(
    recipient: str,
    body: str,
    *,
    contact_name: str | None = None,
    transfer_path: str = "",
) -> SmsEvent:
    """Build an SmsEvent for a message *we* just sent via MAP PushMessage.

    For a sent message the relevant party is the recipient, so the
    `sender_*` / `contact_name` fields carry the recipient — that keeps it
    in the same conversation thread as incoming messages from that person.
    """
    handle = (transfer_path.rsplit("/", 1)[-1] if transfer_path
              else f"sent-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}")
    return SmsEvent(
        kind="sms_sent",
        handle=handle,
        sender_phone=recipient,
        sender_phone_norm=normalize_phone(recipient),
        contact_name=contact_name,
        body=body,
        timestamp=datetime.now().astimezone(),
        is_read=True,
        raw_status="sent",
        raw_type="sms_sent",
        message_path=None,
    )


def sms_event_from_message1_props(
    handle: str, props: dict, contact_name: str | None = None,
) -> SmsEvent:
    """Construct an SmsEvent from BlueZ's org.bluez.obex.Message1 properties.

    See spike/RESULTS.md §3 — the SMS body comes from `Subject`.
    """
    sender_raw = props.get("Sender") or props.get("SenderAddress")
    sender_raw = str(sender_raw) if sender_raw is not None else None
    norm = normalize_phone(sender_raw)
    return SmsEvent(
        kind="sms_received",
        handle=handle,
        sender_phone=sender_raw,
        sender_phone_norm=norm,
        contact_name=contact_name,
        body=str(props.get("Subject", "")) or None,
        timestamp=parse_map_timestamp(props.get("Timestamp")),
        is_read=bool(props.get("Read", False)),
        raw_status=str(props.get("Status", "")) or None,
        raw_type=str(props.get("Type", "")) or None,
    )
