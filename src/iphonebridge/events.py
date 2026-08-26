"""Normalized event types emitted by the OBEX layer.

The iPhone's MAP server speaks bMessages and proprietary metadata;
the rest of the daemon shouldn't have to care. Everything upstream
sees these simple dataclasses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

# ---- helpers ------------------------------------------------------------

_PHONE_KEEP = re.compile(r"\D")

# The MAP folder listing truncates message text (measured at ~125 chars
# on iOS 26.6.1) while a bMessage download carries it in full, so the two
# acquisition paths report different bodies for the same message. Key on
# a prefix short enough to survive that cut but long enough to keep
# distinct messages apart.
_KEY_BODY_CHARS = 40


def _as_instant(value) -> datetime | None:
    """A datetime or ISO string as an aware datetime, or None."""
    if not value:
        return None
    if hasattr(value, "isoformat"):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo is not None else dt.astimezone()


#: Same marker bmessage.py strips. Applied here too so keys written before
#: that fix, and the tombstones holding them, still resolve to one message.
_ADDR_SUFFIX_RE = re.compile(r"\s*\([^()]*\)\s*$")


def _key_sender(sender: str | None) -> str:
    """Sender component of a key: one person, one spelling.

    A number reaches us formatted differently depending on where it came
    from — as typed into the composer for a sent message, as the phone
    reports it for an incoming one, as the folder listing spells it for a
    swept one. Reducing anything phone-like to digits makes those one
    identity, the same way the UI groups conversations.

    Note this does not fold country codes: "+15551234567" and
    "5551234567" still differ, because deciding they are the same number
    needs a region that MAP does not give us.
    """
    text = _ADDR_SUFFIX_RE.sub("", (sender or "").strip()).strip()
    if text and "@" not in text:
        digits = normalize_phone(text)
        if digits:
            return digits
    return text.lower()


def _key_ts(timestamp) -> str:
    """The timestamp component of a message key, always in UTC.

    Accepts a datetime or an ISO string, because keys get built both from
    live events and by re-reading the log. Normalising here means a key
    identifies an instant rather than a spelling of one, so entries
    written before the log moved to UTC still resolve to the same key as
    the ones written after. Anything unparseable is passed through
    verbatim: still stable, just not comparable.
    """
    if not timestamp:
        return ""
    if hasattr(timestamp, "isoformat"):
        dt = timestamp
    else:
        try:
            dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return str(timestamp)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat()


def message_key(timestamp, sender: str | None, body: str | None) -> str:
    """Stable identity for a message, independent of its MAP handle.

    Handles are only stable while the iPhone's message set is: deleting
    one message renumbers the rest (measured — zero of eleven handles
    survived a single delete), so a handle cannot say "already seen"
    across that. Timestamp, sender, and the start of the body can.
    """
    head = " ".join((body or "").split())[:_KEY_BODY_CHARS]
    return "\x1f".join((_key_ts(timestamp), _key_sender(sender), head))


def event_key(ev: dict) -> str:
    """Identity of a logged or serialized message event.

    The timestamp falls back to seen_at, and that fallback is the whole
    point. A live MNS push is exported by BlueZ with no Timestamp, so
    without it the key collapses to (sender, first 40 chars of body) and
    two different messages become one. Confirmation codes are the worst
    case: everything but the trailing code is identical, and the code sits
    past the prefix — so every code from a sender keyed the same, the
    first was delivered, and every one after it was silently dropped.

    It is also the rule the UI already uses for ordering and display, so
    keys and timestamps now agree on what identifies a message.
    """
    return message_key(
        ev.get("timestamp") or ev.get("seen_at"),
        ev.get("sender_phone") or ev.get("sender_email"),
        ev.get("body"))


def normalize_key(key: str) -> str:
    """Re-spell a stored key's timestamp in UTC.

    Tombstones written before the log moved to UTC carry a local-offset
    timestamp in their first field. Normalising them on read maps them
    onto the current key space, so a deleted message stays deleted across
    the change without rewriting deleted-keys.txt.
    """
    parts = key.split("\x1f")
    if len(parts) != 3:
        return key
    return "\x1f".join((_key_ts(parts[0]), _key_sender(parts[1]), parts[2]))


def deleted_keys(path) -> set[str]:
    """Keys the user deleted from local history.

    Seeds the same guard as logged_sms_keys so a deleted message is not
    re-added by the startup inbox sweep while it is still on the phone.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return {normalize_key(line.rstrip("\n"))
                    for line in f if line.strip()}
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
        if (e.get("kind") in ("sms_received", "sms_sent")
                and event_key(e) in keys):
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
                keys.add(event_key(e))
    except OSError:
        pass
    return keys


