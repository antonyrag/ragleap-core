# Changelog

All notable changes to `ragleap-voice` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
- `ragleap_voice.bench`: benchmark JSON result files produced by `write_results` now automatically record `meta["normalizer_version"]` ("1" by default, "1+numbers-en.1" when `run_stt` is called with `numbers=True`). Added `read_results` to load benchmark result files, which defaults missing `normalizer_version` in older result files to "1".
- `ragleap_voice.bench`: optional number step in the WER/CER normalizer (`numbers=True` on `normalize`, `wer`, `cer`, `word_errors`, `char_errors` and `run_stt`). English number words become digits ("four seven two nine" -> "4729", "one hundred twenty" -> "120"), thousands separators between digits are dropped and decimal digits of any script (Devanagari, Tamil, ...) become ASCII. Off by default, so already published numbers are unchanged. `normalizer_version(numbers)` names the settings ("1" by default, "1+numbers-en.1" with the step); record it next to any number measured with the step. Not covered: decimals, ordinals, currency words, years read in pairs, and spelled-out numbers in languages other than English.

## [0.0.1] - first release (date set at tagging)
### Added
- First release: the model-management layer only (manifest, lock files, hash-verified downloads, CLI). There are no speech engines in this release.
- Lock file `locks/flan-t5-large-tokenizer.json` (5 tokenizer files, no weights, revision 0613663d0d48) and `depends_on = ["flan-t5-large-tokenizer"]` on `indic-parler-tts`: `models pull indic-parler-tts` now fetches both repositories, tokenizer first. Both entries stay unverified pending human review.
- Manifest entries may declare `depends_on` (a list of other entries). `models pull` fetches dependencies first and checks that every lock exists before downloading anything; `models verify` checks them too; `models check` rejects unknown names, self-dependencies, duplicates and cycles, and a verified or default entry may only depend on verified entries. A verified entry that is not a default is now held to the same rules as a default one (pinned revision, 64-hex lock digest, allowlisted licences).
- Manifest entry `flan-t5-large-tokenizer` (unverified, not locked yet): the tokenizer files of the text encoder that Indic Parler-TTS loads at run time. Apache-2.0 per the model card.
- First lock file: `locks/indic-parler-tts.json` (revision 660bc53c64ae, 10 files, 3.5 GiB, safetensors only), built and pulled end to end against the real gated Hugging Face repository. Pinned in `models.toml` but still `unverified` pending human review; the separate `google/flan-t5-large` repository its config loads at run time is not covered.
- Lock files for verified or default entries may not list pickle-capable files (.pt, .pth, .bin, .pkl, .pickle, .ckpt, .joblib, .dill): `models check` fails them, `models pull` refuses verified entries that do and warns for unverified ones, and `models lock` warns when its plan includes such files.
- Fix: `models pull` now sends the Hugging Face token on redirects that stay on huggingface.co (gated repositories answer with another huggingface.co URL), still never to another host and never again once a redirect has left huggingface.co.
- `ragleap-voice models pull NAME` (Hugging Face only: HTTPS, host allowlist, manual redirect validation, token sent only to huggingface.co (never to a CDN), per-file size and SHA-256 checks in a staging directory, disk-space check, offline mode) and `models lock NAME` (maintainer tool). Tested against a local fake server only.
- Lock files (`locks/<model>.json`: path, size and SHA-256 per file) with strict validation, a cache layout, and `ragleap-voice models verify NAME` (offline). `models check` now requires a matching lock for every verified or default entry. No download command yet.
- Model manifest loader (`ragleap_voice.manifest`), a strict TOML subset reader for Python 3.10 (`ragleap_voice._toml`) and a read-only `ragleap-voice models list|show|check` command line. No download command yet.
- Package scaffold, licence allowlist, `models.toml` manifest schema and CI licence test.
- `ragleap_voice.bench`: WER/CER metrics with a shared normalizer, CSV test manifest with licence checks, STT runner that records raw CSV/JSON results with environment metadata.
