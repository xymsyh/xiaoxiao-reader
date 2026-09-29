import ast
import asyncio
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock

from 本地词典 import (_词典连接, 提取英文单词, 查询本地词典,
                      是单词查询, 本地词典不可用)


class LocalDictionaryTests(unittest.TestCase):
    def test_single_word_recognition(self):
        for text, expected in [("Hello!", "hello"), ("“apple”", "apple"),
                               ("don't", "don't"), ("don’t", "don't"),
                               ("well-known", "well-known")]:
            with self.subTest(text=text):
                self.assertEqual(提取英文单词(text), expected)
        for text in ("hello world", "hello\nworld", "你好", "hello_world", "123", "", "C++"):
            self.assertIsNone(提取英文单词(text))

    def test_configuration_uses_ecdict_phonetic_directly(self):
        result = 查询本地词典("configuration")
        self.assertEqual(result["类型"], "单词")
        self.assertEqual(result["音标"], "kәn.figju'reiʃәn")
        self.assertEqual(result["来源"], ["ECDICT"])
        self.assertTrue(any("配置" in item["释义"] for item in result["义项"]))
        self.assertTrue(any(item["类型"] == "复数" for item in result["词形"]))

    def test_inflection_returns_richer_lemma_entry(self):
        result = 查询本地词典("configurations")
        self.assertEqual(result["单词"], "configuration")
        self.assertEqual(result["词形关系"], "复数")

    def test_phrase_identifier_and_unknown_word(self):
        self.assertFalse(是单词查询("hello world", "hello world"))
        self.assertFalse(是单词查询("helloWorld", "hello World"))
        self.assertFalse(是单词查询("hello_world", "hello world"))
        self.assertIsNone(查询本地词典("zzzxxyyzz"))

    def test_missing_dictionary_has_explicit_error(self):
        path = Path(tempfile.gettempdir()) / "definitely-missing-dictionary.sqlite3"
        path.unlink(missing_ok=True)
        with self.assertRaises(本地词典不可用):
            _词典连接(path).查询("apple")


class TranslationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).resolve().parents[1] / "01 ⭐️ 主程序.py"
        tree = ast.parse(cls.source.read_text(encoding="utf-8-sig"))
        cls.node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "翻译并显示")

    def _environment(self, local_result, cached=None, key="fake-test-key"):
        messages = queue.Queue()
        api = Mock(return_value="在线结果")
        save = Mock()
        history = Mock()
        env = {
            "asyncio": asyncio,
            "预处理翻译文本": lambda x: x,
            "缓存键": lambda x: x.lower(),
            "翻译缓存": {} if cached is None else cached,
            "KEY": key,
            "调用翻译接口": api,
            "保存翻译缓存": save,
            "更新翻译记录": history,
            "翻译队列": messages,
            "是单词查询": lambda original, processed: " " not in processed,
            "提取英文单词": lambda x: x.lower(),
            "查询本地词典": Mock(return_value=local_result),
            "生成记录摘要": lambda x: "本地摘要",
            "本地词典不可用": 本地词典不可用,
        }
        exec(compile(ast.Module(body=[self.node], type_ignores=[]), str(self.source), "exec"), env)
        return env, messages, api, save, history

    def test_local_word_never_calls_translation_api(self):
        local = 查询本地词典("configuration")
        env, messages, api, _, history = self._environment(local, key="")
        asyncio.run(env["翻译并显示"]("configuration"))
        self.assertEqual(messages.get_nowait()["类型"], "单词")
        api.assert_not_called()
        history.assert_called_once()

    def test_phrase_keeps_online_cache_path(self):
        env, messages, api, _, history = self._environment(None, cached={"hello world": "你好世界"})
        asyncio.run(env["翻译并显示"]("hello world"))
        self.assertEqual(messages.get_nowait(), {"类型": "在线翻译", "译文": "你好世界"})
        api.assert_not_called()
        history.assert_called_once_with("hello world", "hello world", "你好世界")


if __name__ == "__main__":
    unittest.main()
