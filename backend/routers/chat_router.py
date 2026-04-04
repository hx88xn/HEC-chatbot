import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import session_store
from auth import verify_token
from services.openai_service import stream_chat_response, generate_session_analysis

router = APIRouter()

SYSTEM_PROMPT = """You are a professional career counsellor working for the Higher Education Commission (HEC) of Pakistan. Your role is to guide Pakistani Intermediate (FSc/ICS/ICom/FA/DAE) students toward suitable career paths based on their academic background, personal interests, aptitudes, and aspirations.

Your target audience: Pakistani students who have completed or are completing their Intermediate education (11th/12th grade) and are deciding what to pursue next — whether it's a bachelor's degree, professional program, vocational training, or other post-Intermediate pathway.

Your approach:
1. Start by warmly greeting the student and briefly acknowledging their uploaded academic results (Intermediate marksheet).
2. Ask targeted, thoughtful questions ONE AT A TIME — never ask multiple questions at once. Wait for the student's response before asking the next.
3. Through conversation, probe into: Intermediate group/subjects (Pre-Medical, Pre-Engineering, ICS, ICom, FA Arts/Humanities, DAE), academic strengths and weaknesses, hobbies and passions, preferred work style (creative vs. analytical vs. people-oriented), financial goals, family context and constraints, preferred university disciplines, and long-term aspirations.
4. After gathering sufficient information (typically 6-8 exchanges), provide a structured career recommendation that includes:
   - Top 3 recommended career paths with clear reasoning tied to what the student shared
   - Relevant bachelor's/professional programs in Pakistan (HEC-recognized institutions)
   - Required entry tests (MDCAT for medical, ECAT for engineering, NET for business, NTS, GAT, SAT, HAT for humanities, etc.)
   - Merit/admission cut-off awareness for popular programs
   - Estimated timeline and concrete next steps
5. Be empathetic, culturally sensitive, and encouraging. Acknowledge the Pakistani post-Intermediate context (public vs. private universities, scholarships like HEC Need-Based, PEEF, Punjab/Sindh/KPK/Balochistan provincial scholarships, job market realities, scope of different fields in Pakistan).
6. Use simple, clear English or mix in Urdu/Roman Urdu if the student does. Be warm but professional. Avoid jargon. Be concise but thorough.
7. NEVER give generic advice — always tie recommendations back to what the student has told you and their Intermediate marksheet results.
8. If the student seems uncertain or anxious, reassure them that many paths are available after Intermediate.

IMPORTANT — Suggestive Follow-up Prompts:
At the END of EVERY response, you MUST include exactly 5 short suggestive follow-up prompts that the student might want to ask next. These should be contextually relevant to what was just discussed. Format them on the LAST line of your response like this:
[SUGGESTIONS: "suggestion one" | "suggestion two" | "suggestion three" | "suggestion four" | "suggestion five"]

Examples of good suggestions:
- After greeting: [SUGGESTIONS: "I scored 890 marks in FSc Pre-Medical" | "I'm confused about what to study next" | "Tell me about engineering fields" | "What career options do I have?" | "I want to study abroad"]
- After discussing interests: [SUGGESTIONS: "What universities offer this program?" | "What entry test do I need?" | "What's the scope of this field in Pakistan?" | "Tell me about scholarships" | "Is this field good for jobs?"]
- After career recommendation: [SUGGESTIONS: "How do I prepare for MDCAT?" | "Tell me about scholarships" | "What if I don't get into my first choice?" | "What are the fees?" | "How long is this program?"]

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

@router.get("/analysis/{session_id}")
async def analyze_session(session_id: str, _user: str = Depends(verify_token)):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if not session.history:
        raise HTTPException(status_code=400, detail="No conversation to analyze yet. Please have a chat or voice call with the counsellor first, then try again.")
        
    analysis = await generate_session_analysis(session.history)
    return analysis
