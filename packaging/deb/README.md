# Building the .deb

One package installs everything: the daemon, the CLI, the Qt app, the
systemd user unit, the desktop entry and icon, the daemon's AppArmor
profile, and the root unit and polkit rule that set the adapter's class.
The system-level pieces are what ruled sandboxed formats out.
Target: Debian-family distros (Pop!_OS, Kubuntu, Debian).

Anatomy, once: the user-facing build command is `make deb`. It runs
`dpkg-buildpackage`, which writes its output to the checkout's parent
directory; `make deb` then moves the `.deb`, `.buildinfo` and `.changes`
into `dist/` and runs `lintian` on the `.deb`. `dpkg-buildpackage`
runs `debian/rules`, which delegates to the `debhelper` sequencer (`dh`),
which builds the Python package through `pybuild` using the existing
`pyproject.toml`. You write the small files in `debian/`; the tooling
does the rest.

## What the package ships

| Repo source | Installed path |
|---|---|
| `src/iphonebridge/` (incl. `ui/qml/`) | `/usr/lib/python3/dist-packages/iphonebridge/` |
| entry points from `pyproject.toml` | `/usr/bin/iphonebridge`, `/usr/bin/iphonebridge-ui` |
| `systemd/iphonebridge.service` (placeholder substituted) | `/usr/lib/systemd/user/iphonebridge.service` |
| `systemd/iphonebridge-daemon`, the daemon's own entry point | `/usr/libexec/iphonebridge/iphonebridge-daemon` |
| `apparmor/iphonebridge`, the daemon's AppArmor profile | `/etc/apparmor.d/iphonebridge` |
| `systemd/iphonebridge-cod.service`, the root unit that sets the adapter's class | `/usr/lib/systemd/system/iphonebridge-cod.service` |
| `systemd/50-iphonebridge-cod.rules`, the polkit rule that lets a local user start that unit | `/usr/share/polkit-1/rules.d/50-iphonebridge-cod.rules` |
| `data/me.santisbon.iphonebridge.UI.desktop` (as-is: `Exec=iphonebridge-ui` is on PATH now) | `/usr/share/applications/` |
| `data/icons/me.santisbon.iphonebridge.UI.svg` | `/usr/share/icons/hicolor/scalable/apps/` |
| `data/me.santisbon.iphonebridge.UI.metainfo.xml` | `/usr/share/metainfo/` |
| `man/*.1` via `debian/iphonebridge.manpages` | `/usr/share/man/man1/` |

## How the daemon is confined

The daemon parses whatever the paired phone sends: messages, contacts,
notifications. AppArmor confines it, so a crafted message that takes it
over reaches only what the profile allows.

- **Its own path.** `/usr/bin/iphonebridge` is also the CLI, and AppArmor
  attaches a profile by the path of the program run. The user unit runs
  `/usr/libexec/iphonebridge/iphonebridge-daemon` instead, and the
  profile attaches to that path, so the CLI and the app stay unconfined.
- **No sudo.** Setting the adapter's class needs root. The daemon starts
  `iphonebridge-cod.service` over D-Bus (`StartUnit` on the system bus)
  when the class is wrong; the unit runs `btmgmt class 4 8` as root, and
  the polkit rule lets a local user start that one unit. The profile
  allows no other program to run except `wl-copy`.
- **D-Bus by path.** python-dbus sends to a service's unique name
  (`:1.42`), not its well-known name, so the profile's rules match object
  paths and interfaces: BlueZ under `/org/bluez`, oFono's modems under
  `/hfp/org/bluez`, obexd under `/org/bluez/obex`, notifications, and the
  daemon's own `/me/santisbon/iphonebridge`. On the session bus, the one
  systemd call allowed is `RestartUnit`, for obexd; systemd's private
  socket is denied, because it reaches systemd's whole API without passing
  through the D-Bus rules.
- **Files.** Read and write only `~/.local/state/iphonebridge/`, read
  `~/.config/iphonebridge/`, and the OBEX transfer files in `/tmp`.
- **systemd's sandbox settings are not used.** `ProtectSystem=`,
  `ProtectHome=` and `PrivateTmp=` need a mount namespace, which a user
  unit gets only inside a user namespace; Ubuntu restricts those, so
  systemd skips the settings. The unit sets `NoNewPrivileges`,
  `RestrictSUIDSGID`, `LockPersonality` and `UMask=0077`, which work
  without one.

