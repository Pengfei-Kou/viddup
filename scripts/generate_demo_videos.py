#!/usr/bin/env python3
"""
Generate demo videos for VidDup showcase.

Creates a set of synthetic test videos in demo/ that demonstrate all
detection capabilities:
  - Exact copy (same bytes)
  - Re-encoded (H.264 → H.265)
  - Re-scaled (1080p → 720p)
  - Compressed (high → low bitrate)
  - Unique videos (control, should NOT be flagged)

Usage:
    python scripts/generate_demo_videos.py

Requires: ffmpeg on PATH (or installed via imageio-ffmpeg)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def get_ffmpeg() -> str:
    """Find ffmpeg binary."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        print("❌ ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)


FFMPEG = get_ffmpeg()
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"


def run(cmd: list[str], desc: str) -> None:
    """Run a command with progress feedback."""
    print(f"  ⏳ {desc}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ Failed: {result.stderr[-300:]}")
        sys.exit(1)
    print(f"  ✅ {desc} — done")


def generate_source(
    path: Path,
    source: str = "mandelbrot",
    duration: int = 10,
    width: int = 1920,
    height: int = 1080,
    bitrate: str = "5M",
    audio_freq: int = 440,
) -> None:
    """
    Generate a synthetic video using ffmpeg's built-in lavfi sources.

    Available sources:
    - mandelbrot: Fractal zoom animation (visually rich, great for pHash testing)
    - testsrc2: Color bars + timer (classic test pattern)
    - life: Conway's Game of Life simulation
    """
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"{source}=size={width}x{height}:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency={audio_freq}:duration={duration}",
        "-c:v", "libx264", "-preset", "medium", "-b:v", bitrate,
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        str(path),
    ]
    run(cmd, f"Generating {path.name}")


def main() -> None:
    print("🎬 VidDup Demo Video Generator")
    print("=" * 50)

    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Original video (source A — mandelbrot fractal zoom) ────────────────
    original = DEMO_DIR / "vacation_beach_4k.mp4"
    print("\n📹 [1/7] Generating original video (mandelbrot fractal)...")
    generate_source(original, source="mandelbrot", duration=12, bitrate="5M")

    # ── 2. Exact copy ─────────────────────────────────────────────────────────
    exact_copy = DEMO_DIR / "vacation_beach_4k_copy.mp4"
    print("\n📋 [2/7] Creating exact copy...")
    shutil.copy2(original, exact_copy)
    print("  ✅ Exact copy — done")

    # ── 3. Re-encoded (H.264 → H.265/HEVC) ───────────────────────────────────
    reencoded = DEMO_DIR / "vacation_beach_hevc.mp4"
    print("\n🔄 [3/7] Re-encoding to H.265...")
    run([
        FFMPEG, "-y",
        "-i", str(original),
        "-c:v", "libx265", "-preset", "medium", "-b:v", "3M",
        "-c:a", "aac", "-b:a", "128k",
        "-tag:v", "hvc1",
        str(reencoded),
    ], "Re-encode H.264 → H.265")

    # ── 4. Re-scaled (1080p → 720p) ───────────────────────────────────────────
    rescaled = DEMO_DIR / "vacation_beach_720p.mp4"
    print("\n📐 [4/7] Downscaling to 720p...")
    run([
        FFMPEG, "-y",
        "-i", str(original),
        "-vf", "scale=1280:720",
        "-c:v", "libx264", "-preset", "medium", "-b:v", "2M",
        "-c:a", "aac", "-b:a", "128k",
        str(rescaled),
    ], "Downscale 1080p → 720p")

    # ── 5. Compressed (high → low bitrate) ────────────────────────────────────
    compressed = DEMO_DIR / "vacation_beach_compressed.mp4"
    print("\n🗜️  [5/7] Creating low-bitrate compressed version...")
    run([
        FFMPEG, "-y",
        "-i", str(original),
        "-c:v", "libx264", "-preset", "medium", "-b:v", "500k",
        "-c:a", "aac", "-b:a", "64k",
        str(compressed),
    ], "Compress to low bitrate")

    # ── 6. Unique video (source B — test pattern, different content) ──────────
    unique1 = DEMO_DIR / "city_timelapse.mp4"
    print("\n🏙️  [6/7] Generating unique video (test pattern)...")
    generate_source(unique1, source="testsrc2", duration=8, bitrate="3M",
                    audio_freq=660)

    # ── 7. Unique video (source C — Game of Life, different content) ──────────
    unique2 = DEMO_DIR / "cooking_tutorial.mp4"
    print("\n🍳 [7/7] Generating unique video (life simulation)...")
    generate_source(unique2, source="life", duration=15, width=1280,
                    height=720, bitrate="3M", audio_freq=880)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("✅ All demo videos generated!\n")
    print(f"📂 Output directory: {DEMO_DIR}\n")

    total_size = sum(f.stat().st_size for f in DEMO_DIR.glob("*.mp4"))
    print("📋 Generated files:")
    for f in sorted(DEMO_DIR.glob("*.mp4")):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"   {f.name:<40s} {size_mb:>6.1f} MB")
    print(f"\n   {'Total:':<40s} {total_size / (1024 * 1024):>6.1f} MB")

    print("\n🎯 Expected VidDup results:")
    print("   ⚡ Exact duplicate group:")
    print("      - vacation_beach_4k.mp4")
    print("      - vacation_beach_4k_copy.mp4")
    print("   🎯 Near-duplicate group:")
    print("      - vacation_beach_4k.mp4")
    print("      - vacation_beach_hevc.mp4     (re-encoded)")
    print("      - vacation_beach_720p.mp4     (re-scaled)")
    print("      - vacation_beach_compressed.mp4 (compressed)")
    print("   ✅ Not flagged (unique):")
    print("      - city_timelapse.mp4")
    print("      - cooking_tutorial.mp4")

    print(f"\n🚀 Now run:  viddup scan {DEMO_DIR}")


if __name__ == "__main__":
    main()
