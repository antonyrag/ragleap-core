"""
URL ingestion for ragleap-rag. Fetches a web page and extracts clean,
readable text (stripping navigation, ads, footers, and other
boilerplate) - requires the [web] extra (trafilatura).
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_url_text(url: str) -> Optional[str]:
    """
    Fetch a URL and return clean extracted text, or None if fetching
    or extraction failed. Requires the 'web' extra.
    """
    try:
        import trafilatura
    except ImportError:
        raise ImportError(
            "URL ingestion requires the 'web' extra. Install it with: "
            "pip install ragleap-rag[web]"
        )

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as e:
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
