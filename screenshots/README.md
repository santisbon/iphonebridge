# Screenshots

Documentation only. Nothing in this directory is packaged: `debian/install`
lists every shipped file by name, and pybuild only packages what is under
`src/`, so neither the images nor the scripts reach the `.deb`.

| File | View |
| --- | --- |
| `messages.png` | Conversation list and thread, with the link indicator |
| `messages-daemon-down.png` | Same, with the daemon off the bus |
| `notifications.png` | ANCS notification feed |
| `calls.png` | Dialer, and an active call with Answer / Hang up |
| `setup.png` | Daemon health, the iPhone checklist, data counts |

## Why these are light

The app does follow your desktop's light/dark setting — the palette comes
from Qt's platform theme. These captures are light because `shoot.py`
renders on Qt's `offscreen` platform, which loads no platform theme at
all, so the default light palette applies.

That is deliberate: offscreen is the reproducible one. It renders at 1x on
any machine, while an on-screen capture follows the display's device pixel
ratio, and it does not depend on whatever scheme the desktop happens to be
in that day.

There is no way to force the other scheme offscreen. Neither
`QStyleHints.setColorScheme` nor `QGuiApplication.setPalette` changes what
gets drawn — both were tried, and the render is byte-identical either way.
To see the app in your own scheme, use `--onscreen`.

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
