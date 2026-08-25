"""Main application window — the four-surface shell."""
from __future__ import annotations

from gi.repository import Adw, Gtk

from iphonebridge.ui.calls import CallsPage
from iphonebridge.ui.conversations import ConversationsPage
from iphonebridge.ui.notifications import NotificationsPage
from iphonebridge.ui.status import StatusPage
from iphonebridge.ui.util import has_preferred_font


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, client) -> None:
        super().__init__(application=application, title="iphonebridge")
        self._client = client
        # Tall enough to show the whole Setup tab without scrolling. The
        # Recheck strip that used to sit above it now lives in the header,
        # so the page content sets the height on its own.
        self.set_default_size(940, 720)

        if has_preferred_font():
            self.add_css_class("ib-font")
        # style.css keeps its Apple palette in two blocks, :root and
        # .ib-dark. GTK has no media queries, so the scheme is a class we
        # toggle from libadwaita's own light/dark state.
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", self._on_scheme)
        self._on_scheme(style, None)

        self._toasts = Adw.ToastOverlay()
        self._stack = Adw.ViewStack(vexpand=True, hexpand=True)

        for widget, name, title, icon in (
            (ConversationsPage(client, self.toast), "conversations",
             "Messages", "chat-bubbles-empty-symbolic"),
            (NotificationsPage(client, self.toast), "notifications",
             "Notifications", "bell-outline-symbolic"),
            (CallsPage(client, self.toast), "calls",
             "Calls", "phone-right-facing-symbolic"),
            (StatusPage(client, self.toast), "status",
             "Status", "test-pass-symbolic"),
        ):
            self._stack.add_titled_with_icon(widget, name, title, icon)

        # Adw.InlineViewSwitcher renders as a segmented control, which is
        # the Apple section switcher. BOTH rather than LABELS so the
        # bundled tab icons in ui/icons are actually drawn: with labels
        # only they are set on the stack pages and never appear.
        switcher = Adw.InlineViewSwitcher(
            stack=self._stack,
            display_mode=Adw.InlineViewSwitcherDisplayMode.BOTH)
        header = Adw.HeaderBar(title_widget=switcher)

        # One header bar for the whole app, with a single slot for whichever
        # action belongs to the visible page (compose on Messages, Recheck
        # on Setup). Pages opt in via `header_action`.
        #
        # pack_start, not pack_end: on Linux the minimise/maximise/close
        # buttons sit at the end, and a flat icon button next to them reads
        # as a fourth window control rather than an app action. At the start
        # it sits over the sidebar, which is where Messages puts compose
        # (macOS can use the end because its window controls are on the
        # left). It also makes the bare "+" unambiguous: over the
        # conversation list it plainly means a new conversation.
        self._action_slot = Gtk.Box()
        header.pack_start(self._action_slot)
        self._stack.connect("notify::visible-child-name",
                            lambda *_: self._sync_header_action())
        self._sync_header_action()

        self._banner = Adw.Banner(
            title="Daemon not reachable — run: "
                  "systemctl --user start iphonebridge")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self._banner)
        content.append(self._stack)
        self._toasts.set_child(content)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        client.connect("availability-changed", self._on_availability)
        client.connect("call-state-changed", self._on_call)
        self._on_availability(client, client.available)

    def toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))

    # ---- header ---------------------------------------------------------

    def _sync_header_action(self) -> None:
        while (child := self._action_slot.get_first_child()) is not None:
            self._action_slot.remove(child)
        page = self._stack.get_visible_child()
        action = getattr(page, "header_action", None)
        if action is not None:
            self._action_slot.append(action)

    # ---- theme ----------------------------------------------------------

    def _on_scheme(self, style, _param) -> None:
        if style.get_dark():
            self.add_css_class("ib-dark")
        else:
            self.remove_css_class("ib-dark")

    def _on_availability(self, _client, available: bool) -> None:
        self._banner.set_revealed(not available)

    def _on_call(self, _client, ev: dict) -> None:
        if ev.get("kind") == "call_incoming":
            peer = ev.get("contact_name") or ev.get("peer_phone") or "someone"
            self._stack.set_visible_child_name("calls")
            self.toast(f"Incoming call from {peer}")
            self.present()
