# Screenshots

Documentation only. Nothing in this directory is packaged: `debian/install`
lists every shipped file by name, and pybuild only packages what is under
`src/`, so neither the images nor the scripts reach the `.deb`.

| File | View |
| --- | --- |
| `messages.png` | Conversation list and thread |
| `messages-daemon-down.png` | Same, with the daemon off the bus |
| `notifications.png` | ANCS notification feed |
| `calls.png` | Dialer and active calls |
| `setup.png` | Daemon health and the iPhone checklist |

## Light only, for now

The Qt UI uses QtQuick Controls' default Basic style, which draws a fixed
light palette: it follows neither the desktop theme nor
`QStyleHints.setColorScheme`, so a "dark" capture came out byte-identical
to the light one. There is no dark mode to photograph yet. The light/dark
pairs come back when the UI gets a style of its own, which is the step
after the port.

## The data is fake

Every name, number, and message comes from `seed.py`, and the numbers are
all in the 555 range. `shoot.py` points XDG_STATE_HOME and XDG_CONFIG_HOME
at a temp directory it seeds and then deletes, and it stubs the daemon
rather than calling it, so no real message, contact, or config value can
reach a committed image — and a message arriving mid-capture cannot either.

## Regenerating

```sh
/usr/bin/python3 screenshots/shoot.py
```

Use the system interpreter: PyQt6 and dbus-python come from apt, and a
conda or pyenv interpreter cannot see them.

It runs on Qt's `offscreen` platform by default, so no window appears and
it works over SSH; `--onscreen` uses the real display instead. Capture is
`QQuickWindow.grabWindow()`, which returns the scene graph's own composited
output — the same pixels the compositor gets, including scroll position.
The GTK version rendered through `Gtk.WidgetPaintable`, which could not see
scroll offset at all; do not reintroduce that blind spot.

`seed.py` pins its timestamps to a fixed date, so re-running with no code
changes reproduces the existing PNGs pixel for pixel.

Useful flags:

```sh
screenshots/shoot.py --onscreen               # watch it happen
screenshots/shoot.py --src /tmp/old/src \
                     --out /tmp/before        # shoot an older checkout
```

`--src` is how the before/after comparisons for a redesign get made: pull
an older tree out with `git archive <rev> src | tar -x -C /tmp/old`, render
it to a separate directory, and diff the two sets.
