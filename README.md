<div align="center">

# 📱🐧 iPhone Bridge

**Your iPhone's messages, calls, notifications, and contacts — on your Linux desktop, over Bluetooth.**

[![CI](https://github.com/santisbon/iphonebridge/actions/workflows/ci.yml/badge.svg)](https://github.com/santisbon/iphonebridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/santisbon/iphonebridge?color=brightgreen)](https://github.com/santisbon/iphonebridge/releases/latest)
[![License: GPL v2](https://img.shields.io/badge/license-GPL--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![Platform: Linux](https://img.shields.io/badge/platform-Linux%20(GNOME%20%2F%20KDE)-lightgrey.svg)](#requirements)

*No Mac relay. No cloud service. No subscription. Just Bluetooth.*

</div>

---

Windows and macOS users can get their iPhone's texts and notifications on the desktop. There has never been a Linux equivalent:

- KDE Connect needs the Android/iOS *app* and on iOS it's missing notifications, SMS, and needs the iPhone app on-screen to maintain the connection. 
- `ancs4linux` does notifications only.
- Mac-relay bridges (BlueBubbles, AirMessage) need an actual Mac. 
- Beeper no longer supports iMessage.
- Microsoft's Phone Link is Windows-only.

**This is that missing piece.** It's a small Python daemon that talks to a paired iPhone over standard Bluetooth profiles (MAP, PBAP, ANCS, HFP) and surfaces everything as native desktop notifications, a CLI, and a GTK4 desktop app.

## ✨ What it does

| Feature | How | Status |
|---|---|---|
| 📨 **Incoming SMS + iMessage** as desktop notifications | MAP MNS push | ✅ |
| 📤 **Send SMS + iMessage** from the CLI or app | MAP `PushMessage` | ✅ |
| 📋 **Verification codes auto-copied** to the clipboard | OTP detection | ✅ |
| 👤 **Contact-name resolution** (1000s of contacts) | PBAP → SQLite cache | ✅ |
| 🔔 **Every app's notifications** — Slack, WhatsApp, Mail… | ANCS over BLE | ✅ |
| 📞 **Take & place phone calls** — caller ID, answer/decline, dial | HFP via oFono | ✅ |
| 🔁 **Read-state sync** — read on either device, syncs to both | MAP read-state writes | ✅ |
| 📜 **Message history** — incoming + your desktop replies | `sms-list` / the app | ✅ |
| 🖥️ **Desktop app** — conversations, notification feed, call UI | GTK4 / libadwaita | ✅ |
| ⚙️ **Runs unattended** | systemd user service | ✅ |

### Details
- **Incoming messages** appear as **persistent notifications** — they stay until you dismiss them on the desktop *or* read the message on your iPhone. **Read-state syncs both ways.**
- **Verification codes** — when a text carries a one-time / 2FA code, iphonebridge detects it and copies it to your clipboard automatically; press <kbd>Ctrl</kbd>+<kbd>V</kbd> to paste. Detection needs both a verification keyword and a 4–8 digit number, so ordinary texts don't trigger it.
- **Incoming calls** raise a notification with **Answer / Decline** buttons that act on the call directly.
- **Sent messages** — replies you send from the desktop are recorded into conversation history, so a thread shows both sides.
- **History starts shallow** — a fresh install seeds conversations with the recent inbox window iOS exposes over Bluetooth (roughly the last 10 messages); iOS does not serve older history to any Bluetooth bridge. Threads grow from install day forward.

### Note
Every prior writeup of Bluetooth on iOS says **iMessage is invisible** to a paired computer — that you *must* use a Mac relay to bridge blue-bubble messages.

**That is not true on iOS 26.5.** iphonebridge receives *and sends* iMessage through the standard MAP Bluetooth profile, with no Mac, no Apple ID login, nothing. iOS labels iMessage and SMS identically (`Type: sms-gsm`) and exposes both. Outgoing messages route as iMessage automatically when the recipient is iMessage-capable.

As far as we know, **iphonebridge is the first free, open-source, Mac-free iMessage bridge for Linux.** The empirical proof is in [`spike/RESULTS.md`](spike/RESULTS.md) §6.

## 🚧 Limitations

These are Apple's Bluetooth-stack limits, not bugs:

- No iMessage **attachments, reactions, read receipts, or typing indicators** (MAP doesn't carry them).
- No **group iMessage / MMS / RCS** — MAP is 1-to-1 only.
- **Messages composed on the iPhone itself don't sync** — iOS exposes only your *inbox* over MAP, never the sent folder. Replies you send *from* iphonebridge are recorded into conversation history; texts you type on the phone aren't visible to any Bluetooth bridge.
- HFP calls are **1-to-1 voice only** — no conference calls, no FaceTime (HFP carries neither).
- Notification *bodies* are subject to the iPhone's "Show Previews" setting.
- **Deletions don't sync, in either direction.** Deleting on the iPhone does
  not remove the message here: iOS sends no deletion event over MAP, an open
  OBEX session keeps serving the pre-delete view, and conversation history is
  an append-only log with no retraction. Deleting from Linux does not remove
  it there either: writing the per-message `Deleted` flag is accepted without
  error but ignored, and the message reappears on the next reconnect after
  BlueZ drops it from the current session's view. The `Read` flag on the same
  interface does sync both ways, so this is an iOS choice rather than a BlueZ
  limit. Measured on iOS 26.6.1; a delete on the phone also renumbers every
  remaining message handle, which is why history is deduplicated by content
  rather than by handle.

## 📋 Requirements

| | Minimum | Tested with |
|---|---|---|
| **OS** | Linux (GNOME or KDE Plasma), BlueZ 5.72+ | Pop!_OS 24.04 (GNOME) · Kubuntu 26.04 (Plasma 6) |
| **Bluetooth adapter** | Intel chipset (for ANCS) | Intel AX-series · BE200 (MAP/PBAP/HFP work; ANCS doesn't — see Troubleshooting) |
| **Python** | 3.10+ | 3.12, 3.14 |
| **iPhone** | iOS 16.5+ | iPhone 16 Pro Max, iOS 26.5 · iPhone 17 Pro, iOS 26.6.1 |
| **System packages** | `bluez`, `bluez-obexd`, `python3-dbus`, `python3-gi` (+ `ofono` for calls, `wl-clipboard` for code auto-copy) | — |

> ⚠️ **Adapter chipset matters for ANCS.** Per-app notifications need a real BLE bond with the iPhone. Intel adapters do this reliably. **Realtek adapters and every USB Bluetooth dongle tested so far do *not*** — their firmware negotiates legacy keys that block the cross-transport key derivation iOS needs. SMS/iMessage/contacts (MAP/PBAP) work on any adapter; only ANCS is picky. See [bmh129/ancs4linux's hardware notes](https://github.com/bmh129/ancs4linux).

## 🚀 Installation

Two ways to install. Pick **exactly one** as mixing the two is confusing to debug: from-source symlinks in `~/.local/bin` shadow a deb-installed `/usr/bin/iphonebridge` on most PATH setups.

### With a `.deb` package

Use this on any apt-based distro, e.g. **Debian, Ubuntu and its flavors (Kubuntu, Xubuntu…), Pop!_OS, Linux Mint**. Sandboxed formats (Snap/Flatpak) can't ship the daemon's privileged pieces without defeating the purpose of sandboxing.

One package installs everything: daemon, CLI, desktop app, launcher
entry, systemd unit, and the privileged sudoers rules.

Download the `.deb` from the
[latest release](https://github.com/santisbon/iphonebridge/releases/latest),
then:

```bash
sudo apt install ./iphonebridge_*_all.deb
sudo adduser $USER iphonebridge # then reboot
```

Reboot is needed because a re-login is not enough — user services keep their old groups
while any session survives the logout. Then pair your iPhone and run
`iphonebridge pair-setup`.

The full walkthrough, including the iPhone-side toggles, optional calls
and per-app notifications, building the package yourself, and a
teardown script, is in
[`packaging/deb/README.md`](packaging/deb/README.md).

### From source

<details>

<summary> Install from source </summary>

The rest of this section walks through it: venv, symlinks, sudoers
installers, and a path-substituted systemd unit. The package names in step 1
are Debian-family. On non-apt distros, e.g. **Fedora, Arch, openSUSE**  
install your distro's equivalents of BlueZ, `bluez-obexd`, dbus-python, PyGObject, 
and the GTK4/libadwaita introspection bindings. 

You can also use this on any distro when you're developing —
edits to the clone take effect without rebuilding a package (see
*Working on the code*).


#### 1 · System packages

```bash
sudo apt install bluez bluez-obexd python3-dbus python3-gi python3-venv
# For the desktop app (iphonebridge-ui):
sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1
# For auto-copying verification codes (Wayland):
sudo apt install wl-clipboard
```

#### 2 · Clone & install

```bash
git clone https://github.com/santisbon/iphonebridge.git
cd iphonebridge

# A venv that inherits the system PyGObject + dbus-python.
# (Never install those two from PyPI — the builds are notoriously fragile.)
# Spell out /usr/bin/python3: --system-site-packages inherits the *creating*
# interpreter's packages, and only the system one can see apt's dist-packages.
/usr/bin/python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .

# Put `iphonebridge` (CLI + daemon) and `iphonebridge-ui` (app) on your PATH
mkdir -p ~/.local/bin
ln -sf "$(pwd)/.venv/bin/iphonebridge" ~/.local/bin/iphonebridge
ln -sf "$(pwd)/.venv/bin/iphonebridge-ui" ~/.local/bin/iphonebridge-ui
```

#### 3 · Pair your iPhone

Pair normally with your desktop's Bluetooth panel, or with `bluetoothctl`:

- **GNOME** — Settings → Bluetooth → tap the iPhone under *Other Devices*
- **KDE Plasma** — System Settings → Bluetooth → *Add New Device* (same button in the tray applet)
- **CLI** — `bluetoothctl` → `scan on`, `pair <MAC>`, `trust <MAC>`, `quit`

Keep the iPhone on its **Settings → Bluetooth** screen while you pair; iOS is only
discoverable while that screen is open. Confirm the matching 6-digit code on both sides.

If this iPhone was paired to this computer before, remove the old bond on **both**
ends first (Linux: the Bluetooth panel's Remove/Forget, or `bluetoothctl remove <MAC>`;
iPhone: ⓘ → Forget This Device). Forgetting on only one side leaves a stale
half-bond that makes the new pairing fail or misbehave.

Then run the wizard:

```bash
iphonebridge pair-setup
```

It finds your iPhone among paired devices, writes `~/.config/iphonebridge/local.env`, and prints the iPhone-side steps.

#### 4 · Let the daemon set the adapter class

iOS only offers the message and contacts toggles to a device whose Bluetooth
Class-of-Device is **A/V Hands-Free** (major 4, minor 8). Your adapter ships as
*Computer*, and changing that needs root, so grant the daemon one narrowly
scoped rule:

```bash
sudo bash systemd/install-cod-sudoers.sh
```

It unlocks exactly `btmgmt class 4 8` for your user and nothing else. The daemon
re-applies the class on every start, which matters because it resets on reboot
and on `systemctl restart bluetooth`.

Don't want a sudoers rule? Run `sudo btmgmt class 4 8` by hand instead, and
again after each reboot. Check the current value any time with
`iphonebridge doctor`.

#### 5 · Install the daemon as a service

The unit ships with an `@INSTALL_DIR@` placeholder, so substitute your clone
path rather than copying it straight across:

```bash
mkdir -p ~/.config/systemd/user
sed "s|@INSTALL_DIR@|$(pwd)|g" systemd/iphonebridge.service \
  > ~/.config/systemd/user/iphonebridge.service
systemctl --user daemon-reload
systemctl --user enable --now iphonebridge
```

Check it came up with `systemctl --user status iphonebridge` and
`journalctl --user -u iphonebridge -f`. Starting without the toggles from step 6
is expected: the daemon logs `DEGRADED mode`, stays running, and retries every
60s.

#### 6 · iPhone-side toggles

On the iPhone: **Settings → Bluetooth → tap the ⓘ next to your computer →** enable

- **Show Message Notifications** — gates SMS/iMessage (MAP)
- **Sync Contacts** — gates contacts (PBAP)
- **Show System Notifications** — gates per-app notifications (ANCS)

> The toggles need both halves of the setup above: the A/V Hands-Free class from step 4, and the ANCS-soliciting BLE advertisement the daemon registers at startup. If they aren't there, confirm `iphonebridge doctor` reports the class as OK, then forget + re-pair — iOS reads the class at pairing time and caches it.

Two behaviours that look like faults but aren't:

- **The toggles disappear whenever the daemon is stopped.** They depend on that BLE advertisement, which goes away with the process. Start the daemon and they come back.
- **A forget + re-pair resets all the toggles to off.** They stay visible, so it's easy to miss. Re-enable them after every re-pair, then give the daemon 60s to retry.

Only two toggles appear until ANCS is working: *Show Message Notifications* and *Sync Contacts*. *Show System Notifications* shows up once the BLE bond from step 7 exists.


#### 7 · (Optional) Enable per-app notifications — ANCS

ANCS needs a true BLE bond, which only forms during a fresh pairing while the adapter is correctly configured. One-time setup:

```bash
# Install the privileged helper (writes one specific BlueZ setting)
sudo bash systemd/install-ancs-sudoers.sh

# Apply it and re-pair
iphonebridge ancs-enable
```

Then **forget + re-pair** the iPhone one more time (the wizard walks you through it). After the fresh pair, iOS performs cross-transport key derivation and the BLE bond sticks — ANCS notifications start flowing automatically. You only do this once.

*Forget* means dropping the bond on **both** ends; one-sided forgetting leaves a
stale half-bond that breaks the re-pair. On the iPhone: **Settings → Bluetooth →
ⓘ → Forget This Device**. On Linux, pick one:

- **GNOME** — Settings → Bluetooth → the device → *Forget*
- **KDE Plasma** — System Settings → Bluetooth → the device → *Remove* (trash icon)
- **CLI** — `bluetoothctl remove <MAC>`

After the re-pair, re-enable the step 6 toggles on the iPhone, which the
re-pair switched off.

The re-pair also kills the daemon's MAP and PBAP sessions, but you don't have to
do anything about that: a health check notices within 60s, drops to DEGRADED, and
the reopen loop restores both sessions and the MNS listener on its next tick — so
allow up to about two minutes. `systemctl --user restart iphonebridge` still gets
you there immediately if you'd rather not wait.

#### 8 · (Optional) Enable phone calls — HFP

To take and place calls on the laptop, iphonebridge uses **oFono** for HFP
call control and PipeWire's oFono backend for the call audio.

```bash
# Install oFono
sudo apt install ofono
sudo systemctl enable --now ofono

# Write the WirePlumber config + print the remaining steps
iphonebridge hfp-enable
```

`hfp-enable` writes `~/.config/wireplumber/wireplumber.conf.d/51-bluez-hfp-hf.conf`
(routing HFP through oFono) and restarts WirePlumber. Follow its printed
steps — restart oFono **after** WirePlumber so it can claim the HFP profile,
and reconnect the iPhone.

Then restart the bridge daemon, which is what actually enables calls:

```bash
systemctl --user restart iphonebridge
```

The daemon looks for oFono once, at startup. If it started before you installed
oFono it logged `oFono not available — HFP calls disabled` and left call control
dormant for the life of the process; nothing reconnects it later. After the
restart the log should read `HFP manager started (oFono); modem=...`.

Incoming calls then pop up with **Answer / Decline** buttons. Place calls with
`iphonebridge call`.

</details>

## 🖥️ Desktop app

GTK4 / libadwaita app — a separate process from the daemon, talking to it over D-Bus, so you can open and close it freely while the daemon keeps running in the background.
```bash
iphonebridge-ui
```

### Adding it to your app launcher (if installed from source)

The repo ships both pieces already — `data/me.santisbon.iphonebridge.UI.desktop`
and `data/icons/me.santisbon.iphonebridge.UI.svg`. For a user-level install,
copy them into place and rewrite `Exec` to an absolute path:

```bash
APPS=~/.local/share/applications
ICONS=~/.local/share/icons/hicolor/scalable/apps
mkdir -p "$APPS" "$ICONS"

install -m 644 data/icons/me.santisbon.iphonebridge.UI.svg "$ICONS/"
sed "s|^Exec=iphonebridge-ui$|Exec=$HOME/.local/bin/iphonebridge-ui|" \
  data/me.santisbon.iphonebridge.UI.desktop \
  > "$APPS/me.santisbon.iphonebridge.UI.desktop"

update-desktop-database "$APPS"
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
kbuildsycoca6 --noincremental   # KDE only; GNOME picks it up on its own
```

The `Exec` rewrite is the part that matters. The shipped entry says
`Exec=iphonebridge-ui`, which is correct for a distro package that puts the
binary in `/usr/bin`, but a from-source install puts it in `~/.local/bin` —
and that directory is usually absent from the systemd user environment, which
is what Plasma launches menu entries through. Left as-is, the entry appears in
the menu and silently fails to start.

Don't rename the file. It has to match `APP_ID` in `src/iphonebridge/ui/app.py`
or the taskbar won't associate the running window with this icon.

Check it registered:

```bash
desktop-file-validate ~/.local/share/applications/me.santisbon.iphonebridge.UI.desktop
gio launch ~/.local/share/applications/me.santisbon.iphonebridge.UI.desktop
```

To remove it, delete the two installed files, re-run
`update-desktop-database`, and clear KDE's icon cache
(`rm -f ~/.cache/icon-cache.kcache && kbuildsycoca6 --noincremental`),
which otherwise keeps resolving the deleted icon path and shows a broken
window icon.

## 💻 CLI

The `iphonebridge` command does everything the app does, plus setup and diagnostics:

| Command | What it does |
|---|---|
| `iphonebridge run` | Run the daemon in the foreground (the systemd service uses this) |
| `iphonebridge doctor` | Check prerequisites — config, adapter class, obexd, state dir |
| `iphonebridge pair-setup` | First-run wizard — find the paired iPhone, write config |
| `iphonebridge sms-list` | Recent messages — `-n N`, `--from <contact>`, `--source iphone\|local` |
| `iphonebridge sms-send <to> <body>` | Send an SMS / iMessage (`<to>` = number or contact name) |
| `iphonebridge call <to>` | Place a phone call over HFP — number, contact name, or `1-800-LETTERS` |
| `iphonebridge calls` | List active calls |
| `iphonebridge hangup` | Hang up the active call(s) |
| `iphonebridge contacts-sync` | Force a contacts refresh (otherwise automatic every 24 h) |
| `iphonebridge ancs-enable` | One-time setup for per-app notifications (ANCS) |
| `iphonebridge hfp-enable` | One-time setup for phone calls (HFP) |
| `iphonebridge version` | Print the version |

```bash
# Recent messages — live from the iPhone, or from the daemon's own log
iphonebridge sms-list -n 20
iphonebridge sms-list --from Maddie
iphonebridge sms-list --source local

# Send — recipient can be a phone number OR a contact name
iphonebridge sms-send "+15551234567" "on my way"
iphonebridge sms-send Maddie "running late"

# Calls — needs HFP set up (install step 8)
iphonebridge call Maddie
iphonebridge calls
iphonebridge hangup

# Watch the daemon live · control the service
journalctl --user -u iphonebridge -f
systemctl --user {start,stop,restart} iphonebridge
```

## 🏗️ How it works

```
              iPhone  (paired: BR/EDR + BLE)
   ┌──────────┬──────────┬───────────┬──────────┐
   │ MAP      │ PBAP     │ ANCS      │ HFP      │
   │ (OBEX)   │ (OBEX)   │ (BLE GATT)│ (oFono)  │
   ▼          ▼          ▼           ▼
 messages   contacts   app notifs   calls
   └──────────┴──────────┴───────────┴──────────┘
                     │
           iphonebridge daemon
         (Python · GLib · D-Bus)
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  notifications   JSONL log   D-Bus service
  + clipboard     (history)   (CLI · GTK app)
```

- **MAP** (Message Access Profile) — read SMS/iMessage, get real-time push of new ones, and send.
- **PBAP** (Phone Book Access Profile) — pull the iPhone's contacts so messages show names, not numbers.
- **ANCS** (Apple Notification Center Service) — every app's notifications, over a BLE GATT link.
- **HFP** (Hands-Free Profile) — take and place calls; oFono speaks the HFP protocol, PipeWire's oFono backend carries the call audio to the laptop's mic/speakers.
- One daemon, pluggable **sinks** (desktop popups, verification-code clipboard copy, append-only JSONL log), and a **D-Bus service** so the CLI and the GTK app can send messages, control calls, and subscribe to a live event feed.

Design rationale and the empirical Bluetooth findings that shaped it are in [`spike/RESULTS.md`](spike/RESULTS.md).

## 📖 Glossary

- **CoD (Class of Device)**: a 24-bit Bluetooth field every device broadcasts declaring what kind of thing it is: service-class bits, a major class, and a minor class. iOS decides what to offer a paired device based on it. To a *computer* (major 1, minor 12, e.g. `0x3c010c`) iPhones offer nothing interesting; to an *A/V Hands-Free device* (major 4, minor 8, e.g. `0x3c0408`, what a car kit presents as) they offer the message and contacts toggles. That's why install step 4 sets `btmgmt class 4 8`, why it must survive reboots, and why `doctor` checks it. Only major and minor are ours to set; BlueZ derives the service-class bits from registered profiles, so the code compares only major and minor.
- **BlueZ**: Linux's Bluetooth stack. The `bluetoothd` system service owns the adapter; everything here talks to it over D-Bus as `org.bluez`.
- **obexd**: BlueZ's OBEX daemon, a separate per-user service (`obex.service`) that speaks the file-transfer protocol MAP and PBAP ride on. The iPhone allows one OBEX session at a time per fresh obexd, which shapes much of the daemon's session handling.
- **OBEX**: the object-exchange protocol underneath MAP and PBAP.
- **MAP (Message Access Profile)**: read SMS/iMessage, get real-time pushes of new ones (via its notification channel, **MNS**), and send. Gated by the iPhone's *Show Message Notifications* toggle.
- **bMessage**: the wire format MAP wraps each message in; the sender lives in an embedded vCard (`TEL` for phone senders, `EMAIL` for iMessage-via-Apple-ID senders).
- **PBAP (Phone Book Access Profile)**: pull the iPhone's contacts. Gated by *Sync Contacts*. Feeds the SQLite cache that resolves names.
- **ANCS (Apple Notification Center Service)**: Apple's BLE service carrying every app's notifications. Gated by *Show System Notifications*, needs a true BLE bond, and is the picky one (see Troubleshooting).
- **HFP (Hands-Free Profile)**: take and place calls. **oFono** is the telephony daemon that speaks HFP; PipeWire's oFono backend carries the call audio.
- **btmgmt**: BlueZ's low-level management CLI; needs root. Used for exactly one thing here: setting the CoD.

## 🛠️ Working on the code (if installed from source)

The from-source install is editable: `.venv/.../__editable__.iphonebridge-*.pth` holds a
single line pointing at `src/`, so Python imports straight out of the working
tree. **Editing a `.py` file never needs `pip install -e .` again** — adding a
whole new module doesn't either, since that path entry is searched live.

What needs restarting: every process that imports the file you changed. Everything in
`src/iphonebridge/` except `cli.py`, `pair_setup.py`, and `ui/` is daemon code;
`bus.py` and `config.py` are imported by the app as well, so those two need
both actions.

| Changed | Do this |
|---|---|
| Daemon code — anything but `cli.py`, `pair_setup.py`, `ui/` | `systemctl --user restart iphonebridge` |
| CLI — `cli.py`, `pair_setup.py` | Nothing; every `iphonebridge <cmd>` is a fresh process |
| App — `ui/` | Close and reopen `iphonebridge-ui` |
| Shared — `bus.py`, `config.py` | Restart the daemon *and* reopen the app |
| `systemd/iphonebridge.service` | Re-run the install from step 5, then `systemctl --user daemon-reload`, then restart |
| `systemd/sudoers-*`, `set-le-bearer.sh`, or an installer | Re-run the matching installer — `install-cod-sudoers.sh` for the CoD rule, `install-ancs-sudoers.sh` for the ANCS rule + helper |
| `data/*.desktop` or the icon | Re-run the install snippet under *Adding it to your app launcher* — a plain copy loses the `Exec` rewrite |

Only two changes actually need a reinstall:

- **Adding or renaming a `[project.scripts]` / `[project.gui-scripts]` entry.**
  The launchers in `.venv/bin` are generated at install time. A new *subcommand*
  on the existing Typer app doesn't count; a new top-level command does.
- **Adding a dependency.** Nothing installs it for you.

If a change seems to have no effect, check that the daemon actually picked it up
before assuming the code is wrong:

```bash
systemctl --user show iphonebridge -p ExecMainStartTimestamp
```

A restart is not only about code, either. It's when the daemon re-reads
`local.env` and re-registers the BLE advertisement the iPhone toggles depend
on — and after a re-pair it skips the ~2-minute wait for the automatic session
recovery.

Run the tests with:

```bash
.venv/bin/pip install -e '.[dev]'   # once, for pytest
.venv/bin/python -m pytest tests -q
```

## 🩺 Troubleshooting

<details>
<summary><b>Messages stopped arriving</b></summary>

The iPhone times out OBEX sessions, and anything that drops the pairing — a
forget + re-pair, an obexd restart — kills them outright. The daemon recovers on
its own: a 60s health check probes whether the session objects still exist, and
on finding them gone it drops to DEGRADED and reopens on the next tick of the
reopen loop. Worst case is about two minutes.

Watch it happen with `journalctl --user -u iphonebridge -f`; the line to look for
is `MAP/PBAP sessions vanished`. To skip the wait:
```bash
systemctl --user restart iphonebridge
```
What the daemon can't do for you is re-enable the step 6 toggles, which a
forget + re-pair switches off. Do that on the iPhone or it reopens straight back
into `Forbidden`.
</details>

<details>
<summary><b><code>Forbidden</code> errors in the log</b></summary>

An iPhone toggle is off. Check **Settings → Bluetooth → ⓘ → Show Message Notifications / Sync Contacts / Show System Notifications**.
</details>

<details>
<summary><b>Contacts stay at 0 — <code>PBAP transfer wrote no file</code></b></summary>

The first pull straight after you enable *Sync Contacts* often returns an empty
file: the daemon issues `PullAll` within a second of the PBAP session opening and
the iPhone isn't serving the phonebook yet. Restart the daemon and it re-pulls on
startup. A healthy pull logs `parsed N contacts from M bytes` and takes several
seconds for a large phonebook.

`iphonebridge contacts-sync` forces the same pull without a restart. With the
daemon running it asks it over D-Bus, so the daemon's existing MAP and PBAP
sessions are reused rather than torn down; with the daemon stopped it opens its
own sessions and closes them again.
</details>

<details>
<summary><b>ANCS notifications never arrive</b></summary>

ANCS needs a BLE bond, which needs a fresh pair done with the adapter correctly set up. Run `iphonebridge ancs-enable`, then forget + re-pair the iPhone, then restart the daemon.

Side effect to know about: the connection cycling this involves can crash bystander BlueZ user daemons — `mpris-proxy` (media keys for Bluetooth audio) has segfaulted on it, and `ofonod` has aborted on modem power-up. Neither affects messages or contacts; `systemctl --user restart mpris-proxy` / `sudo systemctl restart ofono` bring them back.

Check whether the bond actually formed — if ANCS worked, the iPhone's device object carries the ANCS GATT service UUID:

```bash
busctl --system tree org.bluez | grep dev_          # find your device path
busctl --system get-property org.bluez <path> org.bluez.Device1 UUIDs \
  | grep -i 7905f431-b5ce-4e99-a40f-4b1e122d00d0
```

No match means the bond is still BR/EDR-only, and iOS won't offer the *Show System Notifications* toggle at all. An Intel adapter is necessary but not sufficient; `spike/RESULTS.md` §5 has the BR/EDR-vs-BLE mutex this runs into. Confirm the chipset with:

```bash
lsusb | grep -i bluetooth        # Intel Corp. = supported; Realtek / dongles = not
```

**Check the advertisement registered at all.** The toggle also needs the
ANCS-soliciting BLE advertisement the daemon registers at startup
(`spike/RESULTS.md` §1). A failure is logged plainly:

```bash
journalctl --user -u iphonebridge | grep -i advert
# good: BLE advert registered: /me/santisbon/iphonebridge/ancs_advert
# bad:  RegisterAdvertisement failed: org.bluez.Error.Failed: ...
```

If it failed, first clear stale advertising slots — bluetoothd can hold
instances from earlier sessions that are never released:

```bash
# ActiveInstances = in use, SupportedInstances = still free
busctl --system get-property org.bluez /org/bluez/hci0 \
  org.bluez.LEAdvertisingManager1 ActiveInstances SupportedInstances
sudo systemctl restart bluetooth     # releases stale instances
systemctl --user restart iphonebridge
```

> Known-unresolved: on one BlueZ 5.85 / Intel BE200 setup, registration
> fails with `org.bluez.Error.Failed` even with every slot free and a bare
> `Type: peripheral` advert carrying no payload, from a separate process on
> its own object path. That points below iphonebridge, at BlueZ or the
> controller. MAP and PBAP are unaffected, so messages and contacts keep
> working; only ANCS is lost. Reports from other chipsets welcome.
</details>

<details>
<summary><b>Calls don't connect, or there's no call audio</b></summary>

If `systemctl status ofono` shows `core-dump`, the distro's ofonod crashed (seen once when the modem powered during HFP registration): `sudo systemctl restart ofono`, then restart the daemon.

HFP needs oFono, and oFono must start *after* WirePlumber so it can claim the HFP profile. Run `iphonebridge hfp-enable`, then `sudo systemctl restart ofono`, reconnect the iPhone, and restart the daemon. If `journalctl -u ofono` shows `RegisterProfile … UUID already registered`, the start order is wrong — restart oFono again after WirePlumber is up.
</details>

<details>
<summary><b>App won't open — no window, no error</b></summary>

GTK apps are single-instance per application ID: one process owns the
D-Bus name `me.santisbon.iphonebridge.UI`, and every later launch just
asks it to present its window. If a previous instance is stuck (alive
but not answering D-Bus), new launches delegate to it, wait 25 seconds,
and exit silently — the journal shows `Failed to register: Timeout was
reached`. Fix:

```bash
pkill -f iphonebridge-ui
```

then launch again.
</details>

<details>
<summary><b><code>Unable to acquire the address of the accessibility bus</code></b></summary>

A GTK warning on every `iphonebridge-ui` launch, not a fault — the app works
normally. It means `at-spi-dbus-bus.service` is masked on your system, so GTK
can't reach the accessibility bus. Silence it either way:

```bash
GTK_A11Y=none iphonebridge-ui                       # skip a11y for this launch
systemctl --user unmask at-spi-dbus-bus.service     # or turn a11y back on
systemctl --user start at-spi-dbus-bus.service
```

The app deliberately doesn't set `GTK_A11Y=none` itself — that would silence
the accessibility bus for everyone, including people who need it.
</details>

<details>
<summary><b>Verification codes aren't being copied</b></summary>

Install a clipboard tool: `sudo apt install wl-clipboard` (Wayland) or `xclip` (X11). The daemon log shows `no clipboard tool worked` when none is present.
</details>

<details>
<summary><b><code>iphonebridge: command not found</code></b></summary>

The CLI lives in the venv. Either `source .venv/bin/activate`, or create the `~/.local/bin` symlink from install step 2.
</details>

<details>
<summary><b><code>ModuleNotFoundError: No module named 'dbus'</code></b></summary>

The venv was created by a Python that isn't the system one. Run `head -3 .venv/pyvenv.cfg`; if `command =` names anything under `~/anaconda3`, `~/miniconda3`, or `~/.pyenv`, that's it. `--system-site-packages` inherits the site-packages of whichever interpreter created the venv, so a conda or pyenv venv never sees apt's `/usr/lib/python3/dist-packages` where `python3-dbus` and `python3-gi` live. Those apt builds are also compiled against the system interpreter specifically, so a version mismatch would break them regardless.

Rebuild against the system Python:

```bash
rm -rf .venv
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/python -c "import dbus, gi; print('ok')"
```

The `~/.local/bin` symlinks point at paths inside `.venv`, so they keep working without relinking.
</details>

## 🙏 Credits

This repository is a hard fork of
[gabrielmeir53/iphonebridge](https://github.com/gabrielmeir53/iphonebridge),
forked at v0.4.2 and maintained independently by
[santisbon](https://github.com/santisbon).

iphonebridge stands on the shoulders of two prior projects, both GPL-2.0:

- **[bmh129/ancs4linux](https://github.com/bmh129/ancs4linux)** — an archived (2026-05-31) fork whose empirical work on BR/EDR-vs-BLE coexistence, the `LastUsedBearer=le` unlock, and adapter compatibility made iphonebridge's ANCS support possible. The ANCS wire-format code in [`src/iphonebridge/ancs/`](src/iphonebridge/ancs/) is derived from their `observer/ancs/` modules.
- **[pzmarzly/ancs4linux](https://github.com/pzmarzly/ancs4linux)** — the original 2022 reference implementation of ANCS on Linux.

## 📄 License

[GPL-2.0-or-later](LICENSE) · © 2026 Gabe Shatunovsky · fork modifications © 2026 santisbon
