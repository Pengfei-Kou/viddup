"""
Three-layer fingerprint generation with multiprocess parallelism.

Layer 1 (L1): xxHash3-128 — exact duplicate detection
Layer 2 (L2): ffprobe metadata — duration-based candidate grouping
Layer 3 (L3): pHash over N frames — perceptual similarity

Design note: worker functions (_compute_fingerprint) are module-level
so they can be pickled by ProcessPoolExecutor.
"""
from __future__ import annotations

import io
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import imagehash
import xxhash
from PIL import Image

from viddup.config import MIN_FRAME_VARIANCE
from viddup.core.database import FingerprintRecord
from viddup.utils.ffmpeg_utils import extract_frame_at, probe_video

# ── Worker helpers (module-level for pickling) ────────────────────────────────

def _compute_file_hash(path: Path) -> str:
    """Compute xxHash3-128 of the file in streaming 8 MB chunks."""
    h = xxhash.xxh3_128()
    with open(path, "rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _frame_variance(image_bytes: bytes) -> float:
    """Return the pixel variance of a grayscale frame. Lower = more solid color."""
    try:
        import numpy as np
        with Image.open(io.BytesIO(image_bytes)) as img:
            arr = np.array(img.convert("L"), dtype=np.float32)
            return float(arr.var())
    except Exception:
        return 0.0


def _phash_bytes(image_bytes: bytes) -> str | None:
    """Compute pHash of image bytes. Returns hex string or None on failure."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return str(imagehash.phash(img))
    except Exception:
        return None


def _compute_frame_hashes(
    path: Path,
    num_frames: int,
    duration: float,
    min_variance: float,
) -> list[str] | None:
    """
    Extract *num_frames* pHashes from *path*.

    Strategy:
    1. Primary timestamps: evenly spaced at 5%, 15%, ..., 95% of duration.
    2. For each primary timestamp that yields a low-variance (solid) frame,
       try candidate alternates until a valid frame is found.
    3. Return None if fewer than half the requested frames can be hashed.

    Ultra-short videos (< 3 s) are handled with a reduced frame count to
    avoid timestamp overlap and extraction failures.
    """
    if duration <= 0:
        return None

    # ── Degrade for ultra-short videos ────────────────────────────────────────
    if duration < 3.0:
        num_frames = min(num_frames, 2)

    try:
        return _extract_hashes(path, num_frames, duration, min_variance)
    except Exception:
        return None


def _extract_hashes(
    path: Path,
    num_frames: int,
    duration: float,
    min_variance: float,
) -> list[str] | None:
    """Inner extraction logic, separated for clean try/except wrapping."""
    step = 1.0 / (num_frames + 1)
    primary_ts = [duration * step * (i + 1) for i in range(num_frames)]

    # Alternates: midpoints between primary timestamps
    alt_ts = [duration * step * (i + 0.5) for i in range(num_frames + 1)]
    alt_pool = [t for t in alt_ts if t not in primary_ts]

    hashes: list[str] = []
    used_ts: set[float] = set()

    def _try_timestamp(ts: float) -> str | None:
        frame = extract_frame_at(path, ts)
        if frame is None:
            return None
        if _frame_variance(frame) < min_variance:
            return None  # solid/black frame
        return _phash_bytes(frame)

    for pts in primary_ts:
        h = _try_timestamp(pts)
        if h is not None:
            hashes.append(h)
            used_ts.add(pts)
            continue
        # Primary failed — try alternates
        for alt in alt_pool:
            if alt in used_ts:
                continue
            h = _try_timestamp(alt)
            if h is not None:
                hashes.append(h)
                used_ts.add(alt)
                break

    # For ultra-short videos, accept even 1 frame; otherwise need half
    min_required = 1 if duration < 3.0 else max(1, num_frames // 2)
    if len(hashes) < min_required:
        return None
    return hashes


def _fingerprint_worker(
    path_str: str,
    num_frames: int,
    min_variance: float,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """
    Top-level worker for ProcessPoolExecutor (must be importable at module level).

    Returns:
        (path_str, data_dict, error_message)
        data_dict is None on failure; error_message is None on success.
    """
    path = Path(path_str)
    try:
        stat = path.stat()
    except OSError as e:
        return path_str, None, f"stat failed: {e}"

    # L1: file hash
    try:
        file_hash = _compute_file_hash(path)
    except Exception as e:
        return path_str, None, f"L1 hash failed: {e}"

    # L2: metadata
    meta = probe_video(path)
    if meta is None:
        return path_str, None, "ffprobe failed — skipping"

    # L3: frame hashes
    frame_hashes = _compute_frame_hashes(
        path, num_frames, meta["duration"], min_variance
    )

    return path_str, {
        "file_size": stat.st_size,
        "file_mtime": stat.st_mtime,
        "file_hash": file_hash,
        "duration": meta["duration"],
        "width": meta["width"],
        "height": meta["height"],
        "codec": meta["codec"],
        "frame_hashes": frame_hashes,
    }, None


# ── Public API ────────────────────────────────────────────────────────────────

class FingerprintResult(NamedTuple):
    record: FingerprintRecord
    from_cache: bool
    error: str | None


def generate_fingerprints(
    paths: list[Path],
    *,
    db_path: Path,
    num_frames: int,
    workers: int,
    no_cache: bool,
    min_variance: float = MIN_FRAME_VARIANCE,
    progress_callback: Any = None,  # callable(path, from_cache, error) or None
) -> list[FingerprintResult]:
    """
    Generate fingerprints for all *paths*, using the DB cache where possible.

    Cache hit logic: if file size AND mtime match the cached record, skip
    re-computation.  Pass no_cache=True to force recomputation.

    Args:
        paths:             List of video file paths to fingerprint.
        db_path:           Path to the SQLite cache database.
        num_frames:        Number of frames to sample per video.
        workers:           Number of parallel worker processes.
        no_cache:          If True, ignore cache and recompute all fingerprints.
        min_variance:      Minimum pixel variance to accept a frame as non-solid.
        progress_callback: Optional callable(path, from_cache, error) for progress.

    Returns:
        List of FingerprintResult (one per path, including errors).
    """
    from viddup.core.database import Database

    db = Database(db_path)
    results: list[FingerprintResult] = []
    to_compute: list[Path] = []

    # ── Cache check ───────────────────────────────────────────────────────────
    for path in paths:
        if no_cache:
            to_compute.append(path)
            continue
        try:
            stat = path.stat()
        except OSError:
            to_compute.append(path)
            continue

        cached = db.get(path)
        if (
            cached is not None
            and cached.file_size == stat.st_size
            and cached.file_mtime == stat.st_mtime
        ):
            result = FingerprintResult(record=cached, from_cache=True, error=None)
            results.append(result)
            if progress_callback:
                progress_callback(path, True, None)
        else:
            to_compute.append(path)

    # ── Parallel computation ──────────────────────────────────────────────────
    if to_compute:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    _fingerprint_worker, str(p), num_frames, min_variance
                ): p
                for p in to_compute
            }
            for future in as_completed(future_map):
                path = future_map[future]
                try:
                    path_str, data, error = future.result()
                except Exception as e:
                    error = str(e)
                    data = None

                if data is None:
                    result = FingerprintResult(
                        record=_empty_record(path),
                        from_cache=False,
                        error=error,
                    )
                else:
                    record = FingerprintRecord(
                        path=str(path),
                        file_size=data["file_size"],
                        file_mtime=data["file_mtime"],
                        file_hash=data["file_hash"],
                        duration=data["duration"],
                        width=data["width"],
                        height=data["height"],
                        codec=data["codec"],
                        frame_hashes=data["frame_hashes"],
                        indexed_at=datetime.now(UTC).isoformat(),
                    )
                    db.upsert(record)
                    result = FingerprintResult(
                        record=record, from_cache=False, error=None
                    )

                results.append(result)
                if progress_callback:
                    progress_callback(path, False, error)

    db.close()
    return results


def _empty_record(path: Path) -> FingerprintRecord:
    """Create a placeholder record for failed fingerprints."""
    try:
        stat = path.stat()
        file_size, file_mtime = stat.st_size, stat.st_mtime
    except OSError:
        file_size, file_mtime = 0, 0.0
    return FingerprintRecord(
        path=str(path),
        file_size=file_size,
        file_mtime=file_mtime,
        file_hash=None,
        duration=None,
        width=None,
        height=None,
        codec=None,
        frame_hashes=None,
        indexed_at=datetime.now(UTC).isoformat(),
    )
