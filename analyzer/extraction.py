"""
Text extraction utilities.

Two extraction paths are supported:

1. PDF -> text
   - Primary: pdfplumber, which reads the embedded text layer and keeps
     line/paragraph structure close to the original layout.
   - Fallback: if a PDF has little or no embedded text (i.e. it is a
     scanned document saved as a PDF), each page is rasterised to an
     image with pypdfium2 and run through Tesseract OCR instead.

2. Image -> text
   - The image is normalised (grayscale + upscale small images) and
     passed to Tesseract OCR via pytesseract.

Both paths return a common result shape so the rest of the app does not
need to know which extraction method was used.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps

# Minimum average non-whitespace characters per page before we assume a
# PDF's embedded text layer is unreliable/absent and fall back to OCR.
MIN_CHARS_PER_PAGE = 15

# Render scale used when rasterising PDF pages for OCR (2.5 ~= 180 DPI).
OCR_RENDER_SCALE = 2.5

SUPPORTED_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}


class ExtractionError(Exception):
    """Raised when text cannot be extracted from a file."""


@dataclass
class ExtractionResult:
    text: str
    method: str  # "pdf-text" | "pdf-ocr" | "image-ocr"
    page_count: int = 1
    word_count: int = 0
    char_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def finalize(self) -> "ExtractionResult":
        self.text = self.text.strip()
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)
        return self


def _clean_page_text(raw: str) -> str:
    """Collapse stray whitespace while keeping paragraph breaks."""
    lines = [ln.rstrip() for ln in raw.splitlines()]
    # Drop excess blank lines (keep at most one blank line as a paragraph break)
    cleaned: list[str] = []
    blank_run = 0
    for ln in lines:
        if ln.strip() == "":
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(ln)
    return "\n".join(cleaned).strip()


def _extract_pdf_text_layer(data: bytes) -> tuple[str, int]:
    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            raw = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
            pages_text.append(_clean_page_text(raw))
    return "\n\n".join(p for p in pages_text if p), page_count


def _ocr_pdf(data: bytes) -> tuple[str, int]:
    pages_text: list[str] = []
    pdf = pdfium.PdfDocument(data)
    try:
        page_count = len(pdf)
        for i in range(page_count):
            page = pdf[i]
            bitmap = page.render(scale=OCR_RENDER_SCALE)
            image = bitmap.to_pil()
            text = pytesseract.image_to_string(image)
            pages_text.append(_clean_page_text(text))
    finally:
        pdf.close()
    return "\n\n".join(p for p in pages_text if p), page_count


def extract_from_pdf(data: bytes) -> ExtractionResult:
    """Extract text from PDF bytes, falling back to OCR for scanned PDFs."""
    if not data:
        raise ExtractionError("The uploaded PDF is empty.")

    try:
        text, page_count = _extract_pdf_text_layer(data)
    except Exception as exc:  # noqa: BLE001 - surface as extraction error
        raise ExtractionError(f"Could not read this PDF ({exc}).") from exc

    avg_chars_per_page = len(text.strip()) / max(page_count, 1)
    if avg_chars_per_page >= MIN_CHARS_PER_PAGE:
        return ExtractionResult(text=text, method="pdf-text", page_count=page_count).finalize()

    # Likely a scanned PDF with no usable embedded text -> OCR fallback.
    try:
        ocr_text, page_count = _ocr_pdf(data)
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(
            f"This PDF has no readable text layer and OCR also failed ({exc})."
        ) from exc

    if not ocr_text.strip():
        raise ExtractionError(
            "No text could be found in this PDF, even after running OCR. "
            "Try a higher-resolution scan."
        )

    result = ExtractionResult(text=ocr_text, method="pdf-ocr", page_count=page_count)
    result.warnings.append(
        "This PDF had no embedded text layer, so text was recovered with OCR. "
        "Double-check the result for scanning artifacts."
    )
    return result.finalize()


def extract_from_image(data: bytes, filename: str = "") -> ExtractionResult:
    """Run OCR on an uploaded image file."""
    if not data:
        raise ExtractionError("The uploaded image is empty.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not open this image ({exc}).") from exc

    # Normalise for better OCR accuracy: grayscale, auto-orient, and
    # upscale small images (Tesseract does noticeably better above ~1000px).
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    if max(image.size) < 1000:
        scale = 1000 / max(image.size)
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.LANCZOS)

    try:
        text = pytesseract.image_to_string(image)
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"OCR failed on this image ({exc}).") from exc

    text = _clean_page_text(text)
    if not text.strip():
        raise ExtractionError(
            "No text could be detected in this image. Try a clearer, "
            "higher-resolution screenshot."
        )

    result = ExtractionResult(text=text, method="image-ocr", page_count=1)
    return result.finalize()


def extract(data: bytes, filename: str, content_type: str = "") -> ExtractionResult:
    """Dispatch extraction based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf" or "pdf" in content_type:
        return extract_from_pdf(data)
    if ext in SUPPORTED_IMAGE_TYPES or content_type.startswith("image/"):
        return extract_from_image(data, filename)

    raise ExtractionError(
        f"Unsupported file type '{ext or content_type}'. "
        "Upload a PDF, PNG, JPG, or JPEG file."
    )
