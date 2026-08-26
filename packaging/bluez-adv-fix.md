# ANCS dark on BlueZ 5.85: fixing the advertising registration failure

If per-app notifications never work and the daemon logs this on every
start:

```
RegisterAdvertisement failed: org.bluez.Error.Failed: Failed to register advertisement
```

with `bluetoothd` logging (`journalctl -u bluetooth`):

```
src/advertising.c:add_client_complete() Failed to add advertisement: Invalid Parameters (0x0d)
```

then your adapter is not the problem, whatever its chipset. This page is
the diagnosis and the fix.

## What is actually wrong

Anatomy, once: registering a BLE advertisement goes application →
`bluetoothd` (BlueZ) → kernel → controller. iphonebridge asks bluetoothd
over D-Bus; bluetoothd translates that into a kernel *mgmt* command; only
then would the Bluetooth controller be involved. This failure happens at
the middle hop — the controller is never consulted.

BlueZ 5.85 sizes the buffer for `MGMT_OP_ADD_EXT_ADV_DATA` with the wrong
struct (the legacy `mgmt_cp_add_advertising`, 11-byte header, instead of
`mgmt_cp_add_ext_adv_data`, 3-byte header), so every advertising-data
command it sends carries **8 trailing garbage bytes**. Kernels that
enforce exact mgmt payload length reject the command with
`Invalid Parameters (0x0d)`, bluetoothd reports the generic
`org.bluez.Error.Failed`, and no advertisement can ever be registered —
by any application, with any payload, on any adapter.

Without the ANCS-soliciting advertisement, iOS never offers the *Show
System Notifications* toggle, so ANCS stays dark. MAP and PBAP don't use
LE advertising, which is why messages and contacts keep working.

Fixed upstream in BlueZ commit
[`2a6968b40`](https://github.com/bluez/bluez/commit/2a6968b40378dca5650e18e03ad0407738c47be5)
("advertising: Fix sending extra bytes with MGMT_OP_ADD_EXT_ADV_DATA") —
a one-line change. If your distro ships BlueZ with that commit, none of
this applies.

## Confirm it is this bug

`iphonebridge doctor` probes advertising registration directly and names
this document when it hits this failure. To see the raw evidence
yourself, watch the mgmt exchange while the daemon (or anything)
registers an advertisement:

```bash
sudo btmon
# in another terminal:
systemctl --user restart iphonebridge
```

The signature is a two-step failure, with the second command 8 bytes
longer than its contents:

```
@ MGMT Command: Add Extended Advertising Parameters (0x0054) ...
        Status: Success (0x00)
@ MGMT Command: Add Extended Advertising Data (0x0055) plen 29
        Advertising data length: 18
        Scan response length: 0
@ MGMT Event: Command Status ... Status: Invalid Parameters (0x0d)
```

(Empty advert: `plen 11` for lengths 0/0. The header is 3 bytes, so both
are exactly 8 over.)

## The fix: rebuild the distro package with the upstream patch

On an apt-based distro (shown for Kubuntu/Ubuntu with BlueZ
`5.85-4ubuntu0.1`; adjust versions to yours):

```bash
# 1. Enable source packages (deb822 format), then fetch the source
sudo sed -i.bak 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
sudo apt update
sudo apt install -y quilt devscripts
sudo apt build-dep -y bluez
mkdir -p ~/src/bluezbuild && cd ~/src/bluezbuild
apt source bluez

# 2. Add the upstream commit as a quilt patch
cd bluez-5.85
curl -sL https://github.com/bluez/bluez/commit/2a6968b40.patch \
  > debian/patches/fix-ext-adv-data-extra-bytes.patch
echo "fix-ext-adv-data-extra-bytes.patch" >> debian/patches/series
QUILT_PATCHES=debian/patches quilt push

# 3. Version it so the next distro upload supersedes it automatically
dch --local +fixadv "Cherry-pick upstream 2a6968b40: fix 8 extra bytes on MGMT_OP_ADD_EXT_ADV_DATA rejected by newer kernels."

# 4. Build and install the packages you already have installed
dpkg-buildpackage -us -uc -b
cd ..
sudo apt install ./bluez_5.85-4ubuntu0.1+fixadv1_amd64.deb \
                 ./bluez-obexd_5.85-4ubuntu0.1+fixadv1_amd64.deb \
                 ./bluez-cups_5.85-4ubuntu0.1+fixadv1_amd64.deb \
                 ./libbluetooth3_5.85-4ubuntu0.1+fixadv1_amd64.deb

# 5. Restart the stack
sudo systemctl restart bluetooth
systemctl --user restart iphonebridge
```

Install every bluez binary package you already had (`dpkg -l | grep
bluez`), not just `bluez` itself, so the set stays at one version.

## Verify

```bash
journalctl --user -u iphonebridge | grep -i advert | tail -1
# good: BLE advert registered: /me/santisbon/iphonebridge/ancs_advert

busctl --system get-property org.bluez /org/bluez/hci0 \
  org.bluez.LEAdvertisingManager1 ActiveInstances
# good: y 1
```

## After the fix: the phone side is still ahead of you

The rebuild only lets the advertisement register. Nothing about your
existing pairing changes, so the app's Status tab (and
`iphonebridge doctor`'s bond check) will keep showing ANCS as not
working until you finish the phone side. In order: re-pair first if the
bond predates a capable setup (forget on **both** ends, then pair), and
then:

```bash
iphonebridge ancs-enable
```

which reconnects the iPhone over BLE — answer the
**allow-notifications prompt** that appears on the phone (current iOS
asks this way rather than showing a third Bluetooth toggle). Seeing ANCS
still down immediately after the rebuild is expected, not a sign the fix
failed — the two checks above are what prove the fix took.

## Undoing / afterwards

The `+fixadv1` suffix sorts below any future distro upload, so a fixed
distro package replaces this automatically on a normal upgrade — nothing
is pinned and nothing needs undoing. To return to the stock (broken)
package immediately:

```bash
sudo apt install bluez=5.85-4ubuntu0.1 bluez-obexd=5.85-4ubuntu0.1 \
                 bluez-cups=5.85-4ubuntu0.1 libbluetooth3=5.85-4ubuntu0.1
```

To disable source packages again, restore the backup the `sed` made:
`sudo mv /etc/apt/sources.list.d/ubuntu.sources.bak /etc/apt/sources.list.d/ubuntu.sources && sudo apt update`.
