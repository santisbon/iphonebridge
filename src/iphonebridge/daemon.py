"""iphonebridge daemon — orchestrates everything.

Startup order:
  1. bluez_setup.prepare — set adapter CoD, register BLE advert
  2. SessionManager.open_all — long-lived MAP + PBAP OBEX sessions
     (retries on Forbidden — see _try_open_sessions)
  3. ContactsResolver — warm SQLite cache; if empty, pull PBAP
  4. MapEventListener — subscribe to MAP MNS push events
  5. Sinks — register libnotify + jsonl
  6. DBus service (me.santisbon.iphonebridge.Messages1)
  7. GLib.MainLoop().run()

Shutdown order is the reverse.

Degraded mode: if MAP/PBAP can't open (typically because the user hasn't
enabled iPhone toggles yet), the daemon stays alive, logs a clear
remediation hint, and retries every 60s. This avoids the systemd
crash-loop we hit in an earlier version.
"""
from __future__ import annotations

import logging
import signal
from datetime import datetime

import dbus
from gi.repository import GLib

from iphonebridge import bluez_setup, config
from iphonebridge.ancs.client import AncsClient
from iphonebridge.ancs.events import AncsEvent
from iphonebridge.bus import main_loop, session_bus
from iphonebridge.contacts import ContactsResolver, pull_phonebook
from iphonebridge.dbus_service import MessagesService, claim_bus_name
from iphonebridge.events import (
    SeenEvent,
    SmsEvent,
    deleted_keys,
    drop_events_by_key,
    logged_messages,
    mark_logged_read,
    message_key,
    record_deleted_keys,
    sms_sent_event,
)
from iphonebridge.hfp.events import CallEvent
from iphonebridge.hfp.ofono_client import HfpManager
from iphonebridge.obex.map_events import MapEventListener
from iphonebridge.obex.sessions import SessionError, SessionManager
from iphonebridge.sinks import Sink
from iphonebridge.sinks.clipboard import ClipboardSink
from iphonebridge.sinks.jsonl import JsonlSink
from iphonebridge.sinks.libnotify import LibnotifySink

log = logging.getLogger(__name__)

# How often to re-pull the iPhone's phonebook (so the cache picks up new contacts)
CONTACTS_REFRESH_SEC = 24 * 60 * 60  # 24h

# How often to retry MAP/PBAP session open when blocked by the iPhone
# (toggles off, paired-but-not-connected, etc.)
SESSION_RETRY_SEC = 60
# How often to confirm the OBEX sessions still exist once we're ready.
SESSION_HEALTH_SEC = 60


def _seed_seen_messages():
    """Everything already accounted for: logged messages plus tombstones.

    Tombstones are keys alone, with no arrival time, so they match exactly
    but cannot pair a push against a listing. A message deleted while it
    had only ever been pushed can therefore come back on a later sweep.
    """
    seen = logged_messages(config.EVENTS_JSONL)
    seen.update(deleted_keys(config.DELETED_KEYS))
    return seen


