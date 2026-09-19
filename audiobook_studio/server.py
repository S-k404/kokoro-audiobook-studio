"""
Native macOS Kokoro TTS Server — OpenAI-compatible /v1/audio/speech endpoint.

Uses PyTorch with Apple Metal Performance Shaders (MPS) for 100% GPU acceleration,
eliminating CPU overload and cooling system temperatures.
Listens on 127.0.0.1:8001 by default. The API has no authentication, so do not
bind it to a public interface unless it sits behind your own auth/firewall.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from pathlib import Path
from typing import Generator, Literal

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("kokoro-native")

BASE_DIR = Path(__file__).parent.resolve()

# ---------------------------------------------------------------------------
# Supported voices
# ---------------------------------------------------------------------------
SUPPORTED_VOICES: dict[str, str] = {
    # American Female
    "af_heart":   "af_heart",
    "af_bella":   "af_bella",
    "af_sky":     "af_sky",
    "af_nicole":  "af_nicole",
    "af_sarah":   "af_sarah",
    "af_alloy":   "af_alloy",
    "af_aoede":   "af_aoede",
    "af_jessica": "af_jessica",
    "af_river":   "af_river",
    "af_kore":    "af_kore",
    # American Male
    "am_adam":    "am_adam",
    "am_michael": "am_michael",
    "am_echo":    "am_echo",
    "am_eric":    "am_eric",
    "am_fenrir":  "am_fenrir",
    "am_liam":    "am_liam",
    "am_onyx":    "am_onyx",
    "am_puck":    "am_puck",
    "am_santa":   "am_santa",
    # British Female
    "bf_emma":     "bf_emma",
    "bf_alice":    "bf_alice",
    "bf_isabella": "bf_isabella",
    "bf_lily":     "bf_lily",
    # British Male
    "bm_george":  "bm_george",
    "bm_daniel":  "bm_daniel",
    "bm_fable":   "bm_fable",
    "bm_lewis":   "bm_lewis",
    # Short aliases
    "heart":    "af_heart",
    "bella":    "af_bella",
    "sky":      "af_sky",
    "nicole":   "af_nicole",
    "sarah":    "af_sarah",
    "alloy":    "af_alloy",
    "aoede":    "af_aoede",
    "jessica":  "af_jessica",
    "river":    "af_river",
    "kore":     "af_kore",
    "adam":     "am_adam",
    "michael":  "am_michael",
    "echo":     "am_echo",
    "eric":     "am_eric",
    "fenrir":   "am_fenrir",
    "liam":     "am_liam",
    "onyx":     "am_onyx",
    "puck":     "am_puck",
    "santa":    "am_santa",
    "emma":     "bf_emma",
    "alice":    "bf_alice",
    "isabella": "bf_isabella",
    "lily":     "bf_lily",
    "george":   "bm_george",
    "daniel":   "bm_daniel",
    "fable":    "bm_fable",
    "lewis":    "bm_lewis",
}

DEFAULT_VOICE = "af_heart"
SAMPLE_RATE   = 24_000
MAX_INPUT_CHARS = int(os.getenv("KOKORO_MAX_INPUT_CHARS", "20000"))

# ---------------------------------------------------------------------------
# Lazy globals
# ---------------------------------------------------------------------------
_pipelines: dict[str, object] = {}  # Kokoro lang_code -> KPipeline (voice prefix a=American, b=British)
_device = "cpu"
_gpu_lock = threading.Lock()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Kokoro Native TTS (Metal GPU)",
    description="OpenAI-compatible TTS endpoint powered by PyTorch Metal MPS on Apple Silicon",
    version="1.0.0",
)


def _pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_pipeline(voice: str):
    """Return the pipeline for the voice's language, sharing one loaded model across languages."""
    lang = voice[0]
    if lang not in _pipelines:
        from kokoro import KPipeline
        base = next(iter(_pipelines.values()))
        _pipelines[lang] = KPipeline(lang_code=lang, model=base.model, device=_device)
    return _pipelines[lang]


@app.on_event("startup")
async def load_model() -> None:
    """Load the Kokoro model onto the best available device (Metal MPS > CUDA > CPU)."""
    global _device

    t0 = time.perf_counter()
    _device = _pick_device()
    if _device == "mps":
        log.info("🚀 Apple Metal GPU (MPS) is AVAILABLE — loading Kokoro directly onto GPU...")
    else:
        log.warning("⚠️  Metal MPS not available — running on %s (slower)", _device.upper())

    from kokoro import KPipeline
    _pipelines["a"] = KPipeline(lang_code="a", device=_device)

    # Warmup with single word to precompile Metal shader kernels
    try:
        log.info("Warming up GPU kernels...")
        for _ in _pipelines["a"]("warmup", voice="af_heart", speed=1.0):
            pass
    except Exception as e:
        log.warning("Warmup note: %s", e)

    elapsed = time.perf_counter() - t0
    log.info("✅ Kokoro loaded on %s in %.2f s.", _device.upper(), elapsed)


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class SpeechRequest(BaseModel):
    model: str = Field(default="kokoro")
    input: str = Field(..., max_length=MAX_INPUT_CHARS, description="Text to synthesize")
    voice: str = Field(default=DEFAULT_VOICE)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = Field(
        default="mp3"
    )


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm_int16 = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


