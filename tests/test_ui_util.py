"""Tests for the UI's toolkit-free layer — timestamp ordering and
formatting, conversation grouping, contact suggestions, and the QML
context contract.

None of this imports Qt, so it runs without a display and without PyQt6
installed, which is what CI has.
"""
from __future__ import annotations

import pathlib
import re
from typing import ClassVar

from iphonebridge.ui.util import event_ts, same_group, ts_key

# The daemon now writes UTC throughout, but entries logged before that
# carry a local offset, so both shapes turn up in one file and the UI has
# to order across them.
RECEIVED = "2026-08-25T14:30:00+00:00"
SENT_LATER = "2026-08-25T09:31:00-05:00"   # 14:31 UTC, one minute later


class TestTsKey:
    def test_orders_across_timezones(self):
        assert ts_key(RECEIVED) < ts_key(SENT_LATER)

    def test_raw_string_order_would_be_wrong(self):
        """Guards the actual bug: replies sorted to the top of a thread
        because "09:31-05:00" sorts before "14:30+00:00" as text."""
        assert SENT_LATER < RECEIVED           # what string sorting saw
        assert ts_key(SENT_LATER) > ts_key(RECEIVED)

    def test_same_instant_written_two_ways_is_equal(self):
        assert ts_key("2026-08-25T14:30:00+00:00") == \
               ts_key("2026-08-25T09:30:00-05:00")

    def test_missing_and_unparseable_sort_first(self):
        for bad in (None, "", "not a date"):
            assert ts_key(bad) < ts_key(RECEIVED)

    def test_naive_is_read_as_local(self):
        assert ts_key("2026-08-25T09:12:00").tzinfo is not None

    def test_results_are_mutually_comparable(self):
        stamps = [RECEIVED, SENT_LATER, "2026-08-25T09:12:00", None, ""]
        assert sorted(stamps, key=ts_key)[0] in (None, "")


class TestEventTs:
    def test_prefers_timestamp(self):
        ev = {"timestamp": SENT_LATER, "seen_at": RECEIVED}
        assert event_ts(ev) == SENT_LATER

    def test_falls_back_to_seen_at(self):
        assert event_ts({"seen_at": RECEIVED}) == RECEIVED

    def test_empty_when_neither(self):
        assert event_ts({}) == ""


class TestSameGroup:
    def test_close_together_shares_a_rule(self):
        assert same_group("2026-08-25T14:30:00+00:00",
                          "2026-08-25T14:40:00+00:00")

    def test_wide_gap_starts_a_new_rule(self):
        assert not same_group("2026-08-25T14:30:00+00:00",
                              "2026-08-25T16:00:00+00:00")

    def test_day_change_starts_a_new_rule(self):
        """Naive stamps, so this crosses midnight in whatever the local
        zone is. The rule follows the reader's calendar day, not UTC's:
        two stamps four minutes apart across midnight UTC can still be the
        same local day, and correctly share a rule."""
        assert not same_group("2026-08-25T23:58:00", "2026-08-26T00:02:00")

    def test_no_previous_starts_a_new_rule(self):
        assert not same_group(None, RECEIVED)

    def test_compares_across_timezones(self):
        """Same instant either side of the offset: one minute apart, so
        they belong under the same rule despite the text differing."""
        assert same_group(RECEIVED, SENT_LATER)


class TestThreadGrouping:
    """One person, two spellings of their number. A sent message carries
    the recipient as typed into the composer; an incoming one carries what
    the phone reports. Grouping on the raw string split them into two
    conversations."""

    SENT: ClassVar[dict] = {
        "kind": "sms_sent", "contact_name": None,
        "sender_phone": "+1 (555) 123-4567",
        "sender_phone_norm": "15551234567"}
    RECV: ClassVar[dict] = {
        "kind": "sms_received", "contact_name": None,
        "sender_phone": "+15551234567",
        "sender_phone_norm": "15551234567"}

    def test_both_spellings_land_in_one_thread(self):
        from iphonebridge.ui.model import thread_key
        assert thread_key(self.SENT) == thread_key(self.RECV)

    def test_a_resolved_contact_joins_the_same_thread(self):
        """A name resolving on one side only must not fork the thread."""
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        a, _ = store.ingest(self.SENT, outgoing=True)
        b, _ = store.ingest(dict(self.RECV, contact_name="Dana Whitfield"),
                            outgoing=False)
        assert a == b
        assert len(store.threads) == 1

    def test_different_numbers_stay_apart(self):
        from iphonebridge.ui.model import thread_key
        other = dict(self.RECV, sender_phone="+15559876543",
                     sender_phone_norm="15559876543")
        assert thread_key(self.SENT) != thread_key(other)

    def test_email_senders_still_group(self):
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        a = {"kind": "sms_received", "sender_email": "x@example.com"}
        k1, _ = store.ingest(a, outgoing=False)
        k2, _ = store.ingest(dict(a, sender_email="X@Example.com"),
                             outgoing=False)
        assert k1 == k2
        assert len(store.threads) == 1

    def test_the_displayed_name_keeps_the_readable_form(self):
        """Grouping by digits must not make the thread show bare digits."""
        from iphonebridge.ui.model import thread_name
        assert thread_name(self.SENT) == "+1 (555) 123-4567"
        assert thread_name(dict(self.RECV, contact_name="Dana")) == "Dana"


