"""build.py hidden-import 与动态导入爬虫的一致性防漂移.

背景：7mmtv 爬虫模块名数字开头（7mmtv.py），无法用常规 import 语法，
在 crawlers/__init__.py 经 importlib.import_module 动态注册。
PyInstaller 对运行时字符串解析不可靠，必须显式 --hidden-import 收录；
漏收时打包版运行时刮削才崩溃，本地源码与 CI 均无法发现。
本测试静态锁定：__init__.py 中 import_module 的字面量 ⊆ build.py hidden-import。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_importlib_registered_crawlers_covered_by_hidden_import():
    init_py = (ROOT / "mdcx" / "crawlers" / "__init__.py").read_text(encoding="utf-8")
    build_py = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")

    # import_module("mdcx.crawlers.xxx") 字面量
    dynamic = set(re.findall(r'import_module\(\s*"(mdcx\.crawlers\.[\w.]+)"', init_py))
    assert dynamic, "未发现动态导入爬虫，若爬虫注册方式变更请同步本测试"

    # build.py hidden-import 实参串
    hidden = set(re.findall(r'"--hidden-import",\s*\n\s*"([\w.]+)"', build_py))
    missing = dynamic - hidden
    assert not missing, f"动态导入爬虫缺少 hidden-import（打包版会运行时崩溃）: {sorted(missing)}"


def test_build_py_hidden_import_section_exists():
    """build.py 的 hidden-import 段落存在（防止参数重构后静默丢失全部动态收录）。"""
    build_py = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    assert "mdcx.crawlers.7mmtv" in build_py, "7mmtv hidden-import 缺失：动态注册爬虫需显式收录"
