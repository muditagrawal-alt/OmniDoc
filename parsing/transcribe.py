"""
Speech to text for audio and video uploads, with segment timestamps.

Uses, in order: Groq's free Whisper API (``GROQ_API_KEY``; whisper-large-v3-turbo), any
OpenAI-compatible endpoint set in ``OMNIDOC_WHISPER_BASE_URL``, or a local faster-whisper
model when the package is installed. Video files and recordings larger than the API limit
are first converted to compact mono audio with ffmpeg when it is available.
"""
import os
import shutil
import logging
import subprocess
import tempfile
from typing import Any, Dict, List

logger = logging.getLogger("OmniDoc.Transcribe")

API_LIMIT_BYTES = 24 * 1024 * 1024
WHISPER_MODEL = os.getenv("OMNIDOC_WHISPER_MODEL", "whisper-large-v3-turbo")


class TranscriptionUnavailable(Exception):
    pass


def _compact_audio(path: str) -> str:
    """Mono 16 kHz 48 kbit/s MP3 copy of a recording (needs ffmpeg)."""
    if not shutil.which("ffmpeg"):
        raise TranscriptionUnavailable("This recording is too large for the API; install ffmpeg to compress it.")
    out = os.path.join(tempfile.mkdtemp(prefix="omnidoc-audio-"), "audio.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out],
                   check=True, timeout=900)
    return out


def _segments(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    segs = [{"start": float(s.get("start", 0)), "end": float(s.get("end", 0)), "text": str(s.get("text", ""))}
            for s in data.get("segments") or [] if str(s.get("text", "")).strip()]
    if not segs and data.get("text"):
        segs = [{"start": 0.0, "end": float(data.get("duration") or 0), "text": data["text"]}]
    return segs


def transcribe(path: str) -> Dict[str, Any]:
    """{"segments": [{start, end, text}], "language", "duration", "engine"}; raises TranscriptionUnavailable."""
    from agents.llm_providers import REGISTRY, Provider, openai_transcribe
    ext = os.path.splitext(path)[1].lower()
    groq = REGISTRY.get("groq")
    custom_url = os.getenv("OMNIDOC_WHISPER_BASE_URL", "").strip()
    api = None
    if groq is not None and groq.configured:
        api = groq
    elif custom_url:
        api = Provider(name="whisper", label="Whisper API", base_url=custom_url.rstrip("/"),
                       key_env="OMNIDOC_WHISPER_API_KEY", model=WHISPER_MODEL, fast_model=WHISPER_MODEL)
    if api is not None:
        upload = path
        if ext in (".mp4", ".mov", ".mpeg") or os.path.getsize(path) > API_LIMIT_BYTES:
            upload = _compact_audio(path)
        data = openai_transcribe(api, os.getenv("OMNIDOC_WHISPER_MODEL", WHISPER_MODEL), upload)
        return {"segments": _segments(data), "language": data.get("language"), "duration": data.get("duration"),
                "engine": f"{api.label} {WHISPER_MODEL}"}
    try:
        from faster_whisper import WhisperModel  # optional local engine
    except ImportError:
        raise TranscriptionUnavailable(
            "Transcribing recordings needs a free GROQ_API_KEY in .env (Whisper), or `pip install faster-whisper`.")
    size = os.getenv("OMNIDOC_LOCAL_WHISPER", "small")
    model = WhisperModel(size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(path, vad_filter=True)
    segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    return {"segments": segs, "language": info.language, "duration": info.duration, "engine": f"faster-whisper {size}"}
