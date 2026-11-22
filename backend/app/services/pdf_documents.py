from dataclasses import dataclass

import fitz


class PDFValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PDFMetadata:
    page_count: int


def validate_pdf(data: bytes, max_bytes: int, max_pages: int) -> PDFMetadata:
    if not data:
        raise PDFValidationError("EMPTY_FILE", "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise PDFValidationError("PDF_TOO_LARGE", f"PDF exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if not data.startswith(b"%PDF-"):
        raise PDFValidationError("INVALID_PDF_SIGNATURE", "The file does not have a valid PDF signature.")
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.needs_pass:
            raise PDFValidationError("ENCRYPTED_PDF", "Encrypted or password-protected PDFs are not supported.")
        page_count = document.page_count
        if page_count < 1:
            raise PDFValidationError("EMPTY_PDF", "The PDF contains no pages.")
        if page_count > max_pages:
            raise PDFValidationError("PDF_PAGE_LIMIT", f"PDF exceeds the {max_pages}-page limit.")
        for page_number in range(page_count):
            document.load_page(page_number)
        return PDFMetadata(page_count=page_count)
    except PDFValidationError:
        raise
    except Exception as exc:
        raise PDFValidationError("MALFORMED_PDF", "The PDF is corrupt or cannot be parsed.") from exc
    finally:
        if "document" in locals():
            document.close()

