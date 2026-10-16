"""Run an STT engine over a manifest and record raw, reproducible results.

An engine is any callable engine(audio_path, language) -> transcript string.
Failures are recorded per item (never hidden) and excluded from the error rates.
"""
import csv
import json
import os
import pathlib
import platform
import time
import wave
from datetime import datetime, timezone

from .metrics import char_errors, normalizer_version, word_errors

ROW_FIELDS = ("id", "language", "reference", "hypothesis", "ref_words", "word_errors",
              "ref_chars", "char_errors", "audio_s", "latency_s", "error")


class ResultRows(list):
    """List of result rows from run_stt that carries normalizer_version metadata."""
    def __init__(self, iterable=(), normalizer_version="1"):
        super().__init__(iterable)
        self.normalizer_version = normalizer_version


def _audio_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


def run_stt(engine, items, clock=time.perf_counter, numbers=False):
    """numbers=True uses the optional number step of the normalizer; record
    metrics.normalizer_version(numbers) in the run's metadata when you do."""
    version = normalizer_version(numbers)
    rows = ResultRows(normalizer_version=version)
    for it in items:
        row = {k: None for k in ROW_FIELDS}
        row["_normalizer_version"] = version
        row.update(id=it.id, language=it.language, reference=it.reference,
                   hypothesis="", error="", audio_s=_audio_seconds(it.path))
        t0 = clock()
        try:
            hyp = engine(it.path, it.language)
        except Exception as exc:  # recorded, not hidden
            hyp = ""
            row["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        row["latency_s"] = clock() - t0
        row["hypothesis"] = hyp
        if not row["error"]:
            try:
                row["word_errors"], row["ref_words"] = word_errors(it.reference, hyp, numbers)
                row["char_errors"], row["ref_chars"] = char_errors(it.reference, hyp, numbers)
            except ValueError as exc:
                row["error"] = "ValueError: " + str(exc)
        rows.append(row)
    return rows


def _agg(rows):
    ok = [r for r in rows if not r["error"]]
    out = {"items": len(rows), "failed": len(rows) - len(ok)}
    rw = sum(r["ref_words"] for r in ok)
    rc = sum(r["ref_chars"] for r in ok)
    out["wer"] = (sum(r["word_errors"] for r in ok) / rw) if rw else None
    out["cer"] = (sum(r["char_errors"] for r in ok) / rc) if rc else None
    timed = [r for r in ok if r["audio_s"]]
    audio = sum(r["audio_s"] for r in timed)
    spent = sum(r["latency_s"] for r in timed)
    out["audio_s"] = audio
    out["rtf"] = (spent / audio) if audio else None  # time spent / audio length; below 1 is faster than real time
    return out


def summarize(rows):
    """Corpus-level rates (total errors / total reference units), per language and ALL."""
    langs = sorted({r["language"] for r in rows})
    summary = {lang: _agg([r for r in rows if r["language"] == lang]) for lang in langs}
    summary["ALL"] = _agg(rows)
    return summary


def environment_info(**extra):
    info = {
        "utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "gpu": "not detected by harness; record manually",
    }
    info.update(extra)
    return info


def write_results(out_dir, engine_name, rows, meta):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(meta) if meta else {}
    if "normalizer_version" not in meta:
        version = getattr(rows, "normalizer_version", None)
        if not version and rows:
            for r in rows:
                if isinstance(r, dict):
                    version = r.get("_normalizer_version") or r.get("normalizer_version")
                    if version:
                        break
        meta["normalizer_version"] = version or normalizer_version(False)
    stamp = meta.get("utc_time", "run").replace(":", "").replace("-", "")
    stem = engine_name + "_" + stamp
    csv_path, json_path = out / (stem + ".csv"), out / (stem + ".json")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    clean_rows = []
    for r in rows:
        if isinstance(r, dict) and "_normalizer_version" in r:
            clean_rows.append({k: v for k, v in r.items() if k != "_normalizer_version"})
        else:
            clean_rows.append(r)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"engine": engine_name, "meta": meta, "summary": summarize(rows),
                   "rows": clean_rows}, f, ensure_ascii=False, indent=2)
    return str(csv_path), str(json_path)


def read_results(path):
    """Read a benchmark JSON result file produced by write_results.

    Missing 'normalizer_version' in meta (older result files) defaults to "1".
    """
    path = pathlib.Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        meta = data.setdefault("meta", {})
        if isinstance(meta, dict) and "normalizer_version" not in meta:
            meta["normalizer_version"] = "1"
    return data
