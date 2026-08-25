# Screenshots

Documentation only. Nothing in this directory is packaged: `debian/install`
lists every shipped file by name, and pybuild only packages what is under
`src/`, so neither the images nor the scripts reach the `.deb`.

Each view is captured in both colour schemes:

| File | View |
| --- | --- |
| `messages-{light,dark}.png` | Conversation list and thread |
| `messages-reconnecting-{light,dark}.png` | Same, with the Bluetooth link down |
| `notifications-{light,dark}.png` | ANCS notification feed |
| `calls-{light,dark}.png` | Dialer and active calls |
| `setup-{light,dark}.png` | Daemon health and the iPhone checklist |

## The data is fake

Every name, number, and message comes from `seed.py`, and the numbers are
all in the 555 range. `shoot.py` points XDG_STATE_HOME and XDG_CONFIG_HOME
at a temp directory it seeds and then deletes, so a real message, contact,
or config value can never end up in a committed image.

## Regenerating

```sh
/usr/bin/python3 screenshots/shoot.py
```

Use the system interpreter: PyGObject and dbus-python come from apt, and a
conda or pyenv interpreter cannot see them. A graphical session is needed,
since this opens the real window for a moment. It renders through the
widget's own paintable rather than grabbing the screen, so the result is
the same under X11 and Wayland and never picks up the rest of your desktop.

`seed.py` pins its timestamps to a fixed date, so re-running with no code
changes reproduces the existing PNGs pixel for pixel.

Useful flags:

```sh
screenshots/shoot.py --scheme light           # one scheme only
screenshots/shoot.py --src /tmp/old/src \
                     --out /tmp/before        # shoot an older checkout
```

`--src` is how the before/after comparisons for a redesign get made: pull
an older tree out with `git archive <rev> src | tar -x -C /tmp/old`, render
it to a separate directory, and diff the two sets.
