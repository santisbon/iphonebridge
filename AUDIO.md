# Listening to Apple Music on Linux: Bluetooth or Sidra

iPhone Bridge's Now Playing tab controls playback that is happening **on
the iPhone**, with the sound arriving over Bluetooth. That is one of two
ways to listen to Apple Music at a Linux desktop. The other is
[Sidra](https://github.com/wimpysworld/sidra), a desktop client that
wraps `music.apple.com` and plays through the computer's own audio
stack.

They are good at different things. This page is how to choose, and why.

One clarification: iPhone Bridge's Now Playing tab sends
control commands only. It cannot improve or degrade the sound, because
the audio never passes through it.

This page compares the two routes for **music**, where the difference in
sound quality is the whole question. The tab itself is not limited to
music: AVRCP addresses whichever player the phone has in front, so
podcasts and audiobooks are controlled the same way. For spoken audio
the argument below mostly evaporates, because a second encode at
Bluetooth bitrates costs speech far less than it costs music, and there
is no lossless tier to lose.

## Which one to use

**Use Sidra when the listening matters.** It is the better sounding of
the two, by a margin that comes from the signal path rather than from
tuning: Sidra decodes Apple's audio once and hands it to the sound
system. Bluetooth decodes it on the phone and encodes it a second time
to get it across the radio link. Sidra also leaves the phone out of it,
so nothing depends on the phone's battery, its distance from the desk,
or the 2.4 GHz band being quiet.

**Use Bluetooth with this app when the phone is already the player.**
It earns its place when:

- You arrived with music already playing on the phone and want the
  desk speakers, the track name, and the transport buttons without
  interrupting anything.
- You want one set of controls for music **and** calls and messages.
  A call arrives on the same link; Sidra knows nothing about calls.
- You listen to Dolby Atmos mixes. The iPhone renders those; the web
  player Apple serves to Sidra does not. This is a different mix rather
  than higher fidelity, and whether iOS applies its spatial rendering
  to a generic Bluetooth speaker is not something this project has
  measured.
- You would rather not run a DRM stack on Linux at all. See
  [DRM](#drm-sits-on-opposite-sides-in-the-two-paths) below.

**Neither gives you Apple Music Lossless.** See
[Lossless](#lossless-is-not-available-either-way).

## Why Sidra sounds better: the two signal paths

Apple Music streams AAC at about 256 kbps. What happens next differs.

**Over Bluetooth**, the phone decodes that AAC, then **re-encodes** the
result so it can cross the link, because Bluetooth audio carries a
compressed stream rather than the decoded samples. The computer decodes
that second encoding and plays it. Two lossy generations, and the
second one is applied to audio that has already had material removed.

**In Sidra**, the browser engine decodes Apple's AAC once and the
samples go straight to the sound system. One lossy generation, the one
Apple shipped, and nothing further touches it. Sidra is explicit about
this: it creates no `AudioContext`, so it adds no resampling and no DSP
of its own.

The gap is small on laptop speakers and grows with the quality of what
you listen on.

## The second encoding is usually SBC, not AAC

The sound system on this desktop is **PipeWire**, which
receives the Bluetooth audio stream and decodes it. It does that through
small per-codec plugins, one shared library per codec, and it can only
negotiate a codec it has a plugin for.

Debian and Ubuntu ship those plugins for SBC, aptX, LDAC, LC3 and Opus,
but **not for AAC**, and no package in the archive provides it. The
iPhone offers AAC; with nothing at the Linux end able to decode it, the
two sides settle on **SBC**, which is the oldest and weakest of the
Bluetooth audio codecs.

That matters because AAC into SBC is close to the worst pairing
available. SBC's artifacts land in the high frequencies that the first
AAC pass has already thinned out.

To see what your own link settled on, connect the phone's audio to this
computer, then run these three. Playing something makes the link's state
easy to confirm, but the codec is readable either way.

```sh
# The paired devices, with their addresses as BlueZ spells them.
# Find your iPhone in the list.
bluetoothctl devices
```

```sh
# The codec in use: Codec reads 0 for SBC and 2 for AAC. BlueZ publishes
# one audio transport object per connected audio link, under a path it
# names itself, so this looks the path up rather than making you type an
# address. State reads active while audio is flowing and idle when it is
# not; nothing prints at all if the phone's audio is not connected here.
for fd in $(busctl --system tree org.bluez | grep -oE '/org/bluez/\S+/fd[0-9]+'); do
  busctl --system introspect org.bluez "$fd" org.bluez.MediaTransport1 | grep -E '\.Codec|\.State'
done
```

```sh
# The codec plugins installed, x86-64 path shown. Look for a filename
# containing aac: on Debian and Ubuntu there is none, and without it the
# link cannot use AAC whatever the phone offers.
ls /usr/lib/x86_64-linux-gnu/spa-0.2/bluez5/
```

### Getting AAC over Bluetooth

It takes rebuilding PipeWire with its AAC codec enabled, against
`libfdk-aac-dev`. That is the same kind of exercise as
[`packaging/bluez-adv-fix.md`](packaging/bluez-adv-fix.md), and it is a
real improvement: AAC into AAC cascades more gently than AAC into SBC.
It does not change the fundamental point, though. The audio is still
encoded twice, so it narrows the gap with Sidra rather than closing it.

## Lossless is not available either way

Classic Bluetooth has no lossless audio codec. Every A2DP codec, SBC and
AAC and LDAC alike, discards information. If you subscribe for Apple
Music Lossless, none of it survives the radio link.

Sidra does deliver lossless, but only on macOS and Windows, where the
Widevine DRM component can be production-signed for a verified media
path. Its Linux build does not have that, so Linux gets the standard AAC
tier.

Take this as the practical position rather than a complaint about either
project: **Apple Music Lossless has no sanctioned route to a Linux
desktop today.**

## DRM sits on opposite sides in the two paths

**Bluetooth keeps DRM entirely on the phone.** FairPlay decrypts there,
and the computer receives ordinary audio. Nothing on Linux runs a
content-decryption module, so nothing here breaks when Apple or Google
changes theirs. That is a genuine robustness argument for this path, and
worth weighing against the fidelity argument.

**Sidra runs Widevine on Linux**, through a build of Electron that
includes it, because a stock Electron has no Widevine on Linux at all.
The quality tier Apple serves is gated on how that component is signed,
which is why lossless stops at the macOS and Windows builds. It also
means the path depends on Apple's requirements, Google's component, and
that Electron build continuing to line up.

## What else the Bluetooth path costs

Three things degrade Bluetooth listening in ways that are not obvious
while they happen:

- **The bitrate drops under interference.** Bluetooth shares 2.4 GHz
  with Wi-Fi. A congested band quietly costs quality mid-track.
- **Volume is applied before the encoding.** With absolute volume, the
  phone attenuates the signal digitally before compressing it, which
  spends resolution ahead of a lossy encoder. Keep the phone near
  maximum and set the level on the computer.
- **A call takes the link.** An incoming call switches Bluetooth to the
  call profile and the music stops.

## Summary

| | Bluetooth + this app | Sidra |
|---|---|---|
| Lossy encodes | Two | One |
| Second encode | Usually SBC | None |
| Lossless on Linux | No | No |
| DRM on this computer | None | Widevine |
| Calls and messages | Yes | No |
| Needs the phone | Yes | No |
| Dolby Atmos mixes | Rendered by the phone | Not served |
