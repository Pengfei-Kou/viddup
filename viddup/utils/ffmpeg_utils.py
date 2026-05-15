"""
Thin subprocess wrappers around ffprobe and ffmpeg.

No ffmpeg-python dependency — direct subprocess calls are simpler,
more portable, and easier to debug.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _hw_accel_flags() -> list[str]:
    """
    Return ffmpeg hardware acceleration flags for the current platform.

    On macOS, enables VideoToolbox which uses the GPU/Apple Silicon video
    decoder.  Falls back gracefully if the codec is unsupported.
    """
    if sys.platform == "darwin":
        return ["-hwaccel", "videotoolbox"]
    return []


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return the result."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_ffmpeg() -> tuple[bool, str]:
    """
    Check that both ffmpeg and ffprobe are available on PATH.

    Returns:
        (ok, message) where ok is True if both tools are found.
    """
    for tool in ("ffmpeg", "ffprobe"):
        try:
            result = subprocess.run(
                [tool, "-version"], capture_output=True, timeout=5
            )
            if result.returncode != 0:
                return False, f"`{tool}` found but returned non-zero exit code."
        except FileNotFoundError:
            return False, (
                f"`{tool}` not found on PATH. "
                "Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Ubuntu)"
            )
    return True, "OK"


def probe_video(path: Path) -> dict[str, Any] | None:
    """
    Run ffprobe on *path* and return a metadata dict.

    Returns:
        Dict with keys: duration (float, seconds), width (int), height (int),
        codec (str). Returns None if ffprobe fails or no video stream found.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = _run(cmd)
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    # Find the first video stream
    video_stream: dict[str, Any] | None = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if video_stream is None:
        return None

    fmt = data.get("format", {})
    # duration can be on the format or the stream level
    duration_str = fmt.get("duration") or video_stream.get("duration") or "0"
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        duration = 0.0

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    codec = str(video_stream.get("codec_name", "unknown"))

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "codec": codec,
    }


def extract_frame_at(path: Path, timestamp: float, timeout: int = 30) -> bytes | None:
    """
    Extract a single frame at *timestamp* seconds from *path* as PNG bytes.

    Uses fast input-seek (-ss before -i) for speed.  The resulting frame
    may be up to one keyframe interval away from the requested timestamp,
    which is acceptable for perceptual hashing.

    Returns:
        Raw PNG bytes, or None on failure.
    """
    cmd = [
        "ffmpeg",
        *_hw_accel_flags(),
        "-ss", f"{max(timestamp, 0):.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "-an",
        "-sn",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0 or not result.stdout:
        return None

    return result.stdout


def extract_thumbnail_base64(
    path: Path,
    timestamp: float,
    max_width: int = 280,
    quality: int = 65,
) -> str | None:
    """
    Extract a frame at *timestamp*, resize to *max_width* px wide, and return
    as a base64-encoded JPEG string for embedding in HTML reports.

    Returns None if extraction or image conversion fails.
    """
    import base64
    import io

    from PIL import Image

    raw = extract_frame_at(path, timestamp)
    if not raw:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            w, h = img.size
            if w > max_width:
                img = img.resize((max_width, int(h * max_width / w)), Image.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None
