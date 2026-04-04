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
PAKISTANI_SCRIPT_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")


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
            "Transcribe only spoken content in English, Urdu, Pashto, Sindhi, or Punjabi. "
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
            "Only English, Urdu, Pashto, Sindhi, and Punjabi voice transcription is supported."
        )

    # Pakistani language scripts (Urdu, Pashto, Sindhi, Punjabi) are allowed directly.
    if PAKISTANI_SCRIPT_PATTERN.search(transcript):
        return

    language = await classify_transcript_language(transcript)
    if language in {"english", "urdu", "pashto", "sindhi", "punjabi", "mixed_pakistani"}:
        return

    raise UnsupportedTranscriptionLanguageError(
        "Only English, Urdu, Pashto, Sindhi, and Punjabi voice transcription is supported."
    )


async def classify_transcript_language(transcript: str) -> str:
    response = await client.chat.completions.create(
        model=LANGUAGE_CHECK_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the transcript language into one label: "
                    "english, urdu, pashto, sindhi, punjabi, mixed_pakistani, hindi, or other. "
                    "mixed_pakistani means any mix of English with Urdu/Pashto/Sindhi/Punjabi. "
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
    if label in {"english", "urdu", "pashto", "sindhi", "punjabi", "mixed_pakistani", "mixed_english_urdu", "hindi", "other"}:
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
    turn_count = 0
    for msg in history:
        if msg["role"] == "system":
            continue
        role = "AGENT" if msg["role"] == "assistant" else "STUDENT"
        transcript += f"[{role}]\n{msg['content']}\n\n"
        turn_count += 1

    system_prompt = """You are a supportive educational quality reviewer for the PM Youth Program Career Counsellor Portal. Evaluate the counselling session between a Pakistani Intermediate student (STUDENT) and the AI counsellor (AGENT).

SCORING PHILOSOPHY:
- Be generous and encouraging. This is an AI counsellor doing its best — reward good intent and partial coverage.
- If the counsellor made a reasonable attempt at a topic, give it credit even if it wasn't exhaustive.
- Most scores for a decent session should land in the 65-90% range. Reserve scores below 50% only for topics that were completely absent or clearly wrong.
- A short session (e.g. voice call with few turns) should NOT be penalised for not covering every topic — evaluate what WAS discussed, not what wasn't.
- Give benefit of the doubt: if the counsellor's advice was sensible and contextually appropriate, score it well.

SCORING GUIDE:
- 85-100%: Topic was covered well with good detail
- 70-84%:  Topic was covered adequately
- 55-69%:  Topic was touched on briefly or partially
- 40-54%:  Topic was barely mentioned
- 0-39%:   Topic was completely absent or advice was factually wrong

KPI DESCRIPTIONS (Higher = Better, EXCEPT student_confusion_rate where Lower = Better):

CATEGORY: academic_understanding
  - marksheet_analysis_depth: Did the counsellor reference the student's academic record? Even a brief acknowledgement of marks/grades counts.
  - subject_strength_identification: Did the counsellor note any strong or weak subjects? Doesn't need to be exhaustive — even asking the student about their favourite subjects counts.
  - academic_stream_awareness: Did the counsellor recognise the student's Intermediate group (FSc/ICS/ICom/FA/DAE) and connect it to career options?

CATEGORY: career_guidance_quality
  - career_path_relevance: Were career suggestions reasonable for the student's profile? Even 1-2 good suggestions is adequate.
  - program_knowledge: Did the counsellor mention specific programs or universities in Pakistan? Naming even a couple counts.
  - entry_test_guidance: Did the counsellor mention relevant entry tests (MDCAT, ECAT, NET, etc.)? Just naming the right test for the path is sufficient.
  - scholarship_financial_guidance: Any mention of scholarships, fees, or financial options counts. This is a bonus topic — don't penalise heavily if not discussed, score 50-60% if not raised.
  - merit_cutoff_awareness: Any mention of competition, merit, or admission difficulty counts. This is also a bonus topic — score 50-60% if not raised.

CATEGORY: student_engagement
  - question_quality: Did the counsellor ask questions to understand the student? Even basic questions like "what are your interests?" are good.
  - personalization: Did the counsellor tailor advice to this student rather than giving fully generic responses?
  - empathy_and_encouragement: Was the tone warm and supportive? Any encouragement or reassurance counts.
  - clarity_of_communication: Was the counsellor easy to understand? If the student didn't seem confused, score this high.

CATEGORY: career_recommendation
  - specific_career_suggested: Did the counsellor explicitly recommend a specific career or field (e.g. "you should pursue software engineering" or "medicine is a great fit for you")? A clear, named career recommendation scores 80%+. Vague advice like "explore your options" scores below 40%.
  - reasoning_quality: Was the career recommendation tied to the student's actual profile — their marks, interests, stream, or aspirations? Well-reasoned = 80%+. Generic = 40-60%.
  - actionable_next_steps: Did the counsellor provide concrete next steps for the recommended career (e.g. specific universities, entry tests, preparation timeline)? Even 1-2 actionable items scores 70%+.

CATEGORY: compliance_and_completeness
  - student_confusion_rate (LOWER IS BETTER): What percentage of the student's responses showed confusion? If the conversation flowed naturally, score 0-10%.
  - hec_guidelines_adherence: Was the advice aligned with Pakistani education norms? If nothing was factually wrong, score 75%+.
  - session_completeness: How many key areas were touched: [1] academic background [2] interests [3] strengths [4] career paths [5] programs/universities [6] entry tests [7] financial info [8] next steps. Score proportionally — covering 4-5 of 8 areas in a short session is fine (65-75%).

OUTPUT FORMAT:

Return a STRICT JSON object. Every score field must be a string containing ONLY a percentage (e.g., "78%").

{
  "academic_understanding": {
    "marksheet_analysis_depth": "<score>",
    "subject_strength_identification": "<score>",
    "academic_stream_awareness": "<score>"
  },
  "career_guidance_quality": {
    "career_path_relevance": "<score>",
    "program_knowledge": "<score>",
    "entry_test_guidance": "<score>",
    "scholarship_financial_guidance": "<score>",
    "merit_cutoff_awareness": "<score>"
  },
  "student_engagement": {
    "question_quality": "<score>",
    "personalization": "<score>",
    "empathy_and_encouragement": "<score>",
    "clarity_of_communication": "<score>"
  },
  "career_recommendation": {
    "specific_career_suggested": "<score>",
    "reasoning_quality": "<score>",
    "actionable_next_steps": "<score>"
  },
  "compliance_and_completeness": {
    "student_confusion_rate": "<score>",
    "hec_guidelines_adherence": "<score>",
    "session_completeness": "<score>"
  },
  "summary": "<3-4 sentence summary: who the student is, what was discussed, career paths recommended, and overall session quality>"
}

Return ONLY valid JSON. No markdown, no commentary outside the JSON."""

    response = await client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Total exchanges in session: {turn_count}\n\n"
                    f"Transcript:\n\n{transcript}"
                ),
            },
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
