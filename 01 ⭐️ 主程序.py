import os
import io
import sys
import glob

# 英文 Windows 的重定向输出可能使用 cp1252，统一编码以支持中文和 IPA。
for 输出流 in (sys.stdout, sys.stderr):
    if hasattr(输出流, "reconfigure"):
        输出流.reconfigure(encoding="utf-8", errors="backslashreplace")

if sys.platform != "win32":
    raise SystemExit("晓晓朗读目前仅支持 Windows。")

def _修复tcl环境():
    """修复被污染的 TCL_LIBRARY / TK_LIBRARY 环境变量，
    强制指向当前 Python 解释器自带的 tcl/tk 目录"""
    python目录 = sys.prefix  # 例如 C:\Users\Ran\AppData\Local\Programs\Python\Python38

    def 找目录(模式):
        候选 = sorted(glob.glob(os.path.join(python目录, "tcl", 模式)))
        return 候选[0] if 候选 else None

    tcl目录 = 找目录("tcl8.*")
    tk目录 = 找目录("tk8.*")

    if tcl目录 and os.path.isfile(os.path.join(tcl目录, "init.tcl")):
        os.environ["TCL_LIBRARY"] = tcl目录
    else:
        os.environ.pop("TCL_LIBRARY", None)

    if tk目录 and os.path.isfile(os.path.join(tk目录, "tk.tcl")):
        os.environ["TK_LIBRARY"] = tk目录
    else:
        os.environ.pop("TK_LIBRARY", None)

_修复tcl环境()

# 必须在创建窗口之前启用 DPI 感知，保持框选坐标与截图像素一致。
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk  # 必须在 _修复tcl环境() 之后再导入
import re
import uuid
import queue
import asyncio
import threading
import time
import hashlib
import traceback
from datetime import datetime

# 清除代理环境变量
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

import keyboard
import mouse
import pyperclip
import pygame
import edge_tts
import requests

import json
from 本地词典 import (提取英文单词, 是单词查询, 查询本地词典,
                      生成记录摘要, 本地词典不可用)
from 翻译卡片 import 创建翻译卡片
# 记录拖动后窗口位置的本地文件
位置记录文件 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "翻译窗口位置.json")

# 翻译缓存文件（key -> 译文，用于避免重复调用 API）
翻译缓存文件 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "翻译缓存.json")

# 翻译历史记录文件（JSON 字典，相同内容自动合并计数，供后续用 AI 总结每天学了什么）
翻译记录文件 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "翻译记录.json")

# 语音缓存目录：存放已经合成好的 mp3 音频文件，相同文本下次朗读直接读本地文件播放，
# 跳过 edge-tts 的网络合成，是缩短"选中→出声"延迟的关键
语音缓存目录 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "语音缓存")
os.makedirs(语音缓存目录, exist_ok=True)

# 语音缓存索引文件：key -> {文本/文件名/次数}，仅用于记录和排查，不是查找必需项
语音缓存索引文件 = os.path.join(语音缓存目录, "索引.json")

# ============================================================
# 配置
# ============================================================

语音 = "zh-CN-XiaoxiaoNeural"
纯英文语音 = "en-CA-ClaraNeural"

# 从主程序同目录的 配置.ini 读取按键和 API 设置。
from 配置读取 import 初始化配置, 读取配置

try:
    if 初始化配置():
        print("已生成 配置.ini。可直接朗读；在线翻译请填写微软翻译 API 密钥后重启。")
    配置 = 读取配置()
    按键映射 = 配置["按键映射"]
    已用扫描码 = set()
    for 功能, 键名 in 按键映射.items():
        try:
            扫描码 = set(keyboard.key_to_scan_codes(键名))
        except (ValueError, KeyError):
            raise ValueError(f"配置.ini 中“{功能}”的按键名称无效，请填写单个键，例如 f8。") from None
        if not 扫描码 or 已用扫描码.intersection(扫描码):
            raise ValueError("配置.ini 中存在无效或相互冲突的按键，请为三个功能选择不同的键。")
        已用扫描码.update(扫描码)
except ValueError as e:
    print(f"配置错误：{e}")
    raise SystemExit(1)

KEY = 配置["微软翻译API"]["密钥"]
REGION = 配置["微软翻译API"]["区域"]
ENDPOINT = 配置["微软翻译API"]["地址"]

# 采样率与 edge-tts 输出一致（24kHz 单声道），缓冲区调小，减少起播延迟
pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=512)
pygame.mixer.init()

# 防止 BytesIO 被垃圾回收（pygame 播放期间必须保持引用）
当前音频缓冲 = None

# 拖选键是否处于按下状态（用于防止系统按键重复触发导致重复按下鼠标）
_拖选_按下中 = False

# 选中朗读键是否处于按下状态（用于防止系统按键重复触发导致重复执行）
_选中_按下中 = False
_截图_按下中 = False
OCR请求队列 = queue.Queue()
OCR忙碌 = threading.Event()
OCR引擎 = None
OCR引擎锁 = threading.Lock()

# 主事件循环 & 当前处理任务（用于取消上一次尚未完成的朗读/翻译）
主事件循环 = None
当前处理任务 = None

