from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image

from ..config import get_settings
from ..ocr import OCRError, OCRUnavailableError, ocr_image

logger = logging.getLogger(__name__)


class PdfProcessingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PageExtraction:
    page_number: int
    text: str
    text_source: str
    ocr_confidence: float | None
    width: int
    height: int
    error: str | None = None


def _render_page(page: fitz.Page, dpi: int = 250) -> Image.Image:
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _text_looks_digital(text: str) -> bool:
    stripped = "".join(ch for ch in text if not ch.isspace())
    return len(stripped) >= 40


def extract_pdf(path: Path, progress=None) -> list[PageExtraction]:
    settings = get_settings()
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise PdfProcessingError("INVALID_PDF", f"Could not open PDF: {exc}") from exc

    try:
        if document.needs_pass:
            raise PdfProcessingError("ENCRYPTED_PDF", "PDF is password protected")
        if document.page_count == 0:
            raise PdfProcessingError("EMPTY_PDF", "PDF contains no pages")
        if document.page_count > settings.max_pdf_pages:
            raise PdfProcessingError(
                "TOO_MANY_PAGES",
                f"PDF has {document.page_count} pages; limit is {settings.max_pdf_pages}",
            )

        total = document.page_count
        pages: list[PageExtraction] = []
        for index in range(total):
            page = document.load_page(index)
            page_number = index + 1
            width, height = page.rect.width, page.rect.height
            extracted = ""
            source = "digital"
            confidence: float | None = None
            error: str | None = None
            try:
                extracted = page.get_text("text") or ""
                if not _text_looks_digital(extracted):
                    image = _render_page(page)
                    try:
                        ocr = ocr_image(image)
                        if ocr.text.strip():
                            extracted = ocr.text
                            source = "ocr"
                            confidence = ocr.confidence
                        else:
                            source = "none" if not extracted.strip() else "digital"
                    except OCRUnavailableError:
                        raise
                    except OCRError as exc:
                        error = str(exc)
                        source = "digital" if extracted.strip() else "none"
                else:
                    source = "digital"
            except OCRUnavailableError:
                raise
            except Exception as exc:
                error = f"Page {page_number} failed: {exc}"
                source = "none" if not extracted.strip() else source
                logger.warning("page processing failed doc page=%s: %s", page_number, exc)

            pages.append(
                PageExtraction(
                    page_number=page_number,
                    text=extracted.strip(),
                    text_source=source,
                    ocr_confidence=confidence,
                    width=int(width),
                    height=int(height),
                    error=error,
                )
            )
            if progress:
                progress(page_number, total, source)
        return pages
    finally:
        document.close()


def render_pdf_page(path: Path, page_number: int, dpi: int = 150) -> bytes:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise PdfProcessingError("INVALID_PDF", f"Could not open PDF: {exc}") from exc
    try:
        if page_number < 1 or page_number > document.page_count:
            raise PdfProcessingError("PAGE_NOT_FOUND", "Requested page does not exist")
        page = document.load_page(page_number - 1)
        pix = page.get_pixmap(
            matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), colorspace=fitz.csRGB, alpha=False
        )
        return pix.tobytes("jpeg")
    finally:
        document.close()


def extract_image(path: Path) -> list[PageExtraction]:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB") if image.mode not in {"RGB", "L"} else image
            width, height = image.size
            ocr = ocr_image(image)
            return [
                PageExtraction(
                    page_number=1,
                    text=ocr.text.strip(),
                    text_source="ocr" if ocr.text.strip() else "none",
                    ocr_confidence=ocr.confidence,
                    width=width,
                    height=height,
                )
            ]
    except OCRError:
        raise
    except Exception as exc:
        raise PdfProcessingError("INVALID_IMAGE", f"Could not read image: {exc}") from exc


def image_preview(path: Path, max_dim: int = 1800) -> tuple[bytes, str]:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if max(image.size) > max_dim:
                ratio = max_dim / max(image.size)
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            return buffer.getvalue(), "image/jpeg"
    except Exception as exc:
        raise PdfProcessingError("INVALID_IMAGE", f"Could not render image: {exc}") from exc
