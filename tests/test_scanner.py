"""Tests for the directory scanner and .viddup_ignore support."""
from __future__ import annotations

import pytest

from viddup.core.scanner import is_ignored, load_ignore_patterns, scan_directories

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_video_dir(tmp_path):
    """Create a directory tree of dummy files with video extensions."""
    (tmp_path / "a.mp4").write_bytes(b"dummy")
    (tmp_path / "b.mkv").write_bytes(b"dummy")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.avi").write_bytes(b"dummy")
    (tmp_path / "not_a_video.txt").write_bytes(b"dummy")
    return tmp_path


# ── Basic scan ────────────────────────────────────────────────────────────────

def test_finds_video_files(sample_video_dir):
    result = scan_directories((sample_video_dir,), recursive=True)
    names = {p.name for p in result.paths}
    assert "a.mp4" in names
    assert "b.mkv" in names
    assert "c.avi" in names


def test_excludes_non_video_files(sample_video_dir):
    result = scan_directories((sample_video_dir,), recursive=True)
    names = {p.name for p in result.paths}
    assert "not_a_video.txt" not in names


def test_non_recursive(sample_video_dir):
    result = scan_directories((sample_video_dir,), recursive=False)
    names = {p.name for p in result.paths}
    assert "a.mp4" in names
    assert "c.avi" not in names  # in subdirectory


def test_deduplicates_overlapping_paths(sample_video_dir):
    result = scan_directories((sample_video_dir, sample_video_dir), recursive=True)
    paths = [p.name for p in result.paths]
    assert len(paths) == len(set(paths))


def test_skips_nonexistent_directory(tmp_path):
    missing = tmp_path / "nonexistent"
    result = scan_directories((missing,), recursive=True)
    assert result.paths == []


def test_results_are_sorted(sample_video_dir):
    result = scan_directories((sample_video_dir,), recursive=True)
    assert result.paths == sorted(result.paths)


def test_ignored_count_zero_without_ignore_file(sample_video_dir):
    result = scan_directories((sample_video_dir,), recursive=True)
    assert result.ignored_count == 0
    assert result.ignore_sources == []


# ── .viddup_ignore ────────────────────────────────────────────────────────────

def test_ignore_by_filename_glob(tmp_path):
    (tmp_path / "keep.mp4").write_bytes(b"x")
    (tmp_path / "temp_draft.mp4").write_bytes(b"x")
    (tmp_path / ".viddup_ignore").write_text("temp_*\n")
    result = scan_directories((tmp_path,), recursive=True)
    names = {p.name for p in result.paths}
    assert "keep.mp4" in names
    assert "temp_draft.mp4" not in names
    assert result.ignored_count == 1


def test_ignore_by_directory_pattern(tmp_path):
    (tmp_path / "BRaw").mkdir()
    (tmp_path / "BRaw" / "raw.mp4").write_bytes(b"x")
    (tmp_path / "keep.mp4").write_bytes(b"x")
    (tmp_path / ".viddup_ignore").write_text("BRaw/\n")
    result = scan_directories((tmp_path,), recursive=True)
    names = {p.name for p in result.paths}
    assert "keep.mp4" in names
    assert "raw.mp4" not in names
    assert result.ignored_count == 1


def test_ignore_file_with_comments_and_blanks(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / ".viddup_ignore").write_text(
        "# This is a comment\n\n  # another comment\nb.mp4\n"
    )
    result = scan_directories((tmp_path,), recursive=True)
    names = {p.name for p in result.paths}
    assert "a.mp4" in names
    assert "b.mp4" not in names


def test_ignore_sources_reported(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / ".viddup_ignore").write_text("*.mkv\n")
    result = scan_directories((tmp_path,), recursive=True)
    assert tmp_path.resolve() in result.ignore_sources


def test_load_ignore_patterns_missing_file(tmp_path):
    assert load_ignore_patterns(tmp_path) == []


def test_load_ignore_patterns_filters_comments(tmp_path):
    (tmp_path / ".viddup_ignore").write_text("# comment\n\npattern\n  # another\n")
    assert load_ignore_patterns(tmp_path) == ["pattern"]


def test_is_ignored_directory_pattern(tmp_path):
    video = tmp_path / "BRaw" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"x")
    assert is_ignored(video, tmp_path, ["BRaw/"])
    assert not is_ignored(video, tmp_path, ["Other/"])


def test_is_ignored_filename_glob(tmp_path):
    video = tmp_path / "sub" / "temp_001.mp4"
    video.parent.mkdir()
    video.write_bytes(b"x")
    assert is_ignored(video, tmp_path, ["temp_*"])
    assert not is_ignored(video, tmp_path, ["final_*"])
