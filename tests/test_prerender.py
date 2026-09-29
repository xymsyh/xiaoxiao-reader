import ast
import asyncio
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


SOURCE = Path(__file__).resolve().parents[1] / "01 ⭐️ 主程序.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))


def load_function(name, environment):
    node = next(item for item in TREE.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), environment)
    return environment[name]


class PrerenderExitTests(unittest.TestCase):
    def test_success_waits_five_seconds(self):
        fake_time = Mock()
        function = load_function("等待预渲染结束", {"time": fake_time})
        function(True)
        fake_time.sleep.assert_called_once_with(5)

    def test_failure_keeps_window_open_until_interrupted(self):
        fake_time = Mock()
        fake_time.sleep.side_effect = KeyboardInterrupt
        function = load_function("等待预渲染结束", {"time": fake_time})
        function(False)
        fake_time.sleep.assert_called_once_with(3600)

    def test_failure_does_not_depend_on_stdin(self):
        fake_time = Mock()
        fake_time.sleep.side_effect = KeyboardInterrupt
        function = load_function("等待预渲染结束", {"time": fake_time})
        function(False)
        fake_time.sleep.assert_called_once_with(3600)

    def test_empty_clipboard_is_failure(self):
        clipboard = Mock()
        clipboard.paste.return_value = ""
        function = load_function("执行预渲染", {"pyperclip": clipboard})
        self.assertFalse(asyncio.run(function()))


class PrerenderReliabilityTests(unittest.TestCase):
    def test_extraction_deduplicates_case_insensitive_cache_keys(self):
        function = load_function(
            "提取预渲染文本",
            {"re": re, "语音缓存键": lambda text: text.strip().lower()},
        )
        result = function("Hello hello HELLO")
        words = [text for kind, text in result if kind == "单词"]
        self.assertEqual(words, ["Hello"])

    def test_tts_retries_transient_failures(self):
        calls = {"count": 0}

        class FakeCommunication:
            def __init__(self, attempt):
                self.attempt = attempt

            async def stream(self):
                if self.attempt < 3:
                    raise RuntimeError("429 Invalid response status")
                yield {"type": "audio", "data": b"audio"}

        def communicate(**_kwargs):
            calls["count"] += 1
            return FakeCommunication(calls["count"])

        sleep = AsyncMock()
        environment = {
            "edge_tts": SimpleNamespace(Communicate=communicate),
            "选择朗读语音": lambda _text: "test-voice",
            "预渲染单项重试次数": 4,
            "asyncio": SimpleNamespace(sleep=sleep),
        }
        function = load_function("生成预渲染音频", environment)
        audio, attempts, error = asyncio.run(function("hello"))
        self.assertEqual(audio, b"audio")
        self.assertEqual(attempts, 3)
        self.assertIsNone(error)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1, 2])

    def test_worker_pool_caps_concurrency(self):
        active = 0
        maximum = 0

        async def render(kind, text, _attempts):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return True, f"[{kind}] {text}"

        environment = {
            "asyncio": asyncio,
            "预渲染单项重试次数": 4,
            "预渲染单项": render,
        }
        function = load_function("批量执行预渲染", environment)
        items = [("单词", str(index)) for index in range(12)]
        results = asyncio.run(function(items, 并发数=3))
        self.assertEqual(len(results), len(items))
        self.assertLessEqual(maximum, 3)

    def test_first_pass_can_run_all_items_concurrently(self):
        active = 0
        maximum = 0

        async def render(kind, text, _attempts):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return True, f"[{kind}] {text}"

        environment = {
            "asyncio": asyncio,
            "预渲染单项重试次数": 4,
            "预渲染单项": render,
        }
        function = load_function("批量执行预渲染", environment)
        items = [("单词", str(index)) for index in range(12)]
        results = asyncio.run(function(items, 并发数=None, 单项重试次数=1))
        self.assertEqual(len(results), len(items))
        self.assertEqual(maximum, len(items))


if __name__ == "__main__":
    unittest.main()
