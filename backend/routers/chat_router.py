import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import session_store
from auth import verify_token
from services.openai_service import stream_chat_response

router = APIRouter()

SYSTEM_PROMPT = """You are a professional career counsellor working for the Higher Education Commission (HEC) of Pakistan. Your role is to guide Pakistani students toward suitable career paths based on their academic background, personal interests, aptitudes, and aspirations.

Your approach:
1. Start by warmly greeting the student and briefly acknowledging their uploaded academic results.
2. Ask targeted, thoughtful questions ONE AT A TIME — never ask multiple questions at once. Wait for the student's response before asking the next.
3. Through conversation, probe into: academic strengths and weaknesses, hobbies and passions, preferred work style (creative vs. analytical vs. people-oriented), financial goals, family context and constraints, preferred university disciplines, and long-term aspirations.
4. After gathering sufficient information (typically 6-8 exchanges), provide a structured career recommendation that includes:
   - Top 3 recommended career paths with clear reasoning tied to what the student shared
   - Relevant university programs in Pakistan (HEC-recognized institutions)
   - Required entry tests (MDCAT for medical, ECAT for engineering, NTS, GAT, SAT, etc.)
   - Estimated timeline and concrete next steps
5. Be empathetic, culturally sensitive, and encouraging. Acknowledge the Pakistani higher education context (public vs. private universities, scholarships like HEC Need-Based, PEEF, etc., job market realities).
6. Use simple, clear English. Be warm but professional. Avoid jargon. Be concise but thorough.
7. NEVER give generic advice — always tie recommendations back to what the student has told you and their marksheet results.
8. If the student seems uncertain or anxious, reassure them that many paths are available.

Student's academic record from uploaded marksheet:
{marksheet_context}"""


class ChatRequest(BaseModel):
    session_id: str
    message: str


@router.post("/stream")
async def chat_stream(req: ChatRequest, _user: str = Depends(verify_token)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session = session_store.get_or_create(req.session_id)

    marksheet_context = session.marksheet_summary or session.marksheet_text or "Not provided — ask the student about their academic background."
    system_content = SYSTEM_PROMPT.format(marksheet_context=marksheet_context)

    messages = [{"role": "system", "content": system_content}]
    messages.extend(session.history)
    messages.append({"role": "user", "content": req.message})

    session_store.append_history(req.session_id, "user", req.message)

    async def event_generator():
        full_response = ""
        try:
            async for delta in stream_chat_response(messages):
                full_response += delta
                yield f"data: {json.dumps({'delta': delta, 'done': False})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'delta': '', 'done': True, 'error': str(e)})}\n\n"
            return
        session_store.append_history(req.session_id, "assistant", full_response)
        yield f"data: {json.dumps({'delta': '', 'done': True})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
