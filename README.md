<div align="center">

# 📱🐧 iPhone Bridge

**iPhone messages, notifications, contacts and calls on Linux**  
*No Mac relay. No cloud service. No subscription. Just Bluetooth.*

[![CI](https://github.com/santisbon/iphonebridge/actions/workflows/ci.yml/badge.svg)](https://github.com/santisbon/iphonebridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/santisbon/iphonebridge?color=brightgreen)](https://github.com/santisbon/iphonebridge/releases/latest)
[![License: GPL v2](https://img.shields.io/badge/license-GPL--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![Platform: Linux](https://img.shields.io/badge/platform-Linux%20(GNOME%20%2F%20KDE)-lightgrey.svg)](#requirements)

![](screenshots/messages.png)

</div>

---

## Install

Any apt-based distro: Debian, Ubuntu and its flavours, Pop!_OS, Mint.

```bash
curl -LO "$(curl -s https://api.github.com/repos/santisbon/iphonebridge/releases/latest \
  | grep -o 'https://[^"]*_all\.deb')"

sudo apt install ./iphonebridge_*_all.deb
sudo adduser $USER iphonebridge
sudo reboot   # a re-login is not enough: user services keep old groups
```

Pair the iPhone from your desktop's Bluetooth settings. Keep it on its
**Settings → Bluetooth** screen while you do — iOS is only discoverable
while that screen is open — and confirm the 6-digit code on both sides.

```bash
iphonebridge pair-setup
```

On the iPhone, tap ⓘ next to this computer, give it a moment to show the
toggles, and enable **Show Message Notifications** and **Sync Contacts**.
Then open the app:

```bash
iphonebridge-ui # or through your app launcher
```

The app is a separate process from the daemon, so closing it leaves
messages, notifications and calls still arriving.

Removing a stale pairing, calls over HFP, per-app notifications, building
the package and uninstalling are all in
[`packaging/deb/README.md`](packaging/deb/README.md).

## Why

Windows and macOS users can get their iPhone's texts and notifications on the desktop. There has never been a Linux equivalent:

- KDE Connect needs the Android/iOS *app* and on iOS it's missing notifications, SMS, and needs the iPhone app on-screen to maintain the connection. 
- `ancs4linux` does notifications only.
- Mac-relay bridges (BlueBubbles, AirMessage) need an actual Mac. 
- Beeper no longer supports iMessage.
- Microsoft's Phone Link is Windows-only.

**This is that missing piece.** [How it works](ARCHITECTURE.md).

## What it does

| Feature | How | Status |
|---|---|---|
| 📨 **Incoming SMS + iMessage** as desktop notifications | MAP MNS push | ✅ |
| 📤 **Send SMS + iMessage** from the CLI or app | MAP `PushMessage` | ✅ |
| 📋 **Verification codes auto-copied** to the clipboard | OTP detection | ✅ |
| 👤 **Contact-name resolution** (1000s of contacts) | PBAP → SQLite cache | ✅ |
| 🔔 **Every app's notifications** — Slack, WhatsApp, Mail… | ANCS over BLE | ✅ |
| 📞 **Take & place phone calls** — caller ID, answer/decline, dial | HFP via oFono | ✅ |
| 🔁 **Read on the desktop marks it read on the iPhone** | MAP `Read` flag | ✅ |
| 📜 **Message history** — incoming + your desktop replies | `sms-list` / the app | ✅ |
| 🖥️ **Desktop app** — conversations, notification feed, call UI | Qt 6 / QML | ✅ |
| ⚙️ **Runs unattended** | systemd user service | ✅ |

## Limitations

These are limits of the Bluetooth stack at one end or the other, not bugs:

- No iMessage **attachments, reactions, read receipts, or typing indicators** (MAP doesn't carry them).
- No **group iMessage / MMS / RCS** — MAP is 1-to-1 only.
- **Messages composed on the iPhone itself don't sync** — iOS exposes only your *inbox* over MAP, never the sent folder. Replies you send *from* iphonebridge are recorded into conversation history; texts you type on the phone aren't visible to any Bluetooth bridge.
- HFP calls are **1-to-1 voice only** — no conference calls, no FaceTime (HFP carries neither).
- Notification *bodies* are subject to the iPhone's "Show Previews" setting.
- **Read state mostly travels one way.** Opening a conversation here marks
  those messages read on the iPhone, for any message obexd still exports;
  older ones have no object path left to address and are marked read on this
  computer only. Coming back the other way, a live notification popup does
  close when you read that message on the phone, but a conversation already
  in the app does not lose its unread mark: obexd raises no notification for
  a read-status change, and the inbox sweep skips messages already logged.
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

## Requirements

> ⚠️ **Adapter chipset matters for ANCS.** Per-app notifications need a real BLE bond with the iPhone. Intel adapters like the AX-series do this reliably. **Realtek adapters and every USB Bluetooth dongle tested so far do *not*** — their firmware negotiates legacy keys that block the cross-transport key derivation iOS needs. SMS/iMessage/contacts (MAP/PBAP) work on any adapter; only ANCS is picky. See [bmh129/ancs4linux's hardware notes](https://github.com/bmh129/ancs4linux).

## CLI

The `iphonebridge` command covers sending, history, calls, setup and
diagnostics.

```bash
man iphonebridge
man iphonebridge-ui

# Watch the daemon live · control the service
journalctl --user -u iphonebridge -f
systemctl --user {start,stop,restart} iphonebridge
```

## Troubleshooting

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
What the daemon can't do for you is re-enable the iPhone-side toggles,
which a forget + re-pair switches off. Do that on the iPhone or it reopens straight back
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

ANCS needs a BLE bond and an LE connection. First allow BlueZ's experimental interfaces (`[General] Experimental = true` in `/etc/bluetooth/main.conf`, then `sudo systemctl restart bluetooth` and `systemctl --user restart iphonebridge`). If the pairing is old, forget the iPhone on both ends and re-pair. Then run `iphonebridge ancs-enable`: it steers the next connection over BLE, and the iPhone shows an **allow-notifications prompt** (on current iOS this replaces the third Bluetooth toggle) — answer Allow there.

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

> Known cause on BlueZ 5.85: every `RegisterAdvertisement` fails with
> `org.bluez.Error.Failed` regardless of adapter, payload or free slots.
> bluetoothd 5.85 sizes the `MGMT_OP_ADD_EXT_ADV_DATA` buffer with the
> legacy `mgmt_cp_add_advertising` struct, so every data command carries
> eight trailing slack bytes, and kernels that enforce exact mgmt payload
> length reject it with `Invalid Parameters (0x0d)` before the controller
> is ever consulted (visible in `btmon`; bluetoothd logs
> `add_client_complete() Failed to add advertisement: Invalid Parameters`).
> Fixed upstream in bluez commit `2a6968b40` ("advertising: Fix sending
> extra bytes with MGMT_OP_ADD_EXT_ADV_DATA"); until your distro ships it,
> a bluez rebuilt with that one-line patch restores ANCS —
> [`packaging/bluez-adv-fix.md`](packaging/bluez-adv-fix.md) is the
> walkthrough. The adapter is not at fault. MAP and PBAP are unaffected,
> so messages and contacts keep working; only ANCS is lost.
</details>

<details>
<summary><b>Calls don't connect, or there's no call audio</b></summary>

If `systemctl status ofono` shows `core-dump`, the distro's ofonod crashed (seen once when the modem powered during HFP registration): `sudo systemctl restart ofono`, then restart the daemon.

HFP needs oFono, and oFono must start *after* WirePlumber so it can claim the HFP profile. Run `iphonebridge hfp-enable`, then `sudo systemctl restart ofono`, reconnect the iPhone, and restart the daemon. If `journalctl -u ofono` shows `RegisterProfile … UUID already registered`, the start order is wrong — restart oFono again after WirePlumber is up.
</details>

<details>
<summary><b>App won't open — no window, no error</b></summary>

The window is QML, loaded at startup from the installed package. If the
QtQuick runtime modules are missing the process exits immediately and the
journal shows `QML failed to load from …`. The `.deb` depends on them; a
source checkout has to install them:

```bash
sudo apt install python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick \
                 python3-dbus.mainloop.pyqt6 \
                 qml6-module-qtquick-controls qml6-module-qtquick-layouts \
                 qml6-module-qtquick-templates qml6-module-qtquick-window
```

Note that the app is **not** single-instance: it takes no D-Bus name, so
running `iphonebridge-ui` twice gives you two windows rather than raising
the first one.
</details>

<details>
<summary><b><code>Unable to acquire the address of the accessibility bus</code></b></summary>

Noise, not a fault — the app works normally. `iphonebridge-ui` is a
Qt/QML process, but Qt loads a *platform theme plugin* on startup to pick
up your desktop's fonts, colours and dialogs, and on a GTK desktop that
plugin initialises GTK inside the app's process. The warning is GTK's,
about `at-spi-dbus-bus.service` being masked on your system, and the app
itself never imports GTK. Silence it either way:

```bash
GTK_A11Y=none iphonebridge-ui                       # skip a11y for this launch
systemctl --user unmask at-spi-dbus-bus.service     # or turn a11y back on
systemctl --user start at-spi-dbus-bus.service
```

The app deliberately doesn't set `GTK_A11Y=none` itself — that would
silence the accessibility bus for every GTK program the session starts
afterwards, including for people who need it.
</details>

<details>
<summary><b>Verification codes aren't being copied</b></summary>

Install a clipboard tool: `sudo apt install wl-clipboard` (Wayland) or `xclip` (X11). The daemon log shows `no clipboard tool worked` when none is present.
</details>

<details>
<summary><b><code>iphonebridge: command not found</code></b></summary>

Only applies to a from-source install: the CLI lives in the venv. Either `source .venv/bin/activate`, or create the `~/.local/bin` symlink from [`DEVELOPMENT.md`](DEVELOPMENT.md). A packaged install puts it in `/usr/bin`.
</details>

<details>
<summary><b><code>ModuleNotFoundError: No module named 'dbus'</code></b></summary>

The venv was created by a Python that isn't the system one. Run `head -3 .venv/pyvenv.cfg`; if `command =` names anything under `~/anaconda3`, `~/miniconda3`, or `~/.pyenv`, that's it. `--system-site-packages` inherits the site-packages of whichever interpreter created the venv, so a conda or pyenv venv never sees apt's `/usr/lib/python3/dist-packages` where `python3-dbus`, `python3-gi`, and `python3-pyqt6` live. Those apt builds are also compiled against the system interpreter specifically, so a version mismatch would break them regardless.

Rebuild against the system Python:

```bash
rm -rf .venv
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/python -c "import dbus, gi; print('ok')"
```

The `~/.local/bin` symlinks point at paths inside `.venv`, so they keep working without relinking.
</details>

## Credits

This repository is forked from
[gabrielmeir53/iphonebridge](https://github.com/gabrielmeir53/iphonebridge)
at v0.4.2 and maintained independently by
[santisbon](https://github.com/santisbon).

iphonebridge stands on the shoulders of two prior projects, both GPL-2.0:

- **[bmh129/ancs4linux](https://github.com/bmh129/ancs4linux)** — an archived (2026-05-31) fork whose empirical work on BR/EDR-vs-BLE coexistence, the `LastUsedBearer=le` unlock, and adapter compatibility made iphonebridge's ANCS support possible. The ANCS wire-format code in [`src/iphonebridge/ancs/`](src/iphonebridge/ancs/) is derived from their `observer/ancs/` modules.
- **[pzmarzly/ancs4linux](https://github.com/pzmarzly/ancs4linux)** — the original 2022 reference implementation of ANCS on Linux.

## License

[GPL-2.0-or-later](LICENSE) · © 2026 Gabe Shatunovsky · fork modifications © 2026 santisbon
