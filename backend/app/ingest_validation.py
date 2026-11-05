from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import filetype
from charset_normalizer import from_bytes

ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tif": "image",
    ".tiff": "image",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "spreadsheet",
}

MIME_TYPES = {
    "pdf": "application/pdf",
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/tiff": "image/tiff",
    "spreadsheet": "application/octet-stream",
}


class UploadValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def safe_filename(name: str | None) -> str:
    base = Path(name or "document").name
    base = "".join(ch for ch in base if ch.isalnum() or ch in {" ", ".", "-", "_"}).strip()
    base = base.replace(" ", "_")
    return (base[:180] or "document").lstrip(".")


def detect_extension(filename: str) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    kind = ALLOWED_EXTENSIONS.get(suffix)
    if not kind:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadValidationError(
            "UNSUPPORTED_TYPE", f"Unsupported file type '{suffix or 'none'}'. Allowed: {allowed}"
        )
    return suffix, kind


def _looks_like_pdf(head: bytes) -> bool:
    return head.startswith(b"%PDF-")


def _looks_like_jpeg(head: bytes) -> bool:
    return head.startswith(b"\xff\xd8\xff")


def _looks_like_png(head: bytes) -> bool:
    return head.startswith(b"\x89PNG\r\n\x1a\n")


def _looks_like_tiff(head: bytes) -> bool:
    return head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")


def _looks_like_xls(head: bytes) -> bool:
    return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _looks_like_xlsx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            total_uncompressed = sum(info.file_size for info in archive.infolist())
            total_compressed = max(1, sum(info.compress_size for info in archive.infolist()))
            if total_uncompressed > 1024 * 1024 * 1024:
                raise UploadValidationError("ZIP_BOMB", "Spreadsheet expands beyond the safe limit")
            if total_uncompressed / total_compressed > 200:
                raise UploadValidationError("ZIP_BOMB", "Spreadsheet compression ratio is unsafe")
            return "xl/workbook.xml" in names or "xl/workbook.bin" in names
    except zipfile.BadZipFile:
        return False


def validate_file(path: Path, filename: str, mime_type: str | None) -> tuple[str, str, str]:
    """Return (suffix, kind, detected_mime). Raises UploadValidationError."""
    suffix, kind = detect_extension(filename)
    with path.open("rb") as handle:
        head = handle.read(4096)

    if suffix == ".pdf":
        if not _looks_like_pdf(head):
            raise UploadValidationError("INVALID_PDF", "File does not contain a valid PDF header")
        detected = "application/pdf"
    elif suffix in {".jpg", ".jpeg"}:
        if not _looks_like_jpeg(head):
            raise UploadValidationError("INVALID_IMAGE", "File is not a valid JPEG image")
        detected = "image/jpeg"
    elif suffix == ".png":
        if not _looks_like_png(head):
            raise UploadValidationError("INVALID_IMAGE", "File is not a valid PNG image")
        detected = "image/png"
    elif suffix in {".tif", ".tiff"}:
        if not _looks_like_tiff(head):
            raise UploadValidationError("INVALID_IMAGE", "File is not a valid TIFF image")
        detected = "image/tiff"
    elif suffix == ".xlsx":
        if not head.startswith(b"PK") or not _looks_like_xlsx(path):
            raise UploadValidationError("INVALID_XLSX", "File is not a valid XLSX workbook")
        detected = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif suffix == ".xls":
        if not _looks_like_xls(head):
            raise UploadValidationError("INVALID_XLS", "File is not a valid legacy XLS workbook")
        detected = "application/vnd.ms-excel"
    elif suffix == ".csv":
        raw = path.read_bytes()[:2_000_000]
        if b"\x00" in raw:
            raise UploadValidationError("INVALID_CSV", "CSV contains binary data")
        decoded = from_bytes(raw).best()
        if decoded is None:
            raise UploadValidationError("INVALID_CSV", "Could not decode the CSV file")
        sample = str(decoded)[:65536]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(sample), dialect))
        if not rows or not any(any(cell.strip() for cell in row) for row in rows):
            raise UploadValidationError("EMPTY_CSV", "CSV file contains no data rows")
        detected = "text/csv"
    else:
        raise UploadValidationError("UNSUPPORTED_TYPE", "Unsupported file type")

    guess = filetype.guess(head)
    if guess and kind == "image" and not guess.mime.startswith("image/"):
        raise UploadValidationError("MIME_MISMATCH", "File content does not match its extension")
    return suffix, kind, detected


def guess_extension_for_key(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower()
    return suffix if suffix in ALLOWED_EXTENSIONS else ".bin"
