"""The optional number step of the WER normalizer (issue #754)."""
import pathlib
import sys
import wave

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from ragleap_voice.bench import (cer, load_manifest, normalize, normalizer_version,  # noqa: E402
                                 read_results, run_stt, summarize, wer, write_results)

# benchmarks/stt-neutral-10s: the ground truth, and how an engine that writes digits
# would transcribe the same audio
NEUTRAL_REF = ("Please schedule a callback for tomorrow at three fifteen. Order number four "
               "seven two nine, total due one hundred twenty dollars.")
NEUTRAL_HYP = ("Please schedule a callback for tomorrow at 3:15. Order number 4729, "
               "total due 120 dollars.")


def test_default_is_unchanged():
    """Published numbers were measured without the step, so it stays off by default."""
    assert normalizer_version() == "1"
    assert normalize("four seven two nine") == "four seven two nine"
    assert normalize("4,729") == "4 729"
    assert wer(NEUTRAL_REF, NEUTRAL_HYP) == pytest.approx(9 / 21)


def test_version_names_the_number_step():
    assert normalizer_version(numbers=True) == "1+numbers-en.1"


def test_stt_neutral_10s_example():
    assert normalize(NEUTRAL_REF, numbers=True) == (
        "please schedule a callback for tomorrow at 3 15 order number 4729 total due 120 dollars")
    assert wer(NEUTRAL_REF, NEUTRAL_HYP, numbers=True) == 0
    assert cer(NEUTRAL_REF, NEUTRAL_HYP, numbers=True) == 0


@pytest.mark.parametrize("text, expected", [
    ("four seven two nine", "4729"),                      # digit by digit
    ("one two", "12"),
    ("seven", "7"),
    ("fifteen", "15"),
    ("twenty one", "21"),
    ("twenty-one", "21"),
    ("one hundred twenty", "120"),
    ("one hundred and twenty", "120"),
    ("twelve hundred", "1200"),
    ("one thousand two hundred", "1200"),
    ("two million three hundred thousand", "2300000"),
    ("hundred", "100"),
    ("three fifteen", "3 15"),                            # a word that cannot continue starts a new number
    ("twenty twenty", "20 20"),
    ("one thousand one thousand", "1000 1000"),
    ("one hundred one hundred", "100 100"),
    ("one thousand one", "1001"),
    ("one hundred one", "101"),
    ("nineteen eighty", "19 80"),                         # years in pairs: not covered
    ("rock and roll", "rock and roll"),                   # "and" only joins number words
    ("one hundred and some", "100 and some"),
    ("the one I like", "the 1 i like"),
])
def test_english_number_words(text, expected):
    assert normalize(text, numbers=True) == expected


@pytest.mark.parametrize("text, expected", [
    ("1,200", "1200"),
    ("12,345,678", "12345678"),
    ("3:15", "3 15"),
    ("$120", "120"),
    ("1,2", "1 2"),                                       # not a thousands separator
    ("४७२९", "4729"),                 # Devanagari digits
    ("௪௭", "47"),                               # Tamil digits
])
def test_digits(text, expected):
    assert normalize(text, numbers=True) == expected


def test_indic_text_is_untouched():
    hi = "नमस्ते दुनिया"
    assert normalize(hi, numbers=True) == normalize(hi)


def test_run_stt_passes_the_option(tmp_path):
    with wave.open(str(tmp_path / "a.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    m = tmp_path / "m.csv"
    m.write_text("id,path,reference,language,license,source\n"
                 "a,a.wav,order number four seven two nine,en,CC-BY-4.0,test\n", encoding="utf-8")
    items, problems = load_manifest(m)
    assert problems == []

    def engine(path, lang):
        return "order number 4729"

    assert summarize(run_stt(engine, items))["en"]["wer"] == pytest.approx(4 / 6)
    assert summarize(run_stt(engine, items, numbers=True))["en"]["wer"] == 0


def test_write_results_records_normalizer_version(tmp_path):
    with wave.open(str(tmp_path / "a.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    m = tmp_path / "m.csv"
    m.write_text("id,path,reference,language,license,source\n"
                 "a,a.wav,order number four seven two nine,en,CC-BY-4.0,test\n", encoding="utf-8")
    items, _ = load_manifest(m)

    def engine(path, lang):
        return "order number 4729"

    # With numbers=True
    rows_num = run_stt(engine, items, numbers=True)
    _, json_path_num = write_results(tmp_path / "out1", "fake", rows_num, {})
    data_num = read_results(json_path_num)
    assert data_num["meta"]["normalizer_version"] == "1+numbers-en.1"

    # Without numbers (default)
    rows_def = run_stt(engine, items, numbers=False)
    _, json_path_def = write_results(tmp_path / "out2", "fake", rows_def, {})
    data_def = read_results(json_path_def)
    assert data_def["meta"]["normalizer_version"] == "1"


def test_read_results_legacy_file(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"engine": "old", "meta": {"utc_time": "2026-10-11T00:00:00Z"}, "rows": []}', encoding="utf-8")
    data = read_results(legacy)
    assert data["meta"]["normalizer_version"] == "1"
