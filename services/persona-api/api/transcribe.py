"""
Voice → text via Groq's Whisper-Large-v3 endpoint.

The web composer records audio with MediaRecorder, POSTs the resulting
blob here, and we forward it to Groq's OpenAI-compatible
`/audio/transcriptions` endpoint. Groq's free tier covers the volumes
we care about (~14,400 seconds of audio per day per key as of this
writing), so this replaces the flaky in-browser SpeechRecognition path
without adding a paid dependency.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
from api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Browsers ship audio as webm/opus on Chrome, mp4/aac on Safari. Groq accepts
# both — we just pass whatever the MediaRecorder gave us through, but cap the
# upload size so a stuck "stop" button can't drown the backend in a giant blob.
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — matches OpenAI's Whisper limit


@router.post("/")
async def transcribe(
    file: UploadFile = File(...),
    _user: dict = Depends(get_current_user),
):
    if not config.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Voice transcription isn't configured — set GROQ_API_KEY.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio too large ({len(data)} bytes). Max is {MAX_AUDIO_BYTES}.",
        )

    # Groq uses OpenAI's audio/transcriptions multipart contract. The
    # `file` part is the binary, `model` is the whisper variant.
    files = {
        "file": (file.filename or "audio.webm", data, file.content_type or "audio/webm"),
    }
    form = {
        "model": config.GROQ_WHISPER_MODEL,
        "response_format": "json",
        "temperature": "0",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                files=files,
                data=form,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Transcription timed out.")
    except Exception as e:
        logger.exception("Groq transcribe call failed")
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    if resp.status_code >= 400:
        # Surface Groq's own error JSON when possible — it's usually informative
        # (rate limit hint, model name typo, unsupported audio format, etc.).
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text[:500]}
        logger.warning("Groq returned %s: %s", resp.status_code, payload)
        raise HTTPException(status_code=resp.status_code, detail=payload)

    body = resp.json() or {}
    text = (body.get("text") or "").strip()
    return {"text": text}
