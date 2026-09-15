#!/usr/bin/env python3
"""
Translates README.md into every language core/language.py's
LanguageDetector supports (langdetect's 55 profiles, minus 'en' since
that's the source language README.md is already written in) -- keeps the
docs' language coverage matching what the product can actually detect.
Writes readmes/README.<code>.md for each target language.

Manual trigger only (see .github/workflows/translate-readme.yml,
workflow_dispatch) -- deliberately not run on every README push, to
control API cost against a free-tier Gemini key.

Usage: GEMINI_API_KEY=... python3 scripts/translate_readme.py
"""
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

MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
OUTPUT_DIR = "readmes"


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

    client = genai.Client(api_key=api_key)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    failures = []
    for code, name in TARGET_LANGUAGES.items():
        print(f"Translating -> {name} ({code})...")
        try:
            translated = translate(client, source, name)
            if not translated:
                raise ValueError("empty response")
            out_path = os.path.join(OUTPUT_DIR, f"README.{code}.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(translated + "\n")
            print(f"  wrote {out_path} ({len(translated)} chars)")
        except Exception as e:
            print(f"  FAILED ({code}): {e}", file=sys.stderr)
            failures.append(code)
        time.sleep(1)  # be polite to the free-tier rate limit

    if failures:
        print(f"\n{len(failures)} language(s) failed: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)

    print(f"\nAll {len(TARGET_LANGUAGES)} languages translated successfully.")


if __name__ == "__main__":
    main()
