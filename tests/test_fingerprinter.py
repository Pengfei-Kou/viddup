"""Tests for fingerprinter helpers (unit-testable parts)."""
from __future__ import annotations

import io

from PIL import Image

from viddup.core.fingerprinter import (
    _compute_file_hash,
    _frame_variance,
    _phash_bytes,
)

# ── _compute_file_hash ────────────────────────────────────────────────────────

def test_file_hash_is_deterministic(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world" * 1000)
    h1 = _compute_file_hash(f)
    h2 = _compute_file_hash(f)
    assert h1 == h2


def test_different_files_have_different_hashes(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"content_a" * 500)
    f2.write_bytes(b"content_b" * 500)
    assert _compute_file_hash(f1) != _compute_file_hash(f2)


def test_file_hash_is_hex_string(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"data")
    h = _compute_file_hash(f)
    assert isinstance(h, str)
    int(h, 16)  # should not raise


# ── _frame_variance ───────────────────────────────────────────────────────────

def _make_image_bytes(color: int, size: int = 64) -> bytes:
    img = Image.new("L", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_solid_black_frame_has_zero_variance():
    v = _frame_variance(_make_image_bytes(0))
    assert v == 0.0


def test_solid_white_frame_has_zero_variance():
    v = _frame_variance(_make_image_bytes(255))
    assert v == 0.0


def test_checkerboard_frame_has_high_variance():
    img = Image.new("L", (64, 64))
    pixels = [0 if (x + y) % 2 == 0 else 255 for y in range(64) for x in range(64)]
    img.putdata(pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    v = _frame_variance(buf.getvalue())
    assert v > 10_000  # very high variance expected


def test_invalid_bytes_return_zero_variance():
    v = _frame_variance(b"not an image")
    assert v == 0.0


# ── _phash_bytes ──────────────────────────────────────────────────────────────

def test_phash_returns_hex_string():
    h = _phash_bytes(_make_image_bytes(128))
    assert h is not None
    assert isinstance(h, str)


def test_phash_identical_images_match():
    data = _make_image_bytes(128)
    h1 = _phash_bytes(data)
    h2 = _phash_bytes(data)
    assert h1 == h2


def test_phash_invalid_bytes_returns_none():
    assert _phash_bytes(b"garbage") is None
