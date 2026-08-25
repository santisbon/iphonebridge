"""Notifications page — a live feed of per-app ANCS notifications."""
from __future__ import annotations

from gi.repository import Adw, Gtk, Pango

from iphonebridge.ui.util import event_ts, format_ts


class NotificationsPage(Gtk.Box):
    def __init__(self, client, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client

        # Rows are hand-built cards rather than Adw.ActionRow so each one
        # can carry its own rounded outline, the way a stack of iOS
        # notifications reads.
        self._list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["ib-notes"], valign=Gtk.Align.START,
            margin_top=12, margin_bottom=12)
        scroll = Gtk.ScrolledWindow(
            child=Adw.Clamp(maximum_size=600, child=self._list),
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        # No icon: Adw.StatusPage draws it at 128px, which dominates an
        # otherwise empty pane. Omitting icon-name skips it entirely.
        self._empty = Adw.StatusPage(
            title="No notifications yet",
            description="Per-app notifications from your iPhone — Slack, Mail, "
                        "WhatsApp and the rest — show up here as they arrive.")
        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(scroll, "list")
        self._stack.add_named(self._empty, "empty")
        self.append(self._stack)

        self._count = 0
        for ev in self._client.read_events(kinds={"ancs_notification"}):
            self._prepend(ev)
        self._update_stack()
        client.connect("ancs-notification", self._on_notification)

    def _on_notification(self, _client, ev: dict) -> None:
        if ev.get("is_preexisting"):
            return
        self._prepend(ev)
        self._update_stack()

    def _prepend(self, ev: dict) -> None:
        app = ev.get("app_name") or ev.get("app_id") or "Notification"
        title = (ev.get("title") or "").strip()
        body = (ev.get("body") or "").strip()
        preview = " — ".join(p for p in (title, body) if p) or "(no preview)"

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(Gtk.Label(label=app, xalign=0, hexpand=True,
                             css_classes=["ib-app"],
                             ellipsize=Pango.EllipsizeMode.END))
        ts = format_ts(event_ts(ev), fmt="%H:%M")
        if ts:
            top.append(Gtk.Label(label=ts, css_classes=["ib-time"],
                                 valign=Gtk.Align.START))
        box.append(top)
        box.append(Gtk.Label(label=preview, xalign=0, wrap=True, lines=2,
                             ellipsize=Pango.EllipsizeMode.END,
                             css_classes=["ib-preview"]))

        self._list.prepend(Gtk.ListBoxRow(child=box, activatable=False,
                                          selectable=False))
        self._count += 1

    def _update_stack(self) -> None:
        self._stack.set_visible_child_name("list" if self._count else "empty")
