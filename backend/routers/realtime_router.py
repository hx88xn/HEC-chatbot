import asyncio
import audioop
import base64
import json
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import session_store
from auth import verify_token_raw
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

VOICE_SYSTEM_PROMPT = """You are a female professional career counsellor working for the Higher Education Commission (HEC) of Pakistan, conducting a live voice call with a student. You are a woman — use female pronouns and identity when referring to yourself (e.g. "I'm your counsellor, and I'm here to help you"). Your voice is female. Your role is to guide Pakistani Intermediate (FSc/ICS/ICom/FA/DAE) students toward suitable career paths based on their academic background, personal interests, aptitudes, and aspirations.

Your target audience: Pakistani students who have completed or are completing their Intermediate education (11th/12th grade) and are deciding what to pursue next — whether it's a bachelor's degree, professional program, vocational training, or other post-Intermediate pathway.

Your approach:
1. Start by warmly greeting the student and briefly acknowledging their uploaded academic results (Intermediate marksheet). Mention key details you can see from their results.
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
9. Since this is a voice call, keep your responses conversational and natural. Avoid using bullet points or numbered lists — speak naturally as you would in a real conversation.
10. Keep responses concise for voice — aim for 2-4 sentences per turn unless giving final career recommendations.
11. LANGUAGE: You MUST only speak in English or Urdu. If the student speaks in Urdu or Roman Urdu, you may respond in the same. Do NOT use Hindi, Arabic, or any other language. Default to English unless the student initiates in Urdu.
12. INTERRUPTION: If the student starts speaking while you are talking, stop immediately, listen to them fully, then respond to what they said. Never talk over the student.

Student's academic record from uploaded marksheet:
{marksheet_context}"""

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"


@router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket):
    await websocket.accept()

    # ── Step 1: Wait for "start" event with session_id + JWT ──
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        data = json.loads(raw)
    except Exception:
        await websocket.close(code=4000, reason="Expected start event")
        return

    if data.get("event") != "start":
        await websocket.close(code=4000, reason="First message must be start event")
        return

    start_params = data.get("start", {})
    token = start_params.get("token")
    session_id = start_params.get("session_id")

    # Verify JWT
    try:
        verify_token_raw(token)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Verify session exists with marksheet
    session = session_store.get(session_id)
    if not session or not session.marksheet_text:
        await websocket.close(code=4004, reason="Session not found or no marksheet")
        return

    marksheet_context = (
        session.marksheet_summary
        or session.marksheet_text
        or "Not provided — ask the student about their academic background."
    )
    instructions = VOICE_SYSTEM_PROMPT.format(marksheet_context=marksheet_context)

    # ── Step 2: Connect to OpenAI Realtime API via WebSocket ──
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(
            OPENAI_REALTIME_URL, extra_headers=headers
        ) as openai_ws:
            # ── Step 3: Initialize session ──
            session_update = {
                "type": "session.update",
                "session": {
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 800,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "voice": "sage",
                    "instructions": instructions,
                    "modalities": ["text", "audio"],
                    "temperature": 0.7,
                    "input_audio_transcription": {
                        "model": "gpt-4o-transcribe",
                        "language": "en",
                        "prompt": "Transcribe the student's speech in English or Urdu (Roman Urdu). This is a Pakistani student discussing career counselling, university admissions, MDCAT, ECAT, FSc, ICS, ICom, HEC.",
                    },
                },
            }
            await openai_ws.send(json.dumps(session_update))

            # Send initial greeting trigger
            initial_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Hello, I have uploaded my marksheet. "
                                "Please greet me warmly and start the career counselling session."
                            ),
                        }
                    ],
                },
            }
            await openai_ws.send(json.dumps(initial_item))
            await openai_ws.send(json.dumps({"type": "response.create"}))

            # Notify frontend that session is ready
            await websocket.send_json({"event": "session_ready"})

            # ── Step 4: Bidirectional relay ──
            # Collect transcripts so we can save them to session history
            voice_transcripts: list[dict] = []

            async def frontend_to_openai():
                """Relay audio from browser → OpenAI."""
                try:
                    async for msg in websocket.iter_text():
                        data = json.loads(msg)

                        if data.get("event") == "media":
                            pcm_b64 = data["media"]["payload"]
                            pcm_bytes = base64.b64decode(pcm_b64)
                            # Convert PCM16 → mu-law for OpenAI
                            mulaw_bytes = audioop.lin2ulaw(pcm_bytes, 2)
                            await openai_ws.send(
                                json.dumps(
                                    {
                                        "type": "input_audio_buffer.append",
                                        "audio": base64.b64encode(mulaw_bytes).decode(),
                                    }
                                )
                            )

                        elif data.get("event") == "stop":
                            break
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.error("frontend_to_openai error: %s", e)

            async def openai_to_frontend():
                """Relay audio + events from OpenAI → browser."""
                try:
                    async for msg in openai_ws:
                        response = json.loads(msg)
                        rtype = response.get("type", "")

                        # ── User started speaking → clear browser audio queue ──
                        if rtype == "input_audio_buffer.speech_started":
                            await websocket.send_json({"event": "clear"})
                            continue

                        if rtype == "response.audio.delta" and "delta" in response:
                            # Convert mu-law → PCM16 for browser playback
                            mulaw_bytes = base64.b64decode(response["delta"])
                            try:
                                pcm = audioop.ulaw2lin(mulaw_bytes, 2)
                            except Exception:
                                pcm = mulaw_bytes
                            pcm_b64 = base64.b64encode(pcm).decode()
                            await websocket.send_json(
                                {
                                    "event": "media",
                                    "media": {"payload": pcm_b64},
                                }
                            )

                        elif rtype == "response.audio_transcript.delta":
                            await websocket.send_json(
                                {
                                    "event": "transcript_delta",
                                    "role": "assistant",
                                    "delta": response.get("delta", ""),
                                }
                            )

                        elif rtype == "response.audio_transcript.done":
                            transcript = response.get("transcript", "")
                            if transcript:
                                voice_transcripts.append(
                                    {"role": "assistant", "content": transcript}
                                )
                            await websocket.send_json(
                                {
                                    "event": "transcript_done",
                                    "role": "assistant",
                                    "transcript": transcript,
                                }
                            )

                        elif (
                            rtype
                            == "conversation.item.input_audio_transcription.completed"
                        ):
                            transcript = response.get("transcript", "")
                            if transcript:
                                voice_transcripts.append(
                                    {"role": "user", "content": transcript}
                                )
                            await websocket.send_json(
                                {
                                    "event": "transcript_done",
                                    "role": "user",
                                    "transcript": transcript,
                                }
                            )

                        elif rtype == "error":
                            await websocket.send_json(
                                {
                                    "event": "error",
                                    "message": response.get("error", {}).get(
                                        "message", "Unknown error"
                                    ),
                                }
                            )

                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error("openai_to_frontend error: %s", e)

            await asyncio.gather(
                frontend_to_openai(),
                openai_to_frontend(),
                return_exceptions=True,
            )

            # Save voice transcripts into session history for analysis
            for entry in voice_transcripts:
                session_store.append_history(
                    session_id, entry["role"], entry["content"]
                )

    except Exception as e:
        logger.error("Realtime WS error: %s", e)
        try:
            await websocket.send_json(
                {"event": "error", "message": "Failed to connect to voice service"}
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
