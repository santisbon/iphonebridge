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

from iphonebridge.events import message_key
from iphonebridge.ui.util import event_ts, ts_key


def thread_key(ev: dict) -> str:
    """Which conversation an event belongs to.

    Grouped on the normalised number rather than the raw one: "+1 (555)
    123-4567" and "+15551234567" are one person, and keying on the raw
    string put them in two threads.
    """
    return (ev.get("contact_name") or ev.get("sender_phone_norm")
            or ev.get("sender_phone") or ev.get("sender_email")
            or "(unknown)")


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
    }


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

    def ingest(self, ev: dict, *, outgoing: bool) -> tuple[str, dict]:
        """File an event. Returns the thread key and the new message."""
        key = thread_key(ev)
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
        msg = message_from_event(ev, outgoing=outgoing)
        thread["messages"].append(msg)
        # Newest message wins the thread's sort key and preview even if
        # events arrived out of chronological order, as a seeded history
        # written newest-first does.
        if msg["at"] >= thread["last_at"]:
            thread["last_at"] = msg["at"]
            thread["last_ts"] = msg["ts"]
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

    def remove(self, keys) -> set[str]:
        """Drop messages by key. Returns the threads that became empty."""
        gone = set(keys)
        emptied: set[str] = set()
        for key, thread in list(self.threads.items()):
            thread["messages"] = [m for m in thread["messages"]
                                  if m.get("key") not in gone]
            if not thread["messages"]:
                del self.threads[key]
                emptied.add(key)
            else:
                newest = max(thread["messages"], key=lambda m: m["at"])
                thread["last_at"] = newest["at"]
                thread["last_ts"] = newest["ts"]
        return emptied
