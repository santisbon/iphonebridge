"""Media playback control over AVRCP, via BlueZ's MediaPlayer1 API.

`events` is toolkit-free (no dbus, no Qt) so the state mapping is
CI-testable and safe to import from the UI process; `client` is the only
module here that talks to BlueZ and belongs to the daemon side.
"""
