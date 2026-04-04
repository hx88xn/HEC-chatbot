import io
import json
import re
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

CHAT_MODEL = "gpt-4o"
TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
LANGUAGE_CHECK_MODEL = "gpt-4o-mini"

DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")
URDU_SCRIPT_PATTERN = re.compile(r"[\u0600-\u06FF]")


class UnsupportedTranscriptionLanguageError(Exception):
    pass


async def stream_chat_response(messages: list[dict]) -> AsyncIterator[str]:
    stream = await client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        max_tokens=1024,
        stream=True,
        temperature=0.7,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename

    response = await client.audio.transcriptions.create(
        model=TRANSCRIPTION_MODEL,
        file=audio_file,
        response_format="text",
        prompt=(
            "Transcribe only spoken content in English or Urdu. "
            "Do not output Hindi."
        ),
    )
    transcript = response.strip() if isinstance(response, str) else response.text.strip()
    await ensure_transcript_language_allowed(transcript)
    return transcript


async def ensure_transcript_language_allowed(transcript: str) -> None:
    if not transcript:
        return

    # Hindi in Devanagari can be safely blocked without a model call.
    if DEVANAGARI_PATTERN.search(transcript):
        raise UnsupportedTranscriptionLanguageError(
            "Only English and Urdu voice transcription is supported."
        )

    # Pure Urdu script is allowed directly.
    if URDU_SCRIPT_PATTERN.search(transcript):
        return

    language = await classify_transcript_language(transcript)
    if language in {"english", "urdu", "mixed_english_urdu"}:
        return

    raise UnsupportedTranscriptionLanguageError(
        "Only English and Urdu voice transcription is supported."
    )


async def classify_transcript_language(transcript: str) -> str:
    response = await client.chat.completions.create(
        model=LANGUAGE_CHECK_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the transcript language into one label: "
                    "english, urdu, mixed_english_urdu, hindi, or other. "
                    "Return strict JSON: {\"label\":\"<one_label>\"}."
                ),
            },
            {"role": "user", "content": transcript[:2000]},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or ""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return "other"

    label = str(parsed.get("label", "")).strip().lower()
    if label in {"english", "urdu", "mixed_english_urdu", "hindi", "other"}:
        return label
    return "other"


async def call_gpt4o_vision(image_bytes: bytes, prompt: str) -> str:
    import base64

    b64 = base64.b64encode(image_bytes).decode()
    response = await client.chat.completions.create(
        model="gpt-5.4-2026-03-05",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_completion_tokens=1500,
    )
    return response.choices[0].message.content or ""


async def validate_is_marksheet(content: str, source: str = "text") -> bool:
    """Ask GPT whether the extracted content looks like an academic marksheet."""
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a document classifier. Your ONLY job is to determine whether "
                    "the provided content comes from an academic marksheet, transcript, "
                    "grade report, or result card. Answer with ONLY 'yes' or 'no'."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Does the following {source} content come from a student's academic "
                    f"marksheet, transcript, grade sheet, or result card?\n\n{content[:3000]}"
                ),
            },
        ],
        max_tokens=5,
        temperature=0,
    )
    answer = (response.choices[0].message.content or "").strip().lower()
    return answer.startswith("yes")


async def validate_image_is_marksheet(image_bytes: bytes) -> bool:
    """Ask GPT Vision whether the image looks like an academic marksheet."""
    import base64

    b64 = base64.b64encode(image_bytes).decode()
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Is this image an academic marksheet, transcript, grade report, "
                            "or result card? Answer with ONLY 'yes' or 'no'."
                        ),
                    },
                ],
            }
        ],
        max_tokens=5,
        temperature=0,
    )
    answer = (response.choices[0].message.content or "").strip().lower()
    return answer.startswith("yes")


async def summarize_text(text: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes student academic records concisely.",
            },
            {
                "role": "user",
                "content": (
                    f"Summarize this student's academic marksheet in 2-3 sentences. "
                    f"Include: student name (if present), qualification level, key subjects and grades/marks, "
                    f"overall performance level, and institution (if present).\n\n{text}"
                ),
            },
        ],
        max_tokens=200,
    )
    return response.choices[0].message.content or text[:300]


async def generate_session_analysis(history: list[dict]) -> dict:
    # Format the transcript chronologically
    transcript = ""
    for msg in history:
        role = "AGENT" if msg["role"] == "assistant" else "USER"
        # Ignore system messages if any got in
        if role == "USER" and msg["role"] == "system":
            continue
        transcript += f"[{role}]\n{msg['content']}\n\n"

    system_prompt = """
You are a professional quality assurance analyst evaluating a career counseling session between a student (USER) and the PM's Career Counsellor (AGENT).

Read the transcript and evaluate the session across key performance indicators. Return a STRICT JSON object matching the exact structure below. All <score> fields MUST be strings containing percentages (e.g., "85%").

{
  "core_counseling": {
    "intent_recognition_accuracy": "<score>",
    "career_fit_analysis_quality": "<score>",
    "task_completion_rate": "<score>",
    "marksheet_context_utilization": "<score>"
  },
  "conversational_quality": {
    "context_retention": "<score>",
    "tone_appropriateness": "<score>",
    "empathy_score": "<score>",
    "clarity": "<score>"
  },
  "compliance_and_ux": {
    "student_confusion_rate": "<score>",
    "hec_guidelines_adherence": "<score>"
  },
  "summary": "<3-4 line summary of the counseling session highlighting key points and recommendations made>"
}

Return ONLY valid JSON. Do not include markdown formatting like ```json or outside text.
"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Transcript:\n\n{transcript}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    try:
        parsed = json.loads(content)
        return parsed
    except json.JSONDecodeError:
        return {"error": "Failed to parse LLM analysis", "raw": content}
