import pytest

from backend.modules.knowledge._pti_normalisation import normalise


def test_lowercase():
    assert normalise("Andromeda") == "andromeda"


def test_collapse_whitespace():
    assert normalise("dragon  ball   z") == "dragon ball z"


def test_trim():
    assert normalise("  hello  ") == "hello"


def test_unicode_casefold_ss():
    assert normalise("Straße") == "strasse"


def test_unicode_nfc():
    decomposed = "café"
    composed = "café"
    assert normalise(decomposed) == normalise(composed) == "café"


def test_keeps_punctuation():
    assert normalise("Andromeda-Galaxie!") == "andromeda-galaxie!"


def test_keeps_emoji():
    assert normalise("🐉 dragon") == "🐉 dragon"


def test_keeps_cjk():
    assert normalise("アンドロメダ銀河") == "アンドロメダ銀河"


def test_keeps_cyrillic():
    assert normalise("  Андромеда   Галактика  ") == "андромеда галактика"


def test_idempotent():
    s = "  Foo BAR  baz!  "
    once = normalise(s)
    twice = normalise(once)
    assert once == twice


def test_various_whitespace_classes_collapse():
    s = "a\tb c　d"
    assert normalise(s) == "a b c d"


def test_empty_input():
    assert normalise("") == ""
    assert normalise("   ") == ""
