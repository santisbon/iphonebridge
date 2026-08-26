# Development

## Installation

Two ways to install. A `.deb` package (see `README.md`) and from source. Pick **exactly one** as mixing the two is confusing to debug: from-source symlinks in `~/.local/bin` shadow a deb-installed `/usr/bin/iphonebridge` on most PATH setups.

<details>

<summary> Install from source </summary>

The rest of this section walks through it: venv, symlinks, sudoers
installers, and a path-substituted systemd unit. The package names in step 1
are Debian-family. On non-apt distros, e.g. **Fedora, Arch, openSUSE**  
install your distro's equivalents of BlueZ, `bluez-obexd`, dbus-python, PyGObject
(the daemon's main loop), and PyQt6 with its QtQuick/QML runtime modules (the app). 

You can also use this on any distro when you're developing —
edits to the clone take effect without rebuilding a package (see
*Working on the code*).


#### 1 · System packages

```bash
sudo apt install bluez bluez-obexd python3-dbus python3-gi python3-venv
# For the desktop app (iphonebridge-ui). The QML runtime modules are
# separate packages; the Python bindings do not pull them in, and without
# them the window never loads.
sudo apt install python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick \
                 python3-dbus.mainloop.pyqt6 \
                 qml6-module-qtquick-controls qml6-module-qtquick-layouts \
                 qml6-module-qtquick-templates qml6-module-qtquick-window
# For auto-copying verification codes (Wayland):
sudo apt install wl-clipboard
```

#### 2 · Clone & install

```bash
git clone https://github.com/santisbon/iphonebridge.git
cd iphonebridge

# A venv that inherits the system PyGObject, PyQt6 and dbus-python.
# (Never install those from PyPI — the builds are notoriously fragile,
# and a pip PyQt6 will not see apt's QML modules.)
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

## Adding app to your app launcher (if installed from source)

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
# Freedesktop's hicolor icon cache, not a GTK-app thing — every toolkit
# resolves themed icons through it, and this is the app's desktop icon,
# which has nothing to do with the retired GTK UI. The tool just happens
# to ship in a GTK package.
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
kbuildsycoca6 --noincremental   # KDE only; GNOME picks it up on its own
```

The `Exec` rewrite is the part that matters. The shipped entry says
`Exec=iphonebridge-ui`, which is correct for a distro package that puts the
binary in `/usr/bin`, but a from-source install puts it in `~/.local/bin` —
and that directory is usually absent from the systemd user environment, which
is what Plasma launches menu entries through. Left as-is, the entry appears in
the menu and silently fails to start.

Don't rename the file. Its basename has to match the name passed to
`setDesktopFileName` in `src/iphonebridge/ui/qtapp.py`, which is how the
compositor associates the running window with this entry and its icon.

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

## 🛠️ Working on the code (if installed from source)

The from-source install is editable: `.venv/.../__editable__.iphonebridge-*.pth` holds a
single line pointing at `src/`, so Python imports straight out of the working
tree. **Editing a `.py` file never needs `pip install -e .` again** — adding a
whole new module doesn't either, since that path entry is searched live.

What needs restarting: every process that imports the file you changed. Everything in
`src/iphonebridge/` except `cli.py`, `pair_setup.py`, and `ui/` is daemon code.
`config.py` is imported by the app as well, so it needs both actions. `bus.py`
is **not**: it installs the GLib main loop, and the app deliberately reaches
D-Bus through `ui/qtbus.py` instead, which installs Qt's. Only one main-loop
integration can be default per process, so `ui/qtbus.py` raises on import if
`iphonebridge.bus` got pulled in first.

| Changed | Do this |
|---|---|
| Daemon code — anything but `cli.py`, `pair_setup.py`, `ui/` | `systemctl --user restart iphonebridge` |
| CLI — `cli.py`, `pair_setup.py` | Nothing; every `iphonebridge <cmd>` is a fresh process |
| App — `ui/qt*.py`, `ui/qml/*.qml`, `ui/model.py`, `ui/protocol.py`, `ui/util.py` | Close and reopen `iphonebridge-ui` |
| Shared — `config.py` | Restart the daemon *and* reopen the app |
| Daemon bus — `bus.py` | `systemctl --user restart iphonebridge` (the app doesn't import it) |
| `systemd/iphonebridge.service` | Re-run the install from step 5, then `systemctl --user daemon-reload`, then restart |
| `systemd/sudoers-*`, `set-le-bearer.sh`, or an installer | Re-run the matching installer — `install-cod-sudoers.sh` for the CoD rule, `install-ancs-sudoers.sh` for the ANCS rule + helper |
| `data/*.desktop` or the icon | Re-run the install snippet under *Adding it to your app launcher* — a plain copy loses the `Exec` rewrite |

`ui/` is Qt only. The GTK front end it replaced was deleted once the Qt UI
had caught up on everything it did — conversation and message delete,
recipient autocomplete, the link-health pill, call answer/hang-up, toasts,
empty states, and light/dark. It is in the history if a detail needs
looking up; `ui/style.css` there is where the old Apple palette lives.

The app follows the desktop's light/dark setting through Qt's platform
theme, which supplies the palette. Nothing in the app asks for a scheme:
`QStyleHints.setColorScheme` is ignored here, and so is setting a palette
on the application object. That matters when rendering screenshots — see
`screenshots/README.md`.

Nothing under `src/` imports GTK or libadwaita any more. `bus.py` and
`daemon.py` still import `gi.repository.GLib` — that is the daemon's main
loop, and it stays whatever toolkit the app uses.

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