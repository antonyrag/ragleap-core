# `ingest()` missing `metadata=` parameter

## Problem

`RagLeap` has three raw-input ingestion methods: `ingest()` (raw
bytes, format auto-detected from filename), `ingest_url()` (fetches
and extracts a web page), and `ingest_image()` (OCR/vision on image
bytes). `ingest_url()` and `ingest_image()` both accept an optional
`metadata: Optional[Dict] = None` and thread it through to
`ingest_text()`. `ingest()` does not - it silently drops the ability
to attach metadata at ingest time, calling
`self.ingest_text(filename, text)` with no metadata argument at all.

This is a real, user-facing inconsistency, not a deliberate design
choice - nothing in the codebase or docs explains why `ingest()`
specifically lacks what its two siblings have. It was discovered
downstream: `ragleap-tools`' `ingest_document` tool wraps
`ingest_text()` directly (not `ingest()`), and needed metadata
threading for its own `search_documents` tool's `filename=` scoping
to work (fixed in `ragleap-tools` v0.1.1). Any caller using `ingest()`
directly - the method most real callers would reach for, since it's
the one that does format extraction for them - hits the same gap.

## Fix

Add `metadata: Optional[Dict] = None` to `ingest()`, threaded straight
to the existing `ingest_text()` call. Mirrors `ingest_url()`'s exact
pattern. Backward compatible: the parameter defaults to `None`,
existing callers (including `ragleap-graph`, which depends on this
package) are unaffected.

## Consumer note for `ragleap-agents` / `ragleap-integrations` / `ragleap-flows`

Not part of this fix, but worth recording here since it's directly
relevant to anything ingesting documents at scale: there's no
metadata-key convention enforced anywhere in this codebase.
`ragleap_tools.ingest_document` uses `{"filename": filename}` as its
convention for enabling per-document search scoping. Any other
ingestion path (e.g. `ragleap-integrations` pulling from Gmail/Notion/
Slack) needs to use the same key if it wants documents to be findable
via that same scoping mechanism - there's no schema or validation
that would catch a mismatch, it would just silently fail to match.
