"""Emoji database for the picker — read from the system, not shipped.

The source is ibus's emoji dictionary (`ibus-data`), the same file the
desktop's own Meta+. picker reads, loaded through the IBus introspection
binding. Every entry carries its Unicode name, CLDR category and search
keywords, so the picker gets all of it — search included — without this
project hardcoding a single glyph.

Everything except `load_emoji_db` is pure and CI-tested; the loader does
the one `gi` import lazily and degrades to an empty list, which the UI
renders as "no picker" rather than a crash. CI has python3-gi but not
the IBus typelib, which is another reason the import stays inside the
function.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger(__name__)

DICT_PATH = "/usr/share/ibus/dicts/emoji-en.dict"
RECENTS_CAP = 30

#: The five Unicode skin tone modifiers, lightest first, in the order a
#: picker offers them. Index into this is what `apply_tone` calls a tone;
#: -1 means the neutral form the dictionary lists on its own.
SKIN_TONES = tuple(chr(cp) for cp in range(0x1F3FB, 0x1F400))
NEUTRAL_TONE = -1

#: Variation selectors: the invisible characters that ask for the emoji
#: or the text rendering of a character that has both.
_VARIATION_SELECTORS = ("️", "︎")


class EmojiEntry(NamedTuple):
    emoji: str
    description: str
    category: str
    annotations: tuple[str, ...]


def load_emoji_db(path: str = DICT_PATH) -> list[EmojiEntry]:
    """All entries from the system dictionary; [] when unavailable."""
    try:
        import gi
        gi.require_version("IBus", "1.0")
        from gi.repository import IBus
        data = IBus.EmojiData.load(path)
    except Exception:
        log.exception("emoji dictionary unavailable (%s)", path)
        return []
    out = []
    for d in data:
        try:
            out.append(EmojiEntry(
                emoji=str(d.get_emoji()),
                description=str(d.get_description()),
                category=str(d.get_category()),
                annotations=tuple(str(a) for a in d.get_annotations()),
            ))
        except Exception:
            continue
    return out


def fold_spellings(emoji: list[str]) -> list[str]:
    """One cell per emoji, rather than one per way of spelling it.

    The dictionary lists a sequence once for every arrangement of the
    emoji-presentation selector it allows: the rainbow flag appears
    twice and the transgender flag four times, all drawing the same
    glyph. They are different code point sequences, so only a normalised
    key tells them apart, and a grid built straight from the dictionary
    repeats the same picture two, three or four times over.

    Position is the dictionary's, taken from where the first spelling
    fell. The spelling kept is the fully-qualified one, carrying the most
    selectors: dropping a selector is exactly what asks a font for the
    monochrome text form of a character that has both.
    """
    out: list[str] = []
    at: dict[str, int] = {}
    for e in emoji:
        key = _strip_selectors(e)
        if key not in at:
            at[key] = len(out)
            out.append(e)
        elif _selectors(e) > _selectors(out[at[key]]):
            out[at[key]] = e
    return out


def _selectors(emoji: str) -> int:
    return sum(1 for ch in emoji if ch in _VARIATION_SELECTORS)


def _strip_selectors(emoji: str) -> str:
    return "".join(ch for ch in emoji if ch not in _VARIATION_SELECTORS)


def build_groups(entries: list[EmojiEntry]) -> list[dict]:
    """Category groups for browsing, in the dictionary's own order.

    Skin-tone variants are folded away (the neutral form stays), and the
    Component category — bare tone swatches and hair fragments — is not
    something anyone sends. Each group's icon is simply its first emoji,
    so even the tabs come from the data.
    """
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for e in entries:
        if not e.category or e.category == "Component":
            continue
        if "skin tone" in e.description:
            continue
        if e.category not in groups:
            groups[e.category] = []
            order.append(e.category)
        groups[e.category].append(e.emoji)
    folded = {name: fold_spellings(emoji) for name, emoji in groups.items()}
    return [{"name": name, "icon": folded[name][0], "emoji": folded[name]}
            for name in order if folded[name]]


def search_emoji(entries: list[EmojiEntry], query: str,
                 limit: int = 60) -> list[str]:
    """Names first, keywords second, no duplicates, capped.

    A description hit (the official name) is almost always what was
    meant, so those rank ahead of keyword hits; within each tier the
    dictionary's order stands.
    """
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    by_name: list[str] = []
    by_keyword: list[str] = []
    seen: set[str] = set()
    for e in entries:
        if not e.category or e.category == "Component":
            continue
        if "skin tone" in e.description:
            continue
        if e.emoji in seen:
            continue
        if q in e.description.lower():
            by_name.append(e.emoji)
            seen.add(e.emoji)
        elif any(a.lower().startswith(q) for a in e.annotations):
            by_keyword.append(e.emoji)
            seen.add(e.emoji)
        if len(by_name) >= limit:
            break
    return fold_spellings(by_name + by_keyword)[:limit]


# ---- skin tones ---------------------------------------------------------


def strip_tone(emoji: str) -> str:
    """`emoji` with any skin tone modifier removed."""
    return "".join(ch for ch in emoji if ch not in SKIN_TONES)


def _tone_key(emoji: str) -> str:
    """What a tone lookup files an emoji under.

    Neither the tone modifier nor a variation selector belongs in the
    key. The dictionary lists a raised hand both with and without the
    emoji-presentation selector, and its toned forms carry only one of
    those spellings, so a key that kept the selector would leave the
    other spelling unable to find its own variants.
    """
    return _strip_selectors(strip_tone(emoji))


def build_tone_map(entries: list[EmojiEntry]) -> dict[str, dict[int, str]]:
    """Neutral emoji -> {tone index: the emoji in that tone}.

    Read out of the dictionary rather than assembled from a base and a
    modifier. In a joined sequence the modifier belongs after the person
    it applies to, not at the end (a bearded man in a light tone is the
    man, then the modifier, then the join and the beard), so appending
    one would produce a sequence that renders as two glyphs. Every valid
    form is already an entry of its own; this indexes them.

    Entries carrying two modifiers, the couples and handshakes where each
    person has their own tone, are left out: they have no single tone to
    file them under.
    """
    out: dict[str, dict[int, str]] = {}
    for e in entries:
        mods = [ch for ch in e.emoji if ch in SKIN_TONES]
        if len(mods) != 1:
            continue
        out.setdefault(_tone_key(e.emoji), {})[SKIN_TONES.index(mods[0])] = \
            e.emoji
    return out


def apply_tone(emoji: str, tone: int,
               tone_map: dict[str, dict[int, str]]) -> str:
    """`emoji` in the chosen tone, unchanged when it has no such form.

    Most emoji have no tones at all, so this has to pass them through
    untouched rather than treating a miss as an error.
    """
    if tone < 0:
        return emoji
    return tone_map.get(_tone_key(emoji), {}).get(tone, emoji)


def build_name_map(entries: list[EmojiEntry]) -> dict[str, str]:
    """What to call each emoji, keyed so any spelling or tone finds it.

    Keyed on `_tone_key`, the same normalisation the tone map uses, so a
    name survives both a change of skin tone and whichever spelling the
    fold kept. Where a character has a plain name and a "…: medium skin
    tone" one, the plain name wins: this names the character, and the
    tone is already visible in the glyph.
    """
    out: dict[str, str] = {}
    for e in entries:
        if not e.description:
            continue
        key = _tone_key(e.emoji)
        if key not in out or ("skin tone" in out[key]
                              and "skin tone" not in e.description):
            out[key] = e.description
    return out


def emoji_name(emoji: str, names: dict[str, str]) -> str:
    """The dictionary's name for `emoji`, or "" when it has none."""
    return names.get(_tone_key(emoji), "")


