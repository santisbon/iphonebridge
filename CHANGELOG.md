# Changelog

## [Unreleased]

## [0.5.0] — 2026-08-23

First release of the hard fork of
[gabrielmeir53/iphonebridge](https://github.com/gabrielmeir53/iphonebridge),
forked at v0.4.2 and maintained at
[santisbon/iphonebridge](https://github.com/santisbon/iphonebridge).

### Breaking
- D-Bus bus name, object path, interfaces, error names, and app ID renamed
  from `com.gabriel.*` to `me.santisbon.*`; desktop entry, icon, metainfo,
  and flatpak manifest files renamed to match.

### Added
- `Messages1.RefreshContacts` D-Bus method; `contacts-sync` asks the
  running daemon instead of tearing down its OBEX sessions.
- iMessage senders addressed by Apple ID email now resolve to contact
  names: EMAIL extracted from bMessage vCards, `emails` table in the
  contacts cache, email-aware `resolve()`, UI fallback.
- Session health check: the daemon detects MAP/PBAP sessions dying under
  it (re-pair, obexd restart, iPhone timeout), drops to DEGRADED, and
  reopens automatically; `IsHealthy` probes the link instead of
  null-checking.
- `workflow_dispatch` trigger on CI.

### Fixed
- sudoers rule hardcoded the original author's username; now rendered
  from $SUDO_USER with the btmgmt path resolved and the rendered file
  visudo-checked.
- systemd unit hardcoded the author's clone path; now an @INSTALL_DIR@
  placeholder substituted at install.
- Daemon crash-looped at startup when oFono was absent.
- BLE advert registration reported success it couldn't verify
  (ActiveInstances is adapter-wide); now async with honest callbacks,
  cutting startup from ~12s to under 2s.
- Unescaped ampersand blanked the "SMS & iMessage" subtitle in the app.

### Docs
- README: KDE Plasma throughout, conda-venv trap, install restructure
  (adapter class as its own step, placeholder-substituted unit install),
  desktop-launcher install, "Working on the code" section, accuracy pass.

## [0.4.2] — 2026-05-20

### Verification codes auto-copied to the clipboard

- When an incoming text carries a one-time / 2FA code, the daemon detects it
  and copies it straight to the system clipboard, with a short "Code copied"
  notification — paste with Ctrl+V, no reaching for the phone. New
  `ClipboardSink`.
- Detection requires a verification keyword *and* a 4-8 digit number, so an
  ordinary text that just happens to contain a number doesn't trigger.
- Uses `wl-copy` (Wayland) or `xclip` / `xsel` (X11) — install `wl-clipboard`
  for the Wayland path.

## [0.4.1] — 2026-05-20

### Sent messages in conversation history

- The daemon now records every message sent through iphonebridge (the UI
  compose box or `iphonebridge sms-send`) to `events.jsonl` as a `sms_sent`
  event, and broadcasts a `MessageSent` signal on `Events1`. The UI threads
  these in, so a conversation shows both sides — incoming **and** the replies
  you sent from the desktop.
- No desktop notification fires for your own sent messages.
- Note: messages composed on the iPhone itself remain invisible — iOS does
  not expose sent content over MAP (the `sent` folder is empty, and no MNS
  push fires for outgoing). This was verified empirically; see the commit.

## [0.4.0] — 2026-05-20

### Phase 2d — GTK4 / libadwaita desktop app

- **`iphonebridge-ui`** — a standalone GTK4 / libadwaita app, separate from
  the daemon, talking to it over D-Bus. Four surfaces:
  - **Messages** — SMS/iMessage threads with history and a compose box
  - **Notifications** — a live feed of per-app ANCS notifications
  - **Calls** — a dialer plus answer / hang-up controls for active calls
  - **Setup** — daemon health, data counts, and the iPhone-toggle checklist
- New `src/iphonebridge/ui/` package; `DaemonClient` subscribes to the
  daemon's live signals and reads history from `events.jsonl`.
- Daemon broadcasts a live event feed on a new D-Bus interface
  `com.gabriel.iphonebridge.Events1` (`MessageReceived`, `MessageSeen`,
  `AncsNotification` signals) for the UI to consume.
- `data/` — `.desktop` entry, AppStream metainfo, and an app icon.

## [0.3.0] — 2026-05-20

### Phase 2c — HFP Hands-Free calls

- **Take and place iPhone calls on the laptop.** New `src/iphonebridge/hfp/`
  subsystem: call control runs through oFono (`org.ofono`, system bus), and
  call audio (SCO) rides PipeWire's oFono HFP backend.
- Incoming calls raise a desktop notification with **Answer / Decline**
  buttons; caller ID is resolved against the contacts cache.
- New CLI: `call <number|contact>`, `hangup`, `calls`, and `hfp-enable`
  (writes the WirePlumber config that routes HFP through oFono).
- New D-Bus interface `com.gabriel.iphonebridge.Calls1` — `Dial`,
  `AnswerCall`, `HangupCall`, `HangupAll`, `ListCalls`, and a
  `CallStateChanged` signal.
- Daemon: sinks now initialise independently of the MAP/PBAP sessions, so
  ANCS and call notifications reach the desktop even in degraded mode.
- Empirically confirmed against iPhone 16 Pro Max / iOS 26.5 — including
  **3/3 reliable outgoing dials**, which overturns the old "HFP HF can't
  reliably ATD on iPhone" assumption. See `spike/05b_hfp_ofono.py` and the
  HFP addendum in `spike/RESULTS.md`.
- `pyproject.toml`: `testpaths = ["tests"]` so a bare `pytest` no longer
  recurses (and hangs on) the whole repo tree.

## [0.1.0] — 2026-05-19

First tagged release. Working iphonebridge daemon on Pop!_OS 24.04
against iPhone 16 Pro Max running iOS 26.5.

### Confirmed working
- Real-time SMS + iMessage notifications via MAP MNS push
- Outgoing SMS + iMessage send via MAP `PushMessage` — iOS auto-routes
  as iMessage when the recipient is iMessage-capable
- 1000+ contacts pulled via PBAP, cached in SQLite, name-resolved for
  incoming messages
- systemd user service for autostart, graceful degradation when iPhone
  toggles are off, automatic retry every 60s
- DBus service `com.gabriel.iphonebridge.Messages1` with Send,
  ListRecent, IsHealthy methods
- CLI: `run`, `doctor`, `pair-setup`, `sms-list`, `sms-send`,
  `contacts-sync`, `version`

### Documented constraints (won't change)
- No iMessage attachments / reactions / read receipts / typing
  indicators (MAP doesn't expose them)
- No group iMessage / MMS / RCS (MAP is 1:1 only)
- No outgoing call audio routing (HFP HF role — Phase 2c)

## Early development notes (2026-05-19, upstream)

### Project-defining discoveries (2026-05-19, post-launch)

- **Incoming iMessage IS exposed via MAP on iOS 26.5 / iPhone 16 Pro Max**, labeled as `Type: sms-gsm` indistinguishably from SMS. This contradicts every prior Bluetooth-on-Linux writeup. Verified: sender (Contact B, confirmed iMessage thread, both on iPhone) sent "test-iphonebridge-XYZ123" → daemon received and rendered the body within ~2s.

- **Outgoing iMessage via MAP `PushMessage` ALSO works.** Tested via `spike/07_map_send.py`: constructed a minimal bMessage (originator + BENV-wrapped recipient VCARD), called `MessageAccess1.PushMessage(sourcefile, "telecom/msg/outbox", {})` — transfer completed, the iPhone's outgoing bubble appeared **blue** (iMessage) in the recipient thread.

Together: **iphonebridge is potentially the first free open-source Linux iMessage bridge that does not require a Mac relay**. README, BACKLOG, RESULTS.md updated accordingly.

### Phase 1 — MVP daemon (2026-05-19)
- Working iphonebridge daemon: BLE-advert / CoD startup dance, long-lived MAP + PBAP sessions, MAP MNS push subscription, bMessage parsing, SQLite contacts cache, libnotify + JSONL sinks.
- Typer CLI: `run`, `doctor`, `sms-list`, `contacts-sync`, `version`.
- systemd user service for auto-start.
- sudoers.d entry (`install-cod-sudoers.sh`) for passwordless `btmgmt class 4 8` so CoD survives reboots.
- End-to-end verified: SMS from a known contact arrives as a GNOME desktop notification within ~20 ms of the iPhone push.

### Phase 0 — Empirical spike (2026-05-19)
- Confirmed against iPhone 16 Pro Max / iOS 26.5: MAP read ✓, MAP MNS push ✓, PBAP (1957 contacts) ✓, HFP HF role partial (needs WirePlumber config work), ANCS deferred (needs BLE-only pairing flow incompatible with the BR/EDR pair MAP/PBAP need).
- Documented non-obvious findings in `spike/RESULTS.md`: the hidden-toggle dance, single-OBEX-session-per-fresh-obexd, SMS body in `Subject`, PBAP `Select` vs `SetFolder`, BR/EDR-vs-BLE pairing mutex for ANCS.
