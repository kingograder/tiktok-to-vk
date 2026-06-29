from pathlib import Path
from unittest.mock import patch

from app.video.slideshow import cleanup_slideshow_tmp


class TestSlideshowPerVideoDir:
    def test_cleanup_removes_only_target_video(self, tmp_path):
        with patch("app.video.slideshow.SLIDESHOW_TMP_DIR", tmp_path):
            vid_a = tmp_path / "video_a"
            vid_b = tmp_path / "video_b"
            vid_a.mkdir()
            vid_b.mkdir()
            (vid_a / "1.jpg").write_bytes(b"img_a")
            (vid_b / "1.jpg").write_bytes(b"img_b")

            cleanup_slideshow_tmp("video_a")

            assert not vid_a.exists()
            assert vid_b.exists()
            assert (vid_b / "1.jpg").read_bytes() == b"img_b"

            cleanup_slideshow_tmp("video_b")

    def test_cleanup_all(self, tmp_path):
        with patch("app.video.slideshow.SLIDESHOW_TMP_DIR", tmp_path):
            vid_a = tmp_path / "vid_x"
            vid_b = tmp_path / "vid_y"
            vid_a.mkdir()
            vid_b.mkdir()
            (vid_a / "1.jpg").touch()
            (vid_b / "1.jpg").touch()

            cleanup_slideshow_tmp()

            assert not vid_a.exists()
            assert not vid_b.exists()

    def test_cleanup_nonexistent_video_no_error(self, tmp_path):
        with patch("app.video.slideshow.SLIDESHOW_TMP_DIR", tmp_path):
            cleanup_slideshow_tmp("nonexistent_video_id")

    def test_cleanup_with_subdirs(self, tmp_path):
        with patch("app.video.slideshow.SLIDESHOW_TMP_DIR", tmp_path):
            vid = tmp_path / "complex"
            padded = vid / "padded"
            padded.mkdir(parents=True)
            (padded / "1.jpg").touch()
            (vid / "audio.mp3").touch()

            cleanup_slideshow_tmp("complex")
            assert not vid.exists()
