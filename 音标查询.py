"""从随项目分发的 General American 词典读取 IPA，不联网、不猜读音。"""
from functools import lru_cache
from pathlib import Path
import re


词典路径 = Path(__file__).resolve().parent / "data" / "en_US.txt"


def 提取英文单词(文本):
    文本 = 文本.strip().replace("’", "'").strip("\"'“”‘.,!?;:()[]{}，。！？；：（）")
    if re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", 文本):
        return 文本.lower()
    return None


@lru_cache(maxsize=1)
def 加载词典():
    # 只在第一次查询时加载，后续查词复用内存；相对模块定位，兼容从其他目录启动。
    with 词典路径.open(encoding="utf-8") as 文件:
        return dict(行.rstrip("\n").split("\t", 1) for 行 in 文件 if "\t" in 行)


def 构建翻译结果(原文, 待翻译文本, 译文):
    结果 = {"译文": 译文}
    单词 = 提取英文单词(原文)
    # 驼峰/下划线被拆为多个词时，保持普通翻译布局。
    if not 单词 or 单词 != 提取英文单词(待翻译文本):
        return 结果
    结果["单词"] = 单词
    try:
        音标 = 加载词典().get(单词)
    except (OSError, UnicodeError):
        结果["音标提示"] = "美式 IPA 暂不可用（本地词典无法读取）"
    else:
        if 音标:
            结果["音标"] = list(dict.fromkeys(项.strip() for 项 in 音标.split(",") if 项.strip()))
        else:
            结果["音标提示"] = "美式 IPA 暂未收录"
    return 结果
