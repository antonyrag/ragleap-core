# Model lock files

One JSON file per model, named `<model>.json`, listing every file of that model at the pinned
revision: relative path, size in bytes and SHA-256. The `sha256` field of the model's entry in
`models.toml` is the SHA-256 of the lock's canonical form (sorted keys, compact separators), so
editing a lock without updating the manifest, or the other way round, fails `ragleap-voice models check`.

Format (schema 1):

    {"schema": 1, "model": "NAME", "revision": "PINNED-REVISION", "source_url": "https://...",
     "files": [{"path": "dir/file.bin", "size": 123, "sha256": "<64 lowercase hex>"}]}

Paths are relative POSIX paths without `..`, backslashes or unusual characters. Entries stay
`unverified` until a person has reviewed their lock file. Current lock files: `indic-parler-tts.json`
(10 files, safetensors only) and `flan-t5-large-tokenizer.json` (5 tokenizer files of the text encoder it
loads at run time; its dependency). Both are pinned but not yet reviewed. `whisper-large-v3.json` (7 files, `model.bin` tagged `ctranslate2`) was built on Colab; its `model.bin` size and SHA-256 equal the Hugging Face listing, the six small files rest on our own download only. The entry stays unverified.
`naijavox-2.json` (9 files, safetensors only; the sample audio and image files of the repository are deliberately not locked) and `sunflowerasr-51-african-languages.json` (8 files, safetensors only) were built on Colab; in each, the large file's size and SHA-256 equal the Hugging Face listing and the small files rest on our own download only. Both entries stay unverified.

A lock for a verified or default entry must not list pickle-capable files (`.pt`, `.pth`, `.bin`,
`.pkl`, `.pickle`, `.ckpt`, `.joblib`, `.dill`): loading them can execute code. Exclude them when
locking, or keep the entry unverified. `ragleap-voice models check` enforces this.

One justified exception: a file entry may carry `"format": "ctranslate2"` when it is a `.bin` file
(the CTranslate2 weights of Whisper). The tag is part of the lock, so the lock digest in `models.toml`
covers it. It is honoured only for that suffix, and `models verify` and `models pull` also check the
file's header, in addition to size and SHA-256. Any other format needs a code change. Residual risk: the
header check does not prove the rest of the file is well formed, and CTranslate2 reads the file with native
code. The hash pins what was reviewed; it does not make the file trustworthy.
Write the tag with `ragleap-voice models lock NAME ... --format model.bin=ctranslate2`. A tagged file is downloaded
to a temporary folder (free disk space for the whole file is needed) so its header is checked before the tag is written.

A manifest entry can list other entries in `depends_on`. Each dependency has its own lock file and its own cache
folder. `pull` fetches dependencies first and refuses to start if any lock is missing; a verified or default
entry may only depend on verified entries.

## Pull tests

Run on Google Colab on 2026-10-19, from the locks on `main`, with `models pull NAME --allow-unverified`:

- `naijavox-2` (9 files) and `sunflowerasr-51-african-languages` (8 files, gated; the token was passed only to that one subprocess) were downloaded, checked file by file for size and SHA-256 against the lock, and installed at the pinned revision. `models verify` then passed offline with no token in the environment.
- Tamper test on `naijavox-2`: changing one bit of `config.json` made `models verify` fail with a SHA-256 mismatch for that file, and restoring it made the check pass again.
- After the Colab runtime was recycled (the files were gone), `naijavox-2` was pulled and verified again from the lock on the clean runtime, then loaded with `transformers` 5.18.0 from the verified folder with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and no token variable in the environment. One Yoruba FLEURS clip was transcribed; the first 110 characters of the transcript equal the first 110 characters of the first clip's output from the benchmark run in `benchmarks/voice/README.md` (only that prefix was compared).
- `sunflowerasr-51-african-languages` was later loaded with `transformers` 5.18.0 from its verified folder (`local_files_only=True`, no token in the environment, `HF_HUB_OFFLINE` not set) in the noise measurement of 2026-10-21 (`benchmarks/voice/colab_noise_engines_measure.py`). A load with the offline flags set was not run for it.
- Both entries remain unverified. The training-data licences of both models are not reviewed, and no person has reviewed the lock files. A successful pull and load shows that the files are intact and usable; it says nothing about quality or licences.
