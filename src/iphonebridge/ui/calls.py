"""Calls page — dial out, and answer / hang up active HFP calls."""
from __future__ import annotations

import re

from gi.repository import Adw, Gtk

from iphonebridge.contacts import ContactsResolver
from iphonebridge.events import vanity_to_digits

_PHONE_RE = re.compile(r"^\+?[\d\s()\-.]{7,}$")


class CallsPage(Gtk.Box):
    def __init__(self, client, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client
        self._toast = toast
        self._contacts = ContactsResolver()
        self._call_rows: list = []

        page = Adw.PreferencesPage()
        self.append(page)

        dial_group = Adw.PreferencesGroup(
            title="Place a call",
            description="Call audio routes through this computer's mic and "
                        "speakers.")
        self._entry = Adw.EntryRow(
            title="Number, contact name, or 1 (800) MYAPPLE")
        self._entry.connect("entry-activated", self._on_dial)
        call_btn = Gtk.Button(
            icon_name="call-start-symbolic", valign=Gtk.Align.CENTER,
            css_classes=["suggested-action"], tooltip_text="Call")
        call_btn.connect("clicked", self._on_dial)
        self._entry.add_suffix(call_btn)
        dial_group.add(self._entry)
        page.add(dial_group)

        # Contact-name autocomplete. GtkEntryCompletion can't attach to an
        # Adw.EntryRow (it wraps GtkText, not GtkEntry), so this is a
        # popover under the row. autohide stays off so the popover never
        # steals keyboard focus from the entry while the user types.
        self._suggestions = Gtk.Popover(
            has_arrow=False, autohide=False,
            position=Gtk.PositionType.BOTTOM)
        self._suggestions.set_parent(self._entry)
        self._sug_list = Gtk.ListBox(css_classes=["boxed-list"])
        self._sug_list.connect("row-activated", self._on_suggestion)
        self._suggestions.set_child(self._sug_list)
        self._filling = False  # guard: setting text from a pick re-fires "changed"
        self._entry.connect("changed", self._on_entry_changed)

        self._calls_group = Adw.PreferencesGroup(title="Active calls")
        page.add(self._calls_group)
        self._refresh_calls()

        client.connect("call-state-changed", self._on_call_state)

    # ---- autocomplete --------------------------------------------------

    def _on_entry_changed(self, _entry) -> None:
        if self._filling:
            return
        text = self._entry.get_text().strip()
        # Numbers (plain or vanity) don't want name suggestions.
        if len(text) < 2 or any(ch.isdigit() for ch in text):
            self._suggestions.popdown()
            return
        seen: set[str] = set()
        names: list[tuple[str, str]] = []   # (display name, first phone)
        for name, phone in self._contacts.find_by_name(text):
            if name not in seen:
                seen.add(name)
                names.append((name, phone))
            if len(names) >= 5:
                break
        if not names:
            self._suggestions.popdown()
            return
        while (row := self._sug_list.get_row_at_index(0)) is not None:
            self._sug_list.remove(row)
        for name, phone in names:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                          margin_top=6, margin_bottom=6,
                          margin_start=10, margin_end=10)
            box.append(Gtk.Label(label=name, halign=Gtk.Align.START))
            box.append(Gtk.Label(label=f"+{phone}", halign=Gtk.Align.START,
                                 css_classes=["dim-label", "caption"]))
            row = Gtk.ListBoxRow(child=box)
            row.contact_name = name
            self._sug_list.append(row)
        self._suggestions.popup()

    def _on_suggestion(self, _list, row) -> None:
        self._filling = True
        try:
            self._entry.set_text(row.contact_name)
            self._entry.set_position(-1)
        finally:
            self._filling = False
        self._suggestions.popdown()
        self._entry.grab_focus()

    # ---- dialing -------------------------------------------------------

    def _on_dial(self, _widget) -> None:
        self._suggestions.popdown()
        raw = self._entry.get_text().strip()
        if not raw:
            return
        number = self._resolve(raw)
        if number is None:
            self._toast(f"No contact matches '{raw}'")
            return
        self._entry.set_sensitive(False)

        def ok(_path: str) -> None:
            self._entry.set_sensitive(True)
            self._entry.set_text("")
            self._toast(f"Calling {raw}…")
            self._refresh_calls()

        def err(text: str) -> None:
            self._entry.set_sensitive(True)
            self._toast(f"Call failed: {text}")

        self._client.dial(number, ok, err)

    def _resolve(self, raw: str) -> str | None:
        """A phone number passes through; a name is looked up in contacts.

        Vanity numbers like "1 (800) MYAPPLE" dial as keypad digits — but
        only when the input already contains a digit, so a bare contact
        name is never translated.
        """
        if _PHONE_RE.match(raw):
            return raw
        if any(ch.isdigit() for ch in raw):
            translated = vanity_to_digits(raw)
            if _PHONE_RE.match(translated):
                return translated
        matches = self._contacts.find_by_name(raw)
        if not matches:
            return None
        return "+" + matches[0][1]

    # ---- active calls --------------------------------------------------

    def _on_call_state(self, _client, _ev) -> None:
        self._refresh_calls()

    def _refresh_calls(self) -> None:
        for row in self._call_rows:
            self._calls_group.remove(row)
        self._call_rows = []
        calls = self._client.list_calls()
        if not calls:
            row = Adw.ActionRow(title="No active calls",
                                css_classes=["dim-label"])
            self._calls_group.add(row)
            self._call_rows.append(row)
            return
        for c in calls:
            row = self._make_call_row(c)
            self._calls_group.add(row)
            self._call_rows.append(row)

    def _make_call_row(self, c: dict) -> Adw.ActionRow:
        peer = c.get("contact_name") or c.get("peer_phone") or "(unknown)"
        state = c.get("state", "?")
        direction = c.get("direction", "")
        row = Adw.ActionRow(title=peer, subtitle=f"{direction} · {state}")
        path = c.get("call_path", "")
        if state in ("incoming", "waiting"):
            answer = Gtk.Button(
                icon_name="call-start-symbolic", valign=Gtk.Align.CENTER,
                css_classes=["suggested-action"], tooltip_text="Answer")
            answer.connect("clicked", lambda _b, p=path: self._answer(p))
            row.add_suffix(answer)
        hang = Gtk.Button(
            icon_name="call-stop-symbolic", valign=Gtk.Align.CENTER,
            css_classes=["destructive-action"], tooltip_text="Hang up")
        hang.connect("clicked", lambda _b, p=path: self._hangup(p))
        row.add_suffix(hang)
        return row

    def _answer(self, path: str) -> None:
        err = self._client.answer_call(path)
        if err:
            self._toast(f"Answer failed: {err}")

    def _hangup(self, path: str) -> None:
        err = self._client.hangup_call(path)
        if err:
            self._toast(f"Hang up failed: {err}")
