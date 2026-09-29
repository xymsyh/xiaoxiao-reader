"""本地英汉词典查询。

运行时只读取随程序分发的 SQLite 数据库。数据库由 tools/构建本地词典.py 生成，
中文释义和音标都直接来自 ECDICT。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sqlite3
import threading
import unicodedata


数据库路径 = Path(__file__).resolve().parent / "data" / "dictionary.sqlite3"

_外围标点 = "\"'“”‘’.,!?;:()[]{}，。！？；：（）<>《》"
_词性名称 = {
    "n": "名词", "v": "动词", "vt": "及物动词", "vi": "不及物动词",
    "a": "形容词", "adj": "形容词", "ad": "副词", "adv": "副词", "prep": "介词", "conj": "连词",
    "pron": "代词", "num": "数词", "art": "冠词", "aux": "助动词",
    "int": "感叹词", "abbr": "缩写",
}
_词形名称 = {
    "p": "过去式", "d": "过去分词", "i": "现在分词", "3": "第三人称单数",
    "r": "比较级", "t": "最高级", "s": "复数", "0": "原形", "1": "词形",
}
_词性前缀 = re.compile(
    r"^(?P<pos>n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|num|art|aux|int|abbr)\.\s*",
    re.IGNORECASE,
)


class 本地词典不可用(RuntimeError):
    """词典文件缺失、损坏或版本不兼容。"""


def 提取英文单词(文本: str) -> str | None:
    """识别一个英文词；允许内部撇号和连字符，不接受短语与标识符。"""
    文本 = unicodedata.normalize("NFKC", 文本).strip().replace("’", "'")
    文本 = 文本.strip(_外围标点)
    if re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", 文本):
        return 文本.casefold()
    return None


def 是单词查询(原文: str, 处理后文本: str) -> bool:
    单词 = 提取英文单词(原文)
    return bool(单词 and 单词 == 提取英文单词(处理后文本))


class _词典连接:
    def __init__(self, 路径: Path):
        self.路径 = 路径
        self._连接: sqlite3.Connection | None = None
        self._锁 = threading.RLock()

    def _获取连接(self) -> sqlite3.Connection:
        if self._连接 is not None:
            return self._连接
        if not self.路径.is_file():
            raise 本地词典不可用(f"找不到本地词典：{self.路径}")
        try:
            uri = self.路径.resolve().as_uri() + "?mode=ro&immutable=1"
            连接 = sqlite3.connect(uri, uri=True, check_same_thread=False)
            连接.row_factory = sqlite3.Row
            版本 = 连接.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        except sqlite3.Error as exc:
            raise 本地词典不可用(f"无法打开本地词典：{exc}") from exc
        if not 版本 or 版本[0] != "1":
            连接.close()
            raise 本地词典不可用("本地词典版本不兼容")
        self._连接 = 连接
        return 连接

    def 查询(self, 单词: str) -> dict | None:
        with self._锁:
            连接 = self._获取连接()
            try:
                词条 = 连接.execute(
                    "SELECT * FROM entries WHERE word_key=?", (单词.casefold(),)
                ).fetchone()
                词形关系 = None

                # ECDICT 会给许多屈折形式单独建词条；优先回到信息更完整的原形。
                if 词条:
                    原形 = _从交换字段取原形(词条["exchange"])
                    if 原形 and 原形.casefold() != 词条["word_key"]:
                        原形词条 = 连接.execute(
                            "SELECT * FROM entries WHERE word_key=?", (原形.casefold(),)
                        ).fetchone()
                        if 原形词条:
                            词形关系 = _推断词形关系(词条["exchange"])
                            词条 = 原形词条

                if not 词条:
                    映射 = 连接.execute(
                        "SELECT lemma, relation FROM forms WHERE form_key=? "
                        "ORDER BY priority LIMIT 1", (单词.casefold(),)
                    ).fetchone()
                    if 映射:
                        词条 = 连接.execute(
                            "SELECT * FROM entries WHERE word_key=?", (映射["lemma"].casefold(),)
                        ).fetchone()
                        词形关系 = _词形名称.get(映射["relation"], 映射["relation"])

                if not 词条:
                    return None

            except sqlite3.Error as exc:
                raise 本地词典不可用(f"查询本地词典失败：{exc}") from exc

        return _构建结果(单词, 词条, 词形关系)


def _从交换字段取原形(交换字段: str) -> str | None:
    for 项 in (交换字段 or "").split("/"):
        if 项.startswith("0:"):
            return 项[2:].strip() or None
    return None


def _推断词形关系(交换字段: str) -> str:
    for 项 in (交换字段 or "").split("/"):
        if 项.startswith("1:"):
            代码 = 项[2:]
            名称 = [_词形名称[c] for c in 代码 if c in _词形名称 and c != "1"]
            return "、".join(名称) if 名称 else "词形变化"
    return "词形变化"


def _解析义项(翻译: str) -> list[dict]:
    义项 = []
    for 原始行 in (翻译 or "").replace("\\n", "\n").splitlines():
        行 = 原始行.strip()
        if not 行:
            continue
        匹配 = _词性前缀.match(行)
        词性 = ""
        if 匹配:
            代码 = 匹配.group("pos").lower()
            词性 = _词性名称.get(代码, 代码)
            行 = 行[匹配.end():].strip()
        领域 = ""
        领域匹配 = re.match(r"^\[([^]]+)]\s*", 行)
        if 领域匹配:
            领域 = 领域匹配.group(1)
            行 = 行[领域匹配.end():].strip()
        if 行:
            义项.append({"词性": 词性, "领域": 领域, "释义": 行})
    return 义项


def _解析词形(交换字段: str, 词头: str) -> list[dict]:
    结果 = []
    已见 = set()
    for 项 in (交换字段 or "").split("/"):
        if ":" not in 项:
            continue
        代码, 值 = 项.split(":", 1)
        if 代码 not in _词形名称 or 代码 in {"0", "1"} or not 值 or 值 == 词头:
            continue
        键 = (代码, 值)
        if 键 not in 已见:
            已见.add(键)
            结果.append({"类型": _词形名称[代码], "值": 值})
    return 结果


def _构建结果(查询词, 词条, 词形关系):
    标签 = (词条["tag"] or "").split()
    if 词条["oxford"]:
        标签.append("Oxford 3000")
    if 词条["collins"]:
        标签.append(f"Collins {词条['collins']}星")

    return {
        "类型": "单词",
        "查询词": 查询词,
        "单词": 词条["word"],
        "词形关系": 词形关系,
        "音标": 词条["phonetic"].strip(),
        "义项": _解析义项(词条["translation"]),
        "词形": _解析词形(词条["exchange"], 词条["word"]),
        "标签": 标签,
        "来源": ["ECDICT"],
    }


_词典 = _词典连接(数据库路径)


@lru_cache(maxsize=2048)
def 查询本地词典(单词: str) -> dict | None:
    return _词典.查询(单词)


def 生成记录摘要(词条: dict) -> str:
    return "；".join(项["释义"] for 项 in 词条.get("义项", [])[:3])