#: How far apart a push and a listing may describe the same message. The
#: gap is MNS delivery latency, measured at ~2s; the margin is for a slow
#: link, and stays far below any plausible gap between two genuine sends
#: of identical text.
_PUSH_WINDOW = timedelta(seconds=120)


def _key_parts(key: str) -> tuple[str, str, str]:
    parts = key.split("\x1f")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else (key, "", "")


class SeenMessages(set):
    """Dedupe guard shared by the MNS listener and the inbox sweep.

    One message reaches the log by two routes carrying different detail.
    An MNS push is announced as a Message1 with Status="notification",
    which BlueZ exports with no Timestamp property, so its key holds an
    empty timestamp. The same message in a folder listing arrives with
    the real send time. Their exact keys differ, which is what let the
    startup sweep re-log everything already pushed live.

    Exact keys still decide whenever the two sides agree on what they
    know. When only one side has a timestamp, a match on sender plus body
    prefix within `_PUSH_WINDOW` counts as the same message, compared
    against the push's arrival time. A matched entry is consumed, so two
    genuinely identical messages still pair off one for one rather than
    collapsing into one.
    """

    def __init__(self, keys=()) -> None:
        super().__init__()
        self._timed: dict[tuple[str, str], list[datetime]] = {}
        self._untimed: dict[tuple[str, str], list[datetime]] = {}
        self.update(keys)

    # ---- population ----------------------------------------------------

    def add(self, key: str) -> None:
        self.note(key)

    def update(self, keys) -> None:
        for k in keys:
            self.note(k)

    def note(self, key: str, arrival=None, *, has_timestamp=None) -> None:
        """Record a key, plus the wall-clock time it reached us.

        `has_timestamp` says whether the message carried a MAP timestamp
        of its own. It has to be passed rather than read off the key,
        because a key's timestamp now falls back to seen_at and so is
        never empty. That distinction is what lets a push pair with its
        listing copy without two pushes pairing with each other.

        Left as None it is inferred from the key, which is right for
        tombstones: deleted-keys.txt stores keys alone.
        """
        super().add(key)
        ts, sender, head = _key_parts(key)
        instant = _as_instant(ts) or _as_instant(arrival)
        if instant is None:
            return
        if has_timestamp is None:
            has_timestamp = bool(ts)
        index = self._timed if has_timestamp else self._untimed
        index.setdefault((sender, head), []).append((instant, key))

    # ---- lookup --------------------------------------------------------

    def matches(self, key: str, arrival=None, *, has_timestamp=None) -> bool:
        """True when this message is already accounted for."""
        return self.find(key, arrival, has_timestamp=has_timestamp) is not None

    def find(self, key: str, arrival=None, *, has_timestamp=None):
        """The key this message is already filed under, or None.

        Returning the key rather than a bool matters for the inbox sweep:
        a listing entry is the only thing that knows a message's object
        path, and read-state can only be written back through that path.
        Filing the path under the sweep's own key would leave it
        unreachable, because the log holds the key the message was first
        logged with.
        """
        if key in self:
            return key
        ts, sender, head = _key_parts(key)
        instant = _as_instant(ts) or _as_instant(arrival)
        if instant is None:
            return None
        if has_timestamp is None:
            has_timestamp = bool(ts)
        # A message that carried a MAP timestamp can only pair with one
        # that did not, and the other way round. Two pushes are never
        # paired, which is what keeps a second confirmation code from
        # being mistaken for a re-sighting of the first.
        bucket = (self._untimed if has_timestamp
                  else self._timed).get((sender, head))
        if not bucket:
            return None
        for i, (other, matched_key) in enumerate(bucket):
            if abs(other - instant) <= _PUSH_WINDOW:
                del bucket[i]
                # Record the key as well, so a second sighting of this
                # same message is an exact hit. One listing is announced
                # twice in a single startup: once to the sweep that asked
                # for it, and again to the MNS listener, because
                # ListMessages makes obexd export Message1 objects and the
                # resulting InterfacesAdded signals are only delivered
                # once the sweep returns. Without this the second pass
                # finds the loose entry it needed already consumed here,
                # and logs the message a second time.
                super().add(key)
                return matched_key
        return None


