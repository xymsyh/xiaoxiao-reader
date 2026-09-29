"""翻译浮窗内容：本地词条分层展示，在线译文保持紧凑。"""
import tkinter as tk


def 创建翻译卡片(父窗口, 内容):
    背景 = "#1e1e1e"
    卡片 = tk.Frame(父窗口, bg=背景, padx=18, pady=14)
    卡片.pack(fill="both", expand=True)
    数据 = 内容 if isinstance(内容, dict) else {"译文": 内容}

    def 标签(文本, 字体, 颜色, 下间距=0):
        控件 = tk.Label(卡片, text=文本, font=字体, fg=颜色, bg=背景,
                      wraplength=400, justify="left", anchor="w", bd=0)
        控件.pack(fill="x", pady=(0, 下间距))
        return 控件

    if 数据.get("类型") == "单词":
        tk.Frame(卡片, width=380, height=0, bg=背景).pack()
        查询词 = 数据.get("查询词")
        词头 = 数据["单词"]
        标题 = f"{查询词}  →  {词头}" if 查询词 and 查询词.casefold() != 词头.casefold() else 词头
        标签(标题, ("Segoe UI", 19, "bold"), "#f5f5f5", 3)
        if 数据.get("词形关系"):
            标签(数据["词形关系"], ("微软雅黑", 9), "#9ba7b7", 7)

        if 数据.get("音标"):
            标签("ECDICT 音标", ("微软雅黑", 9), "#9ba7b7", 2)
            标签(数据["音标"], ("Segoe UI", 13), "#8dc8ff", 3)
        else:
            标签("ECDICT 暂未收录音标", ("微软雅黑", 10), "#9ba7b7", 7)

        tk.Frame(卡片, height=1, bg="#39414c").pack(fill="x", pady=(5, 9))
        for 序号, 义项 in enumerate(数据.get("义项", [])[:8], 1):
            说明 = " · ".join(x for x in (义项.get("词性"), 义项.get("领域")) if x)
            前缀 = f"{序号}. " + (f"{说明}  " if 说明 else "")
            标签(前缀 + 义项["释义"], ("微软雅黑", 12), "#ffffff", 5)

        词形 = 数据.get("词形", [])
        if 词形:
            tk.Frame(卡片, height=1, bg="#303740").pack(fill="x", pady=(4, 7))
            标签("词形  " + "　".join(f"{项['类型']} {项['值']}" for 项 in 词形[:6]),
               ("微软雅黑", 9), "#b9c2cc", 5)
        if 数据.get("标签"):
            标签(" · ".join(数据["标签"][:8]), ("Segoe UI", 9), "#7f8b99", 2)
        标签("数据：" + " · ".join(数据.get("来源", [])), ("微软雅黑", 8), "#68727e")
        return 卡片

    标签(数据.get("译文", str(内容)), ("微软雅黑", 14), "#ffffff")
    return 卡片
