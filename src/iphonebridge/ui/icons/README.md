Bundled symbolic icons.

Drop SVGs exported from Icon Library (org.gnome.design.IconLibrary) here,
keeping the `-symbolic.svg` suffix, and reference them anywhere in the UI
by filename without the extension, e.g. `chat-bubble-symbolic.svg` →
`icon_name="chat-bubble-symbolic"`. The directory is registered with the
icon theme at app startup (see app.py), and `-symbolic` icons recolor with
the theme automatically.

Icon Library's icons come from GNOME's icon development kit and are
marked as free to use in your projects.
