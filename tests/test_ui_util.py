"""Tests for iphonebridge.ui.util — timestamp ordering and formatting.

These import the UI helper module but not GTK: util.py keeps its gi
imports inside the functions that need them, so this runs without a
display.
"""
from __future__ import annotations

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

    def test_a_resolved_contact_still_wins(self):
        from iphonebridge.ui.model import thread_key
        named = dict(self.RECV, contact_name="Dana Whitfield")
        assert thread_key(named) == "Dana Whitfield"

    def test_different_numbers_stay_apart(self):
        from iphonebridge.ui.model import thread_key
        other = dict(self.RECV, sender_phone_norm="15559876543")
        assert thread_key(self.SENT) != thread_key(other)

    def test_email_senders_still_group(self):
        from iphonebridge.ui.model import thread_key
        a = {"kind": "sms_received", "sender_email": "x@example.com"}
        assert thread_key(a) == "x@example.com"

    def test_the_displayed_name_keeps_the_readable_form(self):
        """Grouping by digits must not make the thread show bare digits."""
        from iphonebridge.ui.model import thread_name
        assert thread_name(self.SENT) == "+1 (555) 123-4567"
        assert thread_name(dict(self.RECV, contact_name="Dana")) == "Dana"
