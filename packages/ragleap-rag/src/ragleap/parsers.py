"""
Document text extraction for ragleap-rag.
Supports .txt, .pdf, .docx.
"""
import io
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def extract_text(filename: str, raw_bytes: bytes) -> str:
    """Extract plain text from raw file bytes, dispatching on file extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ext = f".{ext}"
    if ext == ".txt":
        return _extract_txt(raw_bytes)
    elif ext == ".pdf":
        return _extract_pdf(raw_bytes)
    elif ext == ".docx":
        return _extract_docx(raw_bytes)
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.")


def _extract_txt(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed, retrying with latin-1")
        return raw_bytes.decode("latin-1")


def _extract_pdf(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("pypdf is required for PDF support — pip install ragleap-rag installs it by default") from e

    reader = PdfReader(io.BytesIO(raw_bytes))
    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text)
        else:
            logger.warning(f"No extractable text on PDF page {i + 1} (likely scanned/image-only)")
    full_text = "\n\n".join(pages_text)
    if not full_text.strip():
        raise ValueError(
            "No text could be extracted from this PDF. It may be a scanned "
            "image-only document, which requires OCR (not currently supported)."
        )
    return full_text


def _extract_docx(raw_bytes: bytes) -> str:
    try:
        import docx
    except ImportError as e:
        raise ValueError("python-docx is required for DOCX support — pip install ragleap-rag installs it by default") from e

    document = docx.Document(io.BytesIO(raw_bytes))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    full_text = "\n\n".join(paragraphs)
    if not full_text.strip():
        raise ValueError("No text could be extracted from this DOCX file — it may be empty.")
    return full_text
