"""Global configuration and runtime constants for VidDup."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ── Default values ────────────────────────────────────────────────────────────

DEFAULT_DB_PATH: Final[Path] = Path.home() / ".viddup" / "fingerprints.db"
DEFAULT_FRAMES: Final[int] = 10
DEFAULT_THRESHOLD: Final[float] = 0.85
DEFAULT_DURATION_TOL: Final[float] = 0.05  # ±5%
DEFAULT_WORKERS: Final[int] = os.cpu_count() or 4

#: Pixel variance below which a frame is treated as "low-content" (solid color).
MIN_FRAME_VARIANCE: Final[float] = 100.0

#: Supported video file extensions (lowercase).
VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm",
        ".wmv", ".m4v", ".ts", ".mpeg", ".mpg", ".3gp",
    }
)


# ── Runtime config ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Config:
    """
    Immutable runtime configuration assembled from CLI flags and defaults.

    All core functions accept a Config instance, making it easy to add
    new options without changing function signatures.
    """

    scan_paths: tuple[Path, ...]
    db_path: Path = DEFAULT_DB_PATH
    threshold: float = DEFAULT_THRESHOLD
    frames: int = DEFAULT_FRAMES
    duration_tol: float = DEFAULT_DURATION_TOL
    workers: int = DEFAULT_WORKERS
    output_dir: Path = field(default_factory=Path.cwd)  # CLI overrides to scan_paths[0]
    recursive: bool = True
    no_cache: bool = False
    dry_run: bool = False
    verbose: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError(f"threshold must be in (0, 1], got {self.threshold}")
        if self.frames < 1:
            raise ValueError(f"frames must be >= 1, got {self.frames}")
        if not 0.0 < self.duration_tol < 1.0:
            raise ValueError(f"duration_tol must be in (0, 1), got {self.duration_tol}")
