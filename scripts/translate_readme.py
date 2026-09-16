#!/usr/bin/env python3
"""
Translates README.md into every language core/language.py's
LanguageDetector supports (langdetect's 55 profiles, minus 'en' since
that's the source language README.md is already written in). Writes
readmes/README.<code>.md for each target language.

Resumable and staleness-aware: readmes/.translation_state.json tracks
the sha256 of the README.md content each language was last translated
from. A language is skipped if its output file exists AND the stored
hash matches the current README.md -- so re-running only translates
languages that are missing or stale (README.md changed since their last
translation), never re-does up-to-date work.

This matters in practice because the free-tier Gemini key this runs
against has a hard 20-requests/day cap (confirmed live, not just a
per-minute limit) -- translating all 54 languages in one run is not
possible on a free key. Each run makes whatever progress the day's
quota allows; running it again (same day or a later day) picks up
exactly where it left off. Quota-exhaustion errors (429
RESOURCE_EXHAUSTED, 503 UNAVAILABLE) are treated as expected/incomplete,
not a hard failure -- the script exits 0 so partial progress still gets
committed/PR'd rather than the whole run being discarded.

Usage: GEMINI_API_KEY=... python3 scripts/translate_readme.py
"""
import hashlib
import json
import os
import sys
import time

import google.genai as genai
from google.genai import types

# Same 55 codes core/language.py's langdetect profiles support, minus 'en'.
TARGET_LANGUAGES = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "es": "Spanish", "et": "Estonian",
    "fa": "Persian", "fi": "Finnish", "fr": "French", "gu": "Gujarati",
    "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian",
    "id": "Indonesian", "it": "Italian", "ja": "Japanese", "kn": "Kannada",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "mk": "Macedonian",
    "ml": "Malayalam", "mr": "Marathi", "ne": "Nepali", "nl": "Dutch",
    "no": "Norwegian", "pa": "Punjabi", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sk": "Slovak", "sl": "Slovenian",
    "so": "Somali", "sq": "Albanian", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "th": "Thai", "tl": "Tagalog",
    "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese",
    "zh-cn": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
}

MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
OUTPUT_DIR = "readmes"
STATE_PATH = os.path.join(OUTPUT_DIR, ".translation_state.json")

# Substrings that mean "quota/capacity, try again later" -- not a real
# bug, expected on a free-tier key. Anything else is treated as a real
# failure worth surfacing loudly.
TRANSIENT_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "429", "503")


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def translate(client, text: str, language_name: str) -> str:
    prompt = (
        f"Translate the following README.md file from English into {language_name}. "
        f"This is a technical open-source software README written in GitHub-flavored "
        f"Markdown. Preserve ALL Markdown formatting exactly (headers, code blocks, "
        f"tables, links, badges, image references, inline code). Do NOT translate: "
        f"code inside ``` fenced blocks, inline `code`, URLs, command names, "
        f"environment variable names, or the literal text inside badge/shield URLs. "
        f"Translate only the human-readable prose, headers, and table cell text. "
        f"Output ONLY the translated Markdown, no preamble, no explanation, no code "
        f"fences wrapping the whole output.\n\n"
        f"--- README.md ---\n{text}"
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    return response.text.strip() if response.text else ""


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    with open("README.md", encoding="utf-8") as f:
        source = f.read()
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = load_state()

    client = genai.Client(api_key=api_key)

    already_current = []
    translated_now = []
    transient_failures = []
    real_failures = []

    for code, name in TARGET_LANGUAGES.items():
        out_path = os.path.join(OUTPUT_DIR, f"README.{code}.md")
        up_to_date = (
            os.path.exists(out_path)
            and state.get(code) == source_hash
        )
        if up_to_date:
            already_current.append(code)
            continue

        print(f"Translating -> {name} ({code})...")
        try:
            translated = translate(client, source, name)
            if not translated:
                raise ValueError("empty response")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(translated + "\n")
            state[code] = source_hash
            save_state(state)  # persist after every success, not just at the end
            translated_now.append(code)
            print(f"  wrote {out_path} ({len(translated)} chars)")
        except Exception as e:
            msg = str(e)
            if any(marker in msg for marker in TRANSIENT_MARKERS):
                print(f"  QUOTA/TRANSIENT ({code}): {msg[:150]}", file=sys.stderr)
                transient_failures.append(code)
            else:
                print(f"  FAILED ({code}): {msg[:300]}", file=sys.stderr)
                real_failures.append(code)
        time.sleep(1)  # be polite to the free-tier rate limit

    total = len(TARGET_LANGUAGES)
    done = len(already_current) + len(translated_now)
    print(f"\n--- Summary ---")
    print(f"Already up to date: {len(already_current)}")
    print(f"Translated this run: {len(translated_now)}")
    print(f"Quota/transient (will retry on next run): {len(transient_failures)}")
    print(f"Real failures: {len(real_failures)}")
    print(f"Progress: {done}/{total} complete")

    if real_failures:
        print(f"\nReal (non-transient) failures: {', '.join(real_failures)}", file=sys.stderr)
        sys.exit(1)

    if transient_failures:
        print(
            f"\n{len(transient_failures)} language(s) hit quota limits this run "
            f"(expected on a free-tier key) -- re-run the workflow later to continue: "
            f"{', '.join(transient_failures)}"
        )
        # Exit 0 deliberately: partial progress is real progress, and quota
        # exhaustion is expected/normal here, not a bug to fail the job over.

    if done == total:
        print(f"\nAll {total} languages are up to date.")


if __name__ == "__main__":
    main()
