"""DBus service the daemon exposes on the session bus for CLI clients.

Bus name:    me.santisbon.iphonebridge
Object path: /me/santisbon/iphonebridge
Interfaces:  me.santisbon.iphonebridge.Messages1   — messaging
             me.santisbon.iphonebridge.Calls1      — HFP call control
             me.santisbon.iphonebridge.Media1      — AVRCP media control

Messages1:
  • Send(string recipient, string body) → string transfer_path
      Send an SMS/iMessage from the iPhone via MAP PushMessage. iOS routes
      as iMessage automatically when the recipient is iMessage-capable.
  • ListRecent(string folder, uint32 limit) → string json
  • GetPhoneStatus() → string json — battery, cellular, model
  • IsHealthy() → bool

Calls1 (HFP, via oFono):
  • Dial(string number) → string call_path
  • AnswerCall(string call_path)
  • HangupCall(string call_path)
  • HangupAll()
  • ListCalls() → string json
  • CallStateChanged(dict)  [signal] — emitted on every call lifecycle change

Media1 (AVRCP, via BlueZ's MediaPlayer1/MediaTransport1):
  • Play() / Pause() / Next() / Previous()
  • SetVolume(uint32 0-127) — absolute A2DP volume
  • SetShuffle(string) / SetRepeat(string) — BlueZ value strings
  • GetMediaState() → string json — flat now-playing snapshot;
      available=false when no player, never raises
  • MediaStateChanged(dict)  [signal] — same flat snapshot

Events1 (live event feed for separate UIs):
  • MessageReceived(dict)   [signal] — a new SMS/iMessage arrived
  • MessageSent(dict)       [signal] — a message we sent via Send()
  • MarkRead(as) -> u       — mark messages read here and on the phone
  • MessageSeen(dict)       [signal] — a message's read-state changed
  • AncsNotification(dict)  [signal] — a per-app ANCS notification
  • PhoneStatusChanged(dict) [signal] — battery/cellular/identity change

Designed to be simple/synchronous. PushMessage typically completes in
<2s on iOS 26.5 over the existing daemon session.
"""
from __future__ import annotations

import json
import logging

import dbus
import dbus.exceptions
import dbus.service

from iphonebridge.bus import session_bus
from iphonebridge.events import dialable
from iphonebridge.hfp.ofono_client import HfpError, HfpManager
from iphonebridge.media.client import (
    REPEAT_VALUES,
    SHUFFLE_VALUES,
    MediaError,
    MediaManager,
)
from iphonebridge.media.events import MediaState
from iphonebridge.obex.map_query import list_recent_messages
from iphonebridge.obex.map_send import send_message
from iphonebridge.obex.sessions import SessionManager
from iphonebridge.phone import build_phone_status

log = logging.getLogger(__name__)

BUS_NAME = "me.santisbon.iphonebridge"
OBJECT_PATH = "/me/santisbon/iphonebridge"
IFACE = "me.santisbon.iphonebridge.Messages1"
CALLS_IFACE = "me.santisbon.iphonebridge.Calls1"
MEDIA_IFACE = "me.santisbon.iphonebridge.Media1"
EVENTS_IFACE = "me.santisbon.iphonebridge.Events1"


def _variant_dict(d: dict) -> dbus.Dictionary:
    """Coerce a plain dict into a D-Bus a{sv}. None → empty string."""
    out = dbus.Dictionary({}, signature="sv")
    for k, v in d.items():
        if v is None:
            out[k] = dbus.String("")
        elif isinstance(v, bool):
            out[k] = dbus.Boolean(v)
        elif isinstance(v, int):
            out[k] = dbus.Int64(v)
        elif isinstance(v, float):
            out[k] = dbus.Double(v)
        elif isinstance(v, (list, tuple)):
            out[k] = dbus.Array([dbus.String(str(x)) for x in v],
                                signature="s")
        else:
            out[k] = dbus.String(str(v))
    return out


