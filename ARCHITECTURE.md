# Architecture


Every prior writeup of Bluetooth on iOS says **iMessage is invisible** to a paired computer — that you *must* use a Mac relay to bridge blue-bubble messages. **That is not true on iOS 26.5.** iPhone Bridge receives *and sends* iMessage through the standard MAP Bluetooth profile, with no Mac, no Apple ID login, nothing. iOS labels iMessage and SMS identically (`Type: sms-gsm`) and exposes both. Outgoing messages route as iMessage automatically when the recipient is iMessage-capable. The empirical proof is in [`spike/RESULTS.md`](spike/RESULTS.md) §6.

### Feature details

- **Incoming messages** appear as **persistent notifications** — they stay until you dismiss them on the desktop *or* read the message on your iPhone. **Read-state syncs both ways.**
- **Verification codes** — when a text carries a one-time / 2FA code, iphonebridge detects it and copies it to your clipboard automatically; press <kbd>Ctrl</kbd>+<kbd>V</kbd> to paste. Detection needs both a verification keyword and a 4–8 digit number, so ordinary texts don't trigger it.
- **Incoming calls** raise a notification with **Answer / Decline** buttons that act on the call directly.
- **Sent messages** — replies you send from the desktop are recorded into conversation history, so a thread shows both sides.
- **History starts shallow** — a fresh install seeds conversations with the recent inbox window iOS exposes over Bluetooth (roughly the last 10 messages); iOS does not serve older history to any Bluetooth bridge. Threads grow from install day forward.

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
  + clipboard     (history)   (CLI · Qt app)
```

- **MAP** (Message Access Profile) — read SMS/iMessage, get real-time push of new ones, and send.
- **PBAP** (Phone Book Access Profile) — pull the iPhone's contacts so messages show names, not numbers.
- **ANCS** (Apple Notification Center Service) — every app's notifications, over a BLE GATT link.
- **HFP** (Hands-Free Profile) — take and place calls; oFono speaks the HFP protocol, PipeWire's oFono backend carries the call audio to the laptop's mic/speakers.
- One daemon, pluggable **sinks** (desktop popups, verification-code clipboard copy, append-only JSONL log), and a **D-Bus service** so the CLI and the Qt app can send messages, control calls, and subscribe to a live event feed.
- The daemon and the desktop app are **separate processes running different main loops**: the daemon runs GLib's, the app runs Qt's. dbus-python delivers signals only under a running loop and takes one integration per process, so the app binds dbus-python to Qt (`ui/qtbus.py`) and must never import `iphonebridge.bus`, which binds it to GLib. D-Bus is the seam between them, which is why the toolkit could be swapped without touching the daemon.

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