The profile was written from what AppArmor logged in complain mode while
messages, a reply, contacts, calls, media and cover art were used on
Ubuntu 26.10 with an iPhone 17 Pro, on 2026-10-27, and then checked in
enforce mode with no denials. Rules for one machine go in
`/etc/apparmor.d/local/iphonebridge`, which the profile includes if it
exists.

## The debian/ directory

Top-level `debian/` exists in the repo with these files, plus
`debian/copyright` (GPL-2+, upstream and ancs4linux attribution;
required, lintian errors without it) and `debian/source/format`
containing `3.0 (native)`. Native format means the version has no
Debian revision: the package is `iphonebridge_<version>_all.deb`, not
`<version>-1`. `debian/rules` also disables pybuild's test run
(`PYBUILD_DISABLE = test`); tests run in CI.

`debian/control`:

```
Source: iphonebridge
Section: comm
Priority: optional
Maintainer: santisbon <santisbon@users.noreply.github.com>
Build-Depends: debhelper-compat (= 13), dh-python, python3-all,
 python3-setuptools, pybuild-plugin-pyproject, dh-apparmor
Standards-Version: 4.6.2
Homepage: https://github.com/santisbon/iphonebridge

Package: iphonebridge
Architecture: all
Depends: ${python3:Depends}, ${misc:Depends},
 python3-dbus, python3-gi, python3-typer,
 python3-pyqt6, python3-pyqt6.qtqml, python3-pyqt6.qtquick,
 python3-dbus.mainloop.pyqt6,
 qml6-module-qtquick-controls, qml6-module-qtquick-layouts,
 qml6-module-qtquick-templates, qml6-module-qtquick-window,
 qt6-wayland, gir1.2-ibus-1.0,
 bluez (>= 5.72), bluez-obexd, polkitd
Recommends: ofono, wl-clipboard, qt6-gtk-platformtheme,
 ibus-data, fonts-noto-color-emoji
Description: iPhone messages, calls, and contacts over Bluetooth
 Daemon, CLI, and Qt app bridging a paired iPhone via the standard
 Bluetooth profiles MAP, PBAP, ANCS, and HFP. No Mac relay, no cloud
 service, no subscription.
 .
 Ships the systemd user unit, the desktop entry, and the AppArmor
 profile that confines the daemon. The one privileged operation, setting
 the adapter's Class-of-Device, runs in a root system unit that a polkit
 rule lets the daemon start.
```

Two of those are about the desktop the app lands on rather than the app
itself. `qt6-wayland` ships Qt's Wayland platform plugin, and nothing in
the PyQt6 dependency chain pulls it in — on this machine it arrived via
`plasma-workspace`, so a KDE box has it by accident. Without it Qt falls
back to XWayland, which runs but is blurry under fractional scaling.
`qt6-gtk-platformtheme` is a Recommends because it only matters on a GTK
desktop, where it is what makes Qt pick up GNOME's fonts, colours and
dark-mode preference; it is also what initialises GTK inside the process
and produces the accessibility-bus warning documented in the README.

