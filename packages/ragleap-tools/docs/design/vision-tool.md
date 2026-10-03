# Vision tool - describe an image from a sandboxed file

## Problem

A tool-calling model sometimes needs to look at an image (screenshot,
chart, photo) and get text back. ragleap-rag already has
describe_image(), but it lives on the generator (reached through a
private attribute), is Gemini-only per its own docstring, and the
public path (ingest_image(mode="caption")) stores the description in
the database. Wrapping it would give this tool a write side effect and
a single hardcoded vendor - the same shape this package rejected for
web search.

## Design

A VisionProvider abstract base class:
describe(image_bytes, mime_type, prompt) -> str, plus a
supported_mime_types attribute. Two reference implementations with
meaningfully different request shapes:

- GeminiVisionProvider - generateContent with an inline_data part
  (mime_type + base64 data); key sent in the x-goog-api-key header.
- AnthropicVisionProvider - POST /v1/messages with a base64 image
  content block (media_type + data); x-api-key and anthropic-version
  headers; max_tokens is required by the API.

Each requires api_key and model at construction: no env-var fallback,
no default provider, no default model (same BYOK rule as SearchProvider
and ragleap-rag's "always specify your model").

VisionConfig holds a provider instance, a FileOpsConfig (the same
sandbox the file tools use), max_image_bytes and max_prompt_chars.
make_vision_tool(config) returns one Tool: describe_image(path,
prompt=None). Same config-binding shape as make_search_tool.

## Input: sandboxed path only

Tool arguments are JSON, so a model cannot supply image bytes. The tool
takes a path relative to the sandbox root, resolved by the existing
_resolve_safe_path() in file_ops.py (Path.resolve() plus an
is_relative_to() check, so ../ traversal and symlink escapes are
rejected). No new path-security code is written; PathEscapeError is
caught and returned as a ToolResult error. Developers who already hold
bytes can call provider.describe() directly.

Deliberately NOT supported: URLs. Fetching a model-supplied URL is an
SSRF surface (ragleap-rag's own ingest_url() has the same gap, tracked
in #534). Out of scope until a dedicated security design pass.

## Validation (before any network call)

In this order, each failure returned as ToolResult(success=False):
1. prompt is a string and within max_prompt_chars (it is
   model-controlled); None or empty falls back to a generic
   describe-this-image instruction.
2. path resolves inside the sandbox and is a regular file.
3. size on disk is within max_image_bytes (default 5,000,000 bytes raw).
   Checked from the file's size before reading it. Deliberately
   conservative: published per-image limits conflict across sources
   (5 MB in some, 10 MB base64-encoded in the official vision page we
   found), and base64 inflates by roughly a third.
4. MIME type detected from magic bytes, not the file extension
   (Anthropic returns a 400 when media_type does not match the actual
   bytes). Rejected if not in provider.supported_mime_types.

## Dependencies

stdlib only (urllib.request, base64, json). dependencies = [] stays.

## Error handling

Network errors (URLError), non-200 responses, malformed JSON, a
response with no text, and every validation failure above are caught
and returned as ToolResult(success=False, error=...) - never raised,
matching every other tool in this package.

## Result shape

{"description": str}. Normalized across providers; the provider's raw
response is not exposed.

## Untrusted content

Text visible inside an image is attacker-controllable and flows into
the calling model's context as the description. A hostile image can
contain instructions aimed at the model (prompt injection). This tool
does not screen descriptions. Callers wiring it into an agent loop
should treat the result as untrusted third-party text.

## Cost

Every call is a paid, uncached provider request, and image tokens count
against the caller's quota. Because the model chooses when to call the
tool, max_image_bytes and the prompt cap bound the damage per call; no
caching, rate limiting or batching in this version.

## What this doesn't do

No URL input, no multi-image calls, no OCR (ragleap-rag's pytesseract
path is separate), no image generation, no Files-API upload (inline
base64 only; Gemini's inline path shares a 20 MB limit across the whole
request, including the prompt).

## Verification status

Checked against current public documentation (see the live check below):
- Gemini: inline_data part with mime_type and base64 data in
  generateContent; 20 MB total-request limit for inline data;
  x-goog-api-key header (seen in one independent curl example).
- Anthropic: POST https://api.anthropic.com/v1/messages with x-api-key,
  anthropic-version: 2023-06-01, content-type: application/json;
  base64 image block with media_type; formats JPEG, PNG, GIF, WebP.

Live check (2026-10-03): one real GeminiVisionProvider call (model
gemini-3.6-flash) on a generated 64x64 solid-red PNG returned the expected
one-word answer. This confirms the x-goog-api-key header, the inline_data
request body and candidates[0].content.parts[].text parsing for PNG input.
Not live-checked: JPEG and WebP input, large images, Gemini's error
responses.

Not confirmed: AnthropicVisionProvider has not been called live, and its
response field names were taken from prior knowledge. Gemini's supported
image formats beyond PNG and both providers' exact per-image size limits
were not confirmed. Any provider that has not been live-checked is
labelled unverified in the README, CHANGELOG and the website, same
standard as Tavily/Serper.
