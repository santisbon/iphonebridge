# Changelog

## [0.9.1] — 2026-08-25

Three message-loss and message-leak fixes. 0.9.0 silently drops repeated
confirmation codes, so upgrading is worth doing promptly.

### Fixed
- **Confirmation codes were silently dropped.** BlueZ exports a live MNS
  push with no `Timestamp`, so a message's key collapsed to
  `(sender, first 40 characters of body)`. In a confirmation code
  everything but the trailing code is identical, and the code sits past
  that prefix, so every code from a sender keyed the same: the first
  arrived and every one after it vanished with no error. Deleting one made
  it permanent, because the tombstone kept matching. Keys now fall back to
  the arrival time, which is the rule the UI already used for ordering.
- **The inbox sweep duplicated messages from iMessage senders**, storing
  the copy truncated at 128 characters. iOS appends a parenthesised MAP
  marker to the originator address in a bMessage vCard — `(smsft)` for an
  SMS forwarded from a paired phone — while the folder listing omits it.
  One person therefore had two identities: two conversations in the app,
  and pushes the sweep could not recognise as already logged. The marker
  is now stripped at the parser and canonicalised in the key, and stored
  keys normalise onto the clean spelling so existing tombstones still
  resolve.
- Marking a thread read no longer fails to reach the iPhone for those
  senders, which was the same mismatch: the path registry was keyed on one
  spelling and the message on the other.

### Security
- **Verification codes are no longer written to the journal.** The
  clipboard sink named the code in both its success line and its
  no-clipboard-tool warning, putting live one-time credentials into a
  persisted, broadly readable log. Both now report only the code's length;
  the value still reaches the clipboard and the desktop notification.
- Message content is out of the journal generally. `sms_received`,
  `sms_sent` and ANCS events logged sender names and the first 40 to 80
  characters of every body at INFO; that moves to DEBUG. Delivery stays
  visible at INFO through content-free lines carrying the message handle
  and a length, and the dedupe skip moves up to INFO so a suppressed
  message and a transfer that never completed are no longer
  indistinguishable.
- A source-wide test walks the AST of `src/` and fails if any log call
  above DEBUG passes message content or a one-time code.

## [0.9.0] — 2026-08-25

### Added
- **The app now looks like the phone it bridges.** The UI is restyled
  after Messages, Phone, and iOS Settings: rounded bubbles in iMessage
  blue and grey, a centred day rule instead of a timestamp on every
  bubble, runs from one sender tightened to 2px, an
  `Adw.NavigationSplitView` conversation list with relative stamps, a
  segmented section switcher, a pill composer with a circular send
  button, green and red circular call buttons, and notification cards.
  All of it in both colour schemes, driven by a token system in the new
  `src/iphonebridge/ui/style.css`.
- **A conversation shows the state of the Bluetooth link carrying it**, as
  a green or amber dot beside quiet secondary text in the conversation
  header. Driven by availability changes and message traffic rather than
  polled: the daemon's `IsHealthy` blocks the main loop for up to 5s on a
  bad link.
- **Read-state syncs in both directions.** Opening a conversation marks it
  read and writes the MAP read flag back to the phone, which iOS honours
  (unlike the delete flag). Reading on the phone clears the unread dot in
  the app. New `Messages1.MarkRead(keys)`, and the `MessageSeen` signal is
  now actually emitted. Conversation rows carry an accent dot when they
  hold something unread.
- `screenshots/`, twelve images across six views in both schemes, plus the
  `seed.py`/`shoot.py` pair that regenerates them from synthetic data.
  Neither the images nor the scripts are packaged.

### Changed
- **BREAKING: every timestamp is stored in UTC.** A local offset is
  unambiguous to a parser but wrong as storage: carry the machine across a
  timezone mid-conversation and the offset changes under you, so lexical
  order stops matching real order inside one log. `parse_map_timestamp`
  now returns UTC, which changes its published contract.
- Message keys normalise their timestamp to UTC before hashing, so a key
  identifies an instant rather than a spelling of one, and tombstones
  written before this release keep matching. No file rewrite: 29 of 32
  tombstones were re-spelled on read in testing, none orphaned.
- `parse_map_timestamp` honours an explicit `Z` or `±HHMM` suffix instead
  of discarding it. iOS sends the bare form, which MAP defines as the
  phone's local time.

### Fixed
- **Replies were appended in the wrong place.** An incoming message has no
  MAP timestamp and fell back to `seen_at` in UTC, while a sent message
  carried a local-offset `timestamp`. The UI ordered the raw ISO strings,
  and "09:31-05:00" sorts before "14:30+00:00" despite being later, so
  every reply sorted to the top of its thread. Ordering now compares
  parsed instants.
- **Every daemon restart duplicated the received messages.** BlueZ exports
  an MNS-pushed message with no `Timestamp` property, so the pushed copy
  keyed on an empty timestamp while the listing copy keyed on the real
  send time, and dedupe could not match them. The guard now pairs the two
  fidelities on sender and body prefix within a delivery window. A
  loosely-matched message is also recorded, because `ListMessages` makes
  obexd export the objects and the resulting `InterfacesAdded` signals
  queue behind the sweep, so every listed message is offered to the guard
  twice in one startup.
