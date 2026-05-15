"""
Filesystem scanner: collect video file paths from one or more directories.

Supports .viddup_ignore files (placed in each scan root) with glob patterns
similar to .gitignore:

    # Comment lines are ignored
    BRaw/              # exclude any directory named "BRaw"
    原始素材/           # directory patterns end with /
    *.tmp              # filename glob
    temp_*/**          # path glob (relative to scan root)
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import NamedTuple

from viddup.config import VIDEO_EXTENSIONS

IGNORE_FILENAME = ".viddup_ignore"


# ── Ignore pattern loading ────────────────────────────────────────────────────

def load_ignore_patterns(root: Path) -> list[str]:
    """
    Read *root*/.viddup_ignore and return non-empty, non-comment lines.

    Returns an empty list if the file does not exist.
    """
    ignore_file = root / IGNORE_FILENAME
    if not ignore_file.is_file():
        return []
    patterns: list[str] = []
    for raw in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """
    Return True if *path* should be excluded based on *patterns*.

    Matching rules (applied relative to *root*):
    - Patterns ending with "/" match directory name components anywhere in the
      relative path  → excludes the whole subtree.
    - Other patterns are matched against the filename (via fnmatch) and also
      against the full relative path string.
    """
    if not patterns:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False  # path is not under root — don't filter

    rel_str = rel.as_posix()   # forward-slash separated, platform-independent
    name = path.name

    for pattern in patterns:
        if pattern.endswith("/"):
            # Directory pattern: match any ancestor directory component
            dir_pat = pattern.rstrip("/")
            for part in rel.parts[:-1]:          # exclude the filename itself
                if fnmatch.fnmatch(part, dir_pat):
                    return True
        else:
            # File pattern: match filename or full relative path
            if fnmatch.fnmatch(name, pattern):
                return True
            if fnmatch.fnmatch(rel_str, pattern):
                return True

    return False


# ── Scan result ───────────────────────────────────────────────────────────────

class ScanResult(NamedTuple):
    paths: list[Path]
    ignored_count: int
    ignore_sources: list[Path]   # which roots had an active .viddup_ignore


# ── Main scanner ──────────────────────────────────────────────────────────────

def scan_directories(
    paths: tuple[Path, ...],
    recursive: bool = True,
) -> ScanResult:
    """
    Collect all video files under *paths*, respecting .viddup_ignore files.

    Each scan root is checked for a .viddup_ignore file; patterns found there
    apply to everything under that root.  Overlapping directories and symlinks
    are deduplicated via resolved paths.

    Args:
        paths:     One or more root directories to scan.
        recursive: If True, descend into subdirectories.

    Returns:
        ScanResult with sorted deduplicated paths, ignored count, and which
        roots had active ignore files.
    """
    seen: set[Path] = set()
    found: list[Path] = []
    ignored_count = 0
    ignore_sources: list[Path] = []

    for root in paths:
        root = root.resolve()
        if not root.is_dir():
            continue

        patterns = load_ignore_patterns(root)
        if patterns:
            ignore_sources.append(root)

        iter_fn = root.rglob if recursive else root.glob
        for p in iter_fn("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if is_ignored(p, root, patterns):
                ignored_count += 1
                continue
            resolved = p.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)

    found.sort()
    return ScanResult(
        paths=found,
        ignored_count=ignored_count,
        ignore_sources=ignore_sources,
    )
