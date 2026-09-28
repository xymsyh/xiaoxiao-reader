"""读取主程序旁的配置，不依赖启动时的工作目录。"""
import configparser
import shutil
from pathlib import Path
from urllib.parse import urlsplit


配置路径 = Path(__file__).resolve().with_name("配置.ini")


def 初始化配置(路径=配置路径):
    """仅首次启动复制无密钥示例，绝不覆盖已有配置。"""
    路径 = Path(路径)
    if 路径.exists():
        return False
    示例 = Path(__file__).resolve().with_name("配置示例.ini")
    try:
        with 示例.open("rb") as 来源, 路径.open("xb") as 目标:
            shutil.copyfileobj(来源, 目标)
    except FileExistsError:
        return False
    except OSError:
        raise ValueError(f"无法创建配置文件：{路径}。请检查目录权限或手动复制 配置示例.ini。") from None
    return True


def 读取配置(路径=配置路径):
    路径 = Path(路径)
    配置 = configparser.ConfigParser(interpolation=None)
    try:
        with 路径.open(encoding="utf-8-sig") as 文件:
            配置.read_file(文件)
    except FileNotFoundError:
        raise ValueError(f"找不到配置文件：{路径}。请复制 配置示例.ini 并重命名为 配置.ini。") from None
    except (OSError, UnicodeError, configparser.Error):
        raise ValueError(f"无法读取配置文件：{路径}。请检查编码和 INI 格式。") from None

    结果 = {}
    for 分组, 字段列表 in {
        "按键映射": ("拖选朗读", "选中朗读", "截图朗读"),
        "微软翻译API": ("密钥", "区域", "地址"),
    }.items():
        结果[分组] = {}
        for 字段 in 字段列表:
            值 = 配置.get(分组, 字段, fallback="").strip()
            if not 值 and 字段 != "密钥":
                raise ValueError(f"{路径} 中 [{分组}] 的“{字段}”不能为空。")
            结果[分组][字段] = 值

    按键 = 结果["按键映射"]
    for 功能, 键名 in 按键.items():
        if "+" in 键名 or "," in 键名:
            raise ValueError(f"“{功能}”请填写单个按键，例如 f8；目前不支持组合键。")
        按键[功能] = 键名.lower()
    if len(set(按键.values())) != len(按键):
        raise ValueError("三个功能必须使用不同的按键，请检查 配置.ini。")
    try:
        地址 = urlsplit(结果["微软翻译API"]["地址"])
        地址有效 = 地址.scheme in ("http", "https") and bool(地址.hostname)
    except ValueError:
        地址有效 = False
    if not 地址有效:
        raise ValueError("[微软翻译API] 的“地址”必须是完整的 HTTP(S) 接口地址。")
    return 结果
