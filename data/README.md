# 本地英汉词典来源

`dictionary.sqlite3` 是供程序运行时只读查询的本地词典，由
[`tools/构建本地词典.py`](../tools/构建本地词典.py) 从 ECDICT 固定版本生成。

- 上游项目：https://github.com/skywind3000/ECDICT
- 固定提交：`bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b`
- 上游 CSV SHA-256：`1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf`
- 收录范围：有中文释义、且词头不含空格的英文单词、连字符词和撇号词
- 当前词条数：401,258
- 使用字段：词头、ECDICT 音标、中英文释义、词性、词形、标签及词频
- 查询方式：本地 SQLite 精确索引；程序运行时不下载、解析或联网更新词典

音标直接显示 ECDICT 的 `phonetic` 字段，不进行 IPA 猜测、口音转换或人工覆盖。
ECDICT 说明该字段以英语英标为主，不保证每个词都具备音标。

ECDICT 项目采用 MIT License，许可证副本见 `ECDICT-LICENSE.txt`。
