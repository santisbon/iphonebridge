"""ui/emoji.py — grouping, search and recents, on fixture data."""
from typing import ClassVar

import pytest

from iphonebridge.ui.emoji import (
    NEUTRAL_TONE,
    SKIN_TONES,
    TONE_SAMPLE,
    EmojiEntry,
    apply_tone,
    build_groups,
    build_name_map,
    build_tone_map,
    emoji_name,
    fold_spellings,
    load_emoji_db,
    load_recents,
    load_tone,
    note_recent,
    save_recents,
    save_tone,
    search_emoji,
    strip_tone,
    tone_swatches,
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
    # Two spellings of one flag, as the dictionary lists them: with the
    # emoji-presentation selector and without.
    entry("\U0001F3F3\ufe0f\u200d\U0001F308", "rainbow flag", cat="Flags"),
    entry("\U0001F3F3\u200d\U0001F308", "rainbow flag", cat="Flags"),
]


class TestGroups:
    def test_grouped_in_first_seen_order_with_icon(self):
        groups = build_groups(FIXTURE)
        assert [g["name"] for g in groups] == [
            "Smileys & Emotion", "Animals & Nature", "People & Body",
            "Food & Drink", "Flags"]
        assert groups[0]["icon"] == "\U0001F600"
        assert groups[2]["emoji"] == ["\U0001F44B"]

    def test_skin_tones_component_and_uncategorised_dropped(self):
        flat = [e for g in build_groups(FIXTURE) for e in g["emoji"]]
        assert "\U0001F44B\U0001F3FB" not in flat
        assert "\U0001F3FB" not in flat
        assert "?" not in flat

    def test_empty_input(self):
        assert build_groups([]) == []

    def test_one_cell_per_flag_not_per_spelling(self):
        flags = next(g for g in build_groups(FIXTURE)
                     if g["name"] == "Flags")
        assert flags["emoji"] == ["\U0001F3F3\ufe0f\u200d\U0001F308"]
        assert flags["icon"] == "\U0001F3F3\ufe0f\u200d\U0001F308"


class TestNames:
    NAMES: ClassVar = build_name_map(FIXTURE)

    def test_names_an_emoji(self):
        assert emoji_name("\U0001F600", self.NAMES) == "grinning face"

    def test_two_flags_that_draw_alike_have_their_own_names(self):
        names = build_name_map([
            entry("\U0001F1F3\U0001F1F4", "Norway", cat="Flags"),
            entry("\U0001F1E7\U0001F1FB", "Bouvet Island", cat="Flags"),
        ])
        assert emoji_name("\U0001F1F3\U0001F1F4", names) == "Norway"
        assert emoji_name("\U0001F1E7\U0001F1FB", names) == "Bouvet Island"

    def test_a_toned_emoji_answers_with_the_plain_name(self):
        # The fixture lists the light-tone waving hand before the plain
        # one, so this also pins that order cannot decide the answer.
        assert emoji_name("\U0001F44B\U0001F3FB", self.NAMES) == "waving hand"
        assert emoji_name("\U0001F44B", self.NAMES) == "waving hand"

    def test_either_spelling_finds_the_name(self):
        assert emoji_name("\U0001F3F3\ufe0f\u200d\U0001F308",
                          self.NAMES) == "rainbow flag"
        assert emoji_name("\U0001F3F3\u200d\U0001F308",
                          self.NAMES) == "rainbow flag"

    def test_unknown_emoji_has_no_name(self):
        assert emoji_name("\U0001F9E8", self.NAMES) == ""


class TestFoldSpellings:
    def test_keeps_the_fully_qualified_spelling(self):
        bare = "\U0001F3F4\u200d\u2620"
        full = "\U0001F3F4\u200d\u2620\ufe0f"
        assert fold_spellings([bare, full]) == [full]
        assert fold_spellings([full, bare]) == [full]

    def test_holds_the_position_of_the_first_spelling(self):
        bare = "\U0001F3F4\u200d\u2620"
        full = "\U0001F3F4\u200d\u2620\ufe0f"
        assert fold_spellings(["a", bare, "b", full]) == ["a", full, "b"]

    def test_distinct_emoji_are_all_kept(self):
        assert fold_spellings(["\U0001F600", "\U0001F415"]) == [
            "\U0001F600", "\U0001F415"]

    def test_empty(self):
        assert fold_spellings([]) == []


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

    def test_one_hit_per_flag_not_per_spelling(self):
        assert search_emoji(FIXTURE, "rainbow") == [
            "\U0001F3F3\ufe0f\u200d\U0001F308"]

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


