"""ui/emoji.py — grouping, search and recents, on fixture data."""
from iphonebridge.ui.emoji import (
    EmojiEntry,
    build_groups,
    load_recents,
    note_recent,
    save_recents,
    search_emoji,
)


def entry(emoji, desc, cat="Smileys & Emotion", ann=()):
    return EmojiEntry(emoji, desc, cat, tuple(ann))


FIXTURE = [
    entry("\U0001F600", "grinning face", ann=("face", "smile")),
    entry("\U0001F415", "dog", cat="Animals & Nature", ann=("pet",)),
    entry("\U0001F44B\U0001F3FB", "waving hand: light skin tone",
          cat="People & Body"),
    entry("\U0001F44B", "waving hand", cat="People & Body",
          ann=("hello", "hi")),
    entry("\U0001F3FB", "light skin tone", cat="Component"),
    entry("\U0001F355", "pizza", cat="Food & Drink", ann=("cheese",)),
    entry("?", "orphan", cat=""),
]


class TestGroups:
    def test_grouped_in_first_seen_order_with_icon(self):
        groups = build_groups(FIXTURE)
        assert [g["name"] for g in groups] == [
            "Smileys & Emotion", "Animals & Nature", "People & Body",
            "Food & Drink"]
        assert groups[0]["icon"] == "\U0001F600"
        assert groups[2]["emoji"] == ["\U0001F44B"]

    def test_skin_tones_component_and_uncategorised_dropped(self):
        flat = [e for g in build_groups(FIXTURE) for e in g["emoji"]]
        assert "\U0001F44B\U0001F3FB" not in flat
        assert "\U0001F3FB" not in flat
        assert "?" not in flat

    def test_empty_input(self):
        assert build_groups([]) == []


class TestSearch:
    def test_keyword_only_match(self):
        assert search_emoji(FIXTURE, "hi") == ["\U0001F44B"]

    def test_name_substring(self):
        assert search_emoji(FIXTURE, "pizz") == ["\U0001F355"]

    def test_keyword_prefix(self):
        assert search_emoji(FIXTURE, "chee") == ["\U0001F355"]

    def test_name_hits_first(self):
        fix = FIXTURE + [entry("\U0001F9C0", "cheese wedge",
                               cat="Food & Drink")]
        assert search_emoji(fix, "cheese") == ["\U0001F9C0", "\U0001F355"]

    def test_short_or_empty_query(self):
        assert search_emoji(FIXTURE, "p") == []
        assert search_emoji(FIXTURE, "") == []
        assert search_emoji(FIXTURE, None) == []

    def test_skin_tone_variants_never_surface(self):
        assert search_emoji(FIXTURE, "waving") == ["\U0001F44B"]

    def test_cap(self):
        fix = [entry(chr(0x1F400 + i), f"bug {i}") for i in range(80)]
        assert len(search_emoji(fix, "bug")) == 60


class TestRecents:
    def test_note_front_dedupe_cap(self):
        r = note_recent(["b", "a"], "a")
        assert r == ["a", "b"]
        r = note_recent([str(i) for i in range(30)], "x")
        assert len(r) == 30 and r[0] == "x"
        assert note_recent(["a"], "") == ["a"]

    def test_roundtrip_and_corruption(self, tmp_path):
        p = tmp_path / "recents.json"
        save_recents(p, ["\U0001F600", "\U0001F355"])
        assert load_recents(p) == ["\U0001F600", "\U0001F355"]
        p.write_text("{not json")
        assert load_recents(p) == []
        assert load_recents(tmp_path / "missing.json") == []
