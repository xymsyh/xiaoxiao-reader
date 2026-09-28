# 美式 IPA 词典来源

`en_US.txt` 是 [open-dict-data/ipa-dict](https://github.com/open-dict-data/ipa-dict) 的 English (General American) 词表，原样随项目分发，用于离线查询，不是从拼写推测音标。

- 上游版本：`43c3570eb3553bdd19fccd2bd0091534889af023`
- 原始文件：[data/en_US.txt](https://github.com/open-dict-data/ipa-dict/blob/43c3570eb3553bdd19fccd2bd0091534889af023/data/en_US.txt)
- SHA-256：`2af6f154a5c363275f052d1f85acedef38ed185ca9745aa4314be77f6b70de67`
- 文件约 3.2 MB，125,927 行；一词可能包含多个读音，不能按词性自动消歧。
- 保留上游 IPA 符号（例如 `ɹ`、`ɫ`）和重音标记，因此可能与其他学习词典的转写习惯不同。

上游说明美式数据基于 [lingz/cmudict-ipa](https://github.com/lingz/cmudict-ipa)，并使用 [syllabify](https://github.com/kylebgorman/syllabify) 添加重音。更早的数据来源为 CMU Pronouncing Dictionary。

本目录附带 ipa-dict、cmudict-ipa 和 CMUdict 的许可文件。查询结果反映该版本词表，可能存在遗漏或错误；未收录时不尝试自动生成读音。
