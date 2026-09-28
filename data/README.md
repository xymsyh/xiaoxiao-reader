# 美式 IPA 词典来源

`en_US.txt` 基于 [open-dict-data/ipa-dict](https://github.com/open-dict-data/ipa-dict) 的 English (General American) 词表，随项目分发并进行下方记录的单词级修正，用于离线查询，不是从拼写推测音标。

- 上游版本：`43c3570eb3553bdd19fccd2bd0091534889af023`
- 原始文件：[data/en_US.txt](https://github.com/open-dict-data/ipa-dict/blob/43c3570eb3553bdd19fccd2bd0091534889af023/data/en_US.txt)
- 上游原始文件 SHA-256（不含本项目修正）：`2af6f154a5c363275f052d1f85acedef38ed185ca9745aa4314be77f6b70de67`
- 文件约 3.2 MB，125,927 行；一词可能包含多个读音，不能按词性自动消歧。
- 保留上游 IPA 符号（例如 `ɹ`、`ɫ`）和重音标记，因此可能与其他学习词典的转写习惯不同。

上游说明美式数据基于 [lingz/cmudict-ipa](https://github.com/lingz/cmudict-ipa)，并使用 [syllabify](https://github.com/kylebgorman/syllabify) 添加重音。更早的数据来源为 CMU Pronouncing Dictionary。

本目录附带 ipa-dict、cmudict-ipa 和 CMUdict 的许可文件。查询结果反映该版本词表，可能存在遗漏或错误；未收录时不尝试自动生成读音。

## 单词级修正记录

| 单词 | 上游标注 | 本项目标注 | 依据 |
| --- | --- | --- | --- |
| configuration | /kənˌfɪɡjɝˈeɪʃən/ | /kənˌfɪɡjəˈreɪʃən/ | 用户确认，符合[剑桥词典美式标注](https://dictionary.cambridge.org/us/pronunciation/english/configuration)，省略音节分隔点 |

仅修正明确核对的词条，不全局替换 `ɝ`。升级上游词表时需保留上述修正并运行回归测试。
