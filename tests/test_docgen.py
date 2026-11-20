import os
import tempfile
import unittest

from ytdip import docgen


def seg(start, end, text):
    return {"idx": 0, "start": start, "end": end, "text": text}


class NormalizeTest(unittest.TestCase):
    def test_halfwidth_comma_between_cjk_becomes_fullwidth(self):
        self.assertEqual(docgen.normalize_text("你好,世界"), "你好，世界")

    def test_ascii_comma_between_latin_is_untouched(self):
        self.assertEqual(docgen.normalize_text("hello, world"), "hello, world")

    def test_empty_input(self):
        self.assertEqual(docgen.normalize_text(""), "")


class DedupeTest(unittest.TestCase):
    def test_drops_adjacent_duplicates(self):
        segments = [seg(0, 1, "同一句"), seg(1, 2, "同一句"), seg(2, 3, "下一句")]
        self.assertEqual([s["text"] for s in docgen.dedupe(segments)], ["同一句", "下一句"])

    def test_drops_empty_segments(self):
        self.assertEqual(docgen.dedupe([seg(0, 1, "  "), seg(1, 2, "有字")]), [seg(1, 2, "有字")])


class ParagraphTest(unittest.TestCase):
    def test_merges_close_segments(self):
        paragraphs = docgen.build_paragraphs([seg(0, 1, "第一句"), seg(1.2, 2, "第二句")], gap=1.2)
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(paragraphs[0]["text"], "第一句，第二句")

    def test_splits_on_gap(self):
        paragraphs = docgen.build_paragraphs([seg(0, 1, "第一句"), seg(5, 6, "第二句")], gap=1.2)
        self.assertEqual(len(paragraphs), 2)

    def test_splits_on_length_limit(self):
        paragraphs = docgen.build_paragraphs(
            [seg(0, 1, "甲" * 10), seg(1.1, 2, "乙" * 10)], gap=1.2, max_chars=15)
        self.assertEqual(len(paragraphs), 2)

    def test_empty_input(self):
        self.assertEqual(docgen.build_paragraphs([]), [])


class OutputTest(unittest.TestCase):
    def test_srt_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.srt")
            docgen.write_srt([seg(0, 1.5, "你好"), seg(61.25, 62, "第二句")], path)
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self.assertEqual(lines[0], "1")
            self.assertEqual(lines[1], "00:00:00,000 --> 00:00:01,500")
            self.assertEqual(lines[2], "你好")
            self.assertEqual(lines[5], "00:01:01,250 --> 00:01:02,000")

    def test_txt_joins_paragraphs_with_blank_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.txt")
            docgen.write_txt([{"start": 0, "end": 1, "text": "一"},
                              {"start": 2, "end": 3, "text": "二"}], path)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "一\n\n二\n")

    def test_stats_counts_speech_and_chars(self):
        counters = docgen.stats([seg(0, 2, "四个字符"), seg(60, 62, "再来四个")], [], 100)
        self.assertEqual(counters["segment_count"], 2)
        self.assertEqual(counters["chars"], 8)
        self.assertAlmostEqual(counters["speech_sec"], 4.0)
        self.assertAlmostEqual(counters["chars_per_min"], 120.0)

    def test_mmss_and_hms(self):
        self.assertEqual(docgen.fmt_mmss(75), "01:15")
        self.assertEqual(docgen.fmt_hms(3725), "01:02:05")


if __name__ == "__main__":
    unittest.main()
