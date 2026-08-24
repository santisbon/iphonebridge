"""Tests for iphonebridge.contacts._parse_vcards — extracting name+phones
from a PBAP vCard blob."""
from __future__ import annotations

import textwrap

from iphonebridge.contacts import _parse_vcards


def test_single_vcard():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        FN:John Smith
        TEL:+15551234567
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    name, phones, _emails = cards[0]
    assert name == "John Smith"
    assert phones == ["15551234567"]


def test_multiple_vcards():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        FN:Alice
        TEL:+15551234567
        END:VCARD
        BEGIN:VCARD
        VERSION:3.0
        FN:Bob
        TEL:+15559876543
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 2
    assert {c[0] for c in cards} == {"Alice", "Bob"}


def test_multiple_phones_per_card():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        FN:Multi
        TEL;TYPE=CELL:+15551111111
        TEL;TYPE=WORK:+15552222222
        TEL;TYPE=HOME:+15553333333
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    name, phones, _emails = cards[0]
    assert name == "Multi"
    assert sorted(phones) == ["15551111111", "15552222222", "15553333333"]


def test_card_with_no_phone():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        FN:Name Only
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    name, phones, _emails = cards[0]
    assert name == "Name Only"
    assert phones == []


def test_card_with_no_name():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        TEL:+15551234567
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    name, phones, _emails = cards[0]
    assert name is None
    assert phones == ["15551234567"]


def test_empty_blob():
    assert _parse_vcards("") == []


def test_malformed_skipped():
    # Half-vcard at end is dropped (no END:VCARD)
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        FN:Complete
        TEL:+15551234567
        END:VCARD
        BEGIN:VCARD
        FN:Truncated
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    assert cards[0][0] == "Complete"


def test_unicode_names():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        FN:Mañuel Garçia
        TEL:+15551234567
        END:VCARD
        BEGIN:VCARD
        FN:Маша
        TEL:+15552222222
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert "Mañuel Garçia" in [c[0] for c in cards]
    assert "Маша" in [c[0] for c in cards]


def test_email_extracted_and_lowercased():
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        FN:Apple Id Friend
        EMAIL;TYPE=INTERNET:Friend@iCloud.com
        END:VCARD
        """)
    cards = _parse_vcards(blob)
    assert len(cards) == 1
    name, phones, emails = cards[0]
    assert name == "Apple Id Friend"
    assert phones == []
    assert emails == ["friend@icloud.com"]


def test_email_only_contact_is_kept():
    # Contacts with no phone used to be dropped entirely — they're exactly
    # the entries that can name an iMessage-from-Apple-ID thread.
    blob = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        FN:No Phone
        EMAIL:np@example.com
        END:VCARD
        """)
    assert _parse_vcards(blob) == [("No Phone", [], ["np@example.com"])]


def test_fold_strips_accents_and_case():
    from iphonebridge.contacts import _fold
    assert _fold("María") == "maria"
    assert _fold("JOSÉ Ñuñez ") == "jose nunez"
    assert _fold("plain") == "plain"