class MessagesService(dbus.service.Object):
    def __init__(
        self,
        bus_name: dbus.service.BusName,
        sessions: SessionManager,
        hfp: HfpManager | None = None,
        ancs=None,
        media: MediaManager | None = None,
        phone=None,
        on_sent=None,
        on_refresh_contacts=None,
        on_delete_local=None,
        on_mark_read=None,
        on_dismiss_ancs=None,
    ):
        super().__init__(bus_name, OBJECT_PATH)
        self.sessions = sessions
        self.hfp = hfp
        self.ancs = ancs
        self.media = media
        # PhoneMonitor, duck-typed: only snapshot() is called.
        self.phone = phone
        # on_dismiss_ancs(eid) -> "phone" | "local" — daemon hook that
        # removes a notification locally and, when its uid is still live,
        # performs the ANCS negative action on the iPhone.
        self._on_dismiss_ancs = on_dismiss_ancs
        # on_sent(recipient, body, transfer_path) — daemon hook to record a
        # message we just sent (logs it to history + the event feed).
        self._on_sent = on_sent
        # on_refresh_contacts() -> int — daemon hook to re-pull the phonebook
        # on its own PBAP session and return the cached contact count.
        self._on_refresh_contacts = on_refresh_contacts
        # on_delete_local(keys) -> int — daemon hook removing messages from
        # local history (the phone is never touched; iOS ignores MAP deletes).
        self._on_delete_local = on_delete_local
        # on_mark_read(keys) -> int — daemon hook marking messages read
        # here and, where the message is still exported by obexd, on the
        # iPhone too.
        self._on_mark_read = on_mark_read

    # ---- Messages1 ------------------------------------------------------

    @dbus.service.method(IFACE, in_signature="ss", out_signature="s")
    def Send(self, recipient: str, body: str) -> str:
        log.info("DBus Send called for %s (%d-byte body)", recipient, len(body))
        if not recipient.strip() or not body.strip():
            raise dbus.exceptions.DBusException(
                "recipient and body must both be non-empty",
                name="me.santisbon.iphonebridge.Error.InvalidArgs",
            )
        if self.sessions.map is None:
            raise dbus.exceptions.DBusException(
                "MAP session not open — iPhone toggles probably off",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        try:
            transfer = send_message(self.sessions.map_path, recipient, body)
        except Exception as e:
            log.exception("Send failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.SendFailed"
            )
        # Record the sent message (history + event feed). Never let a logging
        # failure fail the send — the message already went out.
        if self._on_sent is not None:
            try:
                self._on_sent(recipient, body, transfer)
            except Exception:
                log.exception("on_sent hook failed (message was still sent)")
        return transfer

    @dbus.service.method(IFACE, in_signature="su", out_signature="s")
    def ListRecent(self, folder: str, limit: int) -> str:
        """Return up to `limit` recent messages from `folder` as a JSON array."""
        if self.sessions.map is None:
            raise dbus.exceptions.DBusException(
                "MAP session not open — iPhone toggles probably off",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        folder = folder or "telecom/msg/INBOX"
        try:
            msgs = list_recent_messages(self.sessions.map_path,
                                        folder=folder,
                                        limit=max(1, min(int(limit), 200)))
        except Exception as e:
            log.exception("ListRecent failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.QueryFailed"
            )
        return json.dumps(msgs, ensure_ascii=False)

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def GetStatus(self) -> str:
        """Per-profile liveness as JSON: {"map": b, "pbap": b, "ancs": b}.

        These are inferences, not reads of the iPhone's toggles — a live
        session means the corresponding toggle must be on; a dead one means
        the toggle is off or the session is mid-recovery.
        """
        return json.dumps({
            "map": self.sessions.map_alive(),
            "pbap": self.sessions.pbap_alive(),
            "ancs": bool(self.ancs is not None and self.ancs.active),
        })

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def GetPhoneStatus(self) -> str:
        """Battery, cellular and identity as JSON. Never raises: fields
        the phone doesn't offer read as -1 / empty string."""
        if self.phone is None:
            return json.dumps(build_phone_status())
        return json.dumps(self.phone.snapshot(), ensure_ascii=False)

    @dbus.service.method(IFACE, in_signature="", out_signature="b")
    def IsHealthy(self) -> bool:
        # Probe, don't null-check. A re-pair or an obexd restart removes the
        # session objects while we go on holding their paths, and a handle
        # that is merely non-None says nothing about the link.
        return self.sessions.alive()

    @dbus.service.method(IFACE, in_signature="as", out_signature="i")
    def DeleteLocal(self, keys) -> int:
        """Delete messages from local history by content key. Returns the
        number of events removed.

        Local only. iOS accepts and ignores the MAP Deleted flag, so there
        is no honest way to delete on the phone from here.
        """
        keys = [str(k) for k in keys]
        log.info("DBus DeleteLocal called for %d key(s)", len(keys))
        if self._on_delete_local is None:
            raise dbus.exceptions.DBusException(
                "daemon exposed no delete hook",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        try:
            return int(self._on_delete_local(keys))
        except Exception as e:
            log.exception("DeleteLocal failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.DeleteFailed"
            )

    @dbus.service.method(IFACE, in_signature="as", out_signature="i")
    def MarkRead(self, keys) -> int:
        """Mark messages read by content key. Returns how many changed.

        Unlike deletion, iOS honours this: the MAP read flag is written
        back to the phone for any message obexd still exports. Older
        messages are marked locally only, since the object path is the
        only way to address one and obexd drops those between sessions.
        """
        keys = [str(k) for k in keys]
        log.info("DBus MarkRead called for %d key(s)", len(keys))
        if self._on_mark_read is None:
            raise dbus.exceptions.DBusException(
                "daemon exposed no mark-read hook",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        try:
            return int(self._on_mark_read(keys))
        except Exception as e:
            log.exception("MarkRead failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.MarkReadFailed"
            )

    @dbus.service.method(IFACE, in_signature="", out_signature="i")
    def RefreshContacts(self) -> int:
        """Re-pull the phonebook over the daemon's own PBAP session.

        The iPhone grants one OBEX session at a time, so a second process
        opening its own would tear this one down. Callers ask the daemon
        instead of doing the pull themselves.
        """
        log.info("DBus RefreshContacts called")
        if self._on_refresh_contacts is None:
            raise dbus.exceptions.DBusException(
                "daemon exposed no contacts-refresh hook",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        if self.sessions.pbap is None:
            raise dbus.exceptions.DBusException(
                "PBAP session not open — check the iPhone's Sync Contacts toggle",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        try:
            return int(self._on_refresh_contacts())
        except Exception as e:
            log.exception("RefreshContacts failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.RefreshFailed"
            )

    # ---- Calls1 (HFP) ---------------------------------------------------

    def _require_hfp(self) -> HfpManager:
        if self.hfp is None:
            raise dbus.exceptions.DBusException(
                "HFP not available in this daemon build",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        return self.hfp

    @dbus.service.method(CALLS_IFACE, in_signature="s", out_signature="s")
    def Dial(self, number: str) -> str:
        """Place a call. Returns the new oFono VoiceCall object path."""
        log.info("DBus Dial called for %s", number)
        # oFono rejects formatted numbers (spaces, parens, dashes) with
        # InvalidFormat — strip to digits/+/*/# here, the one choke point
        # every caller (UI, CLI) flows through.
        number = dialable(number)
        if not number.strip("+*#"):
            raise dbus.exceptions.DBusException(
                "number must contain digits",
                name="me.santisbon.iphonebridge.Error.InvalidArgs",
            )
        try:
            return self._require_hfp().dial(number)
        except HfpError as e:
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.NotReady"
            )
        except Exception as e:
            log.exception("Dial failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.CallFailed"
            )

    @dbus.service.method(CALLS_IFACE, in_signature="s", out_signature="")
    def AnswerCall(self, call_path: str) -> None:
        log.info("DBus AnswerCall %s", call_path)
        try:
            self._require_hfp().answer(call_path)
        except HfpError as e:
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.NotReady"
            )
        except Exception as e:
            log.exception("AnswerCall failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.CallFailed"
            )

    @dbus.service.method(CALLS_IFACE, in_signature="s", out_signature="")
    def HangupCall(self, call_path: str) -> None:
        log.info("DBus HangupCall %s", call_path)
        try:
            self._require_hfp().hangup(call_path)
        except HfpError as e:
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.NotReady"
            )
        except Exception as e:
            log.exception("HangupCall failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.CallFailed"
            )

    @dbus.service.method(CALLS_IFACE, in_signature="", out_signature="")
    def HangupAll(self) -> None:
        log.info("DBus HangupAll")
        try:
            self._require_hfp().hangup_all()
        except HfpError as e:
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.NotReady"
            )
        except Exception as e:
            log.exception("HangupAll failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.CallFailed"
            )

    @dbus.service.method(CALLS_IFACE, in_signature="", out_signature="s")
    def ListCalls(self) -> str:
        """Return the currently-tracked calls as a JSON array."""
        calls = self.hfp.list_calls() if self.hfp is not None else []
        return json.dumps(calls, ensure_ascii=False)

    @dbus.service.signal(CALLS_IFACE, signature="a{sv}")
    def CallStateChanged(self, props):
        """Emitted on every call lifecycle change. Payload is CallEvent.to_dict()."""

    def emit_call_state(self, event) -> None:
        """Daemon-side helper — push a CallEvent out as a CallStateChanged signal."""
        try:
            self.CallStateChanged(_variant_dict(event.to_dict()))
        except Exception:
            log.exception("CallStateChanged emit failed")

    # ---- Media1 (AVRCP via BlueZ) ---------------------------------------

    def _require_media(self) -> MediaManager:
        if self.media is None:
            raise dbus.exceptions.DBusException(
                "media control not available in this daemon build",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        return self.media

    def _media_command(self, verb: str, fn) -> None:
        try:
            fn(self._require_media())
        except MediaError as e:
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.NotReady"
            )
        except dbus.exceptions.DBusException:
            raise
        except Exception as e:
            log.exception("%s failed", verb)
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.MediaFailed"
            )

    @dbus.service.method(MEDIA_IFACE, in_signature="", out_signature="")
    def Play(self) -> None:
        log.info("DBus Play")
        self._media_command("Play", lambda m: m.play())

    @dbus.service.method(MEDIA_IFACE, in_signature="", out_signature="")
    def Pause(self) -> None:
        log.info("DBus Pause")
        self._media_command("Pause", lambda m: m.pause())

    @dbus.service.method(MEDIA_IFACE, in_signature="", out_signature="")
    def Next(self) -> None:
        log.info("DBus Next")
        self._media_command("Next", lambda m: m.next())

    @dbus.service.method(MEDIA_IFACE, in_signature="", out_signature="")
    def Previous(self) -> None:
        log.info("DBus Previous")
        self._media_command("Previous", lambda m: m.previous())

    @dbus.service.method(MEDIA_IFACE, in_signature="u", out_signature="")
    def SetVolume(self, volume: int) -> None:
        volume = int(volume)
        if not 0 <= volume <= 127:
            raise dbus.exceptions.DBusException(
                "volume must be 0-127",
                name="me.santisbon.iphonebridge.Error.InvalidArgs",
            )
        self._media_command("SetVolume", lambda m: m.set_volume(volume))

    @dbus.service.method(MEDIA_IFACE, in_signature="s", out_signature="")
    def SetShuffle(self, value: str) -> None:
        value = str(value)
        if value not in SHUFFLE_VALUES:
            raise dbus.exceptions.DBusException(
                f"shuffle must be one of {sorted(SHUFFLE_VALUES)}",
                name="me.santisbon.iphonebridge.Error.InvalidArgs",
            )
        log.info("DBus SetShuffle %s", value)
        self._media_command("SetShuffle", lambda m: m.set_shuffle(value))

    @dbus.service.method(MEDIA_IFACE, in_signature="s", out_signature="")
    def SetRepeat(self, value: str) -> None:
        value = str(value)
        if value not in REPEAT_VALUES:
            raise dbus.exceptions.DBusException(
                f"repeat must be one of {sorted(REPEAT_VALUES)}",
                name="me.santisbon.iphonebridge.Error.InvalidArgs",
            )
        log.info("DBus SetRepeat %s", value)
        self._media_command("SetRepeat", lambda m: m.set_repeat(value))

    @dbus.service.method(MEDIA_IFACE, in_signature="", out_signature="s")
    def GetMediaState(self) -> str:
        """The now-playing snapshot as JSON. Never raises: with no player
        connected the payload simply says available=false."""
        if self.media is None:
            return json.dumps(MediaState().to_dict())
        return json.dumps(self.media.snapshot(), ensure_ascii=False)

    @dbus.service.signal(MEDIA_IFACE, signature="a{sv}")
    def MediaStateChanged(self, props):
        """Emitted whenever the player, track, settings or volume change.
        Payload is the same flat dict GetMediaState returns."""

    def emit_media_state(self, state: dict) -> None:
        """Daemon-side helper — push a media snapshot out as a signal."""
        try:
            self.MediaStateChanged(_variant_dict(state))
        except Exception:
            log.exception("MediaStateChanged emit failed")

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def PhoneStatusChanged(self, props):
        """Emitted when battery, cellular or identity changes. Payload is
        the same flat dict GetPhoneStatus returns."""

    def emit_phone_status(self, state: dict) -> None:
        """Daemon-side helper — push a phone snapshot out as a signal."""
        try:
            self.PhoneStatusChanged(_variant_dict(state))
        except Exception:
            log.exception("PhoneStatusChanged emit failed")

    # ---- Events1 (live event feed for separate UIs) ---------------------

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def MessageReceived(self, props):
        """Emitted when a new SMS/iMessage arrives. Payload: SmsEvent.to_dict()."""

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def MessageSent(self, props):
        """Emitted when we send a message via Send(). Payload: SmsEvent.to_dict()."""

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def MessageSeen(self, props):
        """Emitted on a message read-state change. Payload: SmsEvent.to_dict()."""

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def DismissNotification(self, eid) -> str:
        """Dismiss one notification by its seen_at stamp. Returns where it
        was dismissed: "phone" (negative action sent to the iPhone as
        well) or "local" (removed from history and the feed only — the
        notification predates the current BLE session, or iOS declared no
        negative action for it)."""
        eid = str(eid)
        log.info("DBus DismissNotification called")
        if self._on_dismiss_ancs is None:
            raise dbus.exceptions.DBusException(
                "daemon exposed no dismiss hook",
                name="me.santisbon.iphonebridge.Error.NotReady",
            )
        try:
            return str(self._on_dismiss_ancs(eid))
        except Exception as e:
            log.exception("DismissNotification failed")
            raise dbus.exceptions.DBusException(
                str(e), name="me.santisbon.iphonebridge.Error.DismissFailed"
            )

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def AncsDismissed(self, props):
        """Emitted when a notification is dismissed — from either end.
        Payload: {"eid": seen_at stamp of the notification}."""

    def emit_ancs_dismissed(self, eid: str) -> None:
        try:
            self.AncsDismissed(_variant_dict({"eid": eid}))
        except Exception:
            log.exception("AncsDismissed emit failed")

    @dbus.service.signal(EVENTS_IFACE, signature="a{sv}")
    def AncsNotification(self, props):
        """Emitted on a per-app ANCS notification. Payload: AncsEvent.to_dict()."""

    def emit_message(self, event) -> None:
        """Daemon-side helper — push an SmsEvent out as a D-Bus signal."""
        try:
            payload = _variant_dict(event.to_dict())
            kind = getattr(event, "kind", "")
            if kind == "sms_seen":
                self.MessageSeen(payload)
            elif kind == "sms_sent":
                self.MessageSent(payload)
            else:
                self.MessageReceived(payload)
        except Exception:
            log.exception("message signal emit failed")

    def emit_ancs(self, event) -> None:
        """Daemon-side helper — push an AncsEvent out as an AncsNotification signal."""
        try:
            self.AncsNotification(_variant_dict(event.to_dict()))
        except Exception:
            log.exception("AncsNotification emit failed")


def claim_bus_name() -> dbus.service.BusName:
    """Acquire me.santisbon.iphonebridge on the session bus.

    Raises if the name is already taken by another instance — caller
    should treat that as 'another daemon is already running'.
    """
    return dbus.service.BusName(
        BUS_NAME,
        bus=session_bus,
        do_not_queue=True,
        replace_existing=False,
    )
