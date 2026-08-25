"""Conversations page — SMS/iMessage threads, read history + send replies.

History comes from the daemon's events.jsonl (incoming messages). Messages
sent from this window are appended locally after the daemon confirms the
transfer. Live incoming messages arrive via the `message-received` signal.
"""
from __future__ import annotations

import logging

from gi.repository import GLib, Gtk, Pango

from iphonebridge.contacts import ContactsResolver
from iphonebridge.ui.util import event_ts, format_ts, resolve_recipient
from iphonebridge.ui.util import pin_popover_height as _pin_popover_height

log = logging.getLogger(__name__)

_ELLIPSIZE_END = Pango.EllipsizeMode.END


def _thread_key(ev: dict) -> str:
    return (ev.get("contact_name") or ev.get("sender_phone")
            or ev.get("sender_phone_norm") or ev.get("sender_email")
            or "(unknown)")


class ConversationsPage(Gtk.Box):
    def __init__(self, client, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._client = client
        self._toast = toast
        self._threads: dict[str, dict] = {}
        self._current: str | None = None
        self._contacts = ContactsResolver()
        self._composing_new = False
        self._select_next_sent = False

        # ---- left: thread list ----------------------------------------
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # mail-message-new-symbolic is the stock compose glyph;
        # chat-message-new-symbolic isn't shipped by adwaita-icon-theme.
        new_btn = Gtk.Button(icon_name="gtk-add-symbolic",
                             tooltip_text="New conversation",
                             css_classes=["flat"],
                             margin_top=6, margin_bottom=6,
                             margin_start=6, margin_end=6)
        new_btn.connect("clicked", self._on_new_conversation)
        left.append(new_btn)
        left.append(Gtk.Separator())
        self._thread_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self._thread_list.connect("row-selected", self._on_thread_selected)
        sidebar_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=240,
            vexpand=True, child=self._thread_list)
        left.append(sidebar_scroll)
        self.append(left)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # ---- right: message view + compose ----------------------------
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self._msg_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE, css_classes=["background"])
        self._msg_scroll = Gtk.ScrolledWindow(
            vexpand=True, child=self._msg_list)
        self._placeholder = Gtk.Label(
            label="Select a conversation", css_classes=["dim-label", "title-2"],
            vexpand=True)
        self._stack = Gtk.Stack()
        self._stack.add_named(self._placeholder, "empty")
        self._stack.add_named(self._msg_scroll, "messages")
        self._stack.add_named(
            Gtk.Label(label="New Message",
                      css_classes=["dim-label", "title-2"], vexpand=True),
            "new")
        right.append(self._stack)

        # Recipient bar — only visible while composing a new conversation.
        self._to_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=6, margin_top=6,
                               margin_start=6, margin_end=6, visible=False)
        self._to_entry = Gtk.Entry(
            placeholder_text="To: number, contact name, or 1 (800) MYAPPLE",
            hexpand=True)
        self._to_entry.connect("changed", self._on_to_changed)
        self._to_bar.append(self._to_entry)
        right.append(self._to_bar)

        # Contact-name autocomplete under the recipient entry — same
        # popover pattern as the Calls tab dialer.
        self._to_suggestions = Gtk.Popover(
            has_arrow=False, autohide=False,
            css_classes=["suggestion-pop"],
            position=Gtk.PositionType.BOTTOM)
        self._to_suggestions.set_parent(self._to_entry)
        self._to_sug_list = Gtk.ListBox(css_classes=["boxed-list"])
        self._to_sug_list.connect("row-activated", self._on_to_suggestion)
        # propagate_natural_width matters: without it the scrolled
        # window allocates the list its MINIMUM width, and ellipsized
        # labels have a minimum of a few pixels — names render as "…".
        self._to_sug_scroll = Gtk.ScrolledWindow(
            propagate_natural_width=True,
            child=self._to_sug_list, propagate_natural_height=True,
            max_content_height=320,
            hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._to_suggestions.set_child(self._to_sug_scroll)
        self._to_filling = False

        compose = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                          margin_top=6, margin_bottom=6,
                          margin_start=6, margin_end=6)
        self._entry = Gtk.Entry(
            placeholder_text="Message", hexpand=True, sensitive=False)
        self._entry.connect("activate", self._on_send)
        self._send_btn = Gtk.Button(
            icon_name="document-send-symbolic", sensitive=False,
            css_classes=["suggested-action"], tooltip_text="Send")
        self._send_btn.connect("clicked", self._on_send)
        compose.append(self._entry)
        compose.append(self._send_btn)
        right.append(Gtk.Separator())
        right.append(compose)
        self.append(right)

        self._load_history()
        client.connect("message-received", self._on_incoming)
        client.connect("message-sent", self._on_sent_event)

    # ---- data ----------------------------------------------------------

    def _load_history(self) -> None:
        for ev in self._client.read_events(kinds={"sms_received", "sms_sent"}):
            self._ingest(ev, outgoing=(ev.get("kind") == "sms_sent"),
                         refresh=False)
        self._rebuild_thread_list()

    def _ingest(self, ev: dict, *, outgoing: bool, refresh: bool = True) -> None:
        key = _thread_key(ev)
        thread = self._threads.get(key)
        if thread is None:
            thread = {"key": key, "name": key,
                      "phone": ev.get("sender_phone")
                      or ev.get("sender_phone_norm")
                      or ev.get("sender_email") or key,
                      "messages": []}
            self._threads[key] = thread
        msg = {"body": ev.get("body") or "",
               "ts": event_ts(ev), "outgoing": outgoing}
        thread["messages"].append(msg)
        # Newest message wins the thread's sort key and preview even if
        # events were ingested out of chronological order (e.g. a seeded
        # history written newest-first).
        thread["last_ts"] = max(thread.get("last_ts", ""), msg["ts"])
        if refresh:
            self._rebuild_thread_list()
            if self._current == key:
                self._append_bubble(msg)
                self._scroll_to_bottom()

    # ---- new conversation ----------------------------------------------

    def _on_new_conversation(self, _btn) -> None:
        self._composing_new = True
        self._current = None
        self._thread_list.select_row(None)
        self._stack.set_visible_child_name("new")
        self._to_bar.set_visible(True)
        self._entry.set_sensitive(True)
        self._send_btn.set_sensitive(True)
        self._to_entry.grab_focus()

    def _leave_new_mode(self) -> None:
        self._composing_new = False
        self._to_suggestions.popdown()
        self._to_bar.set_visible(False)
        self._to_entry.set_text("")

    def _on_to_changed(self, _entry) -> None:
        if self._to_filling:
            return
        text = self._to_entry.get_text().strip()
        if len(text) < 2 or any(ch.isdigit() for ch in text):
            self._to_suggestions.popdown()
            return
        try:
            matches = self._contacts.find_by_name(text)
        except Exception:
            log.exception("suggestion lookup failed for %d chars", len(text))
            self._to_suggestions.popdown()
            return
        seen: set[str] = set()
        names: list[tuple[str, str]] = []
        for name, phone in matches:
            if name not in seen:
                seen.add(name)
                names.append((name, phone))
            if len(names) >= 10:
                break
        if not names:
            self._to_suggestions.popdown()
            return
        while (row := self._to_sug_list.get_row_at_index(0)) is not None:
            self._to_sug_list.remove(row)
        for name, phone in names:
            # Single-line rows keep the popover short enough that
            # narrowing matches visibly shrinks it (stacked two-line rows
            # overflowed the height cap at 6+ matches, so 10 matches and
            # 6 looked the same height).
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          margin_top=4, margin_bottom=4,
                          margin_start=10, margin_end=10)
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True,
                                 ellipsize=_ELLIPSIZE_END,
                                 max_width_chars=28))
            box.append(Gtk.Label(label=phone,
                                 css_classes=["dim-label", "caption"]))
            row = Gtk.ListBoxRow(child=box)
            row.contact_name = name
            self._to_sug_list.append(row)
        _pin_popover_height(self._to_sug_list, self._to_sug_scroll)
        self._to_suggestions.popup()

    def _on_to_suggestion(self, _list, row) -> None:
        self._to_filling = True
        try:
            self._to_entry.set_text(row.contact_name)
            self._to_entry.set_position(-1)
        finally:
            self._to_filling = False
        self._to_suggestions.popdown()
        self._entry.grab_focus()

    # ---- thread list ---------------------------------------------------

    def _rebuild_thread_list(self) -> None:
        selected = self._current
        self._thread_list.remove_all()
        order = sorted(self._threads.values(),
                       key=lambda t: t.get("last_ts", ""), reverse=True)
        for thread in order:
            row = Gtk.ListBoxRow()
            row.thread_key = thread["key"]
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                          margin_top=8, margin_bottom=8,
                          margin_start=10, margin_end=10)
            box.append(Gtk.Label(label=thread["name"], xalign=0,
                                 css_classes=["heading"],
                                 ellipsize=_ELLIPSIZE_END))
            msgs = thread["messages"]
            last = (max(msgs, key=lambda m: m["ts"])["body"] if msgs else "")
            box.append(Gtk.Label(label=last.replace("\n", " "), xalign=0,
                                  ellipsize=_ELLIPSIZE_END,
                                  css_classes=["dim-label"]))
            row.set_child(box)
            self._thread_list.append(row)
            if thread["key"] == selected:
                self._thread_list.select_row(row)

    def _on_thread_selected(self, _list, row) -> None:
        if row is None:
            return
        if self._composing_new:
            self._leave_new_mode()
        self._current = row.thread_key
        thread = self._threads.get(self._current)
        self._entry.set_sensitive(True)
        self._send_btn.set_sensitive(True)
        self._stack.set_visible_child_name("messages")
        self._msg_list.remove_all()
        for msg in sorted(thread["messages"], key=lambda m: m["ts"]):
            self._append_bubble(msg)
        self._scroll_to_bottom()

    # ---- message bubbles ----------------------------------------------

    def _append_bubble(self, msg: dict) -> None:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        margin_top=3, margin_bottom=3,
                        margin_start=8, margin_end=8)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         css_classes=["card", "msg-bubble"])
        bubble.set_halign(Gtk.Align.END if msg["outgoing"] else Gtk.Align.START)
        if msg["outgoing"]:
            bubble.add_css_class("msg-out")
        body = Gtk.Label(label=msg["body"], xalign=0, wrap=True,
                         selectable=True, max_width_chars=46)
        bubble.append(body)
        ts = format_ts(msg["ts"])
        if ts:
            bubble.append(Gtk.Label(label=ts, xalign=1,
                                    css_classes=["dim-label", "caption"]))
        outer.append(bubble)
        row.set_child(outer)
        self._msg_list.append(row)

    def _scroll_to_bottom(self) -> None:
        def _scroll() -> bool:
            adj = self._msg_scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
            return False
        GLib.idle_add(_scroll)

    # ---- send ----------------------------------------------------------

    def _on_send(self, _widget) -> None:
        body = self._entry.get_text().strip()
        if not body:
            return
        if self._composing_new:
            raw = self._to_entry.get_text().strip()
            if not raw:
                self._toast("Enter a recipient")
                return
            target = resolve_recipient(self._contacts, raw)
            if target is None:
                self._toast(f"No contact matches '{raw}'")
                return
        elif self._current is not None:
            target = self._threads[self._current]["phone"]
        else:
            return
        self._entry.set_sensitive(False)
        self._send_btn.set_sensitive(False)

        def done(_transfer: str) -> None:
            # The outgoing bubble is added when the daemon's MessageSent
            # signal arrives (see _on_sent_event) — no optimistic append,
            # so there's no chance of a duplicate. For a brand-new
            # conversation that signal also creates the thread, so mark it
            # for selection when it lands.
            if self._composing_new:
                self._select_next_sent = True
                self._leave_new_mode()
            self._entry.set_text("")
            self._entry.set_sensitive(True)
            self._send_btn.set_sensitive(True)
            self._entry.grab_focus()

        def failed(text: str) -> None:
            self._entry.set_sensitive(True)
            self._send_btn.set_sensitive(True)
            self._toast(f"Send failed: {text}")

        self._client.send_message(target, body, done, failed)

    # ---- live ----------------------------------------------------------

    def _on_incoming(self, _client, ev: dict) -> None:
        self._ingest(ev, outgoing=False)

    def _on_sent_event(self, _client, ev: dict) -> None:
        self._ingest(ev, outgoing=True)
        if self._select_next_sent:
            self._select_next_sent = False
            key = _thread_key(ev)
            self._current = key
            self._rebuild_thread_list()
