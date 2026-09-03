"""窗口状态矩阵回归测试：边框模式 x 窗口尺寸 x 日志展开收起 x 页面切换。

回归背景（议题 #68）：QStackedWidget 只会把当前可见页 resize 到自身尺寸，
休眠页永远停留在设计尺寸 820x692。修复前 `_sync_page_layouts` 以 page.width()
为基准计算内部几何，"先缩放窗口再切页"时休眠页全部按陈旧尺寸布局——
日志页上栏只剩 480*0.61≈292 高、按钮飘出页面、工具页右侧被裁。

另修复：show_hide_logs 硬编码 resize(790, 418/689) 覆盖同步结果；
日志页/net 页按钮未跟随页面宽度；下栏隐藏时上栏仍只占 61%。
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
    # Geometry tests do not need the full QSS/resource loading path.
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    # 窗口构造后立即停表：几何测试不依赖定时器回调，
    # 保留运行中的 QTimer 会让 processEvents 触发网络/日志等无关副作用。
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto(win, app, page_name):
    for i in range(win.Ui.stackedWidget.count()):
        if win.Ui.stackedWidget.widget(i).objectName() == page_name:
            win.Ui.stackedWidget.setCurrentIndex(i)
            app.processEvents()
            return win.Ui.stackedWidget.widget(i)
    raise AssertionError(f"page not found: {page_name}")


def test_dormant_pages_resize_with_window(win, app):
    """核心回归：缩放窗口后所有休眠页必须获得新尺寸，而非停留在设计尺寸。"""
    win.resize(1032, 737)
    app.processEvents()
    stacked = win.Ui.stackedWidget
    for i in range(stacked.count()):
        page = stacked.widget(i)
        assert page.width() == stacked.width(), f"{page.objectName()} 未跟随 stackedWidget 宽度"
        assert page.height() == stacked.height(), f"{page.objectName()} 未跟随 stackedWidget 高度"


def test_resize_first_then_switch_log_page_layout(win, app):
    """先缩放再切日志页（报告人操作序列）：上栏 61%、下栏 39%、按钮右缘锚定。"""
    win.resize(1032, 737)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    lower = win.Ui.textBrowser_log_main_2
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert lower.isVisibleTo(page)
    assert lower.height() == pytest.approx(page.height() - upper.height() - 1, abs=2)
    assert lower.y() == upper.height() + 1
    # 按钮右缘距页面右缘约 22px（设计 822-800），且不出界
    btn = win.Ui.pushButton_start_cap2
    assert btn.geometry().right() <= page.width()
    assert page.width() - btn.geometry().right() <= 30


def test_log_lower_hidden_upper_fills_page(win, app):
    """收起下栏后上栏应铺满整页（而非仍占 61%），展开后恢复分栏。"""
    win.resize(1200, 900)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main

    win.show_hide_logs(False)
    app.processEvents()
    assert win.Ui.textBrowser_log_main_2.isHidden()
    assert upper.height() == pytest.approx(page.height(), abs=2)

    win.show_hide_logs(True)
    app.processEvents()
    assert win.Ui.textBrowser_log_main_2.isVisibleTo(page)
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)


def test_maximize_button_present(win):
    """议题 #69: 最大化按钮恢复（#67 曾按报告人要求用 WindowMaximizeButtonHint 屏蔽）。

    #62/#66/#68 的最大化布局错乱根因已修复（见本文件其余用例），
    禁用按钮只是绕过症状且与拖拽边缘缩放能力自相矛盾，应恢复按钮。
    """
    from PyQt6.QtCore import Qt

    assert win.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint


def test_maximized_window_layout_sync(win, app):
    """最大化路径整体回归：showMaximized 后所有休眠页与内部组件跟随新窗口尺寸。"""
    win.showMaximized()
    app.processEvents()
    stacked = win.Ui.stackedWidget
    for i in range(stacked.count()):
        page = stacked.widget(i)
        assert page.width() == stacked.width(), f"{page.objectName()} 最大化后未跟随宽度"
        assert page.height() == stacked.height(), f"{page.objectName()} 最大化后未跟随高度"
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert win.Ui.pushButton_start_cap2.geometry().right() <= page.width()


def test_setting_tabs_scrollareas_follow_window(win, app):
    """设置页 12 个 tab 的 scrollArea 跟随窗口（#66 回归，含休眠 tab）。"""
    win.resize(1400, 950)
    app.processEvents()
    _goto(win, app, "page_setting")
    tab_widget = win.Ui.tabWidget
    for i in range(tab_widget.count()):
        tab_page = tab_widget.widget(i)
        assert tab_page.width() == tab_widget.width(), f"tab{i} 页未跟随 tabWidget"
    from mdcx.views.CustomClass import CustomScrollArea

    for i in range(tab_widget.count()):
        tab_page = tab_widget.widget(i)
        scroll = tab_page.findChild(CustomScrollArea)
        if scroll is not None and scroll.parentWidget() == tab_page:
            assert scroll.width() == pytest.approx(tab_widget.width() - 4, abs=2), f"tab{i} scrollArea 宽未同步"
            assert scroll.height() == pytest.approx(tab_widget.height() - 24, abs=2), f"tab{i} scrollArea 高未同步"


@pytest.mark.parametrize("border", ["show", "hide"])
def test_layout_correct_under_both_border_modes(win, app, border):
    """原生边框与隐藏边框两种外观下，日志页几何规则一致（报告人未开隐藏边框）。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    mw_mod.manager.config.window_title = border
    win._windows_auto_adjust()
    app.processEvents()
    win.resize(1032, 737)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert win.Ui.pushButton_start_cap2.geometry().right() <= page.width()
    mw_mod.manager.config.window_title = "show"
    win._windows_auto_adjust()
    app.processEvents()
