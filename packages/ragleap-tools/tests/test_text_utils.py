from ragleap_tools.text_utils import regex_extract, word_count, text_case_transform


def test_regex_extract():
    r = regex_extract("foo123bar456", r"\d+")
    assert r.success
    assert r.result == ["123", "456"]


def test_regex_extract_invalid_pattern():
    r = regex_extract("text", "[invalid")
    assert not r.success


def test_word_count():
    r = word_count("hello world\nsecond line")
    assert r.success
    assert r.result["words"] == 4
    assert r.result["lines"] == 2


def test_case_transforms():
    assert text_case_transform("hello", "upper").result == "HELLO"
    assert text_case_transform("HELLO", "lower").result == "hello"
    assert text_case_transform("hello world", "title").result == "Hello World"


def test_unknown_mode_rejected():
    r = text_case_transform("hello", "reverse")
    assert not r.success
