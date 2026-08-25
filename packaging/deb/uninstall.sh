#!/usr/bin/env bash
# Remove iphonebridge and everything it installed: the package, its
# privileged pieces, per-user data, the optional call-audio setup, and
# the Linux side of the pairing.
#
# Run as your normal user (it calls sudo where needed), NOT with sudo:
# per-user state lives in your home directory and your systemd user scope.
#
#   bash uninstall.sh               remove everything (asks first)
#   bash uninstall.sh --keep-data   keep message history and contacts
#   bash uninstall.sh --keep-hfp    leave the oFono/WirePlumber setup alone
#   bash uninstall.sh --dry-run     print what would run, change nothing
#   bash uninstall.sh --yes         skip the confirmation
set -uo pipefail

KEEP_DATA=0; KEEP_HFP=0; DRY=0; YES=0
for arg in "$@"; do
    case "$arg" in
        --keep-data) KEEP_DATA=1 ;;
        --keep-hfp)  KEEP_HFP=1 ;;
        --dry-run)   DRY=1 ;;
        -y|--yes)    YES=1 ;;
        -h|--help)   awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

if [[ $EUID -eq 0 ]]; then
    echo "Run this as your normal user, not with sudo." >&2
    echo "It calls sudo itself for the steps that need root." >&2
    exit 1
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/iphonebridge"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/iphonebridge"
WP_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/wireplumber/wireplumber.conf.d/51-bluez-hfp-hf.conf"

# Read the paired MAC before anything deletes the config that holds it.
MAC=""
if [[ -f "$CONFIG_DIR/local.env" ]]; then
    MAC=$(sed -n 's/^IPHONEBRIDGE_MAC=//p' "$CONFIG_DIR/local.env" | tr -d '"' | head -1)
fi

step() { printf '\n[%s] %s\n' "$1" "$2"; }
run()  {
    if (( DRY )); then printf '    would run: %s\n' "$*"
    else "$@" >/dev/null 2>&1 || printf '    (skipped: %s)\n' "$1"
    fi
}

if (( ! YES && ! DRY )); then
    echo "This removes the iphonebridge package, its sudoers rules and group,"
    if (( KEEP_DATA )); then echo "and the Linux side of the pairing. Message history is kept."
    else echo "your message history and contacts cache, and the Linux side of the pairing."
    fi
    read -rp "Continue? [y/N] " ans
    [[ ${ans,,} == y* ]] || { echo "Nothing changed."; exit 0; }
fi

step 1/7 "Stopping the daemon"
run systemctl --user stop iphonebridge

step 2/7 "Purging the package (sudo)"
# purge, not remove: the sudoers rules are conffiles and only purge deletes them
run sudo apt-get purge -y iphonebridge
run sudo apt-get autoremove -y

step 3/7 "Removing the iphonebridge group (sudo)"
run sudo delgroup iphonebridge

if (( KEEP_DATA )); then
    step 4/7 "Keeping per-user data (--keep-data)"
    printf '    kept: %s\n    kept: %s\n' "$CONFIG_DIR" "$STATE_DIR"
else
    step 4/7 "Removing per-user config and state"
    run rm -rf "$CONFIG_DIR"
    run rm -rf "$STATE_DIR"
fi

if (( KEEP_HFP )); then
    step 5/7 "Keeping the call-audio setup (--keep-hfp)"
else
    step 5/7 "Removing the call-audio setup"
    run rm -f "$WP_CONF"
    run systemctl --user restart wireplumber
    printf '    oFono left installed; disable it with:\n'
    printf '      sudo systemctl disable --now ofono\n'
fi

step 6/7 "Removing the pairing (Linux side)"
if [[ -n "$MAC" ]]; then
    run bluetoothctl remove "$MAC"
else
    printf '    no configured MAC found; remove it in your Bluetooth panel\n'
fi

step 7/7 "Clearing desktop caches"
run rm -f "$HOME/.cache/icon-cache.kcache"
run kbuildsycoca6 --noincremental
run update-desktop-database "$HOME/.local/share/applications"

cat <<'DONE'

Done on this machine. One step is left, and only you can do it:

  On the iPhone: Settings, Bluetooth, tap the info icon next to this
  computer, Forget This Device.

Removing only the Linux side leaves a stale half-bond that breaks any
future pairing.
DONE
