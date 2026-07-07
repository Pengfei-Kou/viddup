"""
Thin subprocess wrappers around ffprobe and ffmpeg.

No ffmpeg-python dependency — direct subprocess calls are simpler,
more portable, and easier to debug.

FFmpeg resolution order:
1. System PATH (user-installed ffmpeg/ffprobe)
2. Bundled binary from imageio-ffmpeg (pip-installed, zero-config)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def get_ffmpeg_path() -> str:
    """
    Return the path to an ffmpeg binary.

    Prefers the system PATH version; falls back to the binary bundled by
    imageio-ffmpeg (installed as a pip dependency).
    """
    # 1. System PATH
    system = shutil.which("ffmpeg")
    if system:
        return system

    # 2. imageio-ffmpeg fallback
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"  # will fail at runtime with a clear error


@lru_cache(maxsize=1)
def get_ffprobe_path() -> str:
    """
    Return the path to an ffprobe binary.

    Prefers the system PATH version; falls back to looking next to the
    imageio-ffmpeg bundled ffmpeg binary.  Returns empty string if no
    ffprobe is found (caller should use ffmpeg-based probing instead).
    """
    # 1. System PATH
    system = shutil.which("ffprobe")
    if system:
        return system

    # 2. Derive from imageio-ffmpeg's ffmpeg location
    ffmpeg = get_ffmpeg_path()
    ffprobe_candidate = Path(ffmpeg).parent / (
        "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    )
    if ffprobe_candidate.is_file():
        return str(ffprobe_candidate)

    # imageio-ffmpeg only bundles ffmpeg, not ffprobe — return empty
    return ""


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
    Check that ffmpeg is available (required) and ffprobe if present.

    Tries system PATH first, then falls back to bundled imageio-ffmpeg.
    ffprobe is optional — when unavailable, probe_video uses ffmpeg instead.

    Returns:
        (ok, message) where ok is True if ffmpeg is found.
    """
    ffmpeg = get_ffmpeg_path()

    try:
        result = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, timeout=5
        )
        if result.returncode != 0:
            return False, "`ffmpeg` found but returned non-zero exit code."
    except FileNotFoundError:
        return False, (
            "`ffmpeg` not found. "
            "Install with: pip install imageio-ffmpeg, "
            "or: brew install ffmpeg (macOS) / apt install ffmpeg (Ubuntu)"
        )

    # ffprobe is optional — check but don't fail
    ffprobe = get_ffprobe_path()
    if ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, "-version"], capture_output=True, timeout=5
            )
            if result.returncode != 0:
                pass  # will fall back to ffmpeg-based probing
        except FileNotFoundError:
            pass  # will fall back to ffmpeg-based probing

    return True, "OK"


def _probe_with_ffprobe(path: Path) -> dict[str, Any] | None:
    """Probe video metadata using ffprobe (preferred, more reliable)."""
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        return None

    cmd = [
        ffprobe,
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

    return _parse_probe_json(result.stdout)


def _probe_with_ffmpeg(path: Path) -> dict[str, Any] | None:
    """
    Probe video metadata using ffmpeg (fallback when ffprobe is unavailable).

    Uses 'ffmpeg -i <file> -dump -map 0:v:0' to extract stream info,
    and parses duration/resolution/codec from stderr output.
    """
    cmd = [
        get_ffmpeg_path(),
        "-i", str(path),
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    # ffmpeg -i always returns non-zero, parse stderr regardless
    stderr = result.stderr
    if not stderr:
        return None

    import re

    # Extract duration: "Duration: HH:MM:SS.xx"
    duration = 0.0
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
    if dur_match:
        h, m, s, cs = dur_match.groups()
        duration = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0

    # Extract video stream: "Stream #0:X: Video: codec, ..., WxH"
    width, height, codec = 0, 0, "unknown"
    vid_match = re.search(
        r"Stream\s+#\d+:\d+.*?Video:\s*(\w+).*?,\s*(\d+)x(\d+)", stderr
    )
    if vid_match:
        codec = vid_match.group(1)
        width = int(vid_match.group(2))
        height = int(vid_match.group(3))
    else:
        return None  # no video stream found

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "codec": codec,
    }


def _parse_probe_json(stdout: str) -> dict[str, Any] | None:
    """Parse ffprobe JSON output into our metadata dict."""
    try:
        data = json.loads(stdout)
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


def probe_video(path: Path) -> dict[str, Any] | None:
    """
    Probe *path* for video metadata.

    Tries ffprobe first (more reliable JSON output), falls back to parsing
    ffmpeg stderr when ffprobe is unavailable (e.g. imageio-ffmpeg only
    bundles ffmpeg).

    Returns:
        Dict with keys: duration (float, seconds), width (int), height (int),
        codec (str). Returns None if probing fails or no video stream found.
    """
    result = _probe_with_ffprobe(path)
    if result is not None:
        return result
    return _probe_with_ffmpeg(path)


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
        get_ffmpeg_path(),
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
