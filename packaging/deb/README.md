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
Debian revision: the package is `iphonebridge_<version>_all.deb`, not
`<version>-1`. `debian/rules` also renames the sudoers files at install
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
manually (or use `dch` from `devscripts`). Native versioning: the
version alone, no `-1` suffix. Bump it in the same commit as
`pyproject.toml`, `src/iphonebridge/__init__.py`, and `CHANGELOG.md`.

## Build

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all lintian
dpkg-buildpackage -us -uc -b     # unsigned, binary-only
lintian ../iphonebridge_*_all.deb   # two no-manual-page warnings expected
```

## Cutting a release

Four files carry the version and must move together:

```
pyproject.toml            version = "X.Y.Z"
src/iphonebridge/__init__.py   __version__ = "X.Y.Z"
CHANGELOG.md              new [X.Y.Z] section at the top
debian/changelog          new entry, native versioning (no -1 suffix)
```

Then, from a clean tree:

```bash
python -m pytest tests -q && ruff check src/ tests/   # both must pass
git add pyproject.toml src/iphonebridge/__init__.py CHANGELOG.md debian/changelog
git commit -m "Release X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z — one-line summary"
git push && git push origin vX.Y.Z

dpkg-buildpackage -us -uc -b                          # builds ../iphonebridge_X.Y.Z_all.deb
lintian ../iphonebridge_X.Y.Z_all.deb                 # two no-manual-page warnings expected

gh release create vX.Y.Z -R santisbon/iphonebridge \
  --title "vX.Y.Z" --notes "..." ../iphonebridge_X.Y.Z_all.deb
```

Notes on that last command:

- **`-R` is not optional.** This repo was created with `gh repo fork`,
  which set `upstream` as gh's default repository, so a bare
  `gh release create` targets the original project and fails. Fix it
  permanently with `gh repo set-default santisbon/iphonebridge`.
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
GTK/Adwaita) install automatically. `ofono` and `wl-clipboard` come in as Recommends unless apt is configured to skip those.

Two `apt` notices are normal when installing from a local file: 
- "Note, selecting 'iphonebridge' instead of *path*" is `apt` resolving the file to the
package name it contains, and 
- "Download is performed unsandboxed as root ... Permission denied" appears when the file sits somewhere `apt`'s unprivileged `_apt`
user cannot read, such as a home directory (Ubuntu homes are mode 750). This can be silenced by copying the `.deb` to `/tmp` first.

Both are harmless.  

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
not to work on BE200). 
```sh
iphonebridge ancs-enable
```
then forget and re-pair (both ends, as in step 3), re-enable the step 5
toggles, and look for a third toggle, Show System Notifications.

The connection cycling in this step can crash bystander BlueZ user
daemons; `mpris-proxy` (media keys for Bluetooth audio) has segfaulted
on it. Messages and contacts are unaffected; restore it with
`systemctl --user restart mpris-proxy`.

Compared to the from-source install, the venv, the `~/.local/bin`
symlinks, the unit path substitution, the desktop-entry rewrite, and the
per-user sudoers installers all disappear; the package ships them.

### Reinstall

If you need to reintall
```sh
sudo apt reinstall ../iphonebridge_*_all.deb
systemctl --user restart iphonebridge
```

To deploy a new icon
```sh
sudo apt reinstall ../iphonebridge_*_all.deb
kbuildsycoca6 --noincremental   # nudge Plasma's icon cache; a re-login also does it
```

## Upgrading

Install the new package over the old one. Do not uninstall first:

```bash
sudo apt install ./iphonebridge_<version>_all.deb
systemctl --user daemon-reload
systemctl --user restart iphonebridge
```

Both steps matter. dpkg rewrites the unit file, so systemd warns that it
"changed on disk" and keeps using its cached copy until the reload;
skipping it is harmless while the unit's contents are unchanged between
releases, and applies a stale definition on any release that changes
them. And dpkg cannot restart per-user services at all, so the running
daemon keeps executing the old code until you restart it. Reopen the app
too if it is running.

What survives an upgrade, so none of it needs redoing: your group
membership (postinst only creates the group if missing, so no second
reboot), the pairing, and everything in your home directory — the iPhone
MAC in `~/.config/iphonebridge`, message history and the contacts cache
in `~/.local/state/iphonebridge`. The sudoers rules are conffiles, so
dpkg replaces them when untouched and prompts if you edited them.

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
sudoers rules are conffiles, and only purge deletes them), drops the
`iphonebridge` group, deletes your config and state, removes the
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
  apt repo is the eventual fix (see BACKLOG).
- The daemon is a *user* service, globally enabled at install by
  debhelper's generated maintainer scripts: it starts at every user's
  login. Per-user opt-out is `systemctl --user mask iphonebridge`.