class TestSkinTones:
    """Tone variants are looked up, never assembled from parts."""

    HAND = "\U0001F44B"                      # waving hand
    LIGHT = "\U0001F44B\U0001F3FB"
    DARK = "\U0001F44B\U0001F3FF"
    # A joined sequence: the modifier sits after the person, not at the
    # end, which is why building one by appending would be wrong.
    BEARD = "\U0001F9D4‍♂️"
    BEARD_LIGHT = "\U0001F9D4\U0001F3FB‍♂️"
    TWO_TONE = "\U0001FAF1\U0001F3FB‍\U0001FAF2\U0001F3FF"

    DB: ClassVar[list] = [
        entry(HAND, "waving hand", cat="People & Body"),
        entry(LIGHT, "waving hand: light skin tone", cat="People & Body"),
        entry(DARK, "waving hand: dark skin tone", cat="People & Body"),
        entry(BEARD, "man: beard", cat="People & Body"),
        entry(BEARD_LIGHT, "man: light skin tone, beard", cat="People & Body"),
        entry(TWO_TONE, "handshake: light, dark", cat="People & Body"),
        entry("\U0001F355", "pizza", cat="Food & Drink"),
    ]

    def test_strip_tone(self):
        assert strip_tone(self.LIGHT) == self.HAND
        assert strip_tone(self.BEARD_LIGHT) == self.BEARD
        assert strip_tone(self.HAND) == self.HAND
        assert strip_tone("") == ""

    def test_map_indexes_every_single_tone_form(self):
        m = build_tone_map(self.DB)
        assert m[self.HAND][0] == self.LIGHT
        assert m[self.HAND][4] == self.DARK
        assert apply_tone(self.BEARD, 0, m) == self.BEARD_LIGHT

    def test_a_variation_selector_does_not_hide_the_variants(self):
        # "raised hand" is listed both bare and with the emoji-
        # presentation selector, while its toned forms carry only the
        # bare spelling. Both must still find their tones.
        bare, vs = "\u270B", "\u270B\ufe0f"
        db = [entry(bare, "raised hand"),
              entry(vs, "raised hand"),
              entry(bare + SKIN_TONES[2], "raised hand: medium skin tone")]
        m = build_tone_map(db)
        assert apply_tone(bare, 2, m) == bare + SKIN_TONES[2]
        assert apply_tone(vs, 2, m) == bare + SKIN_TONES[2]

    def test_two_tone_sequences_are_left_out(self):
        m = build_tone_map(self.DB)
        assert strip_tone(self.TWO_TONE) not in m

    def test_apply_tone(self):
        m = build_tone_map(self.DB)
        assert apply_tone(self.HAND, 0, m) == self.LIGHT
        assert apply_tone(self.HAND, 4, m) == self.DARK
        # neutral leaves it alone
        assert apply_tone(self.HAND, NEUTRAL_TONE, m) == self.HAND
        # an emoji with no tones passes through untouched
        assert apply_tone("\U0001F355", 2, m) == "\U0001F355"
        # a tone this emoji does not have falls back to what was asked
        assert apply_tone(self.HAND, 2, m) == self.HAND

    def test_joined_sequence_keeps_the_modifier_inside(self):
        m = build_tone_map(self.DB)
        toned = apply_tone(self.BEARD, 0, m)
        assert toned == self.BEARD_LIGHT
        # the modifier is not simply tacked on the end
        assert not toned.endswith(SKIN_TONES[0])

    def test_swatches_are_six_wide_and_need_no_dictionary(self):
        s = tone_swatches()
        assert len(s) == 1 + len(SKIN_TONES)
        assert s[0] == TONE_SAMPLE
        assert len(set(s)) == 6

    def test_swatches_match_what_the_dictionary_says(self):
        # The selector builds its row by appending a modifier, which is
        # only right because the sample has no joined parts. Check that
        # against the real data where it is installed; CI has no
        # dictionary and skips.
        db = load_emoji_db()
        if not db:
            pytest.skip("no system emoji dictionary here")
        forms = build_tone_map(db).get(TONE_SAMPLE, {})
        assert forms, "the sample emoji should have tone variants"
        for i, want in forms.items():
            assert tone_swatches()[i + 1] == want

    def test_tone_roundtrip_and_bad_values(self, tmp_path):
        p = tmp_path / "tone.json"
        save_tone(p, 3)
        assert load_tone(p) == 3
        save_tone(p, NEUTRAL_TONE)
        assert load_tone(p) == NEUTRAL_TONE
        assert load_tone(tmp_path / "missing.json") == NEUTRAL_TONE
        p.write_text("not json")
        assert load_tone(p) == NEUTRAL_TONE
        p.write_text("99")
        assert load_tone(p) == NEUTRAL_TONE
