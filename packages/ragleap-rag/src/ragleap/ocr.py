"""
OCR text extraction for ragleap-rag. Extracts literal text visible in
an image (scanned documents, screenshots, photos of text) using
Tesseract OCR via pytesseract. Requires the 'ocr' extra.

For images with no text to read (product photos, diagrams, charts),
use vision captioning instead (RagLeap.ingest_image(mode="caption")),
which describes what's in the image rather than reading text from it.
"""
import io
import logging

logger = logging.getLogger(__name__)


def extract_text_from_image(raw_bytes: bytes) -> str:
    """
    Run OCR on image bytes and return extracted text. Requires the
    'ocr' extra: pip install ragleap-rag[ocr] (also requires the
    Tesseract binary installed on the system - see
    https://github.com/tesseract-ocr/tesseract for install instructions).
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise ValueError(
            "OCR requires the 'ocr' extra and the Tesseract binary. "
            "Install with: pip install ragleap-rag[ocr], and install "
            "Tesseract itself (e.g. 'apt install tesseract-ocr' on Debian/Ubuntu)."
        ) from e

    try:
        image = Image.open(io.BytesIO(raw_bytes))
    except Exception as e:
        raise ValueError(f"Could not open image data: {e}") from e

    try:
        text = pytesseract.image_to_string(image)
    except Exception as e:
        raise ValueError(
            f"OCR failed: {e}. If this is a 'tesseract not found' error, "
            f"install the Tesseract binary itself, not just the Python package."
        ) from e

    if not text.strip():
        raise ValueError("OCR found no readable text in this image.")

    return text
