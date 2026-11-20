import io
import json
import os
import tempfile
import unittest

from ytdip import events


def parse(buffer):
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.buffer = io.StringIO()
        self.emit = events.Events(job_id="j_test", stream=self.buffer, echo=False, throttle=0)

    def test_stage_and_progress_are_json_lines(self):
        self.emit.start(source="x")
        self.emit.stage("acquire", "开始")
        self.emit.progress("acquire", done=5, total=10)
        payloads = parse(self.buffer)

        self.assertEqual([p["t"] for p in payloads], ["start", "stage", "progress"])
        self.assertTrue(all(p["job"] == "j_test" for p in payloads))
        self.assertEqual(payloads[1]["stage"], "acquire")
        self.assertEqual(payloads[2]["pct"], 50.0)

    def test_progress_without_total_has_no_pct(self):
        self.emit.progress("x", done=1)
        self.assertNotIn("pct", parse(self.buffer)[0])

    def test_result_and_error_shapes(self):
        self.emit.result({"videoId": "1", "files": ["report.md"]})
        self.emit.error("NO_STREAM", "没找到播放地址", "可能已删除")
        result, error = parse(self.buffer)
        self.assertEqual(result["data"]["videoId"], "1")
        self.assertEqual(error["code"], "NO_STREAM")
        self.assertEqual(error["hint"], "可能已删除")

    def test_progress_is_throttled_by_default(self):
        buffer = io.StringIO()
        emit = events.Events(job_id="j", stream=buffer, echo=False, throttle=10)
        emit.progress("s", done=1, total=100)
        emit.progress("s", done=1, total=100)   # 百分比没变，时间也没到
        emit.progress("s", done=1, total=100)
        self.assertEqual(len(parse(buffer)), 1)

    def test_progress_emits_when_percent_jumps(self):
        buffer = io.StringIO()
        emit = events.Events(job_id="j", stream=buffer, echo=False, throttle=10)
        emit.progress("s", done=1, total=100)
        emit.progress("s", done=2, total=100)   # 跳了 1 个百分点就放行
        self.assertEqual(len(parse(buffer)), 2)

    def test_cancel_checker_reads_marker_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "j.cancel")
            check = events.checker(self.emit, marker)
            self.assertFalse(check())
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("1")
            self.assertTrue(check())

    def test_cancel_checker_reads_in_memory_flag(self):
        check = events.checker(self.emit, "")
        self.assertFalse(check())
        self.emit.canceled = True
        self.assertTrue(check())


if __name__ == "__main__":
    unittest.main()
