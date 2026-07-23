"""
Video ingestion for ragleap-rag. Extracts the audio track from a video
file using ffmpeg, then hands it to the existing TranscriptionService
- no separate video-transcription logic, video ingestion is audio
ingestion plus an extraction step. Requires the ffmpeg binary
installed on the system (not pip-installable, same class of
dependency as Tesseract for OCR).
"""
import logging
import subprocess
import tempfile
import os

logger = logging.getLogger(__name__)


def extract_audio_from_video(raw_bytes: bytes, video_filename: str) -> bytes:
    """
    Extract the audio track from video bytes as MP3, using ffmpeg.
    Returns the extracted audio as bytes. Raises ValueError with a
    clear message if ffmpeg is not installed or extraction fails.
    """
    suffix = "." + video_filename.rsplit(".", 1)[-1] if "." in video_filename else ".mp4"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as video_file:
        video_file.write(raw_bytes)
        video_path = video_file.name

    audio_path = video_path + ".mp3"

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", audio_path],
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError as e:
        os.unlink(video_path)
        raise ValueError(
            "ffmpeg is required for video ingestion but is not installed on this system. "
            "Install it (e.g. 'apt install ffmpeg' on Debian/Ubuntu)."
        ) from e
    except subprocess.TimeoutExpired as e:
        os.unlink(video_path)
        raise ValueError("ffmpeg audio extraction timed out (video may be too long or corrupt).") from e

    try:
        if result.returncode != 0:
            raise ValueError(f"ffmpeg audio extraction failed: {result.stderr[-500:]}")

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            raise ValueError("ffmpeg produced no audio output — the video may have no audio track.")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        return audio_bytes
    finally:
        os.unlink(video_path)
        if os.path.exists(audio_path):
            os.unlink(audio_path)