class TestMessagingYourself:
    """Texting your own number produced two conversations.

    The outgoing copy carries the number as the composer had it, with no
    country code, labelled from your own contact card. The copy that comes
    back carries E.164 and is labelled "My Number". Neither the label nor
    the exact digits match across the pair.
    """

    SENT: ClassVar[dict] = {
        "kind": "sms_sent", "contact_name": "Dana Whitfield",
        "sender_phone": "5551234567", "sender_phone_norm": "5551234567"}
    BACK: ClassVar[dict] = {
        "kind": "sms_received", "contact_name": "My Number",
        "sender_phone": "+15551234567", "sender_phone_norm": "15551234567"}

    def test_one_conversation_not_two(self):
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        sent, _ = store.ingest(self.SENT, outgoing=True)
        back, _ = store.ingest(self.BACK, outgoing=False)
        assert sent == back
        assert len(store.threads) == 1
        assert len(store.messages(sent)) == 2

    def test_the_country_code_alone_does_not_split_it(self):
        from iphonebridge.ui.model import fold_number
        assert fold_number("+15551234567") == fold_number("5551234567")
        assert fold_number("+1 (555) 123-4567") == fold_number("5551234567")

    def test_a_real_name_beats_a_label_of_digits(self):
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        bare = dict(self.SENT, contact_name=None)
        key, _ = store.ingest(bare, outgoing=True)
        store.ingest(self.SENT, outgoing=True)
        assert store.get(key)["name"] == "Dana Whitfield"

    def test_two_threads_merge_when_an_event_links_them(self):
        """The linking identity can arrive after both threads exist."""
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        by_email = {"kind": "sms_received", "sender_email": "d@example.com"}
        by_phone = {"kind": "sms_sent", "sender_phone": "5551234567",
                    "sender_phone_norm": "5551234567"}
        a, _ = store.ingest(by_email, outgoing=False)
        b, _ = store.ingest(by_phone, outgoing=True)
        assert a != b and len(store.threads) == 2
        linking = dict(by_phone, sender_email="d@example.com")
        merged, _ = store.ingest(linking, outgoing=True)
        assert len(store.threads) == 1
        assert len(store.messages(merged)) == 3

    def test_a_chinese_mobile_is_not_a_nanp_number(self):
        """11 digits starting with 1 is also a Chinese mobile. Folding a
        bare leading 1 would put two strangers in one thread."""
        from iphonebridge.ui.model import fold_number
        assert fold_number("13812345678") != fold_number("+13812345678")
        assert fold_number("13812345678") == "13812345678"

    def test_a_longer_country_code_is_not_stripped(self):
        """+52 1 628 555 0138 ends in the same ten digits as the NANP
        number 628 555 0138. Comparing trailing digits would merge them."""
        from iphonebridge.ui.model import fold_number
        assert fold_number("+5216285550138") != fold_number("+16285550138")
        assert fold_number("+5216285550138") != fold_number("6285550138")

    def test_two_strangers_never_share_a_thread(self):
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        a, _ = store.ingest({"kind": "sms_received",
                             "sender_phone": "+5216285550138"}, outgoing=False)
        b, _ = store.ingest({"kind": "sms_received",
                             "sender_phone": "6285550138"}, outgoing=False)
        assert a != b
        assert len(store.threads) == 2

    def test_a_mismatched_pair_of_number_fields_cannot_link_threads(self):
        """The normalised field is a fallback, never a second identity: an
        event whose two number fields disagree must not staple two
        conversations together."""
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        a, _ = store.ingest({"kind": "sms_received",
                             "sender_phone": "+15551234567"}, outgoing=False)
        b, _ = store.ingest({"kind": "sms_received",
                             "sender_phone": "+15559876543",
                             "sender_phone_norm": "15551234567"},
                            outgoing=False)
        assert a != b
        assert len(store.threads) == 2

    def test_the_reply_target_is_the_latest_counterpart(self):
        """Whoever the conversation most recently addressed is who a reply
        goes to, rather than whatever it was created with."""
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        key, _ = store.ingest(dict(self.SENT, seen_at="2026-01-01T00:00:00+00:00"),
                              outgoing=True)
        store.ingest(dict(self.BACK, seen_at="2026-01-01T01:00:00+00:00"),
                     outgoing=False)
        assert store.get(key)["phone"] == "+15551234567"

    def test_unrelated_numbers_still_do_not_merge(self):
        from iphonebridge.ui.model import ThreadStore
        store = ThreadStore()
        a, _ = store.ingest(self.SENT, outgoing=True)
        b, _ = store.ingest(dict(self.BACK, contact_name="Someone Else",
                                 sender_phone="+15559876543",
                                 sender_phone_norm="15559876543"),
                            outgoing=False)
        assert a != b
        assert len(store.threads) == 2


