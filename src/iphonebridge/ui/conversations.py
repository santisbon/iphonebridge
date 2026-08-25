"""Conversations page — SMS/iMessage threads, read history + send replies.

History comes from the daemon's events.jsonl (incoming messages). Messages
sent from this window are appended locally after the daemon confirms the
transfer. Live incoming messages arrive via the `message-received` signal.
"""
from __future__ import annotations

import logging

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from iphonebridge.contacts import ContactsResolver
from iphonebridge.ui.client import dbus_error_text
from iphonebridge.ui.model import ThreadStore, thread_key, unread_keys
from iphonebridge.ui.util import (
    daystamp,
    relative_stamp,
    resolve_recipient,
    same_group,
)
from iphonebridge.ui.util import pin_popover_height as _pin_popover_height

log = logging.getLogger(__name__)

_ELLIPSIZE_END = Pango.EllipsizeMode.END



def _clear_rows(listbox: Gtk.ListBox) -> None:
    """Empty a list box, detaching row context menus first.

    A popover attached with set_parent() is a child of its row. GTK4 has
    no destroy signal to hook the cleanup onto, so a row removed while its
    menu is still attached warns "still has children left" on finalize and
    leaks the popover.
    """
    child = listbox.get_first_child()
    while child is not None:
        menu = getattr(child, "_ib_menu", None)
        if menu is not None and menu.get_parent() is not None:
            menu.unparent()
        child = child.get_next_sibling()
    listbox.remove_all()






