"""Shared test fixtures for VidDup tests."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_db(tmp_dir):
    """Provide a temporary SQLite database path."""
    return tmp_dir / "test_fingerprints.db"


@pytest.fixture
def sample_video_dir(tmp_dir):
    """
    Create a directory tree of dummy files with video extensions.
    (Not real videos — just for scanner tests.)
    """
    (tmp_dir / "a.mp4").write_bytes(b"dummy")
    (tmp_dir / "b.mkv").write_bytes(b"dummy")
    (tmp_dir / "sub").mkdir()
    (tmp_dir / "sub" / "c.avi").write_bytes(b"dummy")
    (tmp_dir / "not_a_video.txt").write_bytes(b"dummy")
    return tmp_dir
