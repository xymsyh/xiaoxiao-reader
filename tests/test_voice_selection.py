import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "01 ⭐️ 主程序.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))


def load_function(name, environment):
    node = next(item for item in TREE.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), environment)
    return environment[name]


class VoiceSelectionTests(unittest.TestCase):
    def test_plain_english_uses_clara(self):
        is_english = load_function("是纯英文", {})
        choose_voice = load_function(
            "选择朗读语音",
            {
                "是纯英文": is_english,
                "纯英文语音": "en-CA-ClaraNeural",
                "语音": "zh-CN-XiaoxiaoNeural",
            },
        )

        self.assertEqual(choose_voice("Hello, world! 2026"), "en-CA-ClaraNeural")

    def test_non_english_text_keeps_default_voice(self):
        is_english = load_function("是纯英文", {})
        choose_voice = load_function(
            "选择朗读语音",
            {
                "是纯英文": is_english,
                "纯英文语音": "en-CA-ClaraNeural",
                "语音": "zh-CN-XiaoxiaoNeural",
            },
        )

        for text in ("你好", "Hello 世界", "12345", "café"):
            with self.subTest(text=text):
                self.assertEqual(choose_voice(text), "zh-CN-XiaoxiaoNeural")

    def test_clara_cache_does_not_reuse_old_default_voice_audio(self):
        cache_key = load_function("语音缓存键", {"语音": "zh-CN-XiaoxiaoNeural"})

        self.assertEqual(cache_key("你好", "zh-CN-XiaoxiaoNeural"), "你好")
        self.assertNotEqual(
            cache_key("Hello", "en-CA-ClaraNeural"),
            cache_key("Hello", "zh-CN-XiaoxiaoNeural"),
        )


if __name__ == "__main__":
    unittest.main()
