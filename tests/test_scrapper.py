import os
from pathlib import Path

from app.tiktok.scrapper import _parse_collection_url, _parse_cookies, _traverse


class TestTraverse:
    def test_dict_nested(self):
        obj = {"a": {"b": {"c": 42}}}
        assert _traverse(obj, ("a", "b", "c")) == 42

    def test_dict_missing_key(self):
        obj = {"a": {"b": 1}}
        assert _traverse(obj, ("a", "x"), default="N/A") == "N/A"

    def test_list_index(self):
        obj = [10, 20, 30]
        assert _traverse(obj, (1,)) == 20

    def test_list_index_out_of_range(self):
        obj = [10, 20]
        assert _traverse(obj, (5,)) is None
        assert _traverse(obj, (-1,)) is None

    def test_tuple_index(self):
        obj = (100, 200)
        assert _traverse(obj, (0,)) == 100

    def test_nested_dict_list(self):
        obj = {"items": [{"name": "first"}, {"name": "second"}]}
        assert _traverse(obj, ("items", 1, "name")) == "second"

    def test_none_intermediate(self):
        obj = {"a": None}
        assert _traverse(obj, ("a", "b")) is None

    def test_wrong_type(self):
        obj = "not a dict"
        assert _traverse(obj, ("a",)) is None

    def test_default_returned(self):
        assert _traverse({}, ("a",), default="missing") == "missing"


class TestParseCollectionUrl:
    def test_valid_url(self):
        url = "https://www.tiktok.com/@user/collection/My%20Collection-123456"
        assert _parse_collection_url(url) == "123456"

    def test_invalid_url(self):
        assert _parse_collection_url("https://www.tiktok.com/@user") is None

    def test_empty_url(self):
        assert _parse_collection_url("") is None


class TestParseCookies:
    def test_valid_netscape_file(self, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".tiktok.com\tTRUE\t/\tFALSE\t0\tttwid\tabc123\n"
            ".tiktok.com\tTRUE\t/\tFALSE\t0\tsessionid\tsid456\n"
        )
        cookies = _parse_cookies(str(cookie_file))
        assert cookies["ttwid"] == "abc123"
        assert cookies["sessionid"] == "sid456"

    def test_skips_comments(self, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text("# comment\n.ttwid\tTRUE\t/\tFALSE\t0\tttwid\tval\n")
        cookies = _parse_cookies(str(cookie_file))
        assert cookies == {"ttwid": "val"}

    def test_missing_file(self):
        cookies = _parse_cookies("/nonexistent/path/cookies.txt")
        assert cookies == {}

    def test_empty_file(self, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text("")
        cookies = _parse_cookies(str(cookie_file))
        assert cookies == {}