def drop_ancs_by_seen_at(path, eids: set[str]) -> int:
    """Rewrite the event log without the given notifications. Returns the
    count removed.

    Notifications are addressed by their `seen_at` stamp rather than a
    content key: the ANCS uid is only unique within one BLE connection,
    so it cannot name a logged event, while `seen_at` is written once at
    arrival and never changes. Same atomic carry-over rewrite as
    drop_events_by_key.
    """
    import json
    import os
    if not eids:
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
        if e.get("kind") == "ancs_notification" and e.get("seen_at") in eids:
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


def mark_logged_read(path, keys) -> int:
    """Set is_read on logged messages. Returns how many changed.

    Read-state has to live in the log, not be read back from BlueZ: the
    Message1 objects it comes from are transient, and obexd drops them
    whenever the OBEX session restarts, taking their Read property with
    them. Same atomic rewrite as drop_events_by_key, since this is the
    other place that touches an otherwise append-only file.
    """
    import json
    import os
    keys = set(keys)
    if not keys:
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0
    out, changed = [], 0
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        if (e.get("kind") == "sms_received" and not e.get("is_read")
                and event_key(e) in keys):
            e["is_read"] = True
            out.append(json.dumps(e) + "\n")
            changed += 1
        else:
            out.append(line)
    if not changed:
        return 0
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(out)
    with open(path, encoding="utf-8") as f:
        now = f.readlines()
    if len(now) > len(lines):          # appended mid-rewrite
        with open(tmp, "a", encoding="utf-8") as f:
            f.writelines(now[len(lines):])
    os.replace(tmp, path)
    return changed


@dataclass(slots=True)
class SeenEvent:
    """A read-state change, addressed by message key.

    Deliberately not an SmsEvent: this is not a message and must never
    reach the JSONL sink, or every read would append a line to a log whose
    other entries are messages.
    """

    keys: tuple[str, ...]
    kind: str = "sms_seen"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "keys": list(self.keys)}


def logged_messages(path) -> SeenMessages:
    """Seed a SeenMessages from every sms_received already in the log.

    Richer than reading keys alone: a pushed message has no timestamp, so
    only its seen_at can place it against a listing entry.
    """
    import json
    seen = SeenMessages()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("kind") != "sms_received":
                    continue
                seen.note(
                    event_key(e), e.get("seen_at"),
                    has_timestamp=bool(e.get("timestamp")))
    except OSError:
        pass
    return seen


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


_MAP_TZ_RE = re.compile(r"^([+-])(\d{2})(\d{2})$")


def parse_map_timestamp(ts: str | None) -> datetime | None:
    """Parse MAP's timestamp format into UTC.

    The format is YYYYMMDDTHHMMSS, optionally followed by "Z" or a
    ±HHMM offset. iOS sends the bare form, which MAP defines as the
    phone's local time; an explicit suffix is honoured when present
    rather than discarded, since that is the only case where the phone's
    zone is actually knowable.
    """
    if not ts:
        return None
    text = str(ts).strip()
    try:
        dt = datetime.strptime(text[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    suffix = text[15:]
    if suffix.upper() == "Z":
        dt = dt.replace(tzinfo=timezone.utc)
    elif (m := _MAP_TZ_RE.match(suffix)):
        offset = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
        dt = dt.replace(tzinfo=timezone(offset if m.group(1) == "+"
                                        else -offset))
    else:
        # Bare: assume the phone shares this computer's zone. Wrong while
        # the two are in different places, and unknowable from MAP alone.
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


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
    # UTC, like every other stamp written to the log. A local offset would
    # be unambiguous to a parser but useless as storage: carry the laptop
    # across a timezone mid-conversation and the offset changes under you,
    # so lexical order stops matching chronological order within a single
    # file. In UTC every stamp shares one offset and sorting the raw
    # strings is always correct.
    #
    # This field matters more than it looks: a live MNS-pushed message is
    # exported by BlueZ as a Message1 with Status="notification", whose
    # property set carries no Timestamp, so `timestamp` above is None for
    # those and consumers fall back to this.
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
        timestamp=datetime.now(timezone.utc),
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
