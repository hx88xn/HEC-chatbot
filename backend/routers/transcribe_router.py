from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import verify_token
from services.openai_service import transcribe_audio

router = APIRouter()

ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/mp4",
    "audio/mpeg",
    "audio/m4a",
    "audio/x-m4a",
    "application/octet-stream",  # some browsers send this for webm
}


class TranscribeResponse(BaseModel):
    transcript: str


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    _user: str = Depends(verify_token),
):
    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file too large. Maximum size is 25 MB.")

    filename = audio.filename or "audio.webm"

    try:
        transcript = await transcribe_audio(audio_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    return TranscribeResponse(transcript=transcript)
