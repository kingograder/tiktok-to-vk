import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.vk.uploader import build_description, upload_clip


class _FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status = status

    async def json(self):
        return self._data

    async def text(self):
        return str(self._data)


class _FakePostCM:
    def __init__(self, data, status=200):
        self._resp = _FakeResponse(data, status)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


def _make_session(responses):
    iter_responses = iter(responses)

    def post(url, **kw):
        data, status = next(iter_responses)
        return _FakePostCM(data, status)

    mock = MagicMock()
    mock.post = post
    return mock


class TestBuildDescription:
    def test_with_username(self):
        desc = build_description("12345", "testuser")
        assert "Author: testuser" in desc
        assert "tiktok.com/@testuser/video/12345" in desc
        assert "Source:" in desc

    def test_without_username(self):
        desc = build_description("12345", None)
        assert "Author:" not in desc
        assert "tiktok.com/video/12345" in desc


class TestVkMethodRateLimiter:
    async def test_rate_limiter_enforces_min_interval(self):
        session = _make_session([({"response": {"ok": True}}, 200)])

        with patch("app.vk.uploader.config") as mock_config:
            mock_config.vk.MIN_INTERVAL = 0.1
            mock_config.vk.TOKEN = "test_token"
            mock_config.vk.API_VERSION = "5.199"

            import app.vk.uploader as mod
            mod._vk_last_request_time = 0.0

            from app.vk.uploader import _vk_method

            start = time.monotonic()
            await _vk_method("test", session, x=1)

            session2 = _make_session([({"response": {"ok": True}}, 200)])
            await _vk_method("test", session2, x=1)
            elapsed = time.monotonic() - start

            assert elapsed >= 0.09

    async def test_raises_on_http_error(self):
        session = _make_session([("server error", 500)])

        with patch("app.vk.uploader.config") as mock_config:
            mock_config.vk.MIN_INTERVAL = 0
            mock_config.vk.TOKEN = "test_token"
            mock_config.vk.API_VERSION = "5.199"

            import app.vk.uploader as mod
            mod._vk_last_request_time = 0.0

            from app.vk.uploader import _vk_method

            with pytest.raises(Exception, match="VK API HTTP 500"):
                await _vk_method("test", session)

    async def test_raises_on_vk_error(self):
        session = _make_session([
            ({"error": {"error_msg": "invalid token"}}, 200)
        ])

        with patch("app.vk.uploader.config") as mock_config:
            mock_config.vk.MIN_INTERVAL = 0
            mock_config.vk.TOKEN = "test_token"
            mock_config.vk.API_VERSION = "5.199"

            import app.vk.uploader as mod
            mod._vk_last_request_time = 0.0

            from app.vk.uploader import _vk_method

            with pytest.raises(Exception, match="VK API error: invalid token"):
                await _vk_method("test", session)


class TestUploadClipPollTimeout:
    async def test_returns_none_on_poll_timeout(self):
        with patch("app.vk.uploader.config") as mock_config:
            mock_config.vk.MIN_INTERVAL = 0
            mock_config.vk.TOKEN = "test_token"
            mock_config.vk.API_VERSION = "5.199"
            mock_config.vk.CLIP_VISIBILITY = "all"
            mock_config.vk.UPLOAD_TIMEOUT = 10
            mock_config.vk.POLL_ATTEMPTS = 2
            mock_config.vk.POLL_INTERVAL = 0.01

            import app.vk.uploader as mod
            mod._vk_last_request_time = 0.0

            session = _make_session([
                ({"response": {"upload_url": "http://upload.test"}}, 200),
                ({"video_id": "999", "owner_id": "123"}, 200),
                ({"response": {"items": []}}, 200),
                ({"response": {"items": []}}, 200),
            ])

            mock_session_cm = MagicMock()
            mock_session_cm.__enter__ = MagicMock(return_value=session)
            mock_session_cm.__exit__ = MagicMock(return_value=False)

            with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                with patch("builtins.open", MagicMock()):
                    with patch("os.path.getsize", return_value=1000):
                        with patch("os.path.isfile", return_value=True):
                            result = await upload_clip("/fake/video.mp4", "desc")

            assert result is None