# 翻译结果 → 悬浮窗口线程 的线程安全队列
翻译队列 = queue.Queue()


# ============================================================
# 获取选中文字
# ============================================================

def 获取选中文本():
    哨兵 = "__CLIPBOARD_WAITING__"

    pyperclip.copy(哨兵)
    keyboard.press_and_release("ctrl+c")

    截止时间 = time.time() + 0.3
    文本 = 哨兵

    while 文本 == 哨兵 and time.time() < 截止时间:
        time.sleep(0.01)
        文本 = pyperclip.paste()

    if 文本 == 哨兵:
        return ""

    文本 = 文本.strip()
    pyperclip.copy(文本)  # 保留选中文本到剪贴板
    return 文本


def 含中文(文本):
    return bool(re.search(r"[\u4e00-\u9fff]", 文本))


def 是纯英文(文本):
    """文本至少含一个英文字母，且所有字母都是 ASCII 英文字母。"""
    字母 = [字符 for 字符 in 文本 if 字符.isalpha()]
    return bool(字母) and all("a" <= 字符.lower() <= "z" for 字符 in 字母)


def 选择朗读语音(文本):
    return 纯英文语音 if 是纯英文(文本) else 语音


# ============================================================
# 代码检测（用于判断选中内容是否为代码，若是则跳过翻译）
# ============================================================

# 常见编程语言关键字（覆盖 Python / JS / Java / C 系等）
_代码关键词 = re.compile(
    r"\b("
    r"def|class|import|from|return|function|var|let|const|public|private|protected|"
    r"static|void|int|float|double|bool|boolean|string|True|False|None|null|nil|"
    r"undefined|print|console\.log|if|else|elif|for|while|try|except|catch|finally|"
    r"switch|case|break|continue|new|this|self|async|await|lambda|yield|package|"
    r"namespace|using|include|struct|enum|interface|extends|implements|throw|throws"
    r")\b"
)

# 常见代码专用符号 / 语法片段
_代码符号 = re.compile(r"[{};]|=>|==|!=|&&|\|\||::|->|#include|<\?php|\+\+|--|\bdef\s+\w+\s*\(")


def 是否是代码(文本):
    """粗略判断选中内容是否为代码片段，宁可漏判也不误伤正常短语/单词"""
    if not 文本 or not 文本.strip():
        return False

    行列表 = 文本.splitlines()

    # 把没有缩进的换行统一替换成空格再判断，避免网页折行/自动换行干扰后续检测
    拼接文本 = re.sub(r"\s*\n\s*", " ", 文本).strip()

    符号命中数 = len(_代码符号.findall(拼接文本))
    关键词命中 = bool(_代码关键词.search(拼接文本))

    # 1) 出现缩进行 且 同时伴随真正的代码符号，才是代码块的强特征；
    #    这里不用"关键词命中"来佐证——this/for/new/case/try/let 等
    #    关键词本身也是极常见的英语单词，配合"关键词+缩进"很容易把
    #    普通英文段落误判为代码，只有实打实的代码符号才够可靠
    if len(行列表) > 1:
        缩进行数 = sum(1 for 行 in 行列表 if 行[:1] in (" ", "\t") and 行.strip())
        if 缩进行数 >= 1 and 符号命中数 >= 1:
            return True

    # 2) 出现两个及以上明显的代码符号
    if 符号命中数 >= 2:
        return True

    # 3) 关键词 + 至少一个代码符号，才判定为代码，避免把普通单词误判
    if 关键词命中 and 符号命中数 >= 1:
        return True

    # 4) 非字母数字/空白/中文字符占比过高，且数量不少，通常是代码或表达式
    非普通字符数 = len(re.findall(r"[^\w\s\u4e00-\u9fff]", 拼接文本))
    if len(拼接文本) > 0 and 非普通字符数 >= 3 and 非普通字符数 / len(拼接文本) > 0.15:
        return True

    return False


# ============================================================
# 翻译前文本预处理：下划线转空格 + 驼峰命名拆分
# ============================================================

def 拆分驼峰(文本):
    """WindowsSelectorEventLoopPolicy -> Windows Selector Event Loop Policy"""
    # 小写/数字 与 紧跟的大写字母之间加空格
    文本 = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", 文本)
    # 连续大写后紧跟"大写+小写"的情况（如 HTTPServer -> HTTP Server）
    文本 = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", 文本)
    return 文本


def 预处理翻译文本(文本):
    文本 = 文本.replace("_", " ")   # 下划线替换为空格
    文本 = 拆分驼峰(文本)            # 驼峰命名拆分为空格分隔的单词
    文本 = re.sub(r"\s+", " ", 文本).strip()  # 合并多余空白
    return 文本


# ============================================================
# 翻译缓存（避免重复调用 API）+ 翻译历史记录（供后续 AI 总结学习内容）
# ============================================================

