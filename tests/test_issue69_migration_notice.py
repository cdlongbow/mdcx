"""议题 #69: 迁移警告与校验错误的分流回归测试。

根因: `Config.update` 返回的迁移警告（如「已移除配置项 严格校验 Amazon 图片」）
原样成为 `manager.load()` 的返回值, `load_config` 把任何非空消息当致命错误,
含旧配置键的用户配置被误判为「读取配置文件出错」并强制切到 `_failed.json`,
再切回时重复失败, 表现为「不能切换配置」且重启无效。

修复约定: 迁移警告一律带 `[迁移]` 前缀(与 `[V1]` 通知同级),
`load_config` 仅对无前缀消息触发 `_failed.json` 保护分支。
"""

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def test_migration_warnings_carry_prefix():
    """migrate_config_data 产出的所有警告必须带 [迁移] 前缀（防回归为无前缀）。"""
    from mdcx.config.migrations import migrate_config_data

    msgs = migrate_config_data({"amazon_strict_pic_verify": True})
    assert msgs, "旧键 amazon_strict_pic_verify 应产生迁移警告"
    assert all(m.startswith("[迁移]") for m in msgs)


def test_migration_notice_does_not_redirect_to_failed_json(win, app, monkeypatch):
    """含旧配置键(仅产生迁移警告)时 load_config 不得切到 _failed.json。"""
    from mdcx.config.manager import manager

    assert manager.path.name != "_failed.json"
    monkeypatch.setattr(
        type(manager),
        "load",
        lambda self: ["[迁移] 已移除配置项「严格校验 Amazon 图片」：测试警告"],
    )
    win.load_config()
    app.processEvents()
    assert manager.path.name != "_failed.json"


def test_real_error_still_redirects_to_failed_json(win, app, monkeypatch):
    """真正的校验错误（无前缀消息）仍须触发 _failed.json 保护分支，防过滤过宽。"""
    from mdcx.config.manager import manager

    monkeypatch.setattr(type(manager), "load", lambda self: ["配置文件校验失败: 测试错误"])
    try:
        win.load_config()
        app.processEvents()
        assert manager.path.name == "_failed.json"
    finally:
        # manager 是进程级单例, 恢复路径避免污染共享 fixture 的其他用例
        manager.path = manager.data_folder / "config.json"