class TestTwoPeopleOneName:
    """Two contacts really can share a display name. Grouping on the label
    alone would put them in one thread whose reply target is whichever of
    them wrote last, which is a message sent to the wrong person."""

    JOHN_A: ClassVar[dict] = {
        "kind": "sms_received", "contact_name": "John Smith",
        "sender_phone": "+15551110001"}
    JOHN_B: ClassVar[dict] = {
        "kind": "sms_received", "contact_name": "John Smith",
        "sender_phone": "+15552220002"}

    def _store(self):
        from iphonebridge.ui.model import ThreadStore
        return ThreadStore()

    def test_they_get_separate_threads(self):
        store = self._store()
        a, _ = store.ingest(self.JOHN_A, outgoing=False)
        b, _ = store.ingest(self.JOHN_B, outgoing=False)
        assert a != b
        assert len(store.threads) == 2

    def test_each_reply_goes_to_the_right_number(self):
        store = self._store()
        a, _ = store.ingest(self.JOHN_A, outgoing=False)
        b, _ = store.ingest(self.JOHN_B, outgoing=False)
        assert store.get(a)["phone"] == "+15551110001"
        assert store.get(b)["phone"] == "+15552220002"

    def test_later_messages_still_reach_the_right_thread(self):
        store = self._store()
        a, _ = store.ingest(self.JOHN_A, outgoing=False)
        store.ingest(self.JOHN_B, outgoing=False)
        again, _ = store.ingest(dict(self.JOHN_A, body="second"), outgoing=False)
        assert again == a
        assert len(store.threads) == 2

    def test_the_label_stops_linking_once_it_is_ambiguous(self):
        """A later name-only event must not be filed under either John."""
        store = self._store()
        a, _ = store.ingest(self.JOHN_A, outgoing=False)
        b, _ = store.ingest(self.JOHN_B, outgoing=False)
        c, _ = store.ingest({"kind": "sms_received",
                             "contact_name": "John Smith"}, outgoing=False)
        assert c not in (a, b)
        assert len(store.threads) == 3

    def test_no_thread_ever_holds_two_numbers(self):
        """The invariant, checked against the messages themselves rather
        than against the index that is supposed to maintain it."""
        from iphonebridge.ui.model import ThreadStore, fold_number
        store = ThreadStore()
        for ev in (self.JOHN_A, self.JOHN_B, self.JOHN_A, self.JOHN_B):
            store.ingest(ev, outgoing=False)
        assert len(store.threads) == 2
        for thread in store.threads.values():
            numbers = {fold_number(m["addr"]) for m in thread["messages"]}
            numbers.discard(None)
            assert len(numbers) == 1, numbers
            # and the reply target is that number
            assert fold_number(thread["phone"]) in numbers

    def test_one_contact_with_a_phone_and_an_apple_id_still_groups(self):
        """The case label-linking exists for: incoming carries an Apple ID,
        outgoing carries a number, and only the label joins them."""
        store = self._store()
        a, _ = store.ingest({"kind": "sms_received", "contact_name": "Dana",
                             "sender_email": "dana@example.com"},
                            outgoing=False)
        b, _ = store.ingest({"kind": "sms_sent", "contact_name": "Dana",
                             "sender_phone": "+15553330003"}, outgoing=True)
        assert a == b
        assert len(store.threads) == 1


