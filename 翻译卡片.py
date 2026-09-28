"""翻译浮窗内容：单词、IPA、释义分层展示，普通消息保持紧凑。"""
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

    if 数据.get("单词"):
        # 给单词卡片一个稳定的最小宽度，避免短词和多个音标来回跳宽。
        tk.Frame(卡片, width=300, height=0, bg=背景).pack()
        标签(数据["单词"], ("Segoe UI", 19, "bold"), "#f5f5f5", 5)
        if 数据.get("音标"):
            标签("美式 IPA", ("微软雅黑", 9), "#9ba7b7", 3)
            标签("\n".join(数据["音标"]), ("Segoe UI", 14), "#8dc8ff", 10)
        else:
            标签(数据.get("音标提示", "美式 IPA 暂未收录"), ("微软雅黑", 10), "#9ba7b7", 10)
        tk.Frame(卡片, height=1, bg="#39414c").pack(fill="x", pady=(0, 10))
    标签(数据["译文"], ("微软雅黑", 14), "#ffffff")
    return 卡片
