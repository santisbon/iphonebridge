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
    return [{"name": name, "icon": groups[name][0], "emoji": groups[name]}
            for name in order if groups[name]]


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
    return (by_name + by_keyword)[:limit]


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
