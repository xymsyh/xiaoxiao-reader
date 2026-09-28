"""支持异步补充剑桥音标，更新时保持浮窗位置和中文译文。"""
import tkinter as tk
from urllib.parse import urlsplit
import webbrowser


class 翻译卡片(tk.Frame):
    def __init__(self, 父窗口, 内容):
        self.背景 = "#1e1e1e"
        super().__init__(父窗口, bg=self.背景, padx=18, pady=14)
        self.pack(fill="both", expand=True)
        self.数据 = dict(内容) if isinstance(内容, dict) else {"译文": 内容}
        self.单词卡片 = bool(self.数据.get("单词"))
        if self.单词卡片:
            tk.Frame(self, width=300, height=0, bg=self.背景).pack()
            self._标签(self.数据["单词"], ("Segoe UI", 19, "bold"), "#f5f5f5", 5)
            self.来源标签 = self._标签("剑桥词典 · 美式 IPA", ("微软雅黑", 9), "#9ba7b7", 3)
            self.音标标签 = self._标签("", ("Segoe UI", 14), "#8dc8ff", 10)
            tk.Frame(self, height=1, bg="#39414c").pack(fill="x", pady=(0, 10))
        self._标签(self.数据["译文"], ("微软雅黑", 14), "#ffffff")
        if self.单词卡片:
            self.版权标签 = self._标签("", ("Segoe UI", 8), "#8b96a6")
            self.原页按钮 = tk.Button(self, text="查看剑桥原页 ↗", font=("微软雅黑", 9),
                                   fg="#9fbce0", bg=self.背景, activebackground="#303946",
                                   activeforeground="white", relief="flat", bd=0,
                                   cursor="hand2", command=self._打开原页)
            self.原页按钮.pack(anchor="w", pady=(8, 0))
            self.更新音标({})

    def _标签(self, 文本, 字体, 颜色, 下间距=0):
        控件 = tk.Label(self, text=文本, font=字体, fg=颜色, bg=self.背景,
                      wraplength=400, justify="left", anchor="w", bd=0)
        控件.pack(fill="x", pady=(0, 下间距))
        return 控件

    def 更新音标(self, 数据):
        if not self.单词卡片:
            return
        self.数据.update(数据)
        if self.数据.get("音标"):
            self.音标标签.configure(text="\n".join(self.数据["音标"]),
                                    font=("Segoe UI", 14), fg="#8dc8ff")
            self.版权标签.configure(text=self.数据.get("音标版权", ""))
        else:
            self.音标标签.configure(text=self.数据.get("音标提示", "暂未获取到剑桥美式音标"),
                                    font=("微软雅黑", 10), fg="#9ba7b7")
        self.原页按钮.configure(state="normal" if self.数据.get("词典链接") else "disabled")

    def _打开原页(self):
        url = self.数据.get("词典链接", "")
        地址 = urlsplit(url)
        if 地址.scheme == "https" and 地址.netloc == "dictionary.cambridge.org":
            webbrowser.open(url)


def 创建翻译卡片(父窗口, 内容):
    return 翻译卡片(父窗口, 内容)
