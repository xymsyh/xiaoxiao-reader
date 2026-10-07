import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "01 ⭐️ 主程序.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))


def load_function(name, environment):
    node = next(item for item in TREE.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), environment)
    return environment[name]


class AudioForwardingTests(unittest.TestCase):
    def test_sends_mp3_with_expected_headers_without_system_proxy(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

        class FakeSession:
            def __init__(self):
                self.trust_env = True
                self.call = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def post(self, url, **kwargs):
                self.call = (url, kwargs)
                return FakeResponse()

        session = FakeSession()
        environment = {
            "requests": SimpleNamespace(Session=lambda: session),
            "音频发送地址": "https://audio.vui.ink/api/play",
            "音频发送文件名": "notice.mp3",
        }
        function = load_function("发送朗读音频", environment)

        function(b"mp3-data")

        self.assertFalse(session.trust_env)
        url, kwargs = session.call
        self.assertEqual(url, "https://audio.vui.ink/api/play")
        self.assertEqual(kwargs["headers"]["Content-Type"], "audio/mpeg")
        self.assertEqual(kwargs["headers"]["X-Filename"], "notice.mp3")
        self.assertEqual(kwargs["data"], b"mp3-data")
        self.assertEqual(kwargs["timeout"], (5, 30))


if __name__ == "__main__":
    unittest.main()
