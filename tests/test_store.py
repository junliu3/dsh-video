import json
import os
import tempfile
import unittest
from unittest import mock

from ytdip import config, store


class SanitizeIdTest(unittest.TestCase):
    def test_keeps_numeric_douyin_ids(self):
        self.assertEqual(store.sanitize_id("7700987993812749610"), "7700987993812749610")

    def test_replaces_unsafe_characters(self):
        self.assertEqual(store.sanitize_id("BV1GJ411x7h7"), "BV1GJ411x7h7")
        self.assertEqual(store.sanitize_id("a b/c:d"), "a-b-c-d")
        self.assertEqual(store.sanitize_id("中文标题"), "item")

    def test_falls_back_when_nothing_remains(self):
        self.assertEqual(store.sanitize_id("中文标题", fallback="item"), "item")
        self.assertEqual(store.sanitize_id("", fallback="item"), "item")

    def test_truncates_long_ids(self):
        self.assertEqual(len(store.sanitize_id("x" * 200)), 80)


class RecordContractTest(unittest.TestCase):
    def test_new_record_has_schema_version_and_fields(self):
        record = store.new_record("123", "https://example.com/v", platform="bilibili")
        self.assertEqual(record["schema_version"], store.SCHEMA_VERSION)
        self.assertEqual(record["platform"], "bilibili")
        for key in ("video_id", "source_url", "title", "duration_sec", "cover_path",
                    "media_path", "media_kind", "audio_path", "captured_at", "pipeline"):
            self.assertIn(key, record)

    def test_write_and_read_media_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "LIB_ROOT", tmp):
            directory = store.asset_dir("42")
            record = store.new_record("42", "https://example.com/42")
            record["title"] = "标题不改文件名"
            store.write_media(directory, record)

            loaded = store.read_media(directory)
            self.assertEqual(loaded["title"], "标题不改文件名")
            # 目录名只能是 ASCII id，中文只存在于字段里
            self.assertEqual(os.path.basename(directory), "42")
            with open(store.media_json_path(directory), encoding="utf-8") as handle:
                raw = json.load(handle)
            self.assertEqual(raw["video_id"], "42")


class ListItemsTest(unittest.TestCase):
    def test_lists_items_and_skips_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "LIB_ROOT", tmp):
            for video_id in ("111", "222"):
                directory = store.asset_dir(video_id)
                record = store.new_record(video_id, "")
                record["title"] = f"title-{video_id}"
                record["captured_at"] = f"2026-01-0{video_id[0]}+08:00"
                store.write_media(directory, record)
            os.makedirs(os.path.join(tmp, ".state", "jobs"))
            os.makedirs(os.path.join(tmp, ".hidden"))

            items = store.list_items(limit=10)
            self.assertEqual([item["videoId"] for item in items], ["222", "111"])
            self.assertTrue(all(item["hasReport"] is False for item in items))

    def test_keyword_filter_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "LIB_ROOT", tmp):
            for video_id, title in (("a1", "猫咪"), ("b2", "狗狗")):
                directory = store.asset_dir(video_id)
                record = store.new_record(video_id, "")
                record["title"] = title
                store.write_media(directory, record)

            self.assertEqual(len(store.list_items(keyword="猫")), 1)
            self.assertEqual(len(store.list_items(limit=1)), 1)

    def test_missing_library_returns_empty(self):
        with mock.patch.object(config, "LIB_ROOT", os.path.join(tempfile.gettempdir(), "definitely-missing-xyz")):
            self.assertEqual(store.list_items(), [])


if __name__ == "__main__":
    unittest.main()