def _wav_bytes_to_mp3(wav_bytes: bytes) -> bytes:
    """Convert WAV → MP3 using lameenc (fast, pure-python) with pydub fallback."""
    try:
        import lameenc
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf) as wf:
            n_channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(sample_rate)
        encoder.set_channels(n_channels)
        encoder.set_quality(5)  # fast quality
        return bytes(encoder.encode(raw) + encoder.flush())
    except Exception:
        from pydub import AudioSegment
        seg = AudioSegment.from_wav(io.BytesIO(wav_bytes))
        out = io.BytesIO()
        seg.export(out, format="mp3", bitrate="128k")
        return out.getvalue()


def _pcm_to_format(pcm: np.ndarray, fmt: str, sample_rate: int = SAMPLE_RATE) -> bytes:
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate)
    if fmt == "wav":
        return wav_bytes
    elif fmt == "mp3":
        return _wav_bytes_to_mp3(wav_bytes)
    elif fmt == "pcm":
        return (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    else:
        buf = io.BytesIO()
        sf_fmt = {"flac": "flac", "opus": "ogg", "aac": "flac"}.get(fmt, "wav")
        sf.write(buf, pcm, sample_rate, format=sf_fmt, subtype="PCM_16")
        return buf.getvalue()


def _mime_type(fmt: str) -> str:
    return {
        "mp3":  "audio/mpeg",
        "wav":  "audio/wav",
        "pcm":  "audio/pcm",
        "opus": "audio/ogg",
        "flac": "audio/flac",
        "aac":  "audio/aac",
    }.get(fmt, "audio/mpeg")


# ---------------------------------------------------------------------------
# Synthesis generator — streams chunks directly from Metal GPU
# ---------------------------------------------------------------------------

def _synthesize_stream(
    text: str, voice: str, speed: float, fmt: str
) -> Generator[bytes, None, None]:
    # Lock GPU access per request to prevent competing kernel dispatches
    with _gpu_lock:
        try:
            generator = _get_pipeline(voice)(text, voice=voice, speed=speed)
            for _, _, audio_tensor in generator:
                if audio_tensor is None or len(audio_tensor) == 0:
                    continue
                if isinstance(audio_tensor, torch.Tensor):
                    pcm = audio_tensor.cpu().numpy()
                else:
                    pcm = np.array(audio_tensor, dtype=np.float32)
                yield _pcm_to_format(pcm, fmt, sample_rate=SAMPLE_RATE)
        except Exception:
            # Re-raise so the chunked response is aborted and the client sees a failure
            # (and retries) instead of receiving silently truncated audio.
            log.exception("Synthesis error")
            raise


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "backend": "pytorch-metal-mps",
        "device": _device,
    })


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    canonical_voices = [v for v in SUPPORTED_VOICES if "_" in v]
    models = [
        {"id": v, "object": "model", "created": 1_700_000_000, "owned_by": "kokoro-metal"}
        for v in ["kokoro"] + canonical_voices
    ]
    return JSONResponse({"object": "list", "data": models})


@app.post("/v1/audio/speech")
async def text_to_speech(req: SpeechRequest) -> StreamingResponse:
    if not _pipelines:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    # Only known voices: an arbitrary string could make Kokoro load an arbitrary local .pt file.
    voice_id = SUPPORTED_VOICES.get(req.voice.strip().lower())
    if voice_id is None:
        raise HTTPException(status_code=400, detail=f"unknown voice {req.voice!r}; see GET /v1/models")
    text = req.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="input text is empty")

    log.info("TTS [Metal MPS] | voice=%s speed=%.2f fmt=%s len=%d chars",
             voice_id, req.speed, req.response_format, len(text))

    fmt = req.response_format
    return StreamingResponse(
        _synthesize_stream(text, voice_id, req.speed, fmt),
        media_type=_mime_type(fmt),
        headers={
            "X-Kokoro-Voice": voice_id,
            "X-Kokoro-Speed": str(req.speed),
            "X-Kokoro-Device": _device,
            "Transfer-Encoding": "chunked",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "audiobook_studio.server:app",
        host=os.getenv("KOKORO_HOST", "127.0.0.1"),
        port=int(os.getenv("KOKORO_PORT", "8001")),
        workers=1,
    )
