import os

from app.tiktok.downloader import _extract_audio_url, _extract_image_urls, _find_video_file, _is_photo_post


class TestFindVideoFile:
    def test_finds_mp4(self, tmp_path):
        (tmp_path / "vid123.mp4").touch()
        assert _find_video_file("vid123", str(tmp_path)) == str(tmp_path / "vid123.mp4")

    def test_finds_webm(self, tmp_path):
        (tmp_path / "vid123.webm").touch()
        assert _find_video_file("vid123", str(tmp_path)) == str(tmp_path / "vid123.webm")

    def test_not_found(self, tmp_path):
        assert _find_video_file("vid123", str(tmp_path)) is None

    def test_ignores_other_extensions(self, tmp_path):
        (tmp_path / "vid123.txt").touch()
        assert _find_video_file("vid123", str(tmp_path)) is None


class TestIsPhotoPost:
    def test_photo_post(self):
        assert _is_photo_post({"format_id": "audio", "vcodec": "none"}) is True

    def test_video_post(self):
        assert _is_photo_post({"format_id": "mp4", "vcodec": "h264"}) is False

    def test_empty_info(self):
        assert _is_photo_post({}) is False


class TestExtractImageUrls:
    def test_extracts_urls(self):
        item = {
            "imagePost": {
                "images": [
                    {"imageURL": {"urlList": ["http://img1.jpg", "http://img1_alt.jpg"]}},
                    {"imageURL": {"urlList": ["http://img2.jpg"]}},
                ]
            }
        }
        urls = _extract_image_urls(item)
        assert urls == ["http://img1.jpg", "http://img2.jpg"]

    def test_empty_images(self):
        assert _extract_image_urls({"imagePost": {"images": []}}) == []

    def test_none_input(self):
        assert _extract_image_urls(None) == []

    def test_no_image_post(self):
        assert _extract_image_urls({}) == []


class TestExtractAudioUrl:
    def test_music_play_url(self):
        item = {"music": {"playUrl": "http://audio.mp3"}}
        assert _extract_audio_url(item) == "http://audio.mp3"

    def test_video_play_addr_dict(self):
        item = {"music": {}, "video": {"playAddr": {"urlList": ["http://vid.mp4"]}}}
        assert _extract_audio_url(item) == "http://vid.mp4"

    def test_video_play_addr_string(self):
        item = {"music": {}, "video": {"playAddr": "http://vid.mp4"}}
        assert _extract_audio_url(item) == "http://vid.mp4"

    def test_bitrate_info_audio(self):
        item = {
            "music": {},
            "video": {
                "playAddr": "",
                "BitrateInfo": [
                    {"CodecType": "video"},
                    {"CodecType": "audio", "PlayAddr": {"UrlList": ["http://audio_br.mp3"]}},
                ],
            },
        }
        assert _extract_audio_url(item) == "http://audio_br.mp3"

    def test_no_audio(self):
        assert _extract_audio_url({"music": {}, "video": {}}) is None
