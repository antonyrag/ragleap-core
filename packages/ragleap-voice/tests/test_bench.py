import json
import pathlib
import sys
import wave

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from ragleap_voice.bench import (cer, edit_distance, environment_info, load_manifest,  # noqa: E402
                                 normalize, read_results, run_stt, summarize, wer, write_results)


def _wav(path, seconds=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * seconds)


def _manifest(tmp_path, rows):
    for name in ("a.wav", "b.wav"):
        _wav(tmp_path / name)
    lines = ["id,path,reference,language,license,source"] + rows
    m = tmp_path / "m.csv"
    m.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return m


GOOD = ["a,a.wav,hello there world,en,CC-BY-4.0,test",
        "b,b.wav,\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e,hi,CC-BY-4.0,test"]


def test_normalize_basic_and_indic():
    assert normalize("Don't  Stop, now!") == "dont stop now"
    assert normalize("\u0928\u092e\u0938\u094d\u0924\u0947\u0964") == "\u0928\u092e\u0938\u094d\u0924\u0947"


def test_edit_distance():
    assert edit_distance(list("kitten"), list("sitting")) == 3
    assert edit_distance([], [1, 2]) == 2


def test_wer_cer_values():
    assert wer("a b c", "a x c") == pytest.approx(1 / 3)
    assert wer("a b", "a b") == 0
    assert cer("abc", "abd") == pytest.approx(1 / 3)
    hi = "\u0928\u092e\u0938\u094d\u0924\u0947"
    assert cer(hi, hi) == 0


def test_empty_reference_raises():
    with pytest.raises(ValueError):
        wer("  ...  ", "x")


def test_manifest_ok_and_problems(tmp_path):
    items, problems = load_manifest(_manifest(tmp_path, GOOD))
    assert problems == [] and len(items) == 2
    _, bad = load_manifest(_manifest(tmp_path, ["a,a.wav,x,en,CC-BY-NC-4.0,t",
                                                "a,missing.wav,x,en,MIT,t"]))
    assert any("licence" in p for p in bad)
    assert any("duplicate" in p for p in bad)
    assert any("not found" in p for p in bad)


def test_manifest_missing_columns(tmp_path):
    m = tmp_path / "bad.csv"
    m.write_text("id,path\nx,y\n", encoding="utf-8")
    items, problems = load_manifest(m)
    assert items == [] and "missing columns" in problems[0]


def test_run_summarize_and_failures(tmp_path):
    items, _ = load_manifest(_manifest(tmp_path, GOOD))
    answers = {"a": "hello world", "b": "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e"}

    def engine(path, lang):
        key = pathlib.Path(path).stem
        if key == "b" and lang == "xx":
            raise RuntimeError("boom")
        return answers[key]

    ticks = iter(range(0, 100, 2))
    rows = run_stt(engine, items, clock=lambda: next(ticks))
    s = summarize(rows)
    assert s["en"]["wer"] == pytest.approx(1 / 3)  # one deleted word out of three
    assert s["hi"]["wer"] == 0
    assert s["ALL"]["items"] == 2 and s["ALL"]["failed"] == 0
    assert s["en"]["rtf"] == pytest.approx(2.0)  # 2 s spent on 1 s of audio

    def broken(path, lang):
        raise RuntimeError("boom")

    rows = run_stt(broken, items)
    assert all(r["error"].startswith("RuntimeError") for r in rows)
    assert summarize(rows)["ALL"]["wer"] is None


def test_write_results_roundtrip(tmp_path):
    items, _ = load_manifest(_manifest(tmp_path, GOOD))
    rows = run_stt(lambda p, l: "hello", items)
    meta = environment_info(engine_version="fake-0")
    csv_path, json_path = write_results(tmp_path / "out", "fake", rows, meta)
    data = read_results(json_path)
    assert data["engine"] == "fake" and len(data["rows"]) == 2
    assert data["meta"]["engine_version"] == "fake-0"
    assert data["meta"]["normalizer_version"] == "1"
    assert pathlib.Path(csv_path).read_text(encoding="utf-8").startswith("id,language")
