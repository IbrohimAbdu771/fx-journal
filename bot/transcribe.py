"""Voice transcription via Yandex SpeechKit (reused from the Worka project).

Telegram voice messages are OGG/OPUS, which SpeechKit accepts natively as
`oggopus` — so no ffmpeg conversion is needed.

Uses the v1 short-audio endpoint (audio up to ~30s / 1 MB), which is plenty for
quick trade notes. Longer clips raise a clear error asking to split the message.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
MAX_BYTES = 1_000_000  # v1 short-audio hard limit


class TranscriptionError(RuntimeError):
    pass


async def transcribe_ogg(
    audio: bytes,
    api_key: str,
    lang: str = "ru-RU",
    *,
    timeout: float = 30.0,
) -> str:
    """Transcribe OGG/OPUS audio bytes to text. Returns "" if nothing recognized."""
    if not audio:
        raise TranscriptionError("Пустой аудиофайл")
    if len(audio) > MAX_BYTES:
        raise TranscriptionError(
            "Голосовое слишком длинное для распознавания (>1 МБ / ~30 сек). "
            "Запиши покороче или напиши текстом."
        )

    # v1 has no true auto-detect; fall back to ru-RU.
    stt_lang = "ru-RU" if lang.lower() == "auto" else lang
    params = {
        "topic": "general",
        "lang": stt_lang,
        "format": "oggopus",
    }
    headers = {"Authorization": f"Api-Key {api_key}"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(STT_URL, params=params, headers=headers, content=audio)

    if resp.status_code != 200:
        logger.error("SpeechKit error %s: %s", resp.status_code, resp.text[:300])
        raise TranscriptionError(
            f"Ошибка распознавания речи (SpeechKit {resp.status_code})"
        )

    data = resp.json()
    text = (data.get("result") or "").strip()
    logger.info("Transcribed %d bytes -> %d chars", len(audio), len(text))
    return text
