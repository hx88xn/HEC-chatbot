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
    turn_count = 0
    for msg in history:
        if msg["role"] == "system":
            continue
        role = "AGENT" if msg["role"] == "assistant" else "STUDENT"
        transcript += f"[{role}]\n{msg['content']}\n\n"
        turn_count += 1

    system_prompt = """You are a senior educational quality assurance evaluator for HEC Pakistan's AI Career Counsellor programme. You must evaluate a counselling session transcript between a Pakistani Intermediate student (STUDENT) and the AI counsellor (AGENT).

IMPORTANT EVALUATION RULES:
- You MUST justify every score with concrete evidence from the transcript. If something was NOT discussed, the score for that KPI must be low — do not assume or infer.
- Scores must reflect what ACTUALLY happened in the conversation, not what could have happened.
- If the session was too short for the counsellor to cover a topic, score it low — incomplete sessions should not receive high marks.
- Use the FULL 0-100 range. Not everything is 70-90. A missing topic is 0-20. A partially covered topic is 30-60. A thoroughly covered topic is 70-90. Only truly exceptional, textbook-quality coverage earns 90+.

STEP-BY-STEP PROCESS (you must follow this internally before producing scores):

1. READ the entire transcript carefully.
2. For EACH KPI below, find the specific lines or exchanges that are relevant.
3. If you find NO evidence for a KPI in the transcript, score it 0-15%.
4. If the topic was MENTIONED but not explored, score it 20-45%.
5. If the topic was DISCUSSED with reasonable depth, score it 50-75%.
6. If the topic was covered THOROUGHLY with specific, accurate, personalised detail, score it 76-95%.

──────────────────────────────────────────────────
KPI RUBRICS (Higher = Better, EXCEPT student_confusion_rate where Lower = Better)
──────────────────────────────────────────────────

CATEGORY: academic_understanding

  marksheet_analysis_depth
    0-20%:  Counsellor did not reference the student's marks, grades, or academic record at all.
    21-50%: Counsellor mentioned the marksheet exists but gave only a generic acknowledgement (e.g., "I can see your results").
    51-75%: Counsellor referenced specific subjects or overall marks/percentage from the marksheet.
    76-100%: Counsellor broke down individual subject scores, identified patterns (e.g., strong in Biology, weak in Maths), and used these specifics to shape advice.

  subject_strength_identification
    0-20%:  No mention of which subjects the student is strong or weak in.
    21-50%: Vague references like "you seem to do well in science" without citing evidence.
    51-75%: Identified at least 1-2 strong/weak subjects with reference to marks or student input.
    76-100%: Clear, evidence-backed identification of multiple strengths and weaknesses, tied to career implications (e.g., "Your 85 in Physics and 90 in Maths make engineering a strong fit, but the 55 in English may need work for CSS/law paths").

  academic_stream_awareness
    0-20%:  Counsellor did not identify or ask about the student's Intermediate group.
    21-50%: Mentioned the group name (FSc, ICS, etc.) but did not discuss its career implications.
    51-75%: Correctly identified the stream and discussed some career paths tied to it.
    76-100%: Deep understanding of the stream — discussed which degrees it qualifies for, which it does NOT, bridging options (e.g., FSc Pre-Med student wanting to do CS), and relevant entry test requirements for that stream.

CATEGORY: career_guidance_quality

  career_path_relevance
    0-20%:  No career paths were recommended, or recommendations were completely disconnected from the student's profile.
    21-50%: Generic career paths mentioned (e.g., "doctor, engineer, business") without connecting to the student's specific marks, interests, or constraints.
    51-75%: 1-2 relevant career paths recommended with some reasoning tied to the student's profile.
    76-100%: 2-3+ specific career paths recommended, each with clear reasoning tied to the student's marks, stated interests, work-style preferences, and constraints. Alternatives discussed.

  program_knowledge
    0-20%:  No specific programs or universities mentioned.
    21-50%: Named a few fields (e.g., "MBBS", "Software Engineering") without specifying where to study.
    51-75%: Mentioned specific programs AND at least 1-2 Pakistani universities or institutions.
    76-100%: Detailed knowledge of multiple HEC-recognised programmes and universities, including public vs. private options, regional availability, and program-specific details (duration, specialisations).

  entry_test_guidance
    0-20%:  No entry tests mentioned at all.
    21-50%: Entry test names dropped (e.g., "you'll need MDCAT") without preparation guidance.
    51-75%: Correct entry tests identified for the recommended paths with basic preparation info.
    76-100%: Thorough guidance — correct tests for each path, registration timelines, preparation strategies, resources, and what scores to aim for.

  scholarship_financial_guidance
    0-20%:  No mention of financial considerations or scholarships.
    21-50%: Brief generic mention (e.g., "there are scholarships available").
    51-75%: Named at least 1-2 specific scholarship programs (HEC Need-Based, PEEF, provincial) or discussed cost differences (public vs. private).
    76-100%: Detailed discussion of multiple financial options — specific scholarship names, eligibility criteria, public vs. private cost comparison, fee waivers, and how to apply.

  merit_cutoff_awareness
    0-20%:  No mention of merit, admission competitiveness, or cut-offs.
    21-50%: Vague references like "it's competitive" without specifics.
    51-75%: Mentioned realistic merit ranges or competitiveness for at least 1 program.
    76-100%: Specific, accurate merit/aggregate information for recommended programs, with awareness of how the student's marks compare, and backup plan if they fall short.

CATEGORY: student_engagement

  question_quality
    0-20%:  Counsellor asked no questions or dumped multiple questions at once repeatedly.
    21-50%: Asked some questions but they were generic (e.g., "what are your interests?") or stacked multiple questions together.
    51-75%: Asked focused, one-at-a-time questions that were mostly relevant.
    76-100%: Asked targeted, probing questions one at a time — each building on the student's previous answer, exploring interests, constraints, and goals systematically.

  personalization
    0-20%:  Advice was entirely generic and could apply to any student.
    21-50%: Some attempt to personalise but mostly template-like responses.
    51-75%: Recommendations clearly referenced the student's specific situation (marks, interests, constraints) in multiple places.
    76-100%: Deeply personalised — every recommendation explicitly tied back to what THIS student said, with specific details from their marksheet and conversation woven throughout.

  empathy_and_encouragement
    0-20%:  Cold, robotic, or dismissive tone.
    21-50%: Polite but impersonal; no emotional acknowledgement.
    51-75%: Warm tone, acknowledged the student's feelings or concerns at least once, offered encouragement.
    76-100%: Consistently empathetic — reassured anxious students, validated concerns, celebrated strengths, acknowledged constraints with cultural sensitivity, and maintained an encouraging tone throughout.

  clarity_of_communication
    0-20%:  Confusing, jargon-heavy, or disorganised responses.
    21-50%: Mostly understandable but some unclear explanations or unnecessary jargon.
    51-75%: Clear communication with minimal jargon; student did not seem confused.
    76-100%: Exceptionally clear — simple language, well-structured responses, complex topics explained accessibly, no ambiguity.

CATEGORY: compliance_and_completeness

  student_confusion_rate (LOWER IS BETTER)
    Count the number of exchanges where the student expressed confusion, asked for clarification, misunderstood the counsellor, or gave an irrelevant response suggesting they didn't follow.
    Formula: (confused exchanges / total student exchanges) * 100, rounded to nearest integer.
    If the student never seemed confused: 0-5%.
    If confused once or twice in a long session: 10-20%.
    If frequently confused: 30%+.

  hec_guidelines_adherence
    0-20%:  Counsellor gave advice that contradicts HEC norms (e.g., recommending unrecognised institutions, incorrect test requirements).
    21-50%: No obvious errors but advice was too generic to evaluate HEC alignment.
    51-75%: Advice aligned with HEC standards — recommended recognised institutions, correct entry tests, valid pathways.
    76-100%: Strong adherence — mentioned HEC recognition explicitly, correct post-Intermediate pathways per Pakistani education system, accurate entry test and eligibility information.

  session_completeness
    Evaluate whether the session covered ALL of these areas (score proportionally):
    [1] Student's academic background / stream  [2] Interests and passions  [3] Strengths and weaknesses
    [4] Career path recommendations  [5] Specific programs / universities  [6] Entry test requirements
    [7] Financial / scholarship info  [8] Next steps and timeline
    0-25%:  Covered 0-2 areas.  26-50%:  Covered 3-4 areas.  51-75%:  Covered 5-6 areas.  76-100%: Covered 7-8 areas.

──────────────────────────────────────────────────
OUTPUT FORMAT
──────────────────────────────────────────────────

Return a STRICT JSON object. Every score field must be a string containing ONLY a percentage (e.g., "72%"). Do NOT include the rubric text in the score value.

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
  "compliance_and_completeness": {
    "student_confusion_rate": "<score>",
    "hec_guidelines_adherence": "<score>",
    "session_completeness": "<score>"
  },
  "summary": "<3-4 sentence summary: who the student is (stream, marks), what career paths were recommended, key strengths and gaps of the counselling session, overall quality verdict>"
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
