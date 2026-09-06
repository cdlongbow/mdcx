"""窗口状态矩阵回归测试：边框模式 x 窗口尺寸 x 日志展开收起 x 页面切换 x 最大化内容跟随。

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


def test_nav_gap_uniform_when_entries_hidden(win, app, monkeypatch):
    """议题 #74：原生边框下开启隐藏入口后，剩余导航按钮间隙必须一致且等于 spacing。

    根因：导航 layout 的固定高度容器没有底部 Expanding spacer，隐藏入口后多余
    空间被摊进可见按钮间隙（实测 8→22px）。修复：垂直布局末尾加 Expanding spacer
    吸收多余空间。本测试锁定隐藏后的间隙与整体结构。
    """
    from mdcx.config.enums import Switch
    from mdcx.controllers.main_window import main_window as mw_mod

    old = list(mw_mod.manager.config.switch_on)
    monkeypatch.setattr(mw_mod.manager.config, "window_title", "show")  # 原生边框
    monkeypatch.setattr(mw_mod.manager.config, "switch_on", [*old, Switch.HIDE_ACTOR_NAV, Switch.HIDE_NFO_NAV])
    win.load_config()
    win._windows_auto_adjust()
    win.show()
    app.processEvents()

    layout = win.Ui.verticalLayout
    assert win.Ui.pushButton_emby_manager_nav.isHidden()
    assert win.Ui.pushButton_nfo_library.isHidden()

    nav_buttons = [
        win.Ui.pushButton_main,
        win.Ui.pushButton_log,
        win.Ui.pushButton_tool,
        win.Ui.pushButton_emby_manager_nav,
        win.Ui.pushButton_nfo_library,
        win.Ui.pushButton_setting,
        win.Ui.pushButton_net,
        win.Ui.pushButton_about,
    ]
    visible = [b for b in nav_buttons if not b.isHidden()]
    assert len(visible) == 6

    from itertools import pairwise

    gaps = [b.y() - (a.y() + a.height()) for a, b in pairwise(visible)]
    assert all(g == layout.spacing() for g in gaps), f"导航间隙不等于 spacing: {gaps}"


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


def test_nav_buttons_hide_switch(win, app):
    """议题 #71: 设置-高级「隐藏入口」开关控制导航按钮显隐（保存后 load_config 即时生效）。"""
    from mdcx.config.enums import Switch
    from mdcx.config.manager import manager

    actor_btn = win.Ui.pushButton_emby_manager_nav
    nfo_btn = win.Ui.pushButton_nfo_library
    assert not actor_btn.isHidden()
    assert not nfo_btn.isHidden()

    old_switch_on = list(manager.config.switch_on)
    try:
        manager.config.switch_on = [*old_switch_on, Switch.HIDE_ACTOR_NAV, Switch.HIDE_NFO_NAV]
        win.load_config()
        app.processEvents()
        assert actor_btn.isHidden()
        assert nfo_btn.isHidden()
        # 设置页复选框同步回写勾选状态
        assert win.Ui.checkBox_hide_actor_nav.isChecked()
        assert win.Ui.checkBox_hide_nfo_nav.isChecked()

        # 取消开关后入口恢复显示
        manager.config.switch_on = old_switch_on
        win.load_config()
        app.processEvents()
        assert not actor_btn.isHidden()
        assert not nfo_btn.isHidden()
        assert not win.Ui.checkBox_hide_actor_nav.isChecked()
    finally:
        manager.config.switch_on = old_switch_on


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


def _size(obj):
    return (obj.width(), obj.height())


