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

## Code changes required first

These are the gaps between the from-source install and a system package.
Do them before the first build:

1. **Group-based sudoers.** The repo templates grant a single username,
   rendered at install time. A system package serves all users, so the
   shipped rules grant a group instead:

   ```
   %iphonebridge ALL=(root) NOPASSWD: /usr/bin/btmgmt class 4 8
   ```

   `bluez_setup.py` needs no change (it just runs `sudo -n`); only the
   rule files change, and `postinst` creates the group. Users add
   themselves once: `sudo adduser $USER iphonebridge`, then re-login.
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

Create top-level `debian/` with these files.

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

`debian/changelog`: generate the first entry with
`dch --create --package iphonebridge --newversion 0.6.0-1` (from the
`devscripts` package). Keep it in sync with `CHANGELOG.md` manually.

## Build

```bash
sudo apt install devscripts debhelper dh-python pybuild-plugin-pyproject
dpkg-buildpackage -us -uc -b     # unsigned, binary-only
lintian ../iphonebridge_0.6.0-1_all.deb
```

## Verify on a clean-ish machine

```bash
sudo apt install ./iphonebridge_0.6.0-1_all.deb
sudo adduser $USER iphonebridge   # then log out and back in
systemctl --user enable --now iphonebridge
iphonebridge doctor
iphonebridge pair-setup
```

The iPhone-side steps (pairing, toggles) are unchanged from the README;
what disappears is the venv, the symlinks, the unit `sed`, and the
per-user sudoers installers.

## Known limits

- Pure-Python package, `Architecture: all`; one deb serves amd64/arm64.
- No auto-updates from a bare deb on GitHub Releases. A PPA or a small
  apt repo is the eventual fix (see BACKLOG).
- The daemon is a *user* service; enabling it is inherently per-user.
  `systemd --user` presets could default it on, but that is a policy
  choice, not a requirement.
