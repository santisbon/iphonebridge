"""Setup & status page — daemon health, data counts, the iPhone checklist."""
from __future__ import annotations

import logging

from gi.repository import Adw, Gtk

from iphonebridge.contacts import ContactsResolver

log = logging.getLogger(__name__)


class StatusPage(Gtk.Box):
    def __init__(self, client, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client

        # Page-level header: Recheck refreshes everything on this tab, so it
        # sits above all groups rather than inside one of them.
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        for setter in (header.set_margin_top, header.set_margin_end,
                       header.set_margin_start):
            setter(12)
        recheck = Gtk.Button(label="Recheck", halign=Gtk.Align.END,
                             hexpand=True)
        recheck.connect("clicked", lambda _b: self._refresh())
        header.append(recheck)
        self.append(header)

        page = Adw.PreferencesPage()
        self.append(page)

        daemon_group = Adw.PreferencesGroup(title="Daemon")
        self._daemon_row = Adw.ActionRow(title="iphonebridge daemon")
        self._daemon_icon = Gtk.Image()
        self._daemon_row.add_suffix(self._daemon_icon)
        self._map_row = Adw.ActionRow(title="Messages — MAP session")
        self._map_icon = Gtk.Image()
        self._map_row.add_suffix(self._map_icon)
        daemon_group.add(self._daemon_row)
        daemon_group.add(self._map_row)
        page.add(daemon_group)

        data_group = Adw.PreferencesGroup(title="Data")
        self._contacts_row = Adw.ActionRow(title="Contacts cached")
        self._events_row = Adw.ActionRow(title="Events logged")
        data_group.add(self._contacts_row)
        data_group.add(self._events_row)
        page.add(data_group)

        checklist = Adw.PreferencesGroup(
            title="iPhone setup",
            description="On the iPhone: Settings → Bluetooth → tap ⓘ next to "
                        "this computer, then enable each toggle:")
        # (title, base subtitle, key in the daemon's GetStatus JSON)
        self._toggle_rows: list[tuple[Adw.ActionRow, Gtk.Image, str, str]] = []
        for item, sub, key in (
            ("Show Message Notifications", "SMS &amp; iMessage (MAP)", "map"),
            ("Sync Contacts", "contact-name resolution (PBAP)", "pbap"),
            ("Show System Notifications", "per-app notifications (ANCS)", "ancs"),
        ):
            row = Adw.ActionRow(title=item, subtitle=sub)
            icon = Gtk.Image()
            row.add_suffix(icon)
            checklist.add(row)
            self._toggle_rows.append((row, icon, sub, key))
        page.add(checklist)

        client.connect("availability-changed", lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        self._client.refresh_availability()
        reachable = self._client.available
        self._daemon_row.set_subtitle("Running" if reachable
                                      else "Not reachable — start it with "
                                           "systemctl --user start iphonebridge")
        self._daemon_icon.set_from_icon_name(
            "emblem-ok-symbolic" if reachable else "dialog-warning-symbolic")

        healthy = self._client.healthy
        self._map_row.set_subtitle(
            "Connected" if healthy
            else "Unavailable — check the iPhone Bluetooth toggles below")
        self._map_icon.set_from_icon_name(
            "emblem-ok-symbolic" if healthy else "dialog-warning-symbolic")

        # Checklist marks are inferred from what's actually working, not
        # read from the iPhone: a live session proves its toggle is on.
        status = self._client.profile_status() if reachable else {}
        for row, icon, base, key in self._toggle_rows:
            if key not in status:
                icon.set_from_icon_name("dialog-question-symbolic")
                row.set_subtitle(base + " — state unknown (daemon unreachable)"
                                 if not reachable else base)
                continue
            if status[key]:
                icon.set_from_icon_name("emblem-ok-symbolic")
                row.set_subtitle(base + " — working now")
            else:
                icon.set_from_icon_name("dialog-warning-symbolic")
                row.set_subtitle(base + " — not detected; check this toggle")

        try:
            n_contacts = ContactsResolver().count()
        except Exception:
            log.exception("contact count failed")
            n_contacts = 0
        self._contacts_row.set_subtitle(f"{n_contacts}")
        self._events_row.set_subtitle(f"{len(self._client.read_events())}")