class TestContactSuggestions:
    """What to offer while a recipient is being typed. The rules exist so
    the list stays useful: a half-typed number is not a name search, and
    one contact with several numbers must not crowd out everyone else."""

    class Contacts:
        ROWS: ClassVar[list] = [
            ("Dana Whitfield", "+15551234567"),
            ("Dana Whitfield", "+15559999999"),   # same person, second number
            ("Danielle Cruz", "+15557654321"),
            ("Marcus Webb", "+15550000001"),
        ]

        def find_by_name(self, query):
            q = query.lower()
            return [r for r in self.ROWS if q in r[0].lower()]

    def test_matches_by_substring(self):
        from iphonebridge.ui.util import contact_suggestions
        names = [n for n, _ in contact_suggestions(self.Contacts(), "dan")]
        assert names == ["Dana Whitfield", "Danielle Cruz"]

    def test_one_row_per_name(self):
        from iphonebridge.ui.util import contact_suggestions
        out = contact_suggestions(self.Contacts(), "dana")
        assert out == [("Dana Whitfield", "+15551234567")]

    def test_too_short_to_be_worth_offering(self):
        from iphonebridge.ui.util import contact_suggestions
        assert contact_suggestions(self.Contacts(), "d") == []
        assert contact_suggestions(self.Contacts(), "") == []
        assert contact_suggestions(self.Contacts(), None) == []

    def test_a_digit_means_a_number_is_being_typed(self):
        from iphonebridge.ui.util import contact_suggestions
        assert contact_suggestions(self.Contacts(), "555") == []
        assert contact_suggestions(self.Contacts(), "dana1") == []

    def test_capped(self):
        from iphonebridge.ui.util import contact_suggestions

        class Many:
            def find_by_name(self, q):
                return [(f"Person {i}", f"+1555000{i:04d}") for i in range(50)]

        assert len(contact_suggestions(Many(), "person", limit=10)) == 10

    def test_a_broken_lookup_is_not_fatal(self):
        """Typing must not blow up because the contact cache is unreadable."""
        from iphonebridge.ui.util import contact_suggestions

        class Broken:
            def find_by_name(self, q):
                raise RuntimeError("database is locked")

        assert contact_suggestions(Broken(), "dana") == []


class TestQmlContext:
    """Every name the QML reaches for must actually be published to it.

    A missing one does not crash: the view simply has no model and the
    bindings read null. The Calls tab shipped permanently empty that way,
    because the screenshot renderer published `calls` and the app did not,
    so every harness passed while the app showed nothing.
    """

    @staticmethod
    def _qml() -> str:
        import iphonebridge.ui as ui
        return (pathlib.Path(ui.__file__).parent / "qml" / "Main.qml").read_text()

    @classmethod
    def _context_refs(cls) -> set[str]:
        """Names a `model:` binding reaches for from outside the file.

        Anything declared with `id:` in the QML resolves locally, and
        `modelData`/`parent` are QML's own, so none of those need
        publishing.
        """
        qml = cls._qml()
        used = set(re.findall(r"\bmodel:\s*([a-z][A-Za-z0-9_]*)", qml))
        local = set(re.findall(r"\bid:\s*([a-z][A-Za-z0-9_]*)", qml))
        return used - local - {"modelData", "parent"}

    def test_every_model_reference_is_published(self):
        from iphonebridge.ui.protocol import QML_CONTEXT_NAMES
        unpublished = self._context_refs() - set(QML_CONTEXT_NAMES)
        assert not unpublished, f"QML uses unpublished context names: {unpublished}"

    def test_it_catches_a_missing_model(self):
        """The guard itself, against the list main() actually had."""
        before_the_fix = {"bridge", "threads", "messages", "notifications"}
        assert self._context_refs() - before_the_fix == {"calls"}

    def test_every_published_name_is_used(self):
        """The other direction, so the list does not rot."""
        from iphonebridge.ui.protocol import QML_CONTEXT_NAMES
        qml = self._qml()
        unused = [n for n in QML_CONTEXT_NAMES if n not in qml]
        assert not unused, f"published but never referenced: {unused}"

    def test_calls_is_among_them(self):
        """The specific regression: the Calls tab needs its model."""
        from iphonebridge.ui.protocol import QML_CONTEXT_NAMES
        assert "calls" in QML_CONTEXT_NAMES
        assert "model: calls" in self._qml()
