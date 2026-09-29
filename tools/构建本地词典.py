"""从固定版本 ECDICT 构建运行时 SQLite 词典。

用法：python tools/构建本地词典.py [ECDICT_CSV]
未传 CSV 时会下载固定提交版本。构建结果写入 data/dictionary.sqlite3。
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import urllib.request


根目录 = Path(__file__).resolve().parents[1]
输出路径 = 根目录 / "data" / "dictionary.sqlite3"
ECDICT提交 = "bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b"
ECDICT地址 = f"https://raw.githubusercontent.com/skywind3000/ECDICT/{ECDICT提交}/ecdict.csv"
ECDICT摘要 = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"


def 下载ECDICT() -> Path:
    路径 = Path(tempfile.gettempdir()) / f"ecdict-{ECDICT提交}.csv"
    if not 路径.exists():
        print(f"下载 ECDICT：{ECDICT地址}")
        urllib.request.urlretrieve(ECDICT地址, 路径)
    return 路径


def 是单词(文本: str) -> bool:
    return bool(文本 and " " not in 文本 and all(字符.isalpha() or 字符 in "-'" for 字符 in 文本))


def 添加词形(连接, 词头, 交换, 优先级):
    for 项 in (交换 or "").split("/"):
        if ":" not in 项:
            continue
        类型, 值 = 项.split(":", 1)
        if 类型 in {"p", "d", "i", "3", "r", "t", "s"} and 是单词(值):
            连接.execute(
                "INSERT OR IGNORE INTO forms(form_key, lemma, relation, priority) VALUES(?,?,?,?)",
                (值.casefold(), 词头.casefold(), 类型, 优先级),
            )


def 构建(csv路径: Path):
    临时输出 = 输出路径.with_suffix(".sqlite3.building")
    临时输出.unlink(missing_ok=True)
    连接 = sqlite3.connect(临时输出)
    连接.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE entries(
            word_key TEXT PRIMARY KEY,
            word TEXT NOT NULL,
            phonetic TEXT NOT NULL DEFAULT '',
            translation TEXT NOT NULL DEFAULT '',
            definition TEXT NOT NULL DEFAULT '',
            pos TEXT NOT NULL DEFAULT '',
            exchange TEXT NOT NULL DEFAULT '',
            tag TEXT NOT NULL DEFAULT '',
            bnc INTEGER NOT NULL DEFAULT 0,
            frq INTEGER NOT NULL DEFAULT 0,
            collins INTEGER NOT NULL DEFAULT 0,
            oxford INTEGER NOT NULL DEFAULT 0
        ) WITHOUT ROWID;
        CREATE TABLE forms(
            form_key TEXT NOT NULL,
            lemma TEXT NOT NULL,
            relation TEXT NOT NULL,
            priority INTEGER NOT NULL,
            PRIMARY KEY(form_key, lemma, relation)
        ) WITHOUT ROWID;
        CREATE INDEX forms_lookup ON forms(form_key, priority);
    """)

    摘要 = hashlib.sha256()
    数量 = 0
    with csv路径.open("rb") as 原始文件:
        for 块 in iter(lambda: 原始文件.read(1024 * 1024), b""):
            摘要.update(块)
    实际摘要 = 摘要.hexdigest()
    if 实际摘要 != ECDICT摘要:
        连接.close()
        临时输出.unlink(missing_ok=True)
        raise ValueError(f"ECDICT CSV 校验失败：期望 {ECDICT摘要}，实际 {实际摘要}")
    with csv路径.open(encoding="utf-8", newline="") as 文件:
        for 行 in csv.DictReader(文件):
            词头 = 行["word"].strip()
            if not 是单词(词头) or not 行["translation"].strip():
                continue
            def 数字(键):
                try:
                    return int(行[键] or 0)
                except ValueError:
                    return 0
            值 = (
                词头.casefold(), 词头, 行["phonetic"], 行["translation"], 行["definition"],
                行["pos"], 行["exchange"], 行["tag"], 数字("bnc"), 数字("frq"),
                数字("collins"), 数字("oxford"),
            )
            连接.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", 值)
            排名 = min(x for x in (数字("frq"), 数字("bnc"), 9999999) if x > 0)
            添加词形(连接, 词头, 行["exchange"], 排名)
            数量 += 1

    元数据 = {
        "schema_version": "1",
        "entry_count": str(数量),
        "ecdict_commit": ECDICT提交,
        "ecdict_sha256": 实际摘要,
    }
    连接.executemany("INSERT INTO metadata VALUES(?,?)", 元数据.items())
    连接.commit()
    连接.execute("VACUUM")
    连接.close()
    try:
        临时输出.replace(输出路径)
    except PermissionError:
        # Windows 上失败的 replace 可能短暂保留源文件句柄，稍后重试清理。
        for _ in range(10):
            try:
                临时输出.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.1)
        raise SystemExit("无法替换本地词典；请先退出正在运行的晓晓朗读，再重新构建。") from None
    print(f"已生成 {输出路径}，{数量:,} 个词条，{输出路径.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    来源 = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else 下载ECDICT()
    构建(来源)
