# Building the .deb

One package installs everything: the daemon, the CLI, the GTK app, the
systemd user unit, the desktop entry and icon, and the privileged pieces
(sudoers rules and the ANCS helper) that ruled sandboxed formats out.
Target: Debian-family distros (Pop!_OS, Kubuntu, Debian).

Anatomy, once: the user-facing build command is `dpkg-buildpackage`. It
runs `debian/rules`, which delegates to the `debhelper` sequencer (`dh`),
which builds the Python package through `pybuild` using the existing
`pyproject.toml`. You write the small files in `debian/`; the tooling
does the rest.

## What the package ships

| Repo source | Installed path |
|---|---|
| `src/iphonebridge/` (incl. `ui/icons/`) | `/usr/lib/python3/dist-packages/iphonebridge/` |
| entry points from `pyproject.toml` | `/usr/bin/iphonebridge`, `/usr/bin/iphonebridge-ui` |
| `systemd/iphonebridge.service` (placeholder substituted) | `/usr/lib/systemd/user/iphonebridge.service` |
| `data/me.santisbon.iphonebridge.UI.desktop` (as-is: `Exec=iphonebridge-ui` is on PATH now) | `/usr/share/applications/` |
| `data/icons/me.santisbon.iphonebridge.UI.svg` | `/usr/share/icons/hicolor/scalable/apps/` |
| `data/me.santisbon.iphonebridge.UI.metainfo.xml` | `/usr/share/metainfo/` |
| CoD sudoers rule, group-based (see below) | `/etc/sudoers.d/iphonebridge-cod` |
| ANCS sudoers rule + `systemd/set-le-bearer.sh` | `/etc/sudoers.d/iphonebridge-ancs`, `/usr/libexec/iphonebridge/set-le-bearer` |

## Code changes required first (done)

These were the gaps between the from-source install and a system
package; all four are implemented in the repo now. Kept here as the
record of why:

1. **Group-based sudoers.** The repo templates grant a single username,
   rendered at install time. A system package serves all users, so the
   shipped rules grant a group instead:

   ```
   %iphonebridge ALL=(root) NOPASSWD: /usr/bin/btmgmt class 4 8
   ```

   `bluez_setup.py` needs no change (it just runs `sudo -n`); only the
   rule files change, and `postinst` creates the group. Users add
   themselves once: `sudo adduser $USER iphonebridge`, then reboot.
   A plain re-login is not enough: user services inherit groups from the
   systemd user manager, which keeps its old groups as long as any
   session survives the logout (a terminal multiplexer, an SSH session,
   an agent). Reboot, or terminate every session.
2. **Unit placeholder.** `systemd/iphonebridge.service` contains
   `@INSTALL_DIR@`. The deb build substitutes `ExecStart=/usr/bin/iphonebridge run`
   (a `sed` in `debian/rules`, or a static `debian/iphonebridge.user.service`).
3. **Package data.** `pyproject.toml` needs the bundled UI icons declared
   so non-editable installs ship them:

   ```toml
   [tool.setuptools.package-data]
   "iphonebridge.ui" = ["icons/*.svg", "icons/README.md"]
   ```
4. **Setup hints in messages.** `pair-setup` and `doctor` print repo
   paths like `sudo bash systemd/install-cod-sudoers.sh`. Installed from
   a deb, the right hint is `sudo adduser $USER iphonebridge`. Gate the
   message on whether the sudoers file already exists, or make it name
   both paths.

## The debian/ directory

Top-level `debian/` exists in the repo with these files, plus
`debian/copyright` (GPL-2+, upstream and ancs4linux attribution;
required, lintian errors without it) and `debian/source/format`
containing `3.0 (native)`. Native format means the version has no
Debian revision: the package is `iphonebridge_0.6.0_all.deb`, not
`0.6.0-1`. `debian/rules` also renames the sudoers files at install
time (dh_install keeps source basenames) and disables pybuild's test
run (`PYBUILD_DISABLE = test`); tests run in CI.

`debian/control`:

```
Source: iphonebridge
Section: comm
Priority: optional
Maintainer: santisbon <santisbon@users.noreply.github.com>
Build-Depends: debhelper-compat (= 13), dh-python, python3-all,
 python3-setuptools, pybuild-plugin-pyproject
Standards-Version: 4.6.2
Homepage: https://github.com/santisbon/iphonebridge

Package: iphonebridge
Architecture: all
Depends: ${python3:Depends}, ${misc:Depends},
 python3-dbus, python3-gi, python3-typer,
 gir1.2-gtk-4.0, gir1.2-adw-1,
 bluez (>= 5.72), bluez-obexd
Recommends: ofono, wl-clipboard
Description: iPhone messages, calls, and contacts over Bluetooth
 Daemon, CLI, and GTK4 app bridging a paired iPhone via MAP, PBAP,
 ANCS, and HFP. No Mac relay, no cloud service.
```

