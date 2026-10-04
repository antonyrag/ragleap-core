"""
URL ingestion for ragleap-rag. Fetches a web page and extracts clean,
readable text (stripping navigation, ads, footers, and other
boilerplate) - requires the [web] extra (trafilatura).

Pages are downloaded by ragleap._net.fetch_public(), which refuses
non-public addresses unless allow_private=True (see that module).
"""
import http.client
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_url_text(url: str, allow_private: bool = False) -> Optional[str]:
    """
    Fetch a URL and return clean extracted text, or None if fetching
    or extraction failed. Raises UnsafeURLError (a ValueError) when the
    URL targets a non-public address and allow_private is False.
    Requires the 'web' extra.
    """
    try:
        import trafilatura
    except ImportError as e:
        raise ImportError(
            "URL ingestion requires the 'web' extra (pip install "
            f"ragleap-rag[web]), but importing trafilatura failed: {e}"
        ) from e

    from ragleap._net import UnsafeURLError, fetch_public

    try:
        downloaded = fetch_public(url, allow_private=allow_private)
    except UnsafeURLError:
        raise
    except (OSError, http.client.HTTPException) as e:
        logger.error(f"Failed to fetch URL '{url}': {e}")
        return None

    if downloaded is None:
        logger.warning(f"No content downloaded from '{url}'")
        return None

    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    if not text or not text.strip():
        logger.warning(f"No extractable text found at '{url}'")
        return None

    return text
