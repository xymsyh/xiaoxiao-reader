import ast
from pathlib import Path
import re
import tempfile
import unittest

from 配置读取 import 初始化配置, 读取配置


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "配置示例.ini").read_text(encoding="utf-8")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "配置.ini"

    def write(self, content):
        self.path.write_text(content, encoding="utf-8-sig")

    def test_initialization_never_overwrites_user_config(self):
        self.assertTrue(初始化配置(self.path))
        self.write(TEMPLATE.replace("f14", "f8"))
        self.assertFalse(初始化配置(self.path))
        self.assertEqual(读取配置(self.path)["按键映射"]["拖选朗读"], "f8")

    def test_blank_key_and_custom_keys(self):
        self.write(TEMPLATE.replace("f14", "F8").replace("f15", "f9").replace("f16", "f10"))
        result = 读取配置(self.path)
        self.assertEqual(list(result["按键映射"].values()), ["f8", "f9", "f10"])
        self.assertEqual(result["微软翻译API"]["密钥"], "")

    def test_literal_secret_characters(self):
        self.write(TEMPLATE.replace("密钥 =", "密钥 = test%value#not-a-real-secret"))
        self.assertEqual(读取配置(self.path)["微软翻译API"]["密钥"], "test%value#not-a-real-secret")

    def test_invalid_configs(self):
        for content in (
            TEMPLATE.replace("f15", "f14"),
            TEMPLATE.replace("f14", "ctrl+f8"),
            TEMPLATE.replace("区域 = eastasia", "区域 ="),
            TEMPLATE.replace("https://api.cognitive.microsofttranslator.com/translate", "invalid"),
            "[broken",
        ):
            with self.subTest(content=content):
                self.write(content)
                with self.assertRaises(ValueError):
                    读取配置(self.path)

    def test_missing_config(self):
        with self.assertRaisesRegex(ValueError, "找不到配置文件"):
            读取配置(self.path)


class TextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 只加载纯文本函数，避免测试时注册全局按键、打开音频设备或联网。
        tree = ast.parse((ROOT / "01 ⭐️ 主程序.py").read_text(encoding="utf-8-sig"))
        names = {"含中文", "是否是代码", "拆分驼峰", "预处理翻译文本"}
        selected = [node for node in tree.body if
                    (isinstance(node, ast.FunctionDef) and node.name in names) or
                    (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id in {"_代码关键词", "_代码符号"})]
        cls.functions = {"re": re}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "text-functions", "exec"), cls.functions)

    def test_normal_english_is_not_code(self):
        self.assertFalse(self.functions["是否是代码"]("This is a useful tool for reading."))

    def test_code_and_chinese_detection(self):
        self.assertTrue(self.functions["是否是代码"]("def hello():\n    return True"))
        self.assertTrue(self.functions["含中文"]("hello 世界"))
        self.assertFalse(self.functions["含中文"]("hello"))

    def test_identifier_preprocessing(self):
        self.assertEqual(self.functions["预处理翻译文本"]("WindowsSelectorEventLoopPolicy_test"),
                         "Windows Selector Event Loop Policy test")


if __name__ == "__main__":
    unittest.main()