def test_save_load_config_keeps_minimized_main_window(win, app, monkeypatch):
    """议题 #82：主窗最小化时，后台触发的配置保存/加载不得还原主窗。

    根因：save_config/load_config 末尾无条件
    `setWindowState(去最小化 | WindowActive)` + `activateWindow()`——Windows 原生
    边框下会强制还原最小化主窗。用户场景：主窗最小化跑刮削/操作演员管理器期间，
    任意自动保存把主窗弹出。修复：仅在主窗可见且未最小化时才恢复激活。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    # dummy manager 无 save 桩——本测试只验证窗口状态行为，配置落盘打桩跳过
    monkeypatch.setattr(mw_mod.manager, "save", lambda *a, **k: None, raising=False)

    win.show()
    app.processEvents()
    win.showMinimized()
    app.processEvents()
    assert win.isMinimized()

    win.save_config()
    app.processEvents()
    assert win.isMinimized(), "save_config 不应还原最小化主窗"

    win.load_config()
    app.processEvents()
    assert win.isMinimized(), "load_config 不应还原最小化主窗"


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


def test_setting_config_bar_docked_to_bottom(win, app):
    """设置页底部配置操作浮框（当前配置/另存为/恢复默认/保存）跟随贴底 + 保存按钮右缘锚定."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    setting_page = _goto(win, app, "page_setting")
    page_h = setting_page.height()

    win.resize(1920, 1040)
    app.processEvents()
    page_h = setting_page.height()

    # 整组控件贴新底部（设计基线距底 692-630=62，允许 DPI 误差）
    for btn, name in (
        (win.Ui.pushButton_save_new_config, "另存为"),
        (win.Ui.pushButton_init_config, "恢复默认"),
        (win.Ui.pushButton_save_config, "保存"),
    ):
        dock = page_h - btn.y()
        assert 55 <= dock <= 75, f"{name} 未贴底: 距底 {dock}（页高 {page_h}）"

    # 保存按钮右缘锚定（设计右距 820-731=89）
    right_gap = setting_page.width() - (win.Ui.pushButton_save_config.x() + win.Ui.pushButton_save_config.width())
    assert 80 <= right_gap <= 100, f"保存按钮右缘未锚定: 右距 {right_gap}"

    # 背景 label 拉伸贴宽
    assert win.Ui.label_config.width() >= setting_page.width() - 30, (
        f"配置浮框背景未拉伸: {win.Ui.label_config.width()} / {setting_page.width()}"
    )