`debian/rules` (executable):

```makefile
#!/usr/bin/make -f
export PYBUILD_NAME = iphonebridge

%:
	dh $@ --with python3 --buildsystem=pybuild

override_dh_install:
	dh_install
	sed 's|@INSTALL_DIR@/.venv/bin/iphonebridge|/usr/bin/iphonebridge|' \
	  systemd/iphonebridge.service \
	  > debian/iphonebridge/usr/lib/systemd/user/iphonebridge.service
```

`debian/install`:

```
data/me.santisbon.iphonebridge.UI.desktop      usr/share/applications/
data/icons/me.santisbon.iphonebridge.UI.svg    usr/share/icons/hicolor/scalable/apps/
data/me.santisbon.iphonebridge.UI.metainfo.xml usr/share/metainfo/
systemd/set-le-bearer.sh                       usr/libexec/iphonebridge/
debian/sudoers-cod                             etc/sudoers.d/
debian/sudoers-ancs                            etc/sudoers.d/
```

(`debian/sudoers-cod` and `debian/sudoers-ancs` are the group-based
rules from step 1; mode 0440 via `debian/postinst` or
`dh_fixperms` overrides. Validate with `visudo -cf` in the build.)

`debian/postinst`:

```sh
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    getent group iphonebridge >/dev/null || addgroup --system iphonebridge
    chmod 0440 /etc/sudoers.d/iphonebridge-cod /etc/sudoers.d/iphonebridge-ancs
fi
#DEBHELPER#
```

`debian/changelog`: hand-written; keep in sync with `CHANGELOG.md`
manually (or use `dch` from `devscripts`). Native versioning: `0.6.0`,
no `-1` suffix.

