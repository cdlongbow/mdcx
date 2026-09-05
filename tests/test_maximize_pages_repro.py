"""复现：Windows 原生最大化后 软件界面/软件工具/软件设置 三页内容不跟随（用户报告）.

用户实测（Windows 原生边框 + 最大化）：软件界面、软件工具、软件设置三页内容停留在设计尺寸，
软件日志、检测网络等其余页面正常。
"""

import sys

import pytest
from PyQt6.QtWidgets import QApplication

from tests.test_window_state_matrix import _goto

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


def _size(obj):
    return (obj.width(), obj.height())


def test_maximize_content_follow_all_pages(win, app):
    """横向放大复现：窗口从设计尺寸放大到 1920 宽（等价 Windows 原生最大化）。"""

    from mdcx.views.CustomClass import CustomScrollArea

    # 1. 正常显示（设计尺寸）
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_scroll = win.Ui.page_tool.findChild(CustomScrollArea)
    setting_tab = win.Ui.tabWidget
    before_tool = _size(tool_scroll)
    before_setting = _size(setting_tab)
    before_main_page = _size(win.Ui.page_main)
    before_tree = _size(win.Ui.treeWidget_number)
    before_file_path = _size(win.Ui.label_file_path)

    # 2. 放大到 1920x1040（Windows 真机最大化等效）
    win.resize(1920, 1040)
    app.processEvents()

    print(f"window     : {win.width()}x{win.height()}")
    print(f"stacked    : {win.Ui.stackedWidget.width()}x{win.Ui.stackedWidget.height()}")
    print(f"page_main  : {before_main_page} -> {_size(win.Ui.page_main)}")
    print(f"tool_scroll: {before_tool} -> {_size(tool_scroll)}")
    print(f"setting_tab: {before_setting} -> {_size(setting_tab)}")
    print(f"main_tree  : {before_tree} -> {_size(win.Ui.treeWidget_number)}")
    print(f"file_path  : {before_file_path} -> {_size(win.Ui.label_file_path)}")

    # 页面本身跟随
    assert win.Ui.page_main.width() == win.Ui.stackedWidget.width(), "page_main 未跟随 stackedWidget"
    assert win.Ui.page_tool.width() == win.Ui.stackedWidget.width(), "page_tool 未跟随 stackedWidget"
    assert win.Ui.page_setting.width() == win.Ui.stackedWidget.width(), "page_setting 未跟随 stackedWidget"

    # 软件界面（初始可见页）：内部内容横向跟随
    assert win.Ui.treeWidget_number.geometry().right() == pytest.approx(win.Ui.page_main.width() - 18, abs=6), (
        f"软件界面结果树未锚定右缘: right={win.Ui.treeWidget_number.geometry().right()}"
    )
    assert win.Ui.label_file_path.width() == pytest.approx(win.Ui.page_main.width() - 34, abs=6), (
        f"软件界面文件路径标签未拉伸: {win.Ui.label_file_path.width()}"
    )
    # 工具/设置页为休眠页：容器几何即时跟随即可（content 拉伸在切页 show 时验证，
    # 见 test_switch_to_pages_after_maximize_content_visible）
    assert tool_scroll.width() == pytest.approx(win.Ui.page_tool.width() - 40, abs=4), (
        f"工具页 scrollArea 宽未跟随: {tool_scroll.width()} != {win.Ui.page_tool.width() - 40}"
    )
    assert setting_tab.width() == pytest.approx(win.Ui.page_setting.width() - 40, abs=4), (
        f"设置页 tabWidget 宽未跟随: {setting_tab.width()} != {win.Ui.page_setting.width() - 40}"
    )


def test_scroll_content_follow_viewport(win, app):
    """工具页 scrollArea 内部内容跟随视口宽（切页显示后验证，对齐用户观察路径）."""

    from mdcx.views.CustomClass import CustomScrollArea

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_page = _goto(win, app, "page_tool")
    tool_scroll = tool_page.findChild(CustomScrollArea)
    content = tool_scroll.widget()
    before_content_w = content.width()

    win.resize(1920, 1040)
    app.processEvents()

    # 视口放大后（页面保持可见），widgetResizable 应把内容拉到视口宽
    after_content_w = content.width()
    print(f"before: viewport={tool_scroll.width()} content={before_content_w}")
    print(f"after : viewport={tool_scroll.width()} content={after_content_w}")
    assert after_content_w > before_content_w, (
        f"工具页 scrollArea 内容宽未跟随视口: {before_content_w} -> {after_content_w}"
    )

    # 宽幅 groupBox 跟随拉伸（sync_wide_children_width，设计基准从 setWidget 登记取）
    design_w = getattr(content, "_wide_children_design_width", 0)
    extra = tool_scroll.viewport().width() - design_w
    from PyQt6.QtWidgets import QGroupBox

    wide_groups = [g for g in content.findChildren(QGroupBox) if g.parentWidget() is content and g.width() > 400]
    print(f"groupBox widths: {[(g.objectName(), g.width()) for g in wide_groups[:4]]}")
    for g in wide_groups:
        assert g.width() >= 700 + extra - 4, f"宽幅容器 {g.objectName()} 未跟随拉伸: {g.width()} (extra={extra})"


def test_switch_to_pages_after_maximize_content_visible(win, app):
    """最大化后切到三个页面，内容尺寸正确（复现用户切页观察）."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()
    win.resize(1920, 1040)
    app.processEvents()

    from mdcx.views.CustomClass import CustomScrollArea

    # 软件工具页
    tool_page = _goto(win, app, "page_tool")
    tool_scroll = tool_page.findChild(CustomScrollArea)
    assert tool_scroll.width() > 700, f"工具页内容未跟随: {tool_scroll.width()}"
    assert tool_scroll.width() == pytest.approx(tool_page.width() - 40, abs=4)
    tool_content = tool_scroll.widget()
    print(f"tool: viewport={tool_scroll.width()} content={tool_content.width()}")
    # 内容必须跟随视口拉宽（用户症状：内容停在 782/860 不放大）
    assert tool_content.width() >= tool_scroll.width() - 30, (
        f"工具页 scrollArea 内容未拉伸: content={tool_content.width()} viewport={tool_scroll.width()}"
    )

    # 软件设置页
    setting_page = _goto(win, app, "page_setting")
    assert win.Ui.tabWidget.width() > 700, f"设置页 tabWidget 未跟随: {win.Ui.tabWidget.width()}"
    assert win.Ui.tabWidget.width() == pytest.approx(setting_page.width() - 40, abs=4)
    # 当前 tab 的 scrollArea 内容同样必须拉伸
    current_tab = win.Ui.tabWidget.currentWidget()
    tab_scroll = current_tab.findChild(CustomScrollArea)
    if tab_scroll is not None and tab_scroll.parentWidget() == current_tab:
        tab_content = tab_scroll.widget()
        print(f"set: viewport={tab_scroll.width()} content={tab_content.width()}")
        assert tab_content.width() >= tab_scroll.width() - 30, (
            f"设置页内容未拉伸: content={tab_content.width()} viewport={tab_scroll.width()}"
        )
