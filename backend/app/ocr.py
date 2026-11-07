from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .config import get_settings

logger = logging.getLogger(__name__)


class OCRError(RuntimeError):
    pass


class OCRUnavailableError(OCRError):
    pass


class OCRResult:
    def __init__(self, text: str, confidence: float, engine: str):
        self.text = text
        self.confidence = max(0.0, min(1.0, confidence))
        self.engine = engine

    def __repr__(self) -> str:  # pragma: no cover
        return f"OCRResult(engine={self.engine!r}, chars={len(self.text)}, confidence={self.confidence:.2f})"


@lru_cache
def detect_ocr_engine() -> str:
    settings = get_settings()
    requested = settings.ocr_engine.lower()
    if requested == "none":
        return "none"

    if requested in {"rapidocr", "auto"}:
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return "rapidocr"
        except Exception:  # pragma: no cover - optional dependency
            if requested == "rapidocr":
                raise OCRUnavailableError(
                    "RapidOCR is not installed. Run `uv sync` or set OCR_ENGINE=tesserocr."
                )

    if requested in {"tesserocr", "auto"}:
        try:
            import tesserocr  # noqa: F401
        except Exception as exc:  # pragma: no cover - optional dependency
            if requested == "tesserocr":
                raise OCRUnavailableError(
                    "tesserocr is not installed. Run `uv sync` or install Tesseract."
                ) from exc
        else:
            return "tesserocr"

    if requested in {"tesseract", "auto"}:
        try:
            import pytesseract

            if settings.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
            pytesseract.get_tesseract_version()
            return "tesseract"
        except Exception:
            if requested == "tesseract":
                raise OCRUnavailableError(
                    "Tesseract is not installed. Install it with `brew install tesseract`."
                )

    if requested not in {"auto", "rapidocr", "tesserocr", "tesseract"}:
        raise OCRUnavailableError(f"Unknown OCR_ENGINE: {requested}")
    return "none"


def _tessdata_dir() -> Path | None:
    """Directory containing eng.traineddata (bundled by default)."""
    settings = get_settings()
    if settings.tessdata_prefix:
        path = Path(settings.tessdata_prefix).expanduser()
        return path if path.is_dir() else None
    bundled = Path(__file__).resolve().parent / "tessdata"
    return bundled if bundled.is_dir() else None


@lru_cache
def _rapidocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    logger.info("initializing RapidOCR engine")
    return RapidOCR()


def preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"L", "RGB"}:
        image = image.convert("RGB")
    width, height = image.size
    max_dim = 3200
    if max(width, height) > max_dim:
        ratio = max_dim / max(width, height)
        image = image.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)
    if image.mode == "RGB":
        gray = ImageOps.grayscale(image)
    else:
        gray = image
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return gray.filter(ImageFilter.SHARPEN)


def _ocr_rapidocr(image: Image.Image) -> OCRResult:
    import numpy as np

    engine = _rapidocr_engine()
    processed = preprocess_image(image)
    result, _elapse = engine(np.array(processed.convert("RGB")))
    if not result:
        return OCRResult("", 0.0, "rapidocr")
    lines: list[str] = []
    scores: list[float] = []
    for item in result:
        # Common format: [box, text, score]
        try:
            text = str(item[1])
            score = float(item[2])
        except (IndexError, TypeError, ValueError):
            text = str(item)
            score = 0.5
        if text.strip():
            lines.append(text.strip())
            scores.append(score)
    confidence = sum(scores) / len(scores) if scores else 0.0
    return OCRResult("\n".join(lines), confidence, "rapidocr")


def _ocr_tesseract(image: Image.Image) -> OCRResult:
    import pytesseract
    from pytesseract import Output

    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    processed = preprocess_image(image)
    data = pytesseract.image_to_data(
        processed, output_type=Output.DICT, config="--oem 1 --psm 6"
    )
    words: list[str] = []
    scores: list[float] = []
    for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
        cleaned = (text or "").strip()
        if cleaned:
            words.append(cleaned)
            try:
                score = float(conf)
                if score >= 0:
                    scores.append(score / 100.0)
            except (TypeError, ValueError):
                pass
    confidence = sum(scores) / len(scores) if scores else 0.0
    return OCRResult(" ".join(words), confidence, "tesseract")


def _ocr_tesserocr(image: Image.Image) -> OCRResult:
    import tesserocr

    processed = preprocess_image(image)
    kwargs: dict = {
        "lang": "eng",
        "oem": tesserocr.OEM.LSTM_ONLY,
        "psm": tesserocr.PSM.SINGLE_BLOCK,
    }
    tessdata = _tessdata_dir()
    if tessdata is not None:
        kwargs["path"] = str(tessdata)
    try:
        api = tesserocr.PyTessBaseAPI(**kwargs)
    except Exception as exc:
        raise OCRUnavailableError(f"Tesseract could not start: {exc}") from exc
    try:
        api.SetImage(processed)
        text = (api.GetUTF8Text() or "").strip()
        try:
            confidence = max(0.0, min(1.0, float(api.MeanTextConf()) / 100.0))
        except Exception:
            confidence = 0.0
    finally:
        api.End()
    return OCRResult(text, confidence, "tesserocr")


def ocr_image(image: Image.Image) -> OCRResult:
    engine = detect_ocr_engine()
    if engine == "rapidocr":
        return _ocr_rapidocr(image)
    if engine == "tesserocr":
        return _ocr_tesserocr(image)
    if engine == "tesseract":
        return _ocr_tesseract(image)
    raise OCRUnavailableError(
        "No OCR engine is available. Install dependencies or set OCR_ENGINE=tesserocr."
    )


def ocr_image_file(path: Path) -> OCRResult:
    try:
        with Image.open(path) as image:
            return ocr_image(image)
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(f"Could not read image: {exc}") from exc


def engine_hint() -> str:
    try:
        return detect_ocr_engine()
    except OCRError:
        return "unavailable"


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None