def sweep_inbox(sessions, listener, contacts, jsonl_sink, *,
                limit: int = 50, remember_path=None) -> int:
    """Seed conversation history with the inbox window iOS serves.

    A fresh install starts with an empty event log, and iOS only pushes
    messages over MNS as they arrive (plus opportunistic re-pushes of
    recent unread ones), so old conversations never appear. This lists
    the inbox once per session-open (iOS caps the listing at roughly 10
    messages), logs the ones not already dispatched, and marks them seen
    so an MNS re-announcement can't duplicate them.

    History only: events go to the JSONL sink alone, never to the
    notification or clipboard sinks — nobody wants ten popups at start.
    Returns the number of messages logged.
    """
    from iphonebridge.obex.map_query import list_recent_messages
    msgs = list_recent_messages(sessions.map_path, limit=limit)
    logged = 0
    # MAP listings are newest-first; log oldest-first so the JSONL stays
    # chronological like the live MNS events appended after it.
    for m in reversed(msgs):
        handle = m.get("handle") or ""
        sender = str(m.get("sender") or "")
        is_email = "@" in sender
        ts = None
        if m.get("timestamp"):
            try:
                ts = datetime.fromisoformat(m["timestamp"])
            except ValueError:
                ts = None
        event = SmsEvent(
            kind="sms_received",
            handle=handle,
            sender_phone=None if is_email else (sender or None),
            sender_phone_norm=m.get("sender_phone_norm") or None,
            sender_email=sender if is_email else None,
            contact_name=contacts.resolve(sender) if sender else None,
            body=m.get("body") or None,
            timestamp=ts,
            is_read=bool(m.get("read")),
            raw_status=str(m.get("status") or "") or None,
            raw_type=str(m.get("type") or "") or None,
        )
        # No seen_at fallback here, unlike a live push: seen_at is the
        # sweep's own clock, so falling back to it would give the same
        # message a new key on every sweep and log it again.
        key = message_key(ts, sender or None, event.body)
        # Register the path even for messages we skip: the whole point of
        # a listing is that it is the only place read-state can be written
        # back to, and a skipped message is one we already have.
        if remember_path is not None and m.get("path"):
            remember_path(key, str(m["path"]))
        # seen_at is the sweep's own clock here, but a listing entry has a
        # real timestamp, so it is that which places this message against
        # anything already pushed live.
        if listener.seen_keys.matches(key, event.seen_at,
                                      has_timestamp=ts is not None):
            continue
        listener.seen_keys.note(key, event.seen_at,
                                has_timestamp=ts is not None)
        try:
            jsonl_sink.handle(event)
        except Exception:
            log.exception("sweep: jsonl write failed for one message")
            continue
        logged += 1
    if logged:
        log.info("inbox sweep: seeded history with %d message(s)", logged)
    return logged


