import fitz  # PyMuPDF

from services.openai_service import call_gpt4o_vision, summarize_text

OCR_PROMPT = (
    "Extract all text from this academic marksheet exactly as shown. "
    "Include: student name, roll number, institution, examination year, "
    "all subject names with their marks/grades, total marks, percentage, "
    "and any other academic information visible. Preserve the structure."
)


async def extract_and_summarize(file_bytes: bytes, content_type: str) -> tuple[str, str]:
    text = await _extract_text(file_bytes, content_type)
    summary = await summarize_text(text)
    return text, summary


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