def 加载翻译缓存():
    try:
        with open(翻译缓存文件, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 缓存 key -> 译文，程序启动时加载一次，之后常驻内存
翻译缓存 = 加载翻译缓存()


def 保存翻译缓存():
    try:
        with open(翻译缓存文件, "w", encoding="utf-8") as f:
            json.dump(翻译缓存, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存翻译缓存失败：", e)


def 缓存键(待翻译文本):
    # 忽略大小写，减少因大小写不同造成的缓存未命中
    return 待翻译文本.strip().lower()


def 加载翻译记录():
    try:
        with open(翻译记录文件, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 学习记录：key -> {原文/译文/首次时间/最新时间/日期/次数}，程序启动时加载一次
翻译记录 = 加载翻译记录()


def 保存翻译记录():
    try:
        with open(翻译记录文件, "w", encoding="utf-8") as f:
            json.dump(翻译记录, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存翻译记录失败：", e)


def 更新翻译记录(原文, 处理后文本, 译文, 类型="文本", 词头=None, 来源=None):
    """相同内容（按处理后文本归一化）只保留一条记录，累加次数，并更新为最新时间/日期"""
    键 = 缓存键(处理后文本)
    现在 = datetime.now()
    时间字符串 = 现在.strftime("%Y-%m-%d %H:%M:%S")
    日期字符串 = 现在.strftime("%Y-%m-%d")

    已有 = 翻译记录.get(键)
    if 已有 is None:
        翻译记录[键] = {
            "原文": 原文,
            "送去翻译的文本": 处理后文本,
            "译文": 译文,
            "类型": 类型,
            "首次时间": 时间字符串,
            "最新时间": 时间字符串,
            "日期": 日期字符串,
            "次数": 1,
        }
    else:
        已有["原文"] = 原文
        已有["送去翻译的文本"] = 处理后文本
        已有["译文"] = 译文
        已有["类型"] = 类型
        已有["最新时间"] = 时间字符串
        已有["日期"] = 日期字符串
        已有["次数"] = 已有.get("次数", 1) + 1

    if 词头:
        翻译记录[键]["词头"] = 词头
    if 来源:
        翻译记录[键]["来源"] = 来源

    保存翻译记录()


# ============================================================
# 语音缓存（避免重复调用 edge-tts，单词/短语第二次朗读时几乎瞬时出声）
# ============================================================

def 加载语音缓存索引():
    try:
        with open(语音缓存索引文件, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# key -> {文本/文件名/次数}，程序启动时加载一次
语音缓存索引 = 加载语音缓存索引()


def 保存语音缓存索引():
    try:
        with open(语音缓存索引文件, "w", encoding="utf-8") as f:
            json.dump(语音缓存索引, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存语音缓存索引失败：", e)


def 语音缓存键(文本, 使用语音=None):
    # 忽略大小写和首尾空白，"hello" / "Hello " 视为同一条缓存
    键 = 文本.strip().lower()
    # 默认语音沿用旧缓存键；纯英文语音带上语音名，避免误用以前由晓晓生成的英文音频。
    if 使用语音 and 使用语音 != 语音:
        return f"{使用语音}\n{键}"
    return 键


def 语音缓存文件路径(键):
    # 文本本身可能含有 Windows 文件名不支持的字符，所以用哈希值做文件名
    文件名 = hashlib.md5(键.encode("utf-8")).hexdigest() + ".mp3"
    return os.path.join(语音缓存目录, 文件名), 文件名


def _写入语音缓存(键, 文件名, 缓存路径, 文本, 音频字节):
    """在线程池里执行的同步写盘逻辑，供 run_in_executor 调用，不阻塞事件循环/播放"""
    try:
        with open(缓存路径, "wb") as f:
            f.write(音频字节)

        已有 = 语音缓存索引.get(键, {})
        语音缓存索引[键] = {
            "文本": 文本,
            "文件名": 文件名,
            "次数": 已有.get("次数", 0) + 1,
        }
        保存语音缓存索引()
    except Exception as e:
        print("保存语音缓存失败：", e)


# ============================================================
# 翻译（微软翻译 API，强制不走代理）
# ============================================================

def 调用翻译接口(文本, 目标语言="zh-Hans"):
    if not KEY:
        raise ValueError("请在 配置.ini 的 [微软翻译API] 中填写密钥，然后重启程序。")
    headers = {
        "Ocp-Apim-Subscription-Key": KEY,
        "Ocp-Apim-Subscription-Region": REGION,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    params = {"api-version": "3.0", "to": [目标语言]}
    body = [{"text": 文本}]

    响应 = requests.post(
        ENDPOINT,
        params=params,
        headers=headers,
        json=body,
        proxies={"http": None, "https": None},
        timeout=10,
    )
    响应.raise_for_status()
    结果 = 响应.json()
    return 结果[0]["translations"][0]["text"]


async def 翻译并显示(文本):
    try:
        循环 = asyncio.get_event_loop()
        待翻译文本 = 预处理翻译文本(文本)
        键 = 缓存键(待翻译文本)

        # 单个英文词走本地结构化词典，命中时完全不请求翻译 API。
        本地查询失败 = None
        if 是单词查询(文本, 待翻译文本):
            单词 = 提取英文单词(文本)
            try:
                词条 = await 循环.run_in_executor(None, 查询本地词典, 单词)
            except 本地词典不可用 as e:
                本地查询失败 = e
                print("本地词典不可用，将尝试在线翻译：", e)
            else:
                if 词条:
                    print("命中本地词典，跳过 API 调用：", 词条["单词"])
                    翻译队列.put(词条)
                    await 循环.run_in_executor(
                        None, 更新翻译记录, 文本, 待翻译文本, 生成记录摘要(词条),
                        "单词", 词条["单词"], "本地词典",
                    )
                    return

        译文 = 翻译缓存.get(键)
        来自缓存 = 译文 is not None

        if 来自缓存:
            print("命中翻译缓存，跳过 API 调用")
        else:
            if not KEY:
                if 是单词查询(文本, 待翻译文本) and 本地查询失败 is None:
                    提示 = "本地词典暂未收录该词；在线翻译未配置。朗读仍可使用。"
                elif 本地查询失败 is not None:
                    提示 = f"本地词典不可用：{本地查询失败}；在线翻译也未配置。"
                else:
                    提示 = "在线翻译未配置：请在 配置.ini 中填写微软翻译 API 密钥，然后重启。朗读仍可使用。"
                翻译队列.put(提示)
                return
            译文 = await 循环.run_in_executor(None, 调用翻译接口, 待翻译文本)
            翻译缓存[键] = 译文
            await 循环.run_in_executor(None, 保存翻译缓存)

        print("翻译结果：", 译文)
        翻译队列.put({"类型": "在线翻译", "译文": 译文})

        # 无论是否命中缓存，都更新学习记录（相同内容自动合并计数，只保留最新时间）
        await 循环.run_in_executor(None, 更新翻译记录, 文本, 待翻译文本, 译文)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print("翻译失败：", e)
        翻译队列.put("翻译失败，请检查网络、API 配置和服务额度；详情见控制台。")


# ============================================================
# 翻译结果悬浮窗口（独立线程，跑自己的 tkinter mainloop）
# ============================================================


# ============================================================
# 截图 OCR：截图不写入磁盘，识别在工作线程中执行
# 依赖：python -m pip install Pillow rapidocr-onnxruntime
# ============================================================

def 识别截图(截图):
    global OCR引擎
    from rapidocr_onnxruntime import RapidOCR
    # 用 PNG 字节传入，避免 RGB/BGR 通道顺序差异。
    缓冲 = io.BytesIO()
    截图.save(缓冲, format="PNG")
    with OCR引擎锁:
        if OCR引擎 is None:
            OCR引擎 = RapidOCR()
        结果, _ = OCR引擎(缓冲.getvalue())
    return "\n".join(项[1].strip() for 项 in (结果 or []) if 项[1].strip())


def 开始屏幕框选(root):
    win = None
    def 清理():
        if win is not None:
            try:
                win.grab_release()
                win.destroy()
            except tk.TclError:
                pass

    def 取消(event=None):
        清理()
        OCR忙碌.clear()
        print("已取消 OCR 框选")

    try:
        from PIL import ImageGrab, ImageTk
        import importlib.util
        if importlib.util.find_spec("rapidocr_onnxruntime") is None:
            raise ImportError("缺少 rapidocr-onnxruntime")
        # 先截图再显示遮罩，避免把框选边框识别为文字。
        截图 = ImageGrab.grab(all_screens=True)
        左 = ctypes.windll.user32.GetSystemMetrics(76)
        上 = ctypes.windll.user32.GetSystemMetrics(77)
        宽, 高 = 截图.size
        win = tk.Toplevel(root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{宽}x{高}+0+0")
        canvas = tk.Canvas(win, width=宽, height=高, highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        背景 = ImageTk.PhotoImage(截图, master=win)
        canvas.create_image(0, 0, image=背景, anchor="nw")
        canvas.背景 = 背景
        canvas.create_text(20, 20, anchor="nw", fill="#ff3333", font=("微软雅黑", 16),
                           text="拖动鼠标左键框选文字；Esc / 右键取消")
        起点 = []
        框 = canvas.create_rectangle(0, 0, 0, 0, outline="#ff3333", width=2)

        def 坐标(event):
            return max(0, min(宽, event.x)), max(0, min(高, event.y))

        def 按下(event):
            起点[:] = 坐标(event)

        def 移动(event):
            if 起点:
                canvas.coords(框, *起点, *坐标(event))

        def 松开(event):
            if not 起点:
                return
            x, y = 坐标(event)
            x0, x1 = sorted((起点[0], x))
            y0, y1 = sorted((起点[1], y))
            if x1 - x0 < 3 or y1 - y0 < 3:
                取消()
                return
            区域 = 截图.crop((x0, y0, x1, y1))
            清理()
            if 主事件循环 is not None and 主事件循环.is_running():
                asyncio.run_coroutine_threadsafe(重新触发处理(截图=区域), 主事件循环)
            else:
                OCR忙碌.clear()

        canvas.bind("<ButtonPress-1>", 按下)
        canvas.bind("<B1-Motion>", 移动)
        canvas.bind("<ButtonRelease-1>", 松开)
        win.bind("<Escape>", 取消)
        win.bind("<Button-3>", 取消)
        win.protocol("WM_DELETE_WINDOW", 取消)
        win.deiconify()
        win.update_idletasks()
        # SetWindowPos 使用绝对坐标，兼容位于主屏左侧的负坐标副屏。
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 左, 上, 宽, 高, 0x0040)
        win.lift()
        win.focus_force()
        win.grab_set()
    except Exception as e:
        清理()
        OCR忙碌.clear()
        提示 = f"OCR 框选失败：{e}"
        if isinstance(e, ImportError):
            提示 += '\n请在运行本程序的 Python 环境执行：\npython -m pip install Pillow rapidocr-onnxruntime'
        print(提示)
        翻译队列.put(提示)


async def 处理OCR截图(截图):
    try:
        print("正在 OCR 识别……")
        文本 = await asyncio.get_running_loop().run_in_executor(None, 识别截图, 截图)
        if not 文本:
            翻译队列.put("未识别到文字，请重新框选清晰的文字区域。")
            return
        print("OCR 识别结果：", 文本)
        pyperclip.copy(文本)
        await 处理选中内容(文本)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print("OCR 识别失败：", e)
        翻译队列.put(f"OCR 识别失败：{e}")
    finally:
        OCR忙碌.clear()


def 截图按下(event):
    global _截图_按下中
    if _截图_按下中:
        return
    _截图_按下中 = True
    if OCR忙碌.is_set():
        return
    OCR忙碌.set()
    pygame.mixer.music.stop()
    OCR请求队列.put(True)


def 截图抬起(event):
    global _截图_按下中
    _截图_按下中 = False


def 翻译窗口线程():
    root = tk.Tk()
    root.withdraw()

    状态 = {"win": None, "timer": None}

    # 读取上次记住的窗口位置（如果文件不存在或损坏，就用 None，走默认居中逻辑）
    记住的位置 = None
    try:
        with open(位置记录文件, "r", encoding="utf-8") as f:
            数据 = json.load(f)
            记住的位置 = (数据["x"], 数据["y"])
    except Exception:
        记住的位置 = None

    def 保存位置(x, y):
        nonlocal 记住的位置
        记住的位置 = (x, y)
        try:
            with open(位置记录文件, "w", encoding="utf-8") as f:
                json.dump({"x": x, "y": y}, f)
        except Exception as e:
            print("保存窗口位置失败：", e)

    def 关闭窗口():
        if 状态["win"] is not None:
            try:
                状态["win"].destroy()
            except tk.TclError:
                pass
            状态["win"] = None

    def 显示译文(文本):
        关闭窗口()

        win = tk.Toplevel(root)
        win.overrideredirect(True)      # 无边框
        win.attributes("-topmost", True)
        win.configure(bg="#1e1e1e")

        创建翻译卡片(win, 文本)

        win.update_idletasks()

        if 记住的位置 is not None:
            x, y = 记住的位置
        else:
            屏幕宽 = win.winfo_screenwidth()
            屏幕高 = win.winfo_screenheight()
            窗口宽 = win.winfo_width()
            窗口高 = win.winfo_height()
            x = int(屏幕宽 * 0.65 - 窗口宽 / 2)
            y = int(屏幕高 / 2 - 窗口高 / 2)

        win.geometry(f"+{x}+{y}")

        # ------------------------------------------------------
        # 拖动逻辑
        # ------------------------------------------------------
        拖动状态 = {"x": 0, "y": 0}

        def 开始拖动(event):
            拖动状态["x"] = event.x_root - win.winfo_x()
            拖动状态["y"] = event.y_root - win.winfo_y()

            if 状态["timer"] is not None:
                root.after_cancel(状态["timer"])
                状态["timer"] = None

        def 拖动中(event):
            新x = event.x_root - 拖动状态["x"]
            新y = event.y_root - 拖动状态["y"]
            win.geometry(f"+{新x}+{新y}")

        def 结束拖动(event):
            保存位置(win.winfo_x(), win.winfo_y())
            状态["timer"] = root.after(99000, 关闭窗口)  # 延长为 99 秒

        def 双击关闭(event):
            # 双击时直接关闭窗口，不需要等定时器
            if 状态["timer"] is not None:
                root.after_cancel(状态["timer"])
                状态["timer"] = None
            关闭窗口()

        # 子控件事件会经 Tk bindtags 传到所属顶层窗口，统一绑定避免重复回调。
        for 控件 in (win,):
            控件.bind("<ButtonPress-1>", 开始拖动)
            控件.bind("<B1-Motion>", 拖动中)
            控件.bind("<ButtonRelease-1>", 结束拖动)
            控件.bind("<Double-Button-1>", 双击关闭)  # 双击关闭窗口

        状态["win"] = win
        if 状态["timer"] is not None:
            root.after_cancel(状态["timer"])
        状态["timer"] = root.after(99000, 关闭窗口)  # 延长为 99 秒

    def 轮询队列():
        try:
            OCR请求队列.get_nowait()
        except queue.Empty:
            pass
        else:
            开始屏幕框选(root)
        try:
            while True:
                文本 = 翻译队列.get_nowait()
                显示译文(文本)
        except queue.Empty:
            pass
        root.after(100, 轮询队列)

    root.after(100, 轮询队列)
    root.mainloop()

# ============================================================
# 朗读：边合成边收集音频，合成完立刻从内存播放
# ============================================================

async def 朗读文本(文本):
    global 当前音频缓冲

    print("\n正在朗读：", 文本)

    循环 = asyncio.get_event_loop()
    使用语音 = 选择朗读语音(文本)
    键 = 语音缓存键(文本, 使用语音)
    缓存路径, 文件名 = 语音缓存文件路径(键)

    try:
        音频 = None

        # 先查本地语音缓存：命中就直接读文件播放，完全跳过 edge-tts 的网络合成，
        # 这是"选中→出声"延迟的主要来源，命中缓存基本是毫秒级出声
        if os.path.isfile(缓存路径):
            try:
                with open(缓存路径, "rb") as f:
                    音频 = f.read()
                print("命中语音缓存，跳过 TTS 合成")
            except Exception as e:
                print("读取语音缓存失败，将重新合成：", e)
                音频 = None

        if not 音频:
            音频字节 = bytearray()
            communicate = edge_tts.Communicate(text=文本, voice=使用语音)

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    音频字节.extend(chunk["data"])

            if not 音频字节:
                print("语音生成失败：未收到音频数据")
                return

            音频 = bytes(音频字节)

            # 写盘放到线程池执行，不等待其完成，不拖慢本次播放
            循环.run_in_executor(None, _写入语音缓存, 键, 文件名, 缓存路径, 文本, 音频)

        pygame.mixer.music.stop()
        当前音频缓冲 = io.BytesIO(音频)
        pygame.mixer.music.load(当前音频缓冲, "mp3")
        pygame.mixer.music.play()
        print("正在播放……")

    except asyncio.CancelledError:
        print("\n（朗读已被新的操作取消）")
        raise

    except Exception as e:
        print("\n朗读失败：", e)


def 替换下划线为空格(文本):
    return 文本.replace("_", " ")


async def 处理选中内容(文本=None):
    if 文本 is None:
        文本 = await asyncio.get_event_loop().run_in_executor(None, 获取选中文本)
    if not 文本:
        print("没有检测到选中的文字")
        return

    朗读用文本 = 替换下划线为空格(文本)
    任务列表 = [asyncio.create_task(朗读文本(朗读用文本))]

    # 不含中文 且 不是代码 → 额外执行翻译；含中文或疑似代码则跳过翻译
    if 含中文(文本):
        pass
    elif 是否是代码(文本):
        print("检测到选中内容疑似代码，跳过翻译")
    else:
        任务列表.append(asyncio.create_task(翻译并显示(文本)))

    await asyncio.gather(*任务列表, return_exceptions=True)


async def 重新触发处理(截图=None):
    """取消上一次尚未完成的朗读/翻译任务，并启动新的一次"""
    global 当前处理任务

    if 当前处理任务 is not None and not 当前处理任务.done():
        当前处理任务.cancel()
        try:
            await 当前处理任务
        except asyncio.CancelledError:
            pass

    if 截图 is None:
        当前处理任务 = asyncio.create_task(处理选中内容())
    else:
        当前处理任务 = asyncio.create_task(处理OCR截图(截图))


# ============================================================
# 拖选键按下 / 抬起处理
# ============================================================

def 拖选按下(event):
    global _拖选_按下中

    if _拖选_按下中:
        return
    _拖选_按下中 = True

    if pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()

    # 单击一次，然后立即再按下并保持（即“双击按下”）
    mouse.click(button="left")
    mouse.press(button="left")


def 拖选抬起(event):
    global _拖选_按下中

    if not _拖选_按下中:
        return
    _拖选_按下中 = False

    mouse.release(button="left")

    if 主事件循环 is not None:
        asyncio.run_coroutine_threadsafe(重新触发处理(), 主事件循环)


# ============================================================
# 选中朗读键按下 / 抬起处理
# 选中朗读不模拟鼠标点击/双击去"框选"文字，
# 而是假定用户已经用鼠标/键盘选好了文字，按下功能键后
# 直接走"获取选中文本 -> 朗读/翻译"这一整套后续流程。
# ============================================================

def 选中按下(event):
    global _选中_按下中

    if _选中_按下中:
        return
    _选中_按下中 = True

    if pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()

    if 主事件循环 is not None:
        asyncio.run_coroutine_threadsafe(重新触发处理(), 主事件循环)


def 选中抬起(event):
    global _选中_按下中
    _选中_按下中 = False


async def 主程序():
    global 主事件循环
    主事件循环 = asyncio.get_running_loop()

    keyboard.on_press_key(按键映射["拖选朗读"], 拖选按下)
    keyboard.on_release_key(按键映射["拖选朗读"], 拖选抬起)

    keyboard.on_press_key(按键映射["选中朗读"], 选中按下)
    keyboard.on_release_key(按键映射["选中朗读"], 选中抬起)

    print("=" * 40)
    keyboard.on_press_key(按键映射["截图朗读"], 截图按下)
    keyboard.on_release_key(按键映射["截图朗读"], 截图抬起)

    print("晓晓朗读已启动")
    print()
    print(f"按住 {按键映射['拖选朗读'].upper()}：双击按下鼠标左键")
    print(f"松开 {按键映射['拖选朗读'].upper()}：抬起鼠标左键并朗读选中文字")
    print(f"按下 {按键映射['选中朗读'].upper()}：直接读取当前选中的文字并朗读/翻译（不模拟鼠标选中）")
    print("（选中内容不含中文且不是代码时，会额外弹窗显示翻译结果）")
    print()
    print(f"按下 {按键映射['截图朗读'].upper()}：框选屏幕区域，OCR 识别后朗读/翻译；Esc 或右键取消")
    print("Ctrl+C 退出")
    print("=" * 40)

    while True:
        await asyncio.sleep(3600)


# ============================================================
# 预渲染缓存模式（单次启动，不常驻）
# 用法：python 主程序.py "预渲染"
# ============================================================

预渲染日志文件 = r"D:\2026\22 晓晓朗读\01 ⭐️ 主程序.预渲染.md"
预渲染单项重试次数 = 4
预渲染首轮并发数 = 32
预渲染补跑并发数 = 8


def 提取预渲染文本(文本):
    """
    按优先级提取：
    1. 单个英语单词
    2. 中文之间连续英语词组（禁止跨行）
    3. 连续英语词组（禁止跨行）
    4. 每行句子（禁止跨行）
    5. 每行完整文本（排在最后，跳过空行）
    """
    结果 = []
    已加入 = set()

    def 添加(项目, 类型):
        项目 = 项目.strip()
        # 语音缓存键忽略大小写；按同一规则去重，避免多个任务同时写同一个 MP3。
        去重键 = 语音缓存键(项目) if 项目 else ""
        if not 项目 or 去重键 in 已加入:
            return
        已加入.add(去重键)
        结果.append((类型, 项目))

    行列表 = 文本.splitlines()

    # 1. 单个英语单词
    for 行 in 行列表:
        for 单词 in re.findall(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b", 行):
            添加(单词, "单词")

    # 2. 中文之间的连续英语词组（同一行）
    for 行 in 行列表:
        for 匹配 in re.findall(r"[\u4e00-\u9fff]\s*([A-Za-z][A-Za-z\s'-]*[A-Za-z])\s*[\u4e00-\u9fff]", 行):
            添加(匹配, "中文夹英文词组")

    # 3. 连续英语词组（禁止跨行）
    for 行 in 行列表:
        for 匹配 in re.findall(r"\b[A-Za-z]+(?:\s+[A-Za-z]+)+\b", 行):
            添加(匹配, "英文词组")

    # 4. 每行句子（禁止跨行）
    for 行 in 行列表:
        行 = 行.strip()
        if re.search(r"[A-Za-z]", 行) and len(行.split()) >= 2:
            添加(行, "句子")

    # 5. 每行完整文本：确保中文、数字、单个符号等未被上述规则提取的行也会预渲染。
    # 已经以完全相同内容加入的行继续去重，避免并发写入同一个缓存文件。
    for 行 in 行列表:
        添加(行, "整行文本")

    return 结果


async def 生成预渲染音频(文本, 最大尝试次数=预渲染单项重试次数):
    """合成音频；对限流、服务端错误和空音频执行指数退避重试。"""
    使用语音 = 选择朗读语音(文本)
    最后错误 = "未收到音频数据"
    for 尝试序号 in range(1, 最大尝试次数 + 1):
        try:
            音频字节 = bytearray()
            communicate = edge_tts.Communicate(text=文本, voice=使用语音)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    音频字节.extend(chunk["data"])
            if 音频字节:
                return bytes(音频字节), 尝试序号, None
            最后错误 = "No audio was received"
        except Exception as e:
            最后错误 = str(e)

        if 尝试序号 < 最大尝试次数:
            等待秒数 = min(2 ** (尝试序号 - 1), 8)
            print(f"TTS 暂时失败，第 {尝试序号} 次重试：{文本[:40]}；{等待秒数} 秒后重试")
            await asyncio.sleep(等待秒数)

    return None, 最大尝试次数, 最后错误


async def 预渲染单项(类型, 文本, 最大尝试次数=预渲染单项重试次数):
    try:
        成功 = True
        # 语音缓存
        使用语音 = 选择朗读语音(文本)
        键 = 语音缓存键(文本, 使用语音)
        缓存路径, 文件名 = 语音缓存文件路径(键)

        缓存有效 = os.path.isfile(缓存路径) and os.path.getsize(缓存路径) > 0
        if not 缓存有效:
            音频字节, 尝试次数, 错误 = await 生成预渲染音频(文本, 最大尝试次数)
            if 音频字节 is not None:
                _写入语音缓存(
                    键, 文件名, 缓存路径, 文本, 音频字节
                )
                if os.path.isfile(缓存路径) and os.path.getsize(缓存路径) > 0:
                    状态 = "生成语音缓存"
                    if 尝试次数 > 1:
                        状态 += f"（第 {尝试次数} 次成功）"
                else:
                    状态 = "语音缓存写入失败"
                    成功 = False
            else:
                状态 = f"语音失败（已尝试 {尝试次数} 次）：{错误}"
                成功 = False
        else:
            状态 = "已有语音缓存"

        # 翻译缓存（仅英语内容）
        if not 含中文(文本):
            翻译键 = 缓存键(预处理翻译文本(文本))
            if 翻译键 not in 翻译缓存 and KEY:
                try:
                    译文 = await asyncio.get_running_loop().run_in_executor(
                        None, 调用翻译接口, 预处理翻译文本(文本)
                    )
                    翻译缓存[翻译键] = 译文
                    保存翻译缓存()
                    状态 += " + 翻译缓存"
                except Exception as e:
                    状态 += f" + 翻译失败：{e}"
                    成功 = False

        输出 = f"[{类型}] {文本} -> {状态}"
        print(输出)
        return 成功, 输出

    except Exception as e:
        输出 = f"[{类型}] {文本} -> 失败：{e}"
        print(输出)
        return False, 输出


async def 批量执行预渲染(项目, 并发数=None, 单项重试次数=预渲染单项重试次数):
    """使用固定数量的 worker，避免一次建立过多网络连接。"""
    if not 项目:
        return []

    if 并发数 is None:
        并发数 = 预渲染首轮并发数

    队列 = asyncio.Queue()
    for 序号, 项 in enumerate(项目):
        队列.put_nowait((序号, 项))
    结果 = [None] * len(项目)

    async def worker():
        while True:
            try:
                序号, (类型, 内容) = 队列.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                结果[序号] = await 预渲染单项(类型, 内容, 单项重试次数)
            finally:
                队列.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(并发数, len(项目)))]
    await asyncio.gather(*workers)
    return 结果


async def 执行预渲染():
    try:
        文本 = pyperclip.paste().strip()
    except Exception as e:
        print("读取剪贴板失败：", e)
        文本 = ""

    if not 文本:
        print("剪贴板为空")
        return False

    项目 = 提取预渲染文本(文本)
    print(f"提取 {len(项目)} 个预渲染项目")
    if not 项目:
        print("没有可预渲染的英语内容")
        return False

    日志 = [
        "# 晓晓朗读预渲染日志",
        "",
        f"- 时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 数量：{len(项目)}",
        ""
    ]

    # Windows SelectorEventLoop 最多只能处理约 512 个 socket。使用固定 worker 池，
    # 防止项目较多时全量并发触发 "too many file descriptors in select()"。
    单项结果 = await 批量执行预渲染(
        项目,
        并发数=预渲染首轮并发数,
        单项重试次数=1,
    )

    # 整轮结束后再补跑最终失败项；已成功写入的缓存不会重复请求。
    失败序号 = [序号 for 序号, (成功, _) in enumerate(单项结果) if not 成功]
    if 失败序号:
        print(f"首轮仍有 {len(失败序号)} 项失败，等待 5 秒后补跑……")
        await asyncio.sleep(5)
        失败项目 = [项目[序号] for 序号 in 失败序号]
        补跑结果 = await 批量执行预渲染(
            失败项目,
            并发数=预渲染补跑并发数,
            单项重试次数=预渲染单项重试次数,
        )
        for 原序号, 新结果 in zip(失败序号, 补跑结果):
            单项结果[原序号] = 新结果

    信号 = [输出 for _, 输出 in 单项结果]
    成功状态 = [成功 for 成功, _ in 单项结果]

    日志.append("```\n" + "\n".join(信号) + "\n```")

    try:
        os.makedirs(os.path.dirname(预渲染日志文件), exist_ok=True)
        with open(预渲染日志文件, "w", encoding="utf-8") as f:
            f.write("\n".join(日志))
        print("日志已保存：", 预渲染日志文件)
        日志成功 = True
    except Exception as e:
        print("日志保存失败：", e)
        日志成功 = False

    成功 = all(成功状态) and 日志成功
    print("预渲染全部成功" if 成功 else "预渲染存在失败项目")
    return 成功


def 启动预渲染模式():
    return asyncio.run(执行预渲染())


def 等待预渲染结束(成功):
    """成功时展示结果 5 秒；失败时保留控制台，便于查看错误。"""
    if 成功:
        print("预渲染成功，5 秒后自动退出……")
        time.sleep(5)
        return

    print("预渲染失败，窗口将保持打开；按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n已退出预渲染窗口。")



if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if len(sys.argv) > 1 and sys.argv[1] == "预渲染":
        try:
            预渲染成功 = 启动预渲染模式()
        except Exception as e:
            # 保证未预料的错误也会进入下方的失败等待，不让命令行窗口直接关闭。
            预渲染成功 = False
            print("\n预渲染发生未处理错误：", e)
            traceback.print_exc()
        finally:
            pygame.mixer.quit()
        等待预渲染结束(预渲染成功)
        raise SystemExit(0 if 预渲染成功 else 1)

    # 悬浮翻译窗口用独立线程跑，不能和 asyncio 事件循环混在一起
    threading.Thread(target=翻译窗口线程, daemon=True).start()

    try:
        asyncio.run(主程序())
    except KeyboardInterrupt:
        print("\n程序已退出")
    finally:
        keyboard.unhook_all()
        if _拖选_按下中:
            mouse.release(button="left")
        pygame.mixer.music.stop()
        pygame.mixer.quit()
