import logging

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract plain text from a PDF file using PyMuPDF (fitz).
    Raises ValueError for image-only (scanned) PDFs with no extractable text.
    Phase 2: called by contract_service.analyze_from_pdf().
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF"
        )

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(
            f"Could not read the file as a PDF. Make sure it is a valid PDF, "
            f"or paste the contract text directly. ({exc})"
        ) from exc
    if doc.page_count == 0:
        raise ValueError("The uploaded PDF has no pages.")

    page_count = doc.page_count
    parts = [page.get_text() for page in doc]
    doc.close()

    text = "\n".join(parts).strip()
    if not text:
        raise ValueError(
            "No text could be extracted from this PDF — it may be a scanned or "
            "image-only document. Please copy and paste the contract text directly."
        )

    logger.info(
        "Extracted %d characters from PDF (%d page(s)).",
        len(text),
        page_count,
    )
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extract plain text from a Word (.docx) file using python-docx.
    Reads paragraphs and table cells; processed in memory only (no disk).
    Raises ValueError if the file is not a valid .docx or has no readable text.
    """
    import io

    try:
        import docx  # python-docx
    except ImportError:
        raise RuntimeError(
            "python-docx is not installed. Run: pip install python-docx"
        )

    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(
            f"Could not read the file as a Word (.docx) document. Make sure it is a "
            f"valid .docx, or paste the contract text directly. ({exc})"
        ) from exc

    parts = [p.text for p in document.paragraphs]
    # Include table cell text — contracts often place terms in tables.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)

    text = "\n".join(p for p in parts if p and p.strip()).strip()
    if not text:
        raise ValueError(
            "No readable text could be found in this Word document. "
            "Please paste the contract text directly."
        )

    logger.info("Extracted %d characters from DOCX.", len(text))
    return text
