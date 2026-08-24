"""Calls page — dial out, and answer / hang up active HFP calls."""
from __future__ import annotations

from gi.repository import Adw, Gtk, Pango

from iphonebridge.contacts import ContactsResolver
from iphonebridge.ui.util import pin_popover_height as _pin_popover_height
from iphonebridge.ui.util import resolve_recipient


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
            title="Contact name or number e.g. 1 (800) MYAPPLE")
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
            css_classes=["suggestion-pop"],
            position=Gtk.PositionType.BOTTOM)
        self._suggestions.set_parent(self._entry)
        self._sug_list = Gtk.ListBox(css_classes=["boxed-list"])
        self._sug_list.connect("row-activated", self._on_suggestion)
        # propagate_natural_width matters: without it the scrolled
        # window allocates the list its MINIMUM width, and ellipsized
        # labels have a minimum of a few pixels — names render as "…".
        self._sug_scroll = Gtk.ScrolledWindow(
            propagate_natural_width=True,
            child=self._sug_list, propagate_natural_height=True,
            max_content_height=320,
            hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._suggestions.set_child(self._sug_scroll)
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
            if len(names) >= 10:
                break
        if not names:
            self._suggestions.popdown()
            return
        while (row := self._sug_list.get_row_at_index(0)) is not None:
            self._sug_list.remove(row)
        for name, phone in names:
            # Single-line rows keep the popover short enough that
            # narrowing matches visibly shrinks it (stacked two-line rows
            # overflowed the height cap at 6+ matches, so 10 matches and
            # 6 looked the same height).
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          margin_top=4, margin_bottom=4,
                          margin_start=10, margin_end=10)
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.END,
                                 max_width_chars=28))
            box.append(Gtk.Label(label=f"+{phone}",
                                 css_classes=["dim-label", "caption"]))
            row = Gtk.ListBoxRow(child=box)
            row.contact_name = name
            self._sug_list.append(row)
        _pin_popover_height(self._sug_list, self._sug_scroll)
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
        return resolve_recipient(self._contacts, raw)

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
