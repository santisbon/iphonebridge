# Working on iphonebridge

`DEVELOPMENT.md` covers how the project is built and run. This file covers
the things that are easy to get wrong, and why.

## Before telling anyone to test

Anatomy, once: the user-facing pieces are `iphonebridge` (CLI + daemon) and
`iphonebridge-ui` (the Qt app). Both install from a `.deb` into
`/usr/lib/python3/dist-packages/iphonebridge/`. The daemon runs as a
systemd **user** service.

1. **Find out which copy runs.** `systemctl --user show iphonebridge -p
   ExecStart`, or `/proc/<pid>/cmdline`. A deb install runs
   `/usr/bin/iphonebridge`; editing `src/` does not affect it.
2. **Rebuild.** `dpkg-buildpackage -us -uc -b`.
3. **Run `lintian` on the result.** A clean build reports exactly two
   warnings, both `no-manual-page`, one per entry point. Anything else is
   new and worth reading rather than waving through.
4. **Prove the artifact carries the change.** `dpkg-deb -x` it to a temp
   directory and grep for the new symbol, then diff every installed `.py`
   and `.qml` against the worktree. `dpkg-deb -c | grep '\.qml'` is the
   quick check that the QML shipped at all, since it rides on
   `package-data` rather than on `debian/install`.
5. **Install.** `sudo apt install --reinstall
   ../iphonebridge_<version>_all.deb`. `--reinstall` is required whenever
   the version has not changed: apt compares versions, finds nothing to
   do, and exits 0 without saying so.
6. **Restart the daemon** (`systemctl --user restart iphonebridge`) and
   **reopen the app**. dpkg cannot restart a user service, and a running
   app does not reload QML.
7. **State what is built, what is deployed, and what is left to run.**

## Test harnesses

- **Set `QML_DISABLE_DISK_CACHE=1`** in anything that loads `Main.qml`
  directly. Qt caches compiled QML keyed on the source path and timestamp,
  and dpkg installs with a build-normalised mtime, so a rebuilt file can be
  served from a stale cache entry. `main()` sets this variable; a harness
  that builds its own engine does not, and will measure the previous build.
- **Publish the QML context with `install_context(engine, bridge)`.** A
  hand-written list of `setContextProperty` calls drifts from the app's,
  and a harness that publishes a model the app does not is testing
  something that only exists in the test.
- **Confirm the instrument moves.** Assert that the state being measured
  actually changed, or a harness can pass while measuring nothing.
- **Drive real input** with `QTest.mouseClick` and `QTest.mouseMove`.
  Setting a property like `highlighted` directly does not move the style's
  own highlight, so a control can measure as correct while drawing wrong.
- **`findChild` does not reach QML delegate items**; their QObject parent
  is not their visual parent. Walk `childItems()` recursively.
- **Offscreen is not a desktop session.** `QT_QPA_PLATFORM=offscreen` loads
  no platform theme, so the palette is default-light and `colorScheme`
  reads `Unknown`. Light/dark and style-dependent behaviour cannot be
  judged from it.
- Do not name scratch files after stdlib modules; the scratch directory is
  on `sys.path` and will shadow them.

## Reproduce before fixing

Do not ship a fix for a fault that has not been reproduced. When it cannot
be reproduced, say so and instrument instead: `IPHONEBRIDGE_UI_DIAG=1` logs
which conversation is open, its row, which rows would draw an unread dot,
and whether an arriving message keys to the open thread, as SHA-256
prefixes.

When a fix does not resolve the reported symptom, say so plainly. A correct
fix for a real bug is still not the reported bug.

## Privacy

Real messages, contacts and phone numbers must never reach a transcript or
a committed file.

- Render screenshots from `screenshots/seed.py`. `shoot.py` redirects
  `XDG_STATE_HOME` and stubs the daemon so the real `events.jsonl` is never
  read.
- When analysing the real log, print digests and counts, never bodies,
  names or numbers. Capturing a screenshot of the running app prints them.

## Qt and QML

- **The desktop's Quick Controls style owns parts of a control.** On the
  target desktops that is `org.kde.desktop`/`org.kde.breeze`, not Basic.
  `Menu`'s internal `ListView` carries the style's highlight item and draws
  it over the `MenuItem` background; replace `contentItem` with a list
  whose `highlight` is `null`.
- **Set `popupType: Popup.Item`** on menus and popups, or the platform
  draws them and ignores the styling.
- **`theme: theme` binds a property to itself and resolves to null.** The
  `Theme` instance is `appTheme` so a component with its own `theme`
  property cannot shadow it.
- **`anchors.fill` overrides an explicit `width`.** Use explicit edges when
  the width is constrained.
- **Do not bind `topMargin` to `height - contentHeight`.** The margin
  changes the flickable's extents, which changes which delegates are
  realised, which re-estimates `contentHeight`. Assign it from a settle
  timer.
- **Following the end of a growing list takes more than one call.** On
  `countChanged` the new delegate is not laid out, so the end is still
  estimated. Re-assert on `contentHeightChanged` and `originYChanged`, and
  compute the end as `originY + contentHeight - height`;
  `positionViewAtEnd()` behaves as though `originY` were zero.
- **`currentIndex` must be bound, never assigned.** An imperative write
  from a delegate destroys the binding and freezes the highlight.
- **Rich text ignores percentage font sizes.** Use absolute `pt`.
- **`font.families` is not assignable on Controls.** Resolve one installed
  family with `Qt.fontFamilies()`.
- **Never hard-code `font.pixelSize`.** Derive sizes from
  `Qt.application.font.pointSize` so the interface follows the desktop's
  font setting, and scale text-dependent geometry with it.
- **`ContextMenu` is a reserved type name**; a file of that name shadows
  Qt's own with something that cannot be instantiated.
- A `Label`'s implicit width is fractional, so its position and width round
  separately and right edges jitter. Use `Layout.preferredWidth:
  Math.ceil(implicitWidth)` where a column of values must align.
- An empty item in a layout still costs its spacing. Hide it.

## Colour

Apple's `systemFill`, `rgb(120,120,128)`, carries +8 blue and is a
**surface** colour. A hover or a press is the surface made lighter or
darker: use `theme.hover` and `theme.pressed`, which are white and black at
low alpha and leave the hue unchanged.

## Tests and CI

CI installs `python3-dbus` and `python3-gi` but **not PyQt6**. Nothing
under `tests/` may import Qt. Logic worth testing belongs in
`ui/model.py`, `ui/protocol.py` or `ui/util.py`, which are toolkit-free by
design. Run `.venv/bin/ruff check src/ tests/` and
`.venv/bin/python -m pytest -q` before reporting anything as done.
