"""Conversation state, with no toolkit dependency.

Everything here is plain Python: which conversation an event belongs to,
how messages are ordered, what counts as unread, and what a delete leaves
behind. Keeping it out of the widget layer means it can be tested without
a display, and it is what a second front end would reuse rather than
reimplement.

The subtle parts are load-bearing and each has a test:

* threads are keyed on the *normalised* number, because a sent message
  carries the recipient as typed into the composer while an incoming one
  carries whatever the phone reports;
* ordering compares parsed instants, never the raw strings, because a log
  can hold both UTC and local-offset entries;
* a message's key derives from timestamp-or-seen_at so it matches the
  daemon's `event_key`, or delete and mark-read address messages the
  daemon cannot find.
"""
from __future__ import annotations

from html import escape

from iphonebridge.events import message_key
from iphonebridge.ui.util import event_ts, ts_key


def fold_number(raw: str | None) -> str | None:
    """The comparable form of a phone number, or None if it isn't one.

    Exactly one country code is removed, and only where its presence is
    provable from the string itself: an explicit leading "+1" on eleven
    digits. NANP national numbers are exactly ten digits, so "+1" followed
    by ten more can only be a country code. That is the case that splits a
    conversation with yourself, where one side is E.164 and the other is
    the ten digits the composer had.

    Nothing else is folded, and the reason is that a wrong merge is
    dangerous rather than untidy: two numbers in one thread means a reply
    can leave for the wrong person. Comparing trailing digits would do
    that — a bare leading "1" also begins an eleven-digit Chinese mobile,
    and "+52 1 628 555 0138" ends in the same ten digits as the NANP
    number "628 555 0138". Neither is folded here. The cost is that some
    international pairs stay in two threads until an event links them by
    contact or address, which is a visible annoyance rather than a message
    sent to a stranger.
    """
    text = (raw or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 7:
        return None
    if text.startswith("+") and len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def identities(ev: dict) -> list[str]:
    """Everything in this event that identifies the other party.

    An event carries some subset, and no single one is present on every
    event or stable across them. Sending to your own number is the case
    that proves it: the outgoing copy is labelled from your contact card
    and the incoming copy comes back labelled "My Number", with one side
    carrying a country code and the other not. Neither the label nor the
    raw number groups those two into one conversation; the union of the
    identities does.

    Ordered most stable first, so the first entry is what a new thread
    gets keyed by.
    """
    out = []
    # The raw field first, and only it when present: it keeps the "+"
    # that proves a country code, and folding it already lands E.164 and
    # national spellings on the same value. Registering the normalised
    # field as well would mean an event whose two number fields disagree
    # could staple two unrelated conversations together, and a thread
    # holding two people's numbers is a reply going to the wrong person.
    number = fold_number(ev.get("sender_phone") or ev.get("sender_phone_norm"))
    if number:
        out.append(f"tel:{number}")
    email = (ev.get("sender_email") or "").strip().lower()
    if email:
        out.append(f"mailto:{email}")
    name = (ev.get("contact_name") or "").strip()
    if name:
        out.append(f"name:{name}")
    return out


def thread_key(ev: dict) -> str:
    """The identity a *new* thread for this event would be keyed by.

    Only meaningful for an event on its own. Which conversation an event
    actually joins is `ThreadStore.ingest`'s answer, since that can see
    the threads already present and merge on any shared identity.
    """
    ids = identities(ev)
    return ids[0] if ids else "(unknown)"


def thread_name(ev: dict) -> str:
    """What to show for that conversation — the most readable form we
    have, which is not the one it is grouped by."""
    return (ev.get("contact_name") or ev.get("sender_phone")
            or ev.get("sender_email") or ev.get("sender_phone_norm")
            or "(unknown)")


def message_from_event(ev: dict, *, outgoing: bool) -> dict:
    """One message, as the view wants it."""
    stamp = event_ts(ev)
    return {
        "body": ev.get("body") or "",
        # `ts` is for display, `at` for ordering. Current logs are UTC
        # throughout and would sort as text, but entries written before
        # that carry a local offset, and mixing the two interleaves
        # replies into the middle of a thread.
        "ts": stamp,
        "at": ts_key(stamp),
        "outgoing": outgoing,
        # Outgoing messages are read by definition; incoming carry
        # whatever the log says, which the daemon keeps in step with the
        # phone.
        "read": bool(outgoing or ev.get("is_read")),
        # `stamp` is timestamp-or-seen_at, matching event_key in the
        # daemon: the two must agree or delete and mark-read address
        # messages the daemon cannot find.
        "key": message_key(stamp,
                           ev.get("sender_phone") or ev.get("sender_email"),
                           ev.get("body")),
        # Who this message was with, as the event spelled it. Kept per
        # message so "which number is this conversation actually with"
        # is answerable from the thread's contents rather than from a
        # field that was set once when the thread was created.
        "addr": ev.get("sender_phone") or ev.get("sender_email") or "",
    }


def _looks_like_digits(name: str | None) -> bool:
    """True for a label that is really just a phone number."""
    stripped = "".join(ch for ch in (name or "") if not ch.isspace())
    return bool(stripped) and all(
        ch.isdigit() or ch in "+()-." for ch in stripped)


def _is_email(value: str | None) -> bool:
    return "@" in (value or "")


def _better_phone(current: str | None, candidate: str | None) -> bool:
    """True when `candidate` is the form worth sending to.

    Anything beats nothing or an email address, and a fully qualified
    number beats a national one: the same conversation reaches us both
    ways, and "+15551234567" is the spelling that works from anywhere.
    """
    if not candidate:
        return False
    if not current or _is_email(current):
        return True
    return candidate.strip().startswith("+") and not current.strip().startswith("+")


#: Codepoint ranges that count as emoji for the purposes below. Not a
#: complete Unicode emoji definition and does not need to be: the question
#: is only "is this message nothing but a couple of pictures", and anything
#: it misses simply renders as ordinary text.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # the pictographic planes
    (0x2600, 0x27BF),     # misc symbols and dingbats
    (0x2B00, 0x2BFF),     # arrows and stars
    (0x1F1E6, 0x1F1FF),   # regional indicators (flags)
)
#: Joiners and modifiers that glue a sequence together without being a
#: picture of their own — skin tones, the zero-width joiner, the
#: variation selectors.
_EMOJI_GLUE = frozenset(
    [0x200D, 0xFE0E, 0xFE0F] + list(range(0x1F3FB, 0x1F400))
)