## Build

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all lintian
dpkg-buildpackage -us -uc -b     # unsigned, binary-only
lintian ../iphonebridge_0.6.0_all.deb   # two no-manual-page warnings expected
```

## Install and set up (complete, self-contained)

Every step from a bare system to working messages, contacts, and calls.

### 1. Install the package

```bash
sudo apt install ./iphonebridge_0.6.0_all.deb
```

Dependencies (`bluez`, `bluez-obexd`, `python3-dbus`, `python3-gi`,
GTK/Adwaita) install automatically.

Two apt notices are normal when installing from a local file: "selecting
'iphonebridge' instead of <path>" is apt resolving the file to the
package name it contains, and "Download is performed unsandboxed as
root" appears when the file sits somewhere apt's unprivileged `_apt`
user cannot read, such as a home directory (Ubuntu homes are mode 750).
Both are harmless; copying the deb to `/tmp` first silences the second. `ofono` and `wl-clipboard` come in
as Recommends unless apt is configured to skip those.

### 2. Authorize and start the daemon

```bash
sudo adduser $USER iphonebridge # then reboot
```

A plain re-login is not enough and you must reboot: user services inherit
groups from the systemd user manager, which keeps its old groups as long
as any session survives the logout (a terminal multiplexer, SSH, an
agent). No enable step is needed: debhelper's maintainer scripts enable the
user unit globally at install time, so the daemon starts at every
user's login. After the reboot it is already running; to start it
without a reboot, `systemctl --user start iphonebridge`. A user who
does not want it can opt out with `systemctl --user mask iphonebridge`
(plain disable is overridden by the global enablement).

The daemon sets the adapter's Bluetooth class (A/V Hands-Free) on every
start; iOS only offers the message and contacts toggles to a device with
that class. Without the toggles yet, the daemon logs `DEGRADED mode`,
stays running, and retries every 60s. That is expected at this point.

### 3. Pair the iPhone

If this iPhone was ever paired to this computer, remove the old bond on
**both** ends first; one-sided forgetting leaves a stale half-bond that
breaks the new pairing. Linux: the Bluetooth panel's Remove/Forget or
`bluetoothctl remove <MAC>`. iPhone: Settings, Bluetooth, tap the info
icon next to the computer, Forget This Device.

Then pair. Keep the iPhone on its Settings, Bluetooth screen; iOS is
only discoverable while that screen is open. Confirm the matching
6-digit code on both sides.

- KDE Plasma: System Settings, Bluetooth, Add New Device
- GNOME: Settings, Bluetooth, tap the iPhone under Other Devices
- CLI: `bluetoothctl` then `scan on`, `pair <MAC>`, `trust <MAC>`, `quit`

### 4. First-run wizard

```bash
iphonebridge pair-setup
```

Finds the paired iPhone, writes `~/.config/iphonebridge/local.env`, and
offers to restart the daemon. Say yes.

### 5. iPhone-side toggles

On the iPhone: Settings, Bluetooth, tap the info icon next to this
computer and **give it a minute** to show the toggles. Then enable:

- **Show Message Notifications** (gates SMS/iMessage)
- **Sync Contacts** (gates contacts)

Notes that look like faults but are not: the toggles only appear while
the daemon is running (they depend on a BLE advertisement it registers);
a forget and re-pair silently resets them to off; after enabling them,
give the daemon up to 60s to connect. Contacts pull automatically once
sessions open.

### 6. Verify

```bash
iphonebridge doctor
```

Everything should pass. Messages arrive as desktop notifications;
`iphonebridge-ui` is in the app launcher as "iphonebridge". On a fresh
install the daemon seeds conversation history with the recent inbox
window iOS serves over Bluetooth (roughly the last 10 messages); older
conversations exist only on the iPhone, and history grows from here.

### 7. Optional: phone calls (HFP)

`ofono` is already installed via Recommends. Enable it and wire the
audio path:

```bash
sudo systemctl enable --now ofono
iphonebridge hfp-enable      # writes the WirePlumber config, prints steps
sudo systemctl restart ofono # after WirePlumber, so it claims HFP
systemctl --user restart iphonebridge
```

The daemon looks for oFono once at startup, hence the final restart.

If calls error out pointing at `hfp-enable` even after this, check
`systemctl status ofono`: the distro's `ofonod` can crash (SIGABRT core
dump) when the modem powers during its HFP registration. Remedy:

```bash
sudo systemctl restart ofono
systemctl --user restart iphonebridge
```

Observed as a one-off; it does not recur once the chain is up.

### 8. Optional: per-app notifications (ANCS)

Works only on some adapters (Intel required, and not sufficient; known
not to work on BE200). If you want to try: `iphonebridge ancs-enable`,
then forget and re-pair (both ends, as in step 3), re-enable the step 5
toggles, and look for a third toggle, Show System Notifications.

The connection cycling in this step can crash bystander BlueZ user
daemons; `mpris-proxy` (media keys for Bluetooth audio) has segfaulted
on it. Messages and contacts are unaffected; restore it with
`systemctl --user restart mpris-proxy`.

Compared to the from-source install, the venv, the `~/.local/bin`
symlinks, the unit path substitution, the desktop-entry rewrite, and the
per-user sudoers installers all disappear; the package ships them.

## Uninstall completely

Everything, in order: the package, its privileged pieces, per-user data,
and the pairing. Skip the steps whose data you want to keep.

### 1. Stop the daemon (per user)

```bash
systemctl --user stop iphonebridge
```

If you also run `disable`, systemd warns that the unit is "enabled in
global scope"; that is expected. The global enablement comes from the
package's maintainer scripts and is removed by the purge in step 2, not
by per-user disable.

### 2. Purge the package

```bash
sudo apt purge iphonebridge
sudo apt autoremove        # drops auto-installed dependencies nobody else uses
```

`purge` (not plain `remove`) matters: the sudoers rules under
`/etc/sudoers.d/` are conffiles, and only purge deletes them.

### 3. Remove the group

```bash
sudo delgroup iphonebridge
```

The package's postinst creates it; removal is left to you because group
deletion while members exist is a policy decision, not packaging.

### 4. Per-user data

```bash
rm -rf ~/.config/iphonebridge          # iPhone MAC config
rm -rf ~/.local/state/iphonebridge     # message history, contacts cache, backups
```

### 5. Undo the optional call-audio setup, if you ran hfp-enable

```bash
rm -f ~/.config/wireplumber/wireplumber.conf.d/51-bluez-hfp-hf.conf
systemctl --user restart wireplumber
sudo systemctl disable --now ofono     # if nothing else uses it
```

### 6. Remove the pairing (both ends)

Linux: the Bluetooth panel's Remove/Forget, or
`bluetoothctl remove <MAC>`. iPhone: Settings, Bluetooth, tap the info
icon next to this computer, Forget This Device. Removing only one side
leaves a stale half-bond that will confuse a future pairing.

### 7. Adapter class

The A/V Hands-Free class the daemon set reverts to the adapter default
on the next reboot, or immediately with:

```bash
sudo systemctl restart bluetooth
```

Desktop menu and icon caches update themselves via package triggers;
nothing manual there.

## Known limits

- Pure-Python package, `Architecture: all`; one deb serves amd64/arm64.
- No auto-updates from a bare deb on GitHub Releases. A PPA or a small
  apt repo is the eventual fix (see BACKLOG).
- The daemon is a *user* service, globally enabled at install by
  debhelper's generated maintainer scripts: it starts at every user's
  login. Per-user opt-out is `systemctl --user mask iphonebridge`.
