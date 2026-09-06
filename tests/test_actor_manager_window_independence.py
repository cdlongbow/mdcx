"""议题 #79：演员管理器（单独弹窗）不干扰主窗最小化状态.

根因（Windows 原生边框）：主窗最小化后，对 actor manager 调 raise_()/
activateWindow() 会联动升起最小化的主窗（Qt 派自 native window 处理）。
修复逻辑：只在「主窗可见且未最小化」时才 raise_/activateWindow；
主窗最小化时只做 show()/showNormal()，不额外 raise。
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
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _w: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda path: str(MAIN_PATH / "resources" / path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, t).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def test_emby_manager_show_does_not_restore_main(win, app):
    """主窗最小化后打开 actor manager，主窗必须维持最小化."""
    from mdcx.controllers.main_window.tool_handlers import (
        pushButton_emby_actor_manager_clicked,
    )

    win.showMinimized()
    app.processEvents()
    assert win.isMinimized()

    pushButton_emby_actor_manager_clicked(win)
    app.processEvents()
    assert win.isMinimized(), f"主窗被自动恢复: state={win.windowState()}"


def test_emby_manager_button_click_no_raise_main(win, app, monkeypatch):
    """主窗最小化时，按钮点击不触发 raise_/activateWindow（Windows 联动主窗根因）."""
    import mdcx.tools.emby_actor_manager_ui as emui
    from mdcx.controllers.main_window import tool_handlers

    raise_calls = []

    class GuardedDialog(emui.EmbyActorManagerDialog):
        def raise_(self):
            raise_calls.append("raise_")
            super().raise_()

        def activateWindow(self):
            raise_calls.append("activateWindow")
            super().activateWindow()

    monkeypatch.setattr(emui, "EmbyActorManagerDialog", GuardedDialog)

    win.showMinimized()
    app.processEvents()

    tool_handlers.pushButton_emby_actor_manager_clicked(win)
    app.processEvents()
    assert not raise_calls, f"第一次点击调用了 raise/activateWindow: {raise_calls}"
