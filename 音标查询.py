"""按需读取剑桥公开词条网页中的美式 IPA，不调用 API、不转换旧词表。"""
from html.parser import HTMLParser
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


网页前缀 = "https://dictionary.cambridge.org/dictionary/english/"


def 提取英文单词(文本):
    文本 = 文本.strip().replace("’", "'").strip("\"'“”‘.,!?;:()[]{}，。！？；：（）")
    if re.fullmatch(r"[A-Za-z]+(?:['-][A-Za-z]+)*", 文本):
        return 文本.lower()
    return None


def 构建翻译结果(原文, 待翻译文本, 译文):
    """先显示中文，再异步补充音标，查询过程不阻塞译文。"""
    结果 = {"译文": 译文}
    单词 = 提取英文单词(原文)
    if 单词 and 单词 == 提取英文单词(待翻译文本):
        结果.update(单词=单词, 音标提示="正在查询剑桥美式音标…",
                    词典链接=网页前缀 + quote(单词, safe=""))
    return 结果


class 音标查询失败(Exception):
    pass


class _剑桥跳转(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        地址 = urlsplit(newurl)
        if 地址.scheme != "https" or 地址.netloc != "dictionary.cambridge.org":
            raise 音标查询失败("剑桥页面跳转到其他站点，已停止查询")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _请求网页(url, 超时):
    请求 = Request(url, headers={"User-Agent": "XiaoxiaoReader/2.0 (+https://github.com/xymsyh/xiaoxiao-reader)",
                                "Accept": "text/html"})
    with build_opener(_剑桥跳转()).open(请求, timeout=超时) as 响应:
        内容 = 响应.read(2_000_001)
        编码 = 响应.headers.get_content_charset() or "utf-8"
    if len(内容) > 2_000_000:
        raise 音标查询失败("剑桥页面过大，暂不显示音标")
    return 内容.decode(编码)


class _节点:
    def __init__(self, 标签="root", 属性=(), 父=None):
        self.标签 = 标签
        self.属性 = dict(属性)
        self.类 = set(self.属性.get("class", "").split())
        self.父 = 父
        self.内容 = []

    def 后代(self):
        for 项 in self.内容:
            if isinstance(项, _节点):
                yield 项
                yield from 项.后代()

    def 文字(self):
        if self.标签 in {"audio", "script", "style", "button"}:
            return ""
        return "".join(项 if isinstance(项, str) else 项.文字() for 项 in self.内容)


class _词条HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.根 = _节点()
        self.当前 = self.根

    def handle_starttag(self, tag, attrs):
        新 = _节点(tag, attrs, self.当前)
        self.当前.内容.append(新)
        if tag not in {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}:
            self.当前 = 新

    def handle_startendtag(self, tag, attrs):
        self.当前.内容.append(_节点(tag, attrs, self.当前))

    def handle_endtag(self, tag):
        节点 = self.当前
        while 节点.父 is not None:
            if 节点.标签 == tag:
                self.当前 = 节点.父
                break
            节点 = 节点.父

    def handle_data(self, data):
        self.当前.内容.append(data)


def _区域(节点):
    标记 = set(节点.类)
    for 键 in ("lang", "data-lang", "region", "type"):
        标记.add(节点.属性.get(键, "").lower())
    美 = bool(标记 & {"us", "en-us", "pron-us", "uspron"})
    英 = bool(标记 & {"uk", "en-gb", "pron-uk", "ukpron"})
    return "us" if 美 and not 英 else "uk" if 英 and not 美 else None


def _是美式(节点):
    当前 = 节点
    while 当前 is not None:
        区域 = _区域(当前)
        if 区域:
            return 区域 == "us"
        if 当前.类 & {"pron-info", "dpron-i"}:
            # 兼容区域标签/音频与音标并列的结构，但不跨过发音块找区域。
            区域集 = {_区域(项) for 项 in 当前.后代()} - {None}
            return 区域集 == {"us"}
        当前 = 当前.父
    return False


def _属于目标词(节点, 单词):
    祖先 = []
    当前 = 节点
    while 当前 is not None:
        祖先.append(当前)
        当前 = 当前.父
    if any(项.类 & {"runon", "drunon", "phrase-block", "dphrase-block", "idiom-block"} for 项 in 祖先):
        return False
    for 当前 in 祖先:
        if 当前.类 & {"pos-header", "di-head", "entry-body__el", "entry"}:
            词头 = [项 for 项 in 当前.后代() if 项.类 & {"hw", "headword", "hwd", "dhw"}]
            if 词头:
                return any(项.文字().strip().casefold() == 单词.casefold() for 项 in 词头)
    return False  # 不能确认词头就不显示，避免把推荐词/词根读音当作查询词。


def 解析美式音标(内容, 单词):
    """仅取词条中的 US 发音；只去掉音节分隔点和排版空白，不替换音素。"""
    if not isinstance(内容, str):
        raise 音标查询失败("剑桥词条格式无法识别，暂不显示音标")
    文档 = _词条HTML()
    文档.feed(内容)
    结果 = []
    for 节点 in 文档.根.后代():
        if not (节点.类 & {"ipa", "pron", "dpron"}):
            continue
        if any(项.类 & {"ipa", "pron", "dpron"} for 项 in 节点.后代()):
            continue  # 只取最内层，避免重叠标签造成重复。
        if not _是美式(节点) or not _属于目标词(节点, 单词):
            continue
        音标 = re.sub(r"[\s.·]", "", 节点.文字()).strip("/[]")
        if not 音标 or len(音标) > 200:
            continue
        音标 = "/" + 音标 + "/"
        if 音标 not in 结果:
            结果.append(音标)
    return 结果


class 剑桥音标客户端:
    def __init__(self, 超时秒=5, 请求=None):
        self.超时秒 = 超时秒
        self.请求 = 请求 or _请求网页
        self._暂停至 = 0
        self._锁 = threading.Lock()

    def 查询(self, 单词):
        if 提取英文单词(单词) != 单词:
            return {"音标提示": "不是可查询的单个英文单词"}
        链接 = 网页前缀 + quote(单词, safe="")
        with self._锁:
            if time.monotonic() < self._暂停至:
                return {"音标提示": "剑桥暂时拒绝访问；稍后重试或打开词典原页", "词典链接": 链接}
        try:
            内容 = self.请求(链接, self.超时秒)
            if not isinstance(内容, str):
                raise 音标查询失败("剑桥网页格式无法识别")
            if any(标记 in 内容.lower() for 标记 in ("cf-chl-", "<title>just a moment", "challenge-platform")):
                self._暂停()
                raise 音标查询失败("剑桥网页要求安全验证，请打开词典原页")
            音标 = 解析美式音标(内容, 单词)
            if not 音标:
                return {"音标提示": "未获取到该词的剑桥美式音标，请查看原页", "词典链接": 链接}
            return {"音标": 音标, "音标来源": "Cambridge Dictionary · US", "词典链接": 链接,
                    "音标版权": "© Cambridge University Press"}
        except HTTPError as 错误:
            if 错误.code in {403, 429}:
                self._暂停()
            提示 = {403: "剑桥拒绝自动访问，请打开词典原页",
                    404: "剑桥未找到该词条", 429: "剑桥查询限流，请稍后重试"}.get(
                        错误.code, "剑桥网页暂不可用")
        except (TimeoutError, socket.timeout):
            提示 = "剑桥音标查询超时"
        except URLError:
            提示 = "剑桥音标网络连接失败"
        except (ValueError, UnicodeError, LookupError):
            提示 = "剑桥网页格式无法识别"
        except 音标查询失败 as 错误:
            提示 = str(错误)
        return {"音标提示": 提示, "词典链接": 链接}

    def _暂停(self):
        # 拒绝/限流后停止自动请求一分钟，不轮换代理、伪装浏览器或绕过验证。
        with self._锁:
            self._暂停至 = time.monotonic() + 60
