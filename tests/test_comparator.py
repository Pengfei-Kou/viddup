"""Tests for the similarity comparator."""
from __future__ import annotations

import imagehash
from PIL import Image

from viddup.core.comparator import (
    DuplicateGroup,
    _UnionFind,
    compare_frame_hashes,
    find_duplicates,
    suggest_keep,
)
from viddup.core.database import FingerprintRecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    path: str,
    file_size: int = 1_000_000,
    duration: float = 60.0,
    width: int = 1920,
    height: int = 1080,
    file_hash: str | None = "abc123",
    frame_hashes: list[str] | None = None,
) -> FingerprintRecord:
    return FingerprintRecord(
        path=path,
        file_size=file_size,
        file_mtime=0.0,
        file_hash=file_hash,
        duration=duration,
        width=width,
        height=height,
        codec="h264",
        frame_hashes=frame_hashes,
        indexed_at="2026-01-01T00:00:00+00:00",
    )


def _identical_hashes(n: int = 10) -> list[str]:
    """Return n identical pHash strings (all-zero image)."""
    img = Image.new("L", (8, 8), color=128)
    h = str(imagehash.phash(img))
    return [h] * n


def _random_hashes(n: int = 10, seed_color: int = 0) -> list[str]:
    """Return n pHash strings from gradient images (guaranteed to differ from solid)."""
    hashes = []
    for i in range(n):
        # Gradient image: pixel value increases across width — gives high-variance pHash
        img = Image.new("L", (64, 64))
        pixels = [(x * 4 + seed_color * 3 + i * 7) % 256 for y in range(64) for x in range(64)]
        img.putdata(pixels)
        hashes.append(str(imagehash.phash(img)))
    return hashes


# ── compare_frame_hashes ──────────────────────────────────────────────────────

def test_identical_hashes_return_1():
    hashes = _identical_hashes()
    sim = compare_frame_hashes(hashes, hashes)
    assert sim == 1.0


def test_empty_hashes_return_0():
    assert compare_frame_hashes([], []) == 0.0
    assert compare_frame_hashes(_identical_hashes(), []) == 0.0


def test_different_hashes_lower_similarity():
    hashes_a = _identical_hashes()
    hashes_b = _random_hashes(seed_color=200)
    sim = compare_frame_hashes(hashes_a, hashes_b)
    assert 0.0 <= sim < 1.0


def test_similarity_is_symmetric():
    hashes_a = _identical_hashes()
    hashes_b = _random_hashes()
    assert compare_frame_hashes(hashes_a, hashes_b) == compare_frame_hashes(hashes_b, hashes_a)


# ── suggest_keep ──────────────────────────────────────────────────────────────

def test_suggest_keep_prefers_higher_resolution():
    r_hd = _make_record("/hd.mp4", width=1920, height=1080, file_size=1_000_000)
    r_sd = _make_record("/sd.mp4", width=1280, height=720, file_size=2_000_000)
    assert suggest_keep([r_hd, r_sd]).path == "/hd.mp4"


def test_suggest_keep_prefers_larger_file_on_same_resolution():
    r_big = _make_record("/big.mp4", width=1920, height=1080, file_size=2_000_000)
    r_small = _make_record("/small.mp4", width=1920, height=1080, file_size=1_000_000)
    assert suggest_keep([r_big, r_small]).path == "/big.mp4"


# ── find_duplicates ───────────────────────────────────────────────────────────

def test_finds_exact_duplicates():
    hashes = _identical_hashes()
    r1 = _make_record("/a.mp4", file_hash="same_hash", frame_hashes=hashes)
    r2 = _make_record("/b.mp4", file_hash="same_hash", frame_hashes=hashes)
    exact, similar = find_duplicates([r1, r2], threshold=0.85, duration_tol=0.05)
    assert len(exact) == 1
    assert len(exact[0].records) == 2


def test_finds_similar_duplicates():
    hashes = _identical_hashes()
    r1 = _make_record("/a.mp4", file_hash="hash_a", frame_hashes=hashes)
    r2 = _make_record("/b.mp4", file_hash="hash_b", frame_hashes=hashes)
    exact, similar = find_duplicates([r1, r2], threshold=0.85, duration_tol=0.05)
    assert len(similar) == 1


def test_duration_filter_prevents_false_positives():
    hashes = _identical_hashes()
    r1 = _make_record("/a.mp4", duration=60.0, file_hash="h1", frame_hashes=hashes)
    r2 = _make_record("/b.mp4", duration=120.0, file_hash="h2", frame_hashes=hashes)
    # duration diff > 5% default tol → should not be grouped
    exact, similar = find_duplicates([r1, r2], threshold=0.85, duration_tol=0.05)
    assert len(similar) == 0


def test_no_duplicates_empty_input():
    exact, similar = find_duplicates([], threshold=0.85, duration_tol=0.05)
    assert exact == [] and similar == []


# ── UnionFind ─────────────────────────────────────────────────────────────────

def test_union_find_basic():
    uf = _UnionFind(5)
    uf.union(0, 1)
    uf.union(1, 2)
    assert uf.find(0) == uf.find(2)
    assert uf.find(0) != uf.find(3)