def emoji_only(body: str | None, limit: int = 3) -> bool:
    """True when a message is nothing but a few emoji.

    Messages draws those large and without a bubble, which is the one
    place the picture is the message rather than decoration on it. Capped,
    because a wall of emoji is a paragraph and should be set like one.
    """
    text = (body or "").strip()
    if not text:
        return False
    pictures = 0
    for ch in text:
        cp = ord(ch)
        if ch.isspace() or cp in _EMOJI_GLUE:
            continue
        if any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES):
            pictures += 1
            continue
        return False
    return 0 < pictures <= limit


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return cp in _EMOJI_GLUE or any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def emoji_markup(body: str | None, point_size: float) -> str:
    """`body` as Qt rich text, with its emoji set larger than the words.

    Colour emoji are drawn at the text size, and at a size comfortable for
    reading a sentence they come out too small to make out. Qt honours an
    absolute font-size on a rich-text run — percentages it ignores — so
    each run of emoji carries its own, and the sentence around it keeps
    the size the reader chose.

    Returns escaped text with no markup at all when there is nothing to
    enlarge, which is almost every message.
    """
    text = body or ""
    if not any(_is_emoji(ch) for ch in text):
        return escape(text, quote=False).replace("\n", "<br>")

    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            out.append(f'<span style="font-size:{point_size:.1f}pt">'
                       + escape("".join(run), quote=False) + "</span>")
            run.clear()

    for ch in text:
        if _is_emoji(ch):
            run.append(ch)
        else:
            flush()
            out.append("<br>" if ch == "\n" else escape(ch, quote=False))
    flush()
    return "".join(out)


