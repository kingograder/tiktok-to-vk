import os
from pathlib import Path

from app.video.processor import _ensure_vertical_sync, _read_dimensions


class TestReadDimensions:
    def test_returns_none_for_nonexistent_file(self):
        assert _read_dimensions("/nonexistent/video.mp4") is None


class TestEnsureVerticalSync:
    def test_returns_same_if_no_dimensions(self):
        result = _ensure_vertical_sync("/nonexistent/video.mp4")
        assert result == "/nonexistent/video.mp4"

    def test_removes_original_after_successful_conversion(self, tmp_path):
        original = tmp_path / "test.mp4"
        original.touch()

        with (
            patch("app.video.processor._read_dimensions", return_value=(1920, 1080)),
            patch("app.video.processor._convert_video"),
            patch("os.path.exists", side_effect=lambda p: True),
            patch("os.remove"),
        ):
            result = _ensure_vertical_sync(str(original))
            assert result.endswith("_vertical.mp4")


from unittest.mock import patch


class TestEnsureVerticalFallback:
    def test_keeps_original_on_conversion_failure(self, tmp_path):
        original = tmp_path / "test.mp4"
        vertical = tmp_path / "test_vertical.mp4"
        original.touch()

        with (
            patch("app.video.processor._read_dimensions", return_value=(1920, 1080)),
            patch("app.video.processor._convert_video", side_effect=RuntimeError("ffmpeg fail")),
            patch("os.path.exists", return_value=True),
            patch("os.remove") as mock_rm,
        ):
            result = _ensure_vertical_sync(str(original))
            assert result == str(original)
            mock_rm.assert_called_with(str(vertical))
