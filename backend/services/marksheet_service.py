import fitz  # PyMuPDF

from services.openai_service import (
    call_gpt4o_vision,
    summarize_text,
    validate_image_is_marksheet,
    validate_is_marksheet,
)

OCR_PROMPT = (
    "Extract all text from this academic marksheet exactly as shown. "
    "Include: student name, roll number, institution, examination year, "
    "all subject names with their marks/grades, total marks, percentage, "
    "and any other academic information visible. Preserve the structure."
)


class NotAMarksheetError(Exception):
    """Raised when the uploaded document is not an academic marksheet."""
    pass


async def extract_and_summarize(file_bytes: bytes, content_type: str) -> tuple[str, str]:
    # Step 1: validate the document is actually a marksheet
    await _validate_document(file_bytes, content_type)

    # Step 2: extract text and summarize
    text = await _extract_text(file_bytes, content_type)
    summary = await summarize_text(text)
    return text, summary


async def _validate_document(file_bytes: bytes, content_type: str) -> None:
    """Check with GPT whether the upload is a real marksheet."""
    if content_type == "application/pdf":
        # Try text extraction first for validation
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        first_page_image = None
        for page_num in range(min(len(doc), 2)):  # check first 2 pages
            page = doc[page_num]
            page_text = page.get_text().strip()
            if len(page_text) >= 50:
                text += page_text + "\n"
            elif first_page_image is None:
                # Scanned page — grab image for vision check
                pix = page.get_pixmap(dpi=150)
                first_page_image = pix.tobytes("png")
        doc.close()

        if text:
            is_valid = await validate_is_marksheet(text, source="text")
        elif first_page_image:
            is_valid = await validate_image_is_marksheet(first_page_image)
        else:
            raise NotAMarksheetError(
                "The uploaded PDF appears to be empty. Please upload a valid academic marksheet."
            )
    else:
        # Image upload — validate via vision
        is_valid = await validate_image_is_marksheet(file_bytes)

    if not is_valid:
        raise NotAMarksheetError(
            "The uploaded file does not appear to be an academic marksheet. "
            "Please upload your official marksheet, transcript, or result card."
        )


async def _extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        return await _extract_from_pdf(file_bytes)
    else:
        return await call_gpt4o_vision(file_bytes, OCR_PROMPT)


async def _extract_from_pdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_text = ""

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text().strip()

        if len(page_text) >= 50:
            all_text += page_text + "\n"
        else:
            # Scanned page — use GPT-4o Vision for OCR
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            ocr_text = await call_gpt4o_vision(img_bytes, OCR_PROMPT)
            all_text += ocr_text + "\n"

    doc.close()
    return all_text.strip() or "Could not extract text from the provided document."