def test_setting_form_inputs_stretch_with_viewport(win, app):
    """设置页表单输入控件随视口拉宽（gridLayout 重排，修复"表单缩在左侧"）."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    _goto(win, app, "page_setting")
    # 切到刮削目录 tab（tab0），取其中行编辑框
    from PyQt6.QtWidgets import QLineEdit

    tab0 = win.Ui.tabWidget.widget(0)
    edits = tab0.findChildren(QLineEdit)
    assert edits, "刮削目录 tab 无输入框"
    before = max(e.width() for e in edits)

    win.resize(1920, 1040)
    app.processEvents()

    after = max(e.width() for e in edits)
    print(f"form edit width: {before} -> {after}")
    assert after > before + 100, f"表单输入框未随视口拉宽: {before} -> {after}"


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


def test_probe_main_tool_content(win, app):
    """软件界面/软件工具页内容随视口拉宽（与设置页同款自适应）。"""

    from PyQt6.QtWidgets import QLineEdit

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_page = _goto(win, app, "page_tool")
    before_edit = max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0)
    before_outline = win.Ui.label_outline.width()
    before_series_x = win.Ui.label_series.x()

    win.resize(1920, 1040)
    app.processEvents()

    # 软件工具页：输入框跟随拉宽
    after_edit = max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0)
    print(f"tool_lineEdit : {before_edit} -> {after_edit}")
    print(f"main_outline  : {before_outline} -> {win.Ui.label_outline.width()}")
    print(f"series_x      : {before_series_x} -> {win.Ui.label_series.x()}")
    assert after_edit > before_edit + 200, f"工具页输入框未随视口拉宽: {before_edit} -> {after_edit}"

    # 软件界面：信息区标签拉伸、下半区右列平移（贴结果树左缘-30）
    tree_x = win.Ui.treeWidget_number.x()
    assert win.Ui.label_outline.width() > before_outline + 200, "简介标签未拉伸"
    assert win.Ui.label_outline.geometry().right() == pytest.approx(tree_x - 30, abs=4)
    assert win.Ui.label_series.x() > before_series_x + 200, "下半区右列未平移"
    # 上区受右侧按钮限制的拉伸右界
    assert win.Ui.label_number.geometry().right() == pytest.approx(min(450, tree_x - 30), abs=4)

    # 幂等性：还原-再放大后，几何与直接放大结果一致（固定公式基准，无累积漂移）
    win.resize(1040, 760)
    app.processEvents()
    win.resize(1920, 1040)
    app.processEvents()
    assert win.Ui.label_series.x() == pytest.approx(350 + (tree_x - 30 - 570), abs=4), "右列平移漂移"
    assert win.Ui.label_outline.geometry().right() == pytest.approx(tree_x - 30, abs=4), "标签拉伸漂移"
    assert after_edit == max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0), "工具页输入框宽漂移"


def test_runtime_row_follows_right_column_on_maximize(win, app):
    """议题 #82：最大化后「时长」行（右列 y=530）必须随右列平移。

    根因：_sync_page_layouts 下半区右列平移清单漏了 label_22（时长：标签,
    设计 x=310）与 label_runtime（时长值, 设计 x=350）——系列/发行平移后，
    时长行滞留原位，与左列日期行重叠错位。
    """
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    win.resize(1920, 1040)
    app.processEvents()

    tree_x = win.Ui.treeWidget_number.x()
    expected_extra = tree_x - 30 - 570
    assert win.Ui.label_22.x() == pytest.approx(310 + expected_extra, abs=4), (
        f"时长标签未平移: {win.Ui.label_22.x()} != {310 + expected_extra}"
    )
    assert win.Ui.label_runtime.x() == pytest.approx(350 + expected_extra, abs=4), (
        f"时长值未平移: {win.Ui.label_runtime.x()} != {350 + expected_extra}"
    )


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


def test_nfo_lib_layout_probe(win, app):
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    page = _goto(win, app, "page_nfo_library")
    top = win.Ui.nfo_lib_top_bar
    content = win.Ui.nfo_lib_content
    print(
        f"before: page={page.width()}x{page.height()} top={top.height()} content={content.width()}x{content.height()}"
    )

    win.resize(1920, 1040)
    app.processEvents()
    print(
        f"after : page={page.width()}x{page.height()} top={top.height()} content={content.width()}x{content.height()}"
    )
    print(
        f"gap right={page.width() - (content.x() + content.width())} bottom={page.height() - (content.y() + content.height())}"
    )

    # 嵌套子布局激活验证：page → content → scrollArea → formLayout
    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    form_layout = form_content.layout()
    print(f"form scroll viewport={form_scroll.viewport().width()} content={form_content.width()}")
    if form_layout is not None:
        print(f"form layout active={form_layout.isEnabled()} activated={form_layout.isEmpty()}")

    # 断言内容宽度跟随视口（消除右侧 194px 空白）
    assert form_content.width() >= form_scroll.viewport().width() - 20, (
        f"表单内容未跟随视口: content={form_content.width()} viewport={form_scroll.viewport().width()}"
    )

    # 保存按钮可见性：最大化后表单内容压缩简介/标签面积（议题 #78 用户建议），
    # 保存按钮必须落在滚动视口内、无需滚动即可见
    save_btn = win.Ui.pushButton_nfo_lib_save
    print(f"save btn: y={save_btn.y()} h={save_btn.height()} visible={save_btn.isVisible()}")
    print(f"form content height={form_content.height()} viewport height={form_scroll.viewport().height()}")
    # 简介/标签面积压缩（60px 固定，消除下拉栏）
    outline_h = win.Ui.plainTextEdit_nfo_lib_outline.height()
    tag_h = win.Ui.plainTextEdit_nfo_lib_tag.height()
    print(f"outline h={outline_h} tag h={tag_h}")
    assert outline_h == 60, f"简介未压到 60: {outline_h}"
    assert tag_h == 60, f"标签未压到 60: {tag_h}"
    # 保存按钮必须在视口内（无滚动可见），留 4px 安全边距应对平台差异
    save_bottom = save_btn.y() + save_btn.height()
    assert save_bottom <= form_scroll.viewport().height() - 4, (
        f"保存按钮仍被推视口: bottom={save_bottom} viewport={form_scroll.viewport().height()}"
    )
    # 内容总高不显著超过视口（缩列下拉栏消除——用户报告"下拉栏"现象）
    assert form_content.height() <= form_scroll.viewport().height() + 40, (
        f"表单总高超视口: content={form_content.height()} viewport={form_scroll.viewport().height()}"
    )


def test_scrollareas_restore_compact_after_maximize(win, app):
    """议题 #82：最大化→还原后，各页 scrollArea 内容几何必须回落紧凑基线。

    根因三层叠加：
    1. sync_wide_children_width 只增不减（extra<=0 直接 return），最大化拉宽的
       宽幅容器还原时不缩回；
    2. content.minimumWidth 从「拉宽后的」childrenRect 计算并锁死，widgetResizable
       受 minimumWidth 阻挡无法把内容缩回视口——设置/工具页内容右缘被裁剪；
    3. layout 驱动内容（NFO 表单 QFormLayout）的 minimumHeight 从膨胀
       childrenRect 计算：Expanding 行（简介/标签多行框）在超高容器中分得额外
       空间，childrenRect 抬高 → 最小高自锁（993 降不回紧凑 674），保存按钮
       被推出视口。
    修复：宽幅容器按「设计几何+extra」双向幂等伸缩；min_width 以设计宽为上界；
    layout 驱动内容的 min 尺寸改用 layout.sizeHint（紧凑排布，与容器拉伸无关）。
    """
    from mdcx.views.CustomClass import CustomScrollArea

    win.resize(1040, 760)
    win.show()
    app.processEvents()
    _goto(win, app, "page_nfo_library")

    # 最大化 → 还原
    win.resize(1920, 1040)
    app.processEvents()
    win.resize(1040, 760)
    app.processEvents()

    # 设置页当前 tab：内容宽度回落视口内，min 宽不再锁死在最大化值（1599）
    _goto(win, app, "page_setting")
    tab0 = win.Ui.tabWidget.widget(0)
    scroll = tab0.findChild(CustomScrollArea)
    assert scroll.widget().width() <= scroll.viewport().width() + 2, (
        f"设置页内容宽未回落: content={scroll.widget().width()} viewport={scroll.viewport().width()}"
    )
    assert scroll.widget().minimumWidth() <= 800, f"设置页内容 min 宽锁死: {scroll.widget().minimumWidth()}"

    # 工具页：同上（曾锁死 1603）
    _goto(win, app, "page_tool")
    tool_scroll = win.Ui.page_tool.findChild(CustomScrollArea)
    assert tool_scroll.widget().width() <= tool_scroll.viewport().width() + 2, (
        f"工具页内容宽未回落: content={tool_scroll.widget().width()} viewport={tool_scroll.viewport().width()}"
    )
    assert tool_scroll.widget().minimumWidth() <= 800, f"工具页内容 min 宽锁死: {tool_scroll.widget().minimumWidth()}"

    # NFO 表单：内容回落紧凑、保存按钮回到视口内（曾 y=946 > 视口 674）
    _goto(win, app, "page_nfo_library")
    app.processEvents()
    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    assert form_content.height() <= 760, f"NFO 表单未回落紧凑: {form_content.height()}"
    save_btn = win.Ui.pushButton_nfo_lib_save
    assert save_btn.y() + save_btn.height() <= form_scroll.viewport().height() + 4, (
        f"NFO 保存按钮仍在视口外: bottom={save_btn.y() + save_btn.height()} viewport={form_scroll.viewport().height()}"
    )
