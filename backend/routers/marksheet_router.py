from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import session_store
from auth import verify_token
from services.marksheet_service import NotAMarksheetError, extract_and_summarize

router = APIRouter()

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


class MarksheetResponse(BaseModel):
    session_id: str
    summary: str
    status: str = "success"


@router.post("/upload", response_model=MarksheetResponse)
async def upload_marksheet(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    _user: str = Depends(verify_token),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {file.content_type}. Use PDF, JPEG, PNG, or WEBP.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")

    try:
        text, summary = await extract_and_summarize(file_bytes, file.content_type)
    except NotAMarksheetError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process marksheet: {str(e)}")

    session_store.update_marksheet(session_id, text, summary)

    return MarksheetResponse(session_id=session_id, summary=summary)