The emoji picker reads the system's emoji dictionary rather than
shipping one: `gir1.2-ibus-1.0` (tiny, a Depends) is the binding that
loads it, and `ibus-data` (a Recommends — GNOME and KDE both install it
anyway, it feeds the desktop's own Meta+. picker) is the dictionary
itself. Without it the picker shows a hint naming the package.
`fonts-noto-color-emoji` draws the glyphs in colour.

`debian/rules` (executable) points the user unit at the daemon's own
path, installs and loads the AppArmor profile with `dh_apparmor`, and
keeps dh_installsystemd from starting `iphonebridge-cod.service` at
installation:

```makefile
override_dh_install:
	dh_install
	mkdir -p debian/iphonebridge/usr/lib/systemd/user
	sed "s|@INSTALL_DIR@/.venv/bin/iphonebridge run|/usr/libexec/iphonebridge/iphonebridge-daemon|" \
	  systemd/iphonebridge.service \
	  > debian/iphonebridge/usr/lib/systemd/user/iphonebridge.service
	dh_apparmor --profile-name=iphonebridge -piphonebridge

override_dh_installsystemd:
	dh_installsystemd --no-start iphonebridge-cod.service
```

`debian/install`:

```
data/me.santisbon.iphonebridge.UI.desktop      usr/share/applications/
data/icons/me.santisbon.iphonebridge.UI.svg    usr/share/icons/hicolor/scalable/apps/
data/me.santisbon.iphonebridge.UI.metainfo.xml usr/share/metainfo/
systemd/iphonebridge-daemon                    usr/libexec/iphonebridge/
systemd/iphonebridge-cod.service               usr/lib/systemd/system/
systemd/50-iphonebridge-cod.rules              usr/share/polkit-1/rules.d/
apparmor/iphonebridge                          etc/apparmor.d/
```

`debian/postinst` reloads each logged-in user's systemd manager, so the
rewritten user unit is not served from cache. On an upgrade from 0.19.0
or earlier it also deletes the `iphonebridge` group, which granted the
two passwordless sudo rules those versions shipped;
`debian/iphonebridge.maintscript` deletes the two sudoers files
(`/etc/sudoers.d/iphonebridge-cod` and `iphonebridge-ancs`).

`debian/changelog`: hand-written; keep in sync with `CHANGELOG.md`
manually (or use `dch` from `devscripts`). Native versioning: the
version alone, no `-1` suffix. Bump it in the same commit as
`pyproject.toml`, `src/iphonebridge/__init__.py`, and `CHANGELOG.md`.

## Build

```bash
sudo apt install debhelper dh-python dh-apparmor pybuild-plugin-pyproject python3-all lintian
```

```bash
make deb     # unsigned, binary-only, into dist/; lintian prints nothing for a clean build
```

## Cutting a release

Five files carry the version and must move together:

```
pyproject.toml            version = "X.Y.Z"
src/iphonebridge/__init__.py   __version__ = "X.Y.Z"
CHANGELOG.md              new [X.Y.Z] section at the top
debian/changelog          new entry, native versioning (no -1 suffix)
data/me.santisbon.iphonebridge.UI.metainfo.xml   new <release> entry
```

The man pages are deliberately not a sixth: their `.TH` version is
substituted from `debian/changelog` at build time. The metainfo file is
the one that gets forgotten, because nothing in the build reads it, so it
goes stale silently — and it is what a software centre shows as the app's
latest version and what changed in it. Check it with
`appstreamcli validate data/me.santisbon.iphonebridge.UI.metainfo.xml`.

Then, from a clean tree:

```bash
python -m pytest tests -q && ruff check src/ tests/   # both must pass
git add pyproject.toml src/iphonebridge/__init__.py CHANGELOG.md \
        debian/changelog data/me.santisbon.iphonebridge.UI.metainfo.xml
git commit -m "Release X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z — one-line summary"
git push && git push origin vX.Y.Z

make deb             # builds dist/iphonebridge_X.Y.Z_all.deb; lintian prints nothing for a clean build

gh release create vX.Y.Z -R santisbon/iphonebridge \
  --title "vX.Y.Z" --notes "..." dist/iphonebridge_X.Y.Z_all.deb
```

Notes on that last command:

- **Keep `-R`.** It names the repository the release is cut against,
  and being explicit costs nothing. This repo began as a `gh repo fork`,
  which points gh's default repository at the project it was forked
  from; a bare `gh release create` then targets that project and fails.
  The default here is already `santisbon/iphonebridge`, and the fork's
  `upstream` remote has been removed, but neither of those is visible
  from the command, and `gh repo set-default` is per clone. A fresh
  clone gets it wrong again. Check with `gh repo set-default --view`.
- Attach the `.deb`. The README's install instructions point users at
  the latest release, so a release without the asset is a broken link
  for them.
- Build the package *after* tagging, so what you attach matches the tag.
- Version numbering is SemVer, pre-1.0: breaking changes and new
  features bump the minor, fixes bump the patch.

## Install

Every step from a bare system to working messages, contacts, and calls.

### 1. Install the package

```bash
sudo apt install ./iphonebridge_*_all.deb
```

Dependencies (`bluez`, `bluez-obexd`, `python3-dbus`, `python3-gi`,
PyQt6 and the QtQuick QML modules) install automatically. `ofono` and `wl-clipboard` come in as Recommends unless apt is configured to skip those.

Two `apt` notices are normal when installing from a local file: 
- "Note, selecting 'iphonebridge' instead of *path*" is `apt` resolving the file to the
package name it contains, and 
- "Download is performed unsandboxed as root ... Permission denied" appears when the file sits somewhere `apt`'s unprivileged `_apt`
user cannot read, such as a home directory (Ubuntu homes are mode 750). This can be silenced by copying the `.deb` to `/tmp` first.

Both are harmless.  

### 2. Start the daemon

```bash
systemctl --user start iphonebridge
```

No enable step is needed: debhelper's maintainer scripts enable the user
unit globally at install time, so the daemon starts at every user's
login from now on. A user who does not want it can opt out with
`systemctl --user mask iphonebridge` (plain disable is overridden by the
global enablement).

The daemon sets the adapter's Bluetooth class (A/V Hands-Free) on every
start, through `iphonebridge-cod.service`; iOS only offers the message
and contacts toggles to a device with that class. Without the toggles
yet, the daemon logs `DEGRADED mode`, stays running, and retries every
60s. That is expected at this point.

### 3. Pair the iPhone

If this iPhone was ever paired to this computer, remove the old bond on
**both** ends first; one-sided forgetting leaves a stale half-bond that
breaks the new pairing. Linux: the Bluetooth panel's Remove/Forget or
`bluetoothctl remove <MAC>`. iPhone: Settings, Bluetooth, tap the info
icon next to the computer, Forget This Device.

Then start the pairing **on the iPhone**, with the computer discoverable
and a Bluetooth agent (the program that shows and confirms the 6-digit
code) running on the computer:

- KDE Plasma: keep System Settings, Bluetooth open on the computer
- GNOME: keep Settings, Bluetooth open on the computer
- CLI: `bluetoothctl`, then `agent on`, `default-agent`, `pairable on`,
  `discoverable on`

On the iPhone, open Settings, Bluetooth and tap the computer under Other
Devices. Confirm the matching 6-digit code on both sides; with
`bluetoothctl`, also answer `yes` to its Authorize service questions,
then run `trust <MAC>` and `quit`. A pairing the iPhone starts gives the
bond the Low Energy keys per-app notifications need (step 8): on an Intel
BE200 adapter, a pairing the computer started stored classic Bluetooth
keys only.

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

Adapter-dependent: Intel chipsets (AX-series, BE200) can form the BLE
bond this needs; Realtek and USB dongles cannot. Two prerequisites, in
order:

1. BlueZ's experimental interfaces, with BlueZ's own Hands-Free client
   off. A systemd drop-in runs bluetoothd with `-E --noplugin=hfp`:

   ```sh
   sudo mkdir -p /etc/systemd/system/bluetooth.service.d
   printf '[Service]\nExecStart=\nExecStart=/usr/libexec/bluetooth/bluetoothd -E --noplugin=hfp\n' \
     | sudo tee /etc/systemd/system/bluetooth.service.d/iphonebridge.conf
   sudo systemctl daemon-reload
   sudo systemctl restart bluetooth
   systemctl --user restart iphonebridge
   ```

   `-E` turns on BlueZ's experimental interfaces, which `ancs-enable`'s bearer control needs. On BlueZ 5.86 and later it also turns on BlueZ's own Hands-Free client (the plugin `hfp`), which connects to the iPhone by itself and takes the Hands-Free link oFono needs for calls; `--noplugin=hfp` keeps it off. The drop-in leaves the bluez package's `/etc/bluetooth/main.conf` as shipped. `/usr/libexec/bluetooth/bluetoothd` is the path in Debian's and Ubuntu's bluez package; elsewhere, use the path in the `ExecStart=` line of `systemctl cat bluetooth`. A `[General] Experimental = true` line in `/etc/bluetooth/main.conf` can stay: the drop-in still keeps the `hfp` plugin off.

2. A bond with LE keys. A pairing made per step 3 on a capable adapter
   already has them; if in doubt, forget on both ends and re-pair (then
   re-enable the step 5 toggles).

Then:

```sh
iphonebridge ancs-enable
```

reconnects the iPhone over BLE; the phone then offers a third toggle,
**Share System Notifications** (some iOS versions ask with an
allow-notifications prompt instead) — turn it on, and `iphonebridge
doctor` should report the bond exposing ANCS with the LE link up.

The connection cycling in this step can crash bystander BlueZ user
daemons; `mpris-proxy` (media keys for Bluetooth audio) has segfaulted
on it. Messages and contacts are unaffected; restore it with
`systemctl --user restart mpris-proxy`.

Compared to the from-source install, the venv, the `~/.local/bin`
symlinks, the unit path substitution, the desktop-entry rewrite, and the
system pieces for the adapter's class all disappear; the package ships
them.

### Reinstall

If you need to reintall
```sh
sudo apt reinstall ./dist/iphonebridge_<version>_all.deb
systemctl --user restart iphonebridge
```

To deploy a new icon
```sh
sudo apt reinstall ./dist/iphonebridge_<version>_all.deb
kbuildsycoca6 --noincremental   # nudge Plasma's icon cache; a re-login also does it
```

## Upgrading

Install the new package over the old one. Do not uninstall first:

```bash
sudo apt install ./iphonebridge_<version>_all.deb
systemctl --user restart iphonebridge
```

**Rebuilding the same version needs `--reinstall`.** During development
`debian/changelog` usually does not get a new entry between builds, so the
freshly built `.deb` carries the version that is already installed. apt
compares versions, sees no upgrade, and does nothing — silently, with a
zero exit status. The result is a build that never reaches the system and
a daemon that keeps running the old code:

```bash
sudo apt install --reinstall ./iphonebridge_<version>_all.deb
systemctl --user restart iphonebridge
```

The restart is required and is not optional politeness: dpkg cannot
restart per-user services, so the running daemon keeps executing the old
code until you restart it. Reopen the app too if it is running.

Confirm the running daemon is the one you just built, rather than assuming
the install landed:

```bash
journalctl --user -u iphonebridge -n 20 | grep "sink ready"
```

No `daemon-reload` is needed: dpkg rewrites the unit file and systemd
would otherwise keep its cached copy, so `postinst` reloads each
logged-in user's manager. (`systemctl --global daemon-reload` does not
exist — `--global` covers enable and disable only — so the reload
iterates over `loginctl list-users`. Anyone logging in later starts a
fresh manager that reads the unit anyway.)

