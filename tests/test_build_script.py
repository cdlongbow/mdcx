"""打包脚本回归：subprocess.run 必须显式 UTF-8 解码输出。

实证（release tag 20260905 首跑）：Windows runner 上 `_run_command` 的
`subprocess.run(..., text=True)` 未指定 encoding 时默认 GBK/charmap，
PyInstaller 输出含 UTF-8 字节即 `UnicodeDecodeError: charmap`，构建直接失败。
AST 哨兵锁定：scripts/build.py 中所有 subprocess.run 调用必须带
encoding="utf-8"，防止回退。
"""

import ast
from pathlib import Path

BUILD_PY = Path(__file__).resolve().parent.parent / "scripts" / "build.py"


def _subprocess_run_calls_has_utf8() -> list[str]:
    """返回 build.py 中缺少 encoding="utf-8" 的 subprocess.run 调用位置。"""
    tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # 仅匹配 subprocess.run(...)
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            continue
        enc = next((k.value for k in node.keywords if k.arg == "encoding"), None)
        if enc is None or not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
            problems.append(f"build.py:{node.lineno} subprocess.run 缺少 encoding='utf-8'")
    return problems


def test_build_py_subprocess_run_uses_utf8():
    assert not _subprocess_run_calls_has_utf8(), "\n".join(_subprocess_run_calls_has_utf8())


def test_build_py_run_command_returns_stdout_text():
    """_run_command 在 Windows 默认 GBK 环境下也应能处理 UTF-8 输出。

    直接调用 _run_command 跑一个输出 UTF-8 中文的 python -c，验证解码不炸。
    """
    import sys

    from scripts.build import BuildManager

    mgr = BuildManager(app_name="t", app_version="1", create_dmg=False, debug=False)
    out = mgr._run_command([sys.executable, "-c", "print('中文✅')"], error_msg="boom")
    assert "中文" in out and "✅" in out