def unread_keys(thread: dict | None) -> list[str]:
    """Keys of the incoming messages in `thread` still marked unread."""
    if not thread:
        return []
    return [m["key"] for m in thread["messages"]
            if not m["read"] and not m["outgoing"] and m.get("key")]


class ThreadStore:
    """Every conversation the view knows about."""

    def __init__(self) -> None:
        self.threads: dict[str, dict] = {}
        # identity -> the thread it belongs to. One conversation usually
        # answers to several: a number, an Apple-ID email, a contact label.
        self._owner: dict[str, str] = {}
        # Labels found to describe more than one party. Once a name is in
        # here it never links anything again — see _claim.
        self._ambiguous: set[str] = set()

    # ---- reading --------------------------------------------------------

    def get(self, key: str) -> dict | None:
        return self.threads.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self.threads

    def ordered(self) -> list[dict]:
        """Threads, newest first."""
        return sorted(self.threads.values(),
                      key=lambda t: t["last_at"], reverse=True)

    def messages(self, key: str) -> list[dict]:
        """A thread's messages, oldest first."""
        thread = self.threads.get(key)
        if thread is None:
            return []
        return sorted(thread["messages"], key=lambda m: m["at"])

    def preview(self, thread: dict) -> str:
        """The line shown under a conversation's name."""
        msgs = thread["messages"]
        if not msgs:
            return ""
        return max(msgs, key=lambda m: m["at"])["body"].replace("\n", " ")

    # ---- writing --------------------------------------------------------

    def _numbers_of(self, key: str) -> set[str]:
        """Every distinct number registered to a thread."""
        return {i for i, owner in self._owner.items()
                if owner == key and i.startswith("tel:")}

    def _claim(self, ev: dict) -> str:
        """The thread this event belongs to, creating or merging as needed.

        Addresses and labels are not equally trustworthy, and treating
        them as though they were is how a message reaches the wrong
        person. A number or an Apple ID belongs to exactly one party, so
        matching on one is proof. A contact label is not: two people can
        both be "John Smith", and merging on that alone would put them in
        one thread whose reply target is whichever of them wrote last.

        So a label only links threads it does not contradict. The moment
        one is seen against a second number it is marked ambiguous and
        stops linking anything, permanently — including the pairing it had
        already made, which is left alone but never extended.

        The invariant this maintains, and that `_absorb` re-checks, is
        that a thread never holds two different numbers.
        """
        ids = identities(ev) or ["(unknown)"]
        numbers = {i for i in ids if i.startswith("tel:")}

        owners: list[str] = []
        for identity in ids:
            by_label = identity.startswith("name:")
            if by_label and identity in self._ambiguous:
                continue
            owner = self._owner.get(identity)
            if owner is None or owner in owners:
                continue
            if by_label and len(numbers | self._numbers_of(owner)) > 1:
                # Same label, a different number: two different people.
                self._ambiguous.add(identity)
                self._owner.pop(identity, None)
                continue
            owners.append(owner)
            numbers |= self._numbers_of(owner)

        key = owners[0] if owners else ids[0]
        for other in owners[1:]:
            self._absorb(other, key)
        for identity in ids:
            if identity not in self._ambiguous:
                self._owner[identity] = key
        return key

    def _absorb(self, src: str, dst: str) -> None:
        """Fold thread `src` into `dst`. Used when an event proves that two
        threads were always one conversation."""
        if src == dst or src not in self.threads or dst not in self.threads:
            return
        if len(self._numbers_of(src) | self._numbers_of(dst)) > 1:
            # Belt and braces: never let two numbers share a thread, no
            # matter which path asked for the merge.
            return
        gone = self.threads.pop(src)
        keep = self.threads[dst]
        keep["messages"].extend(gone["messages"])
        if gone["last_at"] > keep["last_at"]:
            keep["last_at"], keep["last_ts"] = gone["last_at"], gone["last_ts"]
        # Prefer a label a person would recognise over bare digits.
        if _looks_like_digits(keep["name"]) and not _looks_like_digits(gone["name"]):
            keep["name"] = gone["name"]
        if _better_phone(keep.get("phone"), gone.get("phone")):
            keep["phone"] = gone["phone"]
        for identity, owner in self._owner.items():
            if owner == src:
                self._owner[identity] = dst

    def ingest(self, ev: dict, *, outgoing: bool) -> tuple[str, dict]:
        """File an event. Returns the thread key and the new message."""
        key = self._claim(ev)
        thread = self.threads.get(key)
        if thread is None:
            thread = {
                "key": key,
                "name": thread_name(ev),
                "phone": (ev.get("sender_phone") or ev.get("sender_phone_norm")
                          or ev.get("sender_email") or key),
                "messages": [],
                "last_ts": "",
                "last_at": ts_key(None),
            }
            self.threads[key] = thread
        else:
            # A later event can carry a better label or a dialable number
            # than the one the thread was created with.
            name = thread_name(ev)
            if _looks_like_digits(thread["name"]) and not _looks_like_digits(name):
                thread["name"] = name
            if _better_phone(thread.get("phone"), ev.get("sender_phone")):
                thread["phone"] = ev["sender_phone"]
        msg = message_from_event(ev, outgoing=outgoing)
        thread["messages"].append(msg)
        # Newest message wins the thread's sort key and preview even if
        # events arrived out of chronological order, as a seeded history
        # written newest-first does.
        if msg["at"] >= thread["last_at"]:
            thread["last_at"] = msg["at"]
            thread["last_ts"] = msg["ts"]
            # A reply goes to whoever this conversation most recently
            # addressed, not to whatever spelling it happened to be
            # created with. Anything else risks answering the wrong
            # number in a thread that has seen more than one.
            target = ev.get("sender_phone") or ev.get("sender_email")
            if target:
                thread["phone"] = target
        return key, msg

    def mark_thread_read(self, key: str) -> list[str]:
        """Mark a whole thread read. Returns the keys that were unread."""
        thread = self.threads.get(key)
        keys = unread_keys(thread)
        if not keys:
            return []
        for msg in thread["messages"]:
            msg["read"] = True
        return keys

    def mark_read(self, keys) -> bool:
        """Mark specific messages read. True if anything changed."""
        wanted = set(keys)
        if not wanted:
            return False
        touched = False
        for thread in self.threads.values():
            for msg in thread["messages"]:
                if not msg["read"] and msg.get("key") in wanted:
                    msg["read"] = True
                    touched = True
        return touched

    def message_keys(self, key: str) -> list[str]:
        """Every addressable message key in a thread."""
        thread = self.threads.get(key)
        if thread is None:
            return []
        return [m["key"] for m in thread["messages"] if m.get("key")]

    def _forget(self, key: str) -> None:
        """Drop a thread's identities. The ambiguity record is deliberately
        kept: a label that proved to describe two people still does."""
        for identity in [i for i, o in self._owner.items() if o == key]:
            del self._owner[identity]

    def remove(self, keys) -> set[str]:
        """Drop messages by key. Returns the threads that became empty."""
        gone = set(keys)
        emptied: set[str] = set()
        for key, thread in list(self.threads.items()):
            thread["messages"] = [m for m in thread["messages"]
                                  if m.get("key") not in gone]
            if not thread["messages"]:
                del self.threads[key]
                self._forget(key)
                emptied.add(key)
            else:
                newest = max(thread["messages"], key=lambda m: m["at"])
                thread["last_at"] = newest["at"]
                thread["last_ts"] = newest["ts"]
        return emptied