- **The delete menu had invisible text in light mode.** The popover is
  parented to its row, so the selected-conversation rule painted the
  popover's own label white. Dark mode masked it.
- The compose button read as a fourth window control. It sat at the end of
  the header, which works on macOS because window controls are on the
  left; on Linux they are on the right. Moved to the start, over the
  sidebar.
- The notifications empty state drew a 128px icon that dominated the pane.
- The four tab icons stopped being drawn when the switcher moved to an
  inline view switcher set to labels only.

## [0.8.0] — 2026-08-25

### Added
- **Delete messages and conversations from local history.** Right-click a
  conversation or a message bubble in the app. New
  `Messages1.DeleteLocal(keys)` rewrites the event log and records
  tombstones, so a deleted message is not re-added by the startup inbox
  sweep while it is still on the phone. Local only, and the app says so:
  iOS accepts and ignores the MAP `Deleted` flag.
- Uninstall script for the deb install (`packaging/deb/uninstall.sh`),
  with `--dry-run`, `--keep-data`, and `--keep-hfp`.
- Release process and end-user install instructions in the docs.

### Fixed
- **Messages went to the wrong number.** The recipient was built by
  prefixing "+" to the digits stored in the contacts cache, so a contact
  without a country code became a foreign address: "+" plus a 10-digit
  US number is a Netherlands number. 161 of 348 numbers in a real
  phonebook were affected. The cache now keeps the raw phone string and
  restores "+" only when the contact carried one.
- **Every swept message appeared twice**, once truncated and once
  complete. The MAP folder listing cuts message text at ~125 characters
  while a bMessage download carries it whole, so the two paths logged
  different bodies for the same message and dedupe never matched.
  Messages are now keyed by a body prefix, inside the truncation point.

### Documented
- Deletions do not sync in either direction, with the mechanism for each
  (measured on iOS 26.6.1).

## [0.7.0] — 2026-08-24

### Added
- **Single `.deb` package**: one `apt install` ships the daemon, CLI, GTK
  app, systemd user unit, desktop entry, icon, metainfo, the ANCS helper,
  and group-based sudoers rules. Build and install instructions in
  `packaging/deb/README.md` (self-contained, including uninstall).
- Conversation history is seeded at startup from the inbox window iOS
  serves over Bluetooth (~10 messages), so a fresh install no longer
  shows an empty Messages tab. Logged to the JSONL sink only — no
  notification or clipboard popups — deduplicated against MNS
  re-announcements, and written oldest-first.
- Glossary in the README (CoD, BlueZ, obexd, OBEX, MAP/MNS, bMessage,
  PBAP, ANCS, HFP/oFono, btmgmt).

### Fixed
- **btmgmt hung forever when run from a service.** It registers stdin in
  its epoll loop, and `/dev/null` — the stdin of every systemd service
  and `subprocess.run` call — is not pollable, so it slept without ever
  opening the management socket. Every "adapter wedge" and "settling
  window" observed while debugging the adapter class was this one bug.
  The adapter class now sets itself at boot, in milliseconds.
- The daemon claims its D-Bus name before the first MAP/PBAP attempt, so
  the app and CLI can reach it during the minute the iPhone may take to
  reconnect at login; the app also watches the name's owner and clears
  its "not reachable" banner without a manual Recheck.
- Conversations order by timestamp rather than ingestion order, so no
  log ordering can invert a thread.

### Changed
- New app icon: a white speech bubble with the Bluetooth rune on an
  iMessage-blue gradient.
- README installation is split into two labeled options (the `.deb` for
  apt-family distros, from source for everything else and for
  development) with a warning against mixing them.

## [0.6.0] — 2026-08-24

### Added
- Start a new conversation from the app: a compose button on the Messages
  tab opens a To: field (number, contact name, or vanity number) over the
  normal compose box; the sent message creates and selects the thread.
- Contact-name autocomplete in the Calls dialer and the new-conversation
  To: field — accent-insensitive, prefix-ranked, popover sized to the
  match list.
- Vanity number dialing (1 (800) MYAPPLE) in the Calls tab and CLI;
  Dial sanitizes formatted numbers to what oFono accepts, fixing
  "+1 555-123-4567"-style input that always failed.
- Setup tab marks which iPhone toggles are actually working, backed by a
  new Messages1.GetStatus D-Bus method (additive).
- Bundled-icon support: SVGs in ui/icons/ resolve like stock theme icons.

### Fixed
- The daemon no longer re-logs (and re-notifies) the whole inbox on
  every obexd restart — six restarts had produced six copies of every
  message in conversation history.
- Contact search: deterministic prefix-first ordering (was set-ordered,
  randomly hiding matches), accent folding (67 accented contacts were
  unfindable), and popover rendering/resize fixes for real typing.
- Default window size fits the whole Setup tab.

### Removed
- The abandoned Flatpak draft; the packaging plan is a single .deb
  shipping daemon, CLI, and UI (see BACKLOG).


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
