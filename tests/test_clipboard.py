"""Tests for iphonebridge.clipboard — verification-code detection."""
from __future__ import annotations

import pytest

from iphonebridge.clipboard import extract_verification_code


class TestExtractVerificationCode:
    @pytest.mark.parametrize("body,expected", [
        ("474229 is your Instagram code. Don't share it.", "474229"),
        ("Your verification code is 123456", "123456"),
        ("G-558211 is your Google verification code.", "558211"),
        ("Your Apple ID Code is: 901234. Do not share it.", "901234"),
        ("Use 1234 to verify your number.", "1234"),
        ("Your one-time passcode is 12345678.", "12345678"),
        ("Your code is 123-456.", "123456"),
        ("PayPal: 778 990 is your security code.", "778990"),
        ("Enter 55213 to sign in.", "55213"),
    ])
    def test_detects_real_codes(self, body, expected):
        assert extract_verification_code(body) == expected

    @pytest.mark.parametrize("body", [
        "Hey, are you free at 7?",
        "Call me back at 5551234567",          # 10 digits, and no keyword
        "See you in 2026!",
        "Your package 4471123 has shipped",    # digits but no keyword
        "Running late, be there in 15",
        "",
        None,
    ])
    def test_ignores_non_codes(self, body):
        assert extract_verification_code(body) is None

    def test_keyword_alone_without_a_number(self):
        assert extract_verification_code("Check the code on the door") is None

    def test_year_not_picked_when_a_real_code_is_present(self):
        assert extract_verification_code(
            "Your login code 558211 expires in 2026") == "558211"

    def test_long_phone_number_not_treated_as_code(self):
        # Has the keyword 'code' but the only number is an 11-digit phone.
        assert extract_verification_code(
            "Text the code to 15551234567") is None


class TestCodeNeverReachesTheLog:
    """A one-time code is a live credential while it is valid, and the
    journal is persisted and readable by anything with journal access. The
    sink may put the value on the clipboard and in a desktop notification,
    but never into a log line."""

    CODE = "062208"
    BODY = f"Your Example Corp verification code is: {CODE}"

    def _sink(self, monkeypatch, tool):
        from iphonebridge.sinks import clipboard as mod
        monkeypatch.setattr(mod, "copy_to_clipboard", lambda code: tool)
        sink = mod.ClipboardSink.__new__(mod.ClipboardSink)
        sink._notif = None            # skip the desktop notification
        return sink

    def _event(self):
        from iphonebridge.events import SmsEvent
        return SmsEvent(
            kind="sms_received", handle="h1", sender_phone="+15550143",
            sender_phone_norm="15550143", contact_name=None, body=self.BODY,
            timestamp=None, is_read=False, raw_status="notification",
            raw_type="sms-gsm")

    def test_success_path_omits_the_code(self, monkeypatch, caplog):
        import logging
        sink = self._sink(monkeypatch, "wl-copy")
        with caplog.at_level(logging.DEBUG):
            sink.handle(self._event())
        assert caplog.text, "expected the sink to log something"
        assert self.CODE not in caplog.text

    def test_failure_path_omits_the_code(self, monkeypatch, caplog):
        """The no-clipboard-tool warning named the code too."""
        import logging
        sink = self._sink(monkeypatch, None)
        with caplog.at_level(logging.DEBUG):
            sink.handle(self._event())
        assert caplog.text, "expected the sink to warn"
        assert self.CODE not in caplog.text

    def test_the_body_is_not_logged_either(self, monkeypatch, caplog):
        import logging
        sink = self._sink(monkeypatch, "wl-copy")
        with caplog.at_level(logging.DEBUG):
            sink.handle(self._event())
        assert self.BODY not in caplog.text


class TestNoMessageContentAboveDebug:
    """A source-wide guard, so this cannot quietly come back.

    Message bodies, notification titles, sender names and one-time codes
    may be logged at DEBUG, which is off by default. Anything at INFO or
    louder ends up in a persisted journal that is readable by anything
    with journal access.

    A `len(...)` of any of those is allowed: INFO needs to say that a
    message was delivered, and how big it was, without saying what it
    said. That distinction is what keeps a delivered message and a
    silently dropped one from looking identical at the default level.
    """

    RISKY = ("event.body", "parsed.body", "event.title", "display_sender",
             "body or", "title or")

    def _offenders(self):
        import ast
        import pathlib
        out = []
        root = pathlib.Path(__file__).resolve().parent.parent / "src"
        for f in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(f.read_text())):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "log"
                        and node.func.attr in ("info", "warning", "error",
                                               "exception")):
                    continue
                for arg in node.args[1:]:
                    # len(...) of message content is the intended form: it
                    # says how big something was without saying what it is.
                    if (isinstance(arg, ast.Call)
                            and isinstance(arg.func, ast.Name)
                            and arg.func.id == "len"):
                        continue
                    src = ast.unparse(arg)
                    if src == "code" or any(r in src for r in self.RISKY):
                        out.append(f"{f.relative_to(root)}:{node.lineno} "
                                   f"log.{node.func.attr}({src})")
        return out

    def test_nothing_above_debug_logs_message_content(self):
        offenders = self._offenders()
        assert offenders == [], (
            "these log calls would put message content or a one-time code "
            "into the journal; use log.debug or log a length instead:\n  "
            + "\n  ".join(offenders))
