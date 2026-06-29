import os
from pathlib import Path

from main import _cleanup_file_sync


class TestCleanupFileSync:
    def test_removes_existing_file(self, tmp_path):
        f = tmp_path / "to_delete.mp4"
        f.touch()
        assert _cleanup_file_sync(str(f)) is True
        assert not f.exists()

    def test_returns_true_for_nonexistent_file(self, tmp_path):
        f = tmp_path / "already_gone.mp4"
        assert _cleanup_file_sync(str(f)) is True