class ConversationsPage(Gtk.Box):
    def __init__(self, client, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client
        self._toast = toast
        self._store = ThreadStore()
        self._current: str | None = None
        self._contacts = ContactsResolver()
        self._composing_new = False
        self._select_next_sent = False
        self._rendered: list[dict] = []
        # True while _rebuild_thread_list is restoring the selection
        # it just cleared, so that bookkeeping is not mistaken for
        # the user opening a conversation.
        self._restoring_selection = False

        # The compose action lives in the window's single header bar (see
        # MainWindow._sync_header_action), the way Messages puts it there
        # rather than floating it above the conversation list.
        self.header_action = Gtk.Button(
            icon_name="plus-symbolic", tooltip_text="New conversation",
            css_classes=["flat"], valign=Gtk.Align.CENTER)
        self.header_action.connect("clicked", self._on_new_conversation)

        # ---- left: thread list ----------------------------------------
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       css_classes=["ib-sidebar"])
        self._thread_list = Gtk.ListBox(css_classes=["ib-threads"],
                                        vexpand=True)
        self._thread_list.connect("row-selected", self._on_thread_selected)
        sidebar_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True, child=self._thread_list)
        left.append(sidebar_scroll)

        # ---- right: message view + compose ----------------------------
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)

        # Conversation header: who, and the state of the link carrying it.
        self._convo_header = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2,
            css_classes=["ib-convo-header"], visible=False)
        self._convo_title = Gtk.Label(
            label="", css_classes=["ib-convo-title"],
            ellipsize=_ELLIPSIZE_END)
        self._link_pill = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=5,
            css_classes=["ib-linkpill"], halign=Gtk.Align.CENTER)
        self._link_dot = Gtk.Label(label="●", css_classes=["ib-linkdot"],
                                   valign=Gtk.Align.CENTER)
        self._link_text = Gtk.Label(label="")
        self._link_pill.append(self._link_dot)
        self._link_pill.append(self._link_text)
        self._convo_header.append(self._convo_title)
        self._convo_header.append(self._link_pill)
        right.append(self._convo_header)

        # Anchored to the bottom: a short thread sits above the composer
        # rather than hanging from the top of an empty pane.
        self._msg_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["ib-canvas", "ib-msglist"],
            valign=Gtk.Align.END)
        self._msg_scroll = Gtk.ScrolledWindow(
            vexpand=True, child=self._msg_list, css_classes=["ib-canvas"])
        self._placeholder = Adw.StatusPage(
            icon_name="chat-bubbles-empty-symbolic",
            title="No conversation selected",
            description="Pick a thread on the left, or start a new one from "
                        "the compose button.")
        self._new_placeholder = Adw.StatusPage(
            icon_name="plus-symbolic", title="New message",
            description="Enter a name or number above, then write your "
                        "message below.")
        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(self._placeholder, "empty")
        self._stack.add_named(self._msg_scroll, "messages")
        self._stack.add_named(self._new_placeholder, "new")
        right.append(self._stack)

        # Recipient bar — only visible while composing a new conversation.
        self._to_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=6, css_classes=["ib-recipient"],
                               visible=False)
        self._to_entry = Gtk.Entry(
            placeholder_text="To: number, contact name, or 1 (800) MYAPPLE",
            hexpand=True, css_classes=["ib-pill"])
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

        compose = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          css_classes=["ib-composer"])
        self._entry = Gtk.Entry(
            placeholder_text="Message", hexpand=True, sensitive=False,
            css_classes=["ib-pill"])
        self._entry.connect("activate", self._on_send)
        self._send_btn = Gtk.Button(
            icon_name="go-up-symbolic", sensitive=False,
            valign=Gtk.Align.CENTER, css_classes=["ib-circle"],
            tooltip_text="Send")
        self._send_btn.connect("clicked", self._on_send)
        compose.append(self._entry)
        compose.append(self._send_btn)
        right.append(compose)

        # No breakpoint is wired, so the split never collapses: a collapsed
        # NavigationSplitView pushes the conversation as a page and would
        # need a header bar with a back button to get out of.
        split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Messages", child=left),
            content=Adw.NavigationPage(title="Conversation", child=right),
            min_sidebar_width=240, max_sidebar_width=340,
            sidebar_width_fraction=0.30, vexpand=True)
        self.append(split)

        self._load_history()
        self._update_link_pill()
        client.connect("message-received", self._on_incoming)
        client.connect("message-sent", self._on_sent_event)
        client.connect("message-seen", self._on_seen)
        client.connect("availability-changed",
                       lambda *_: self._update_link_pill())

    # ---- data ----------------------------------------------------------

    def _load_history(self) -> None:
        for ev in self._client.read_events(kinds={"sms_received", "sms_sent"}):
            self._ingest(ev, outgoing=(ev.get("kind") == "sms_sent"),
                         refresh=False)
        self._rebuild_thread_list()

    def _ingest(self, ev: dict, *, outgoing: bool, refresh: bool = True) -> None:
        key, msg = self._store.ingest(ev, outgoing=outgoing)
        if not refresh:
            return
        self._rebuild_thread_list()
        if self._current == key:
            # Live messages are newer than everything rendered, so they
            # append; anything out of order forces a full rebuild.
            if self._rendered and msg["at"] >= self._rendered[-1]["at"]:
                self._append_message(msg)
            else:
                self._render_thread(key)
            self._scroll_to_bottom()
        # Message traffic is itself proof the link is up.
        self._update_link_pill(alive=True)

    # ---- new conversation ----------------------------------------------

    def _on_new_conversation(self, _btn) -> None:
        self._composing_new = True
        self._current = None
        self._thread_list.select_row(None)
        self._stack.set_visible_child_name("new")
        self._convo_header.set_visible(False)
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
            box.append(Gtk.Label(label=phone, css_classes=["ib-time"]))
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
        # remove_all() clears the selection and select_row() puts it back,
        # and both emit row-selected. Left unguarded that re-runs
        # _on_thread_selected, which redraws the whole conversation — so a
        # message that had just been appended got drawn a second time.
        self._restoring_selection = True
        try:
            self._rebuild_rows(selected)
        finally:
            self._restoring_selection = False

    def _rebuild_rows(self, selected: str | None) -> None:
        _clear_rows(self._thread_list)
        for thread in self._store.ordered():
            row = Gtk.ListBoxRow()
            row.thread_key = thread["key"]
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            unread = unread_keys(thread)
            # A filled accent dot, the way Messages marks a conversation
            # with something waiting in it.
            dot = Gtk.Label(label="\u25cf", css_classes=["ib-unread"],
                            valign=Gtk.Align.CENTER, visible=bool(unread))
            top.append(dot)
            top.append(Gtk.Label(label=thread["name"], xalign=0, hexpand=True,
                                 css_classes=["ib-name"],
                                 ellipsize=_ELLIPSIZE_END))
            top.append(Gtk.Label(label=relative_stamp(thread.get("last_ts")),
                                 css_classes=["ib-time"],
                                 valign=Gtk.Align.START))
            box.append(top)

            msgs = thread["messages"]
            last = (max(msgs, key=lambda m: m["at"])["body"] if msgs else "")
            box.append(Gtk.Label(label=last.replace("\n", " "), xalign=0,
                                 ellipsize=_ELLIPSIZE_END,
                                 css_classes=["ib-preview"]))
            row.set_child(box)
            self._attach_delete_menu(
                row, "Delete conversation",
                lambda key=thread["key"]: self._delete_thread(key))
            self._thread_list.append(row)
            if thread["key"] == selected:
                self._thread_list.select_row(row)

    def _on_thread_selected(self, _list, row) -> None:
        if row is None or self._restoring_selection:
            return
        if self._composing_new:
            self._leave_new_mode()
        self._open_thread(row.thread_key)

    def _open_thread(self, key: str) -> None:
        """Show a conversation. Shared by picking a row and by landing in
        a thread the moment a first message to it is sent."""
        self._current = key
        thread = self._store.get(key)
        self._entry.set_sensitive(True)
        self._send_btn.set_sensitive(True)
        self._convo_title.set_label(thread["name"] if thread else "")
        self._convo_header.set_visible(True)
        self._stack.set_visible_child_name("messages")
        self._render_thread(key)
        self._scroll_to_bottom()
        self._mark_thread_read(thread)

    # ---- message bubbles ----------------------------------------------

    def _render_thread(self, key: str) -> None:
        """Rebuild the whole conversation.

        Everything that changes what is on screen goes through here or
        _append_message, so grouping and day rules stay consistent.
        """
        _clear_rows(self._msg_list)
        self._rendered = []
        for msg in self._store.messages(key):
            self._append_message(msg)

    def _append_message(self, msg: dict) -> None:
        prev = self._rendered[-1] if self._rendered else None
        prev_ts = prev["ts"] if prev else None
        if not same_group(prev_ts, msg["ts"]):
            self._msg_list.append(self._daystamp_row(msg["ts"]))
            new_run = True
        else:
            new_run = prev is None or prev["outgoing"] != msg["outgoing"]
        self._msg_list.append(self._bubble_row(msg, new_run))
        self._rendered.append(msg)

    def _daystamp_row(self, ts: str) -> Gtk.ListBoxRow:
        label = Gtk.Label(css_classes=["ib-daystamp"],
                          halign=Gtk.Align.CENTER,
                          margin_top=14, margin_bottom=6)
        label.set_markup(daystamp(ts))
        return Gtk.ListBoxRow(child=label, activatable=False, selectable=False)

    def _bubble_row(self, msg: dict, new_run: bool) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        margin_top=8 if new_run else 2,
                        margin_start=12, margin_end=12)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                         css_classes=["ib-bubble"])
        bubble.set_halign(Gtk.Align.END if msg["outgoing"] else Gtk.Align.START)
        bubble.add_css_class("ib-out" if msg["outgoing"] else "ib-in")
        # The timestamp moved out of the bubble and onto the day rule, so a
        # run of messages reads as one block instead of a stack of cards.
        bubble.append(Gtk.Label(label=msg["body"], xalign=0, wrap=True,
                                selectable=True, max_width_chars=40))
        outer.append(bubble)
        row.set_child(outer)
        if msg.get("key"):
            self._attach_delete_menu(
                row, "Delete message",
                lambda key=msg["key"]: self._delete_messages([key]))
        return row

    def _scroll_to_bottom(self) -> None:
        def _scroll() -> bool:
            adj = self._msg_scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
            return False
        GLib.idle_add(_scroll)

    # ---- read state ------------------------------------------------------

    def _mark_thread_read(self, thread: dict | None) -> None:
        """Opening a conversation is reading it.

        Marked locally first so the dot clears immediately; the daemon
        writes back to the iPhone for any message obexd still exports.
        """
        if thread is None:
            return
        keys = self._store.mark_thread_read(thread["key"])
        if not keys:
            return
        self._rebuild_thread_list()
        try:
            self._client.mark_read(keys)
        except Exception as e:
            log.warning("mark read failed: %s", dbus_error_text(e))

    def _on_seen(self, _client, ev: dict) -> None:
        """The iPhone marked something read while we were watching."""
        keys = set(ev.get("keys") or ())
        if not keys:
            return
        if self._store.mark_read(keys):
            self._rebuild_thread_list()

    # ---- link state -----------------------------------------------------

    def _update_link_pill(self, *, alive: bool | None = None) -> None:
        """The Bluetooth link, stated where it matters.

        Driven by availability changes and by message traffic (which proves
        the link), never polled: the daemon's IsHealthy call blocks the main
        loop for up to 5s on a bad link.
        """
        up = alive if alive is not None else (
            self._client.available and self._client.healthy)
        if up:
            self._link_text.set_label("iPhone connected")
            self._link_pill.remove_css_class("warn")
        else:
            self._link_text.set_label("Reconnecting…")
            self._link_pill.add_css_class("warn")

    # ---- delete ---------------------------------------------------------

    def _attach_delete_menu(self, widget, label: str, on_delete) -> None:
        """Right-click (or long-press) a row for a one-item delete menu."""
        popover = Gtk.Popover(has_arrow=True, autohide=True)
        button = Gtk.Button(label=label, css_classes=["flat"],
                            margin_top=4, margin_bottom=4,
                            margin_start=4, margin_end=4)

        def activate(_b):
            popover.popdown()
            on_delete()

        button.connect("clicked", activate)
        popover.set_child(button)
        popover.set_parent(widget)
        # Held so _clear_rows can detach it before the row dies.
        widget._ib_menu = popover

        def on_right_click(_gesture, _n_press, x, y):
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            popover.set_pointing_to(rect)
            popover.popup()

        gesture = Gtk.GestureClick(button=3)
        gesture.connect("pressed", on_right_click)
        widget.add_controller(gesture)

        longpress = Gtk.GestureLongPress()
        longpress.connect("pressed", lambda _g, _x, _y: popover.popup())
        widget.add_controller(longpress)

    def _delete_thread(self, thread_key: str) -> None:
        self._delete_messages(self._store.message_keys(thread_key),
                              thread_key=thread_key)

    def _delete_messages(self, keys: list[str], thread_key: str | None = None) -> None:
        """Delete from local history. The phone is never touched: iOS
        ignores MAP deletes (see README limitations)."""
        if not keys:
            return
        try:
            removed = self._client.delete_local(keys)
        except Exception as e:
            self._toast(f"Delete failed: {dbus_error_text(e)}")
            return
        if self._current in self._store.remove(keys):
            self._current = None
            self._stack.set_visible_child_name("empty")
            self._convo_header.set_visible(False)
            self._entry.set_sensitive(False)
            self._send_btn.set_sensitive(False)
        self._rebuild_thread_list()
        if self._current and self._current in self._store:
            self._render_thread(self._current)
        noun = "message" if removed == 1 else "messages"
        self._toast(f"Deleted {removed} {noun} from this computer")

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
            target = self._store.get(self._current)["phone"]
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
            key = thread_key(ev)
            self._rebuild_thread_list()
            # Explicit, because restoring the selection no longer opens the
            # thread on its own.
            self._open_thread(key)