#: The emoji the tone selector is drawn on. A raised hand is one
#: character with no joined parts, so its toned forms really are the
#: base followed by the modifier. That is what lets `tone_swatches`
#: build the selector without the dictionary loaded, which matters
#: because the button carrying it exists from startup while the
#: dictionary is not read until the picker is first opened.
TONE_SAMPLE = "✋"


def tone_swatches() -> list[str]:
    """The selector's row: the neutral sample, then it in each tone."""
    return [TONE_SAMPLE] + [TONE_SAMPLE + t for t in SKIN_TONES]


def load_tone(path: Path) -> int:
    """The saved tone index, or neutral when there is none."""
    try:
        tone = int(json.loads(Path(path).read_text()))
    except (OSError, ValueError, TypeError):
        return NEUTRAL_TONE
    return tone if -1 <= tone < len(SKIN_TONES) else NEUTRAL_TONE


def save_tone(path: Path, tone: int) -> None:
    try:
        Path(path).write_text(json.dumps(int(tone)))
    except OSError:
        log.exception("could not save the emoji skin tone")


# ---- recently used ------------------------------------------------------


def note_recent(recents: list[str], emoji: str,
                cap: int = RECENTS_CAP) -> list[str]:
    """New list with `emoji` first, deduplicated, capped."""
    if not emoji:
        return list(recents)[:cap]
    out = [emoji] + [e for e in recents if e != emoji]
    return out[:cap]


def load_recents(path: Path) -> list[str]:
    try:
        data = json.loads(Path(path).read_text())
        return [str(e) for e in data if e][:RECENTS_CAP]
    except (OSError, ValueError, TypeError):
        return []


def save_recents(path: Path, recents: list[str]) -> None:
    try:
        Path(path).write_text(json.dumps(recents[:RECENTS_CAP]))
    except OSError:
        log.exception("could not save emoji recents")
