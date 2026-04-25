from backend.modules.chat._emoji_extractor import extract_emojis


def test_extract_emojis_returns_empty_list_for_plain_text():
    assert extract_emojis("Hello world, no emoji here") == []


def test_extract_emojis_returns_single_emoji():
    assert extract_emojis("Hello 👋") == ["👋"]


def test_extract_emojis_preserves_order():
    assert extract_emojis("First 🔥 second 🤘 third 😊") == ["🔥", "🤘", "😊"]


def test_extract_emojis_handles_skin_tone_modifier_as_one_unit():
    # 👍🏽 = 👍 (U+1F44D) + skin-tone modifier (U+1F3FD)
    assert extract_emojis("nice 👍🏽 work") == ["👍🏽"]


def test_extract_emojis_handles_zwj_family_as_one_unit():
    # Family emoji = man + ZWJ + woman + ZWJ + girl + ZWJ + boy
    assert extract_emojis("our family 👨‍👩‍👧‍👦 yes") == [
        "👨‍👩‍👧‍👦"
    ]


def test_extract_emojis_returns_duplicates_in_order():
    assert extract_emojis("😂😂lol😂") == ["😂", "😂", "😂"]


def test_extract_emojis_empty_input():
    assert extract_emojis("") == []


def test_extract_emojis_keeps_vs16_with_red_heart():
    # ❤️ = U+2764 + U+FE0F (variation selector 16). The VS16 must stay
    # bonded to the base — losing it would break LRU dedupe against the
    # default set, which spells the heart with VS16.
    assert extract_emojis("love it ❤️") == ["❤️"]


def test_extract_emojis_handles_regional_indicator_flag_as_one_unit():
    # 🇩🇪 = U+1F1E9 + U+1F1EA, a regional-indicator pair = Germany flag.
    assert extract_emojis("from 🇩🇪 with love") == ["🇩🇪"]


def test_extract_emojis_handles_two_adjacent_flags():
    # Two flags in a row must come out as two units, not one merged.
    assert extract_emojis("🇩🇪🇫🇷") == ["🇩🇪", "🇫🇷"]