What survives an upgrade, so none of it needs redoing: the pairing, and
everything in your home directory — the iPhone MAC in
`~/.config/iphonebridge`, message history and the contacts cache in
`~/.local/state/iphonebridge`. The AppArmor profile is a conffile, so
dpkg replaces it when untouched and prompts if you edited it; put local
rules in `/etc/apparmor.d/local/iphonebridge` instead.

## Uninstall completely

```bash
bash packaging/deb/uninstall.sh
```

Without a clone, fetch just the script — it is deliberately not shipped
inside the package, since a script that purges the package owning it
would be deleting itself mid-run:

```bash
curl -fsSLO https://raw.githubusercontent.com/santisbon/iphonebridge/main/packaging/deb/uninstall.sh
bash uninstall.sh
```

Run it as your normal user, not with sudo: per-user state lives in your
home directory and your systemd user scope, and the script calls sudo
itself for the steps that need root. It asks before doing anything, and
`--dry-run` prints every command without changing a thing.

It stops the daemon, purges the package (purge rather than remove: the
AppArmor profile is a conffile, and only purge deletes it), deletes the
`iphonebridge` group that versions up to 0.19.0 created, deletes your
config and state, removes the
call-audio setup, unpairs the iPhone on the Linux side, and clears the
desktop icon and menu caches (per-user caches outlive the package and
otherwise leave a broken window icon behind).

Flags: `--keep-data` keeps message history and the contacts cache,
`--keep-hfp` leaves the oFono and WirePlumber setup alone, `--yes` skips
the confirmation.

The script reads your paired MAC from the config before deleting it, so
it can unpair; the iPhone side it cannot touch. Finish there: Settings,
Bluetooth, tap the info icon next to this computer, Forget This Device.
Removing only the Linux side leaves a stale half-bond that breaks any
future pairing.

oFono stays installed, since other software may use it. Remove it with
`sudo systemctl disable --now ofono`.

## Known limits

- Pure-Python package, `Architecture: all`; one deb serves amd64/arm64.
- No auto-updates from a bare deb on GitHub Releases. A PPA or a small
  apt repo is the eventual fix.
- The daemon is a *user* service, globally enabled at install by
  debhelper's generated maintainer scripts: it starts at every user's
  login. Per-user opt-out is `systemctl --user mask iphonebridge`.
