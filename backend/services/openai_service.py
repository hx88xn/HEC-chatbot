import io
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

CHAT_MODEL = "gpt-4o"
TRANSCRIPTION_MODEL = "gpt-4o-transcribe"


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
    )
    return response.strip() if isinstance(response, str) else response.text.strip()


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
