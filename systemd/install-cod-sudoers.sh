#!/usr/bin/env bash
# Install a sudoers.d entry that lets the iphonebridge user daemon set the
# adapter CoD without prompting for a password — but only for that one
# specific btmgmt invocation.
#
# Run as root: sudo bash systemd/install-cod-sudoers.sh
set -euo pipefail

SRC="$(dirname "$0")/sudoers-iphonebridge-cod"
DST=/etc/sudoers.d/iphonebridge-cod

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0" >&2; exit 1
fi

# Grant to the human who invoked sudo, not to root.
USER_TO_GRANT="${SUDO_USER:-}"
if [[ -z "$USER_TO_GRANT" || "$USER_TO_GRANT" == "root" ]]; then
    echo "Could not determine the non-root user to grant. Run via sudo." >&2
    exit 1
fi

# Resolve btmgmt: sudoers rules must name an absolute path, and it has to
# be the same path sudo resolves `btmgmt` to from secure_path.
BTMGMT=$(command -v btmgmt || true)
if [[ -z "$BTMGMT" ]]; then
    echo "btmgmt not found on PATH — sudo apt install bluez" >&2; exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
sed -e "s|@USER@|$USER_TO_GRANT|g" -e "s|@BTMGMT@|$BTMGMT|g" "$SRC" > "$TMP"

# Validate the rendered file before installing — bad sudoers files can lock you out
if ! visudo -cf "$TMP" >/dev/null; then
    echo "FATAL: rendered sudoers entry failed visudo -c. Not installing." >&2
    exit 1
fi

install -m 440 -o root -g root "$TMP" "$DST"
echo "[+] Installed $DST (for $USER_TO_GRANT)"

cat <<EOM

[+] The iphonebridge user daemon can now run '$BTMGMT class 4 8' without
    a password. On each daemon start (e.g. boot, login), it will set
    the adapter to A/V Hands-Free CoD automatically.

    Verify by restarting the daemon:
      systemctl --user restart iphonebridge

    Then check journalctl --user -u iphonebridge for a 'CoD set ok' line.

    Uninstall:
      sudo rm $DST
EOM
