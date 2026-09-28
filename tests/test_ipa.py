import ast
import asyncio
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch

import 音标查询
from 音标查询 import 提取英文单词, 构建翻译结果


class IPATests(unittest.TestCase):
    def test_single_word_recognition(self):
        for text, expected in [("Hello!", "hello"), ("“apple”", "apple"),
                               ("don't", "don't"), ("don’t", "don't"), ("well-known", "well-known")]:
            with self.subTest(text=text):
                self.assertEqual(提取英文单词(text), expected)
        for text in ("hello world", "hello\nworld", "你好", "hello_world", "123", "", "C++"):
            self.assertIsNone(提取英文单词(text))

    def test_bundled_american_dictionary(self):
        result = 构建翻译结果("apple", "apple", "苹果")
        self.assertEqual(result["音标"], ["/ˈæpəɫ/"])
        self.assertEqual(result["译文"], "苹果")
        self.assertGreater(len(构建翻译结果("read", "read", "读")["音标"]), 1)

    def test_phrases_and_split_identifiers_keep_plain_layout(self):
        for original, processed in (("hello world", "hello world"),
                                    ("helloWorld", "hello World"), ("hello_world", "hello world")):
            self.assertEqual(构建翻译结果(original, processed, "你好世界"), {"译文": "你好世界"})

    def test_configuration_corrected_pronunciation(self):
        for word in ("configuration", "Configuration", "configuration!"):
            with self.subTest(word=word):
                result = 构建翻译结果(word, word, "配置")
                self.assertEqual(result["音标"], ["/kənˌfɪɡjəˈreɪʃən/"])
        # 其他词中的卷舌元音不得被全局替换。
        self.assertIn("ɝ", " ".join(构建翻译结果("bird", "bird", "鸟")["音标"]))

    def test_unknown_word_and_missing_dictionary_do_not_break_translation(self):
        self.assertIn("未收录", 构建翻译结果("zzzxxyyzz", "zzzxxyyzz", "测试")["音标提示"])
        with patch.object(音标查询, "加载词典", side_effect=FileNotFoundError):
            result = 构建翻译结果("apple", "apple", "苹果")
            self.assertIn("无法读取", result["音标提示"])
            self.assertEqual(result["译文"], "苹果")


class TranslationIntegrationTests(unittest.TestCase):
    def test_cached_and_fresh_translations_both_include_ipa(self):
        source = Path(__file__).resolve().parents[1] / "01 ⭐️ 主程序.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "翻译并显示")
        for cached in (True, False):
            with self.subTest(cached=cached):
                messages = queue.Queue()
                api = Mock(return_value="苹果")
                save = Mock()
                history = Mock()
                env = {"asyncio": asyncio, "预处理翻译文本": lambda x: x,
                       "缓存键": lambda x: x.lower(), "翻译缓存": {"apple": "苹果"} if cached else {},
                       "KEY": "fake-test-key", "调用翻译接口": api, "保存翻译缓存": save,
                       "更新翻译记录": history, "翻译队列": messages, "构建翻译结果": 构建翻译结果}
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), env)
                asyncio.run(env["翻译并显示"]("apple"))
                self.assertEqual(messages.get_nowait()["音标"], ["/ˈæpəɫ/"])
                self.assertEqual(api.call_count, 0 if cached else 1)
                history.assert_called_once_with("apple", "apple", "苹果")


if __name__ == "__main__":
    unittest.main()