class Daemon:
    def __init__(self) -> None:
        self.sessions = SessionManager()
        self.contacts = ContactsResolver()
        self.sinks: list[Sink] = []
        self.listener: MapEventListener | None = None
        self.ancs: AncsClient | None = None
        self.hfp: HfpManager | None = None
        self._contacts_refresh_id: int | None = None
        # message key -> live obex object path, and back. Rebuilt every
        # session rather than persisted: obexd renumbers these objects on
        # every restart, so a stored path is a lie by the next boot.
        self._paths: dict[str, str] = {}
        self._keys_by_path: dict[str, str] = {}
        self._read_watch = None
        self._session_retry_id: int | None = None
        self._session_health_id: int | None = None
        self._bus_name = None
        self._dbus_service: MessagesService | None = None
        self._post_sessions_done = False

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        log.info("=== iphonebridge starting ===")
        config.ensure_dirs()

        if not bluez_setup.prepare():
            log.warning(
                "bluez_setup.prepare reported issues — continuing anyway, "
                "but MAP/PBAP may be refused. Re-pair on iPhone after the "
                "adapter is in A/V Hands-Free CoD if the toggles aren't there."
            )

        # ANCS — per-app notifications via BLE GATT. Independent of MAP/PBAP;
        # may or may not work depending on whether BlueZ has established a
        # BLE link to the iPhone (we don't yet do the LastUsedBearer=le
        # dance). Either way, the client just waits patiently for the three
        # ANCS characteristics to appear and subscribes when they do.
        device_path = (
            f"/org/bluez/{config.ADAPTER}"
            f"/dev_{config.IPHONE_MAC.replace(':', '_')}"
        )
        self.ancs = AncsClient(device_path, on_event=self._fanout_ancs)
        self.ancs.start()

        # HFP — take/place calls via oFono. Also independent of MAP/PBAP; if
        # oFono isn't set up it logs a hint and stays dormant.
        self.hfp = HfpManager(
            on_event=self._fanout_call,
            resolve_contact=lambda raw: self.contacts.resolve(raw),
        )
        self.hfp.start()

        # Sinks don't need the OBEX sessions — set them up now so ANCS and
        # HFP events still reach the desktop while MAP/PBAP are degraded.
        self._setup_sinks()

        # Claim the DBus name BEFORE the first session attempt: at login the
        # iPhone is often still reconnecting, so that attempt can block for
        # a minute — and until the name is claimed, the app and CLI report
        # "daemon not reachable" instead of the honest degraded state.
        try:
            self._bus_name = claim_bus_name()
            self._dbus_service = MessagesService(
                self._bus_name, self.sessions, hfp=self.hfp,
                ancs=self.ancs,
                on_sent=self._record_sent,
                on_refresh_contacts=lambda: self._refresh_contacts(
                    raise_on_error=True),
                on_delete_local=self._delete_local,
                on_mark_read=self.mark_read)
            log.info("DBus service ready: me.santisbon.iphonebridge")
        except Exception:
            log.exception("DBus service registration failed — continuing "
                          "without send capability")

        # Try to open MAP/PBAP. If blocked, stay alive and retry every minute.
        self._try_open_sessions(first_attempt=True)

        # Signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal)

        if not self._post_sessions_done:
            log.warning("=== iphonebridge running in DEGRADED mode ===")
            log.warning("    No MAP/PBAP session yet. Retrying every %ds.",
                        SESSION_RETRY_SEC)
        # The "ready" line in the happy path is emitted by
        # _post_sessions_setup, so we don't duplicate it here.

    def _try_open_sessions(self, *, first_attempt: bool) -> None:
        """Open MAP + PBAP. On Forbidden, schedule a periodic retry instead
        of crashing. Idempotent."""
        try:
            self.sessions.open_all()
        except SessionError as e:
            msg = str(e)
            log.warning("could not open MAP/PBAP sessions: %s", msg)
            if "Forbidden" in msg or "0x43" in msg:
                log.warning("")
                log.warning("  → This usually means the iPhone toggles aren't on.")
                log.warning("  → On the iPhone:")
                log.warning("       Settings → Bluetooth → tap (i) next to this device")
                log.warning("       Enable: Show Message Notifications")
                log.warning("       Enable: Sync Contacts")
                log.warning("")
            if first_attempt:
                self._arm_session_retry()
            return
        # Sessions opened — wire everything that depends on them.
        self._post_sessions_setup()

    def _retry_sessions(self) -> bool:
        """GLib timer callback. Return True to keep the timer firing."""
        log.info("retrying MAP/PBAP session open ...")
        try:
            self.sessions.open_all()
        except SessionError as e:
            # Still blocked — keep timer alive
            log.info("still blocked: %s", str(e)[:120])
            return True

        log.info("sessions opened on retry — promoting to ready state")
        # Clear the id first: _post_sessions_setup arms the health check, and
        # returning False below is what actually removes this timer.
        self._session_retry_id = None
        self._post_sessions_setup()
        return False

    def _arm_session_retry(self) -> None:
        """Start the 60s reopen loop, unless it's already running."""
        if self._session_retry_id is not None:
            return
        self._session_retry_id = GLib.timeout_add_seconds(
            SESSION_RETRY_SEC, self._retry_sessions
        )
        log.warning("  → Daemon stays running. Will retry every %ds.",
                    SESSION_RETRY_SEC)

    def _check_session_health(self) -> bool:
        """GLib timer callback. Notice sessions that died under us.

        Without this the daemon holds dead handles indefinitely: the reopen
        loop only runs before we first reach the ready state, so a forget +
        re-pair used to leave the daemon reporting healthy while every query
        failed with UnknownObject.
        """
        if self.sessions.alive():
            return True
        log.warning("MAP/PBAP sessions vanished (re-pair, obexd restart, or "
                    "an iPhone-side timeout) — dropping to DEGRADED and "
                    "reopening")
        self._session_health_id = None
        self._on_sessions_lost()
        return False

    def _on_sessions_lost(self) -> None:
        """Tear down everything that depended on the dead sessions, then
        re-arm the reopen loop. Mirror image of _post_sessions_setup."""
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                log.exception("MNS listener stop failed during recovery")
            self.listener = None
        self.sessions.close_all()
        self._post_sessions_done = False
        log.warning("=== iphonebridge running in DEGRADED mode ===")
        self._arm_session_retry()

    def _setup_sinks(self) -> None:
        """Register the JSONL + libnotify sinks. Independent of the OBEX
        sessions, so ANCS/HFP events reach the desktop even in degraded mode."""
        if self.sinks:
            return
        self.sinks.append(JsonlSink())
        try:
            self.sinks.append(LibnotifySink(hfp=self.hfp))
        except Exception:
            log.exception("libnotify sink failed to init — continuing")
        try:
            self.sinks.append(ClipboardSink())
        except Exception:
            log.exception("clipboard sink failed to init — continuing")
        log.info("sinks ready: %s", [s.name for s in self.sinks])

    def _post_sessions_setup(self) -> None:
        """Everything that requires live MAP+PBAP sessions. Idempotent so
        we can call it either at first-attempt success or at retry success."""
        if self._post_sessions_done:
            return
        self._post_sessions_done = True

        # Warm contacts; if empty, do a one-time pull. PBAP pull is cheap.
        if self.contacts.count() == 0:
            log.info("contacts cache empty — pulling from iPhone via PBAP")
            self._refresh_contacts()

        # Schedule periodic contacts refresh
        if self._contacts_refresh_id is None:
            self._contacts_refresh_id = GLib.timeout_add_seconds(
                CONTACTS_REFRESH_SEC, self._periodic_refresh_contacts
            )

        # Wire up MAP MNS listener.
        # IMPORTANT: pass an indirect lambda so the resolver can be refreshed
        # in place via self.contacts.refresh() without breaking this binding.
        if self.listener is None:
            self.listener = MapEventListener(
                sessions=self.sessions,
                on_sms=self._fanout,
                resolve_contact=lambda raw: self.contacts.resolve(raw),
                seen_keys=_seed_seen_messages(),
            )
            self.listener.start()
        self._watch_read_state()

        # Seed history with whatever inbox window iOS serves — without
        # this, a fresh install shows an empty Messages tab until the
        # first new message arrives.
        try:
            jsonl = next((sk for sk in self.sinks if sk.name == "jsonl"), None)
            if jsonl is not None:
                sweep_inbox(self.sessions, self.listener,
                            self.contacts, jsonl,
                            remember_path=self._remember_path)
        except Exception:
            log.exception("inbox sweep failed — history stays as-is")

        # Watch for the sessions dying under us from here on.
        if self._session_health_id is None:
            self._session_health_id = GLib.timeout_add_seconds(
                SESSION_HEALTH_SEC, self._check_session_health
            )

        log.info("=== iphonebridge ready (contacts=%d, sinks=%s) ===",
                 self.contacts.count(),
                 [s.name for s in self.sinks])

    def _delete_local(self, keys: list[str]) -> int:
        """Remove messages from local history and remember them as deleted.

        Local only: iOS ignores the MAP Deleted flag (see README
        limitations), so this never touches the phone. The tombstones are
        what stop the startup inbox sweep from re-adding a message that is
        still in the iPhone's inbox window.
        """
        keyset = {k for k in keys if k}
        if not keyset:
            return 0
        record_deleted_keys(config.DELETED_KEYS, keyset)
        if self.listener is not None:
            for k in keyset:
                self.listener.seen_keys.note(k)
        removed = drop_events_by_key(config.EVENTS_JSONL, keyset)
        log.info("local delete: %d message(s) removed from history", removed)
        return removed

    def _refresh_contacts(self, *, raise_on_error: bool = False) -> int:
        """Pull phonebook from iPhone + reload in-process cache. Idempotent.

        Returns the cached contact count. Failures are swallowed by default so
        a periodic tick or a startup hiccup can't take the daemon down; the
        DBus RefreshContacts hook passes raise_on_error so a caller that asked
        for the pull hears about it failing.
        """
        try:
            pulled = pull_phonebook(self.sessions)
            count = self.contacts.refresh()
            log.info("contacts refresh: pulled %d, cached %d", pulled, count)
            return count
        except Exception:
            log.exception("contacts refresh failed — running with previous cache")
            if raise_on_error:
                raise
            return self.contacts.count()

    def _periodic_refresh_contacts(self) -> bool:
        """GLib timeout callback. Return True to keep the timer running."""
        log.info("periodic contacts refresh tick")
        self._refresh_contacts()
        return True

    def stop(self) -> None:
        log.info("=== iphonebridge stopping ===")
        for tid_attr in ("_contacts_refresh_id", "_session_retry_id",
                         "_session_health_id"):
            tid = getattr(self, tid_attr, None)
            if tid is not None:
                try:
                    GLib.source_remove(tid)
                except Exception:
                    pass
                setattr(self, tid_attr, None)
        if self.listener is not None:
            self.listener.stop()
        if self.ancs is not None:
            self.ancs.stop()
        if self.hfp is not None:
            self.hfp.stop()
        self.sessions.close_all()
        bluez_setup.unregister_advert()
        main_loop.quit()

    def run(self) -> None:
        self.start()
        try:
            main_loop.run()
        finally:
            self.stop()

    # ---- internals -------------------------------------------------------

    # ---- read-state ------------------------------------------------

    def _remember_path(self, key: str, path: str) -> None:
        old = self._paths.get(key)
        if old is not None and old != path:
            self._keys_by_path.pop(old, None)
        self._paths[key] = path
        self._keys_by_path[path] = key

    def _watch_read_state(self) -> None:
        """Notice when the iPhone marks a message read.

        The libnotify sink already watches this per popup, but only for as
        long as the popup is up, which is why reading on the phone later
        went unnoticed. This one lives for the life of the daemon.
        """
        if self._read_watch is not None:
            return
        self._read_watch = session_bus.add_signal_receiver(
            self._on_message_props,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path_keyword="path",
        )

    def _on_message_props(self, iface, changed, _invalidated, path=None) -> None:
        if str(iface) != "org.bluez.obex.Message1":
            return
        if not bool(changed.get("Read", False)):
            return
        key = self._keys_by_path.get(str(path))
        if key is None:
            return
        # Nothing changed means this is the echo of our own writeback, so
        # there is nothing to announce.
        if mark_logged_read(config.EVENTS_JSONL, {key}):
            log.info("iPhone marked a message read")
            self._notify_seen([key])

    def mark_read(self, keys) -> int:
        """Mark messages read here and on the iPhone. Returns how many.

        Only messages obexd still exports can be written back, since the
        path is the only handle on them. Anything older is marked locally
        so the app agrees with itself, and the phone keeps its own state.
        """
        keys = [str(k) for k in keys if k]
        if not keys:
            return 0
        pushed = 0
        for key in keys:
            path = self._paths.get(key)
            if path is None:
                continue
            try:
                dbus.Interface(
                    session_bus.get_object("org.bluez.obex", path),
                    "org.freedesktop.DBus.Properties",
                ).Set("org.bluez.obex.Message1", "Read", dbus.Boolean(True))
                pushed += 1
            except dbus.exceptions.DBusException as e:
                log.debug("mark-read failed for %s: %s", path,
                          e.get_dbus_name())
        changed = mark_logged_read(config.EVENTS_JSONL, set(keys))
        log.info("mark read: %d local, %d pushed to the iPhone",
                 changed, pushed)
        if changed:
            self._notify_seen(keys)
        return changed

    def _notify_seen(self, keys) -> None:
        """Announce a read-state change on D-Bus only.

        Deliberately not through _fanout: a SeenEvent is not a message,
        and the JSONL sink would append a line for every read.
        """
        if self._dbus_service is not None:
            self._dbus_service.emit_message(SeenEvent(tuple(keys)))

    def _fanout(self, event: SmsEvent) -> None:
        if event.kind == "sms_received" and event.message_path:
            self._remember_path(
                message_key(event.timestamp or event.seen_at,
                            event.sender_phone or event.sender_email,
                            event.body),
                event.message_path)
        for sink in self.sinks:
            try:
                sink.handle(event)
            except Exception:
                log.exception("sink %s failed on event %s",
                              sink.name, event.handle)
        if self._dbus_service is not None:
            self._dbus_service.emit_message(event)

    def _record_sent(self, recipient: str, body: str, transfer_path: str) -> None:
        """Hook for DBus Send() — log + broadcast a message we just sent so it
        shows up in conversation history alongside incoming messages."""
        event = sms_sent_event(
            recipient, body,
            contact_name=self.contacts.resolve(recipient),
            transfer_path=transfer_path,
        )
        log.info("sms_sent: %d-char body", len(body or ""))
        log.debug("sms_sent to %s: %r", event.display_sender, (body or "")[:80])
        self._fanout(event)

    def _fanout_ancs(self, event: AncsEvent) -> None:
        for sink in self.sinks:
            try:
                handler = getattr(sink, "handle_ancs", None)
                if handler is None:
                    continue  # sink doesn't know about ANCS events
                handler(event)
            except Exception:
                log.exception("sink %s failed on ANCS event %d",
                              sink.name, event.notification_id)
        if self._dbus_service is not None:
            self._dbus_service.emit_ancs(event)

    def _fanout_call(self, event: CallEvent) -> None:
        for sink in self.sinks:
            try:
                handler = getattr(sink, "handle_call", None)
                if handler is None:
                    continue  # sink doesn't know about call events
                handler(event)
            except Exception:
                log.exception("sink %s failed on call event %s",
                              sink.name, event.call_path)
        if self._dbus_service is not None:
            self._dbus_service.emit_call_state(event)

    def _signal(self, signum, _frame):
        log.info("received signal %d, stopping", signum)
        main_loop.quit()
