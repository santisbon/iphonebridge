"""Tests for iphonebridge.obex.bmessage.parse — extracting sender + body
from a MAP bMessage envelope."""
from __future__ import annotations

import textwrap

from iphonebridge.obex.bmessage import parse


def _bmsg(sender_tel: str, body: str, status: str = "UNREAD") -> str:
    """Build a minimal incoming bMessage for testing."""
    return textwrap.dedent(f"""\
        BEGIN:BMSG
        VERSION:1.0
        STATUS:{status}
        TYPE:SMS_GSM
        FOLDER:telecom/msg/inbox
        BEGIN:VCARD
        VERSION:2.1
        N:Doe;Jane;;;
        FN:Jane Doe
        TEL:{sender_tel}
        END:VCARD
        BEGIN:BENV
        BEGIN:BBODY
        CHARSET:UTF-8
        LENGTH:{len(body)}
        BEGIN:MSG
        {body}
        END:MSG
        END:BBODY
        END:BENV
        END:BMSG
        """).replace("\n", "\r\n")


class TestBasicParsing:
    def test_simple_incoming(self):
        blob = _bmsg("+15551234567", "Hello from the test")
        p = parse(blob)
        assert p.sender_phone == "+15551234567"
        assert p.sender_name == "Jane Doe"
        assert p.body == "Hello from the test"
        assert p.status == "UNREAD"
        assert p.type == "SMS_GSM"
        assert p.folder == "telecom/msg/inbox"

    def test_status_read(self):
        blob = _bmsg("+15551234567", "x", status="READ")
        p = parse(blob)
        assert p.status == "READ"

    def test_empty_body_handled(self):
        blob = _bmsg("+15551234567", "")
        p = parse(blob)
        # body might be empty string or None depending on regex behavior — both OK
        assert p.body in ("", None)

    def test_no_vcard(self):
        # bMessage without originator VCARD (degenerate but possible)
        blob = (
            "BEGIN:BMSG\r\n"
            "VERSION:1.0\r\n"
            "TYPE:SMS_GSM\r\n"
            "BEGIN:BENV\r\n"
            "BEGIN:BBODY\r\n"
            "LENGTH:5\r\n"
            "BEGIN:MSG\r\n"
            "hello\r\n"
            "END:MSG\r\n"
            "END:BBODY\r\n"
            "END:BENV\r\n"
            "END:BMSG\r\n"
        )
        p = parse(blob)
        assert p.sender_phone is None
        assert p.body == "hello"


class TestEdgeCases:
    def test_multiline_body(self):
        body = "Line 1\nLine 2\nLine 3"
        blob = _bmsg("+15551234567", body)
        p = parse(blob)
        # The body may have line normalization but content should be preserved
        assert "Line 1" in p.body
        assert "Line 3" in p.body

    def test_unicode_body(self):
        blob = _bmsg("+15551234567", "héllo 👋 wörld")
        p = parse(blob)
        assert p.body == "héllo 👋 wörld"

    def test_n_field_fallback_when_fn_missing(self):
        # Only N: present, no FN:
        blob = (
            "BEGIN:BMSG\r\n"
            "TYPE:SMS_GSM\r\n"
            "BEGIN:VCARD\r\n"
            "N:Smith;John;;;\r\n"
            "TEL:+15551234567\r\n"
            "END:VCARD\r\n"
            "BEGIN:BENV\r\n"
            "BEGIN:BBODY\r\n"
            "LENGTH:2\r\n"
            "BEGIN:MSG\r\n"
            "hi\r\n"
            "END:MSG\r\n"
            "END:BBODY\r\n"
            "END:BENV\r\n"
            "END:BMSG\r\n"
        )
        p = parse(blob)
        # Parser uses "first;rest" reorder; just check we got *something*
        assert p.sender_name and len(p.sender_name) > 0

    def test_tel_with_type_attribute(self):
        blob = (
            "BEGIN:BMSG\r\n"
            "TYPE:SMS_GSM\r\n"
            "BEGIN:VCARD\r\n"
            "FN:Alice\r\n"
            "TEL;TYPE=CELL:+15551234567\r\n"
            "END:VCARD\r\n"
            "BEGIN:BENV\r\n"
            "BEGIN:BBODY\r\n"
            "LENGTH:2\r\n"
            "BEGIN:MSG\r\n"
            "hi\r\n"
            "END:MSG\r\n"
            "END:BBODY\r\n"
            "END:BENV\r\n"
            "END:BMSG\r\n"
        )
        p = parse(blob)
        assert p.sender_phone == "+15551234567"
        assert p.sender_name == "Alice"

    def test_garbage_input_doesnt_crash(self):
        # Defensive — any string should produce a ParsedBMessage, not raise
        for garbage in ["", "not a bmessage", "BEGIN:BMSG\r\nEND:BMSG", "{'json': 'huh'}"]:
            p = parse(garbage)
            assert p is not None  # may have None fields, but doesn't crash


def test_email_sender_no_tel():
    # iMessage from an Apple ID: originator vCard has EMAIL, no TEL.
    blob = (
        "BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:UNREAD\r\nTYPE:SMS_GSM\r\n"
        "FOLDER:telecom/msg/INBOX\r\n"
        "BEGIN:VCARD\r\nVERSION:2.1\r\nN:;;;;\r\n"
        "EMAIL:friend@icloud.com\r\nEND:VCARD\r\n"
        "BEGIN:BENV\r\nBEGIN:BBODY\r\nCHARSET:UTF-8\r\n"
        "BEGIN:MSG\r\nhello from blue bubble\r\nEND:MSG\r\n"
        "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n"
    )
    p = parse(blob)
    assert p.sender_phone is None
    assert p.sender_email == "friend@icloud.com"
    assert p.body == "hello from blue bubble"


class TestAddressSuffixStripped:
    """iOS appends a parenthesised MAP marker to the originator address in
    a bMessage vCard — "(smsft)" for an SMS forwarded from a paired phone.
    The folder listing reports the same sender without it, so leaving it on
    gives one person two identities: two conversations in the app, and a
    push the inbox sweep cannot recognise as already logged.
    """

    def _vcard(self, line):
        return ("BEGIN:BMSG\r\nBEGIN:VCARD\r\nVERSION:2.1\r\n"
                f"{line}\r\nEND:VCARD\r\n"
                "BEGIN:BENV\r\nBEGIN:BBODY\r\nBEGIN:MSG\r\n"
                "hello\r\nEND:MSG\r\nEND:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")

    def test_email_marker_is_dropped(self):
        from iphonebridge.obex.bmessage import parse
        p = parse(self._vcard("EMAIL:someone@example.com(smsft)"))
        assert p.sender_email == "someone@example.com"

    def test_tel_marker_is_dropped(self):
        from iphonebridge.obex.bmessage import parse
        p = parse(self._vcard("TEL:+15551234567(smsft)"))
        assert p.sender_phone == "+15551234567"

    def test_a_plain_address_is_untouched(self):
        from iphonebridge.obex.bmessage import parse
        p = parse(self._vcard("EMAIL:someone@example.com"))
        assert p.sender_email == "someone@example.com"

    def test_parentheses_inside_an_address_survive(self):
        """Only a trailing group is a marker; anything earlier is address."""
        from iphonebridge.obex.bmessage import parse
        p = parse(self._vcard("EMAIL:od(d)name@example.com"))
        assert p.sender_email == "od(d)name@example.com"

    def test_an_address_that_is_only_a_marker_becomes_none(self):
        from iphonebridge.obex.bmessage import parse
        p = parse(self._vcard("EMAIL:(smsft)"))
        assert p.sender_email is None
