import os
import tempfile
import unittest
from unittest import mock

from ytdip import acquire, config
from ytdip.errors import BadInput


class ClassifyTest(unittest.TestCase):
    def test_douyin_url(self):
        self.assertEqual(acquire.classify("https://www.douyin.com/video/7700987993812749610"), "douyin")
        self.assertEqual(acquire.classify("https://v.douyin.com/iAbCdEf/"), "douyin")
        self.assertEqual(acquire.classify("https://www.iesdouyin.com/share/video/123456789012345"), "douyin")

    def test_numeric_id_is_douyin(self):
        self.assertEqual(acquire.classify("7700987993812749610"), "douyin")

    def test_other_sites_are_generic(self):
        self.assertEqual(acquire.classify("https://www.bilibili.com/video/BV1GJ411x7h7"), "generic")
        self.assertEqual(acquire.classify("https://youtu.be/dQw4w9WgXcQ"), "generic")

    def test_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            path = handle.name
        try:
            self.assertEqual(acquire.classify(path), "local")
        finally:
            os.remove(path)

    def test_invalid_input(self):
        for bad in ("", "   ", "不是链接", "/path/that/does/not/exist.mp4"):
            with self.assertRaises(BadInput):
                acquire.classify(bad)

    def test_forced_ytdlp_mode_reroutes_douyin(self):
        with mock.patch.object(config, "DOUYIN_VIA_YTDLP", True):
            self.assertEqual(acquire.classify("https://www.douyin.com/video/7700987993812749610"), "generic")


class LocalMetaTest(unittest.TestCase):
    def test_local_id_is_sanitized(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, prefix="中文名") as handle:
            path = handle.name
        try:
            meta = acquire.resolve(path, local_id="我的 测试")
            self.assertEqual(meta["kind"], "local")
            self.assertEqual(meta["video_id"], "local")  # 纯中文被清空后回落
            self.assertEqual(meta["media_kind"], "audio")
        finally:
            os.remove(path)

    def test_missing_local_file_raises(self):
        with self.assertRaises(BadInput):
            acquire.resolve("D:/definitely/not/here.mp4")


if __name__ == "__main__":
    unittest.main()
