from dataclasses import dataclass, field

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QComboBox, QScrollArea, QSlider, QSpinBox, QWidget

# 子控件跟随分类
_STRETCH = "stretch"  # 宽幅拉伸：宽 ≥ groupBox 内宽 55%（输入框等）
_DOCK_RIGHT = "dock_right"  # 右缘锚定：设计右缘 ≥ groupBox 内宽 90%（浏览按钮等）
_KEEP = "keep"  # 保持原位：其余（标签、小组件）


@dataclass
class _InnerItem:
    """groupBox 内部子项：控件 + 设计几何 + 跟随分类."""

    widget: QWidget
    geometry: tuple[int, int, int, int]
    kind: str = _KEEP


@dataclass
class _WideChildEntry:
    """宽幅顶层容器登记项：容器本体 + 设计几何 + 内部子项清单."""

    widget: QWidget
    geometry: tuple[int, int, int, int]
    inner: list[_InnerItem] = field(default_factory=list)


class CustomQComboBox(QComboBox):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


class CustomQSpinBox(QSpinBox):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


class CustomQSlider(QSlider):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


class CustomScrollArea(QScrollArea):
    """widgetResizable=true 时按子控件包围盒维护内容最小高度的滚动区。

    背景：设计器生成的滚动区内容 widget 无布局，子控件绝对定位；
    widgetResizable=false 时内容保持固定几何尺寸、垂直滚动正常，但内容
    宽度不跟随视口（高 DPI 下右侧被裁剪）；widgetResizable=true 后宽度自
    适应，但 Qt 对无布局 widget 的最小尺寸提示不来自 childrenRect，内容
    被拉伸到视口高度，垂直滚动条失效。这里在滚动区尺寸变化 / 页面显示时
    按 childrenRect 显式补最小高度，同时保留宽度自适应。

    另：内容里的宽幅容器（groupBox 等，设计右缘≈内容设计右缘）在视口变宽时
    跟随拉伸——休眠页 content 拉宽后绝对定位子控件不会自行展开，表单会缩在
    设计宽度 860 内、右侧大片留白（用户反馈"最大化后内容横向不放大"）。
    """

    # Leave enough room for the last row, frame, font metrics, and DPI scaling.
    # ≥ 浮框带侵入视口底部的 63px（page_setting 底部配置浮框盖住滚动区下缘），
    # 保证滚动到底时最后一行完全位于浮框带上方（用户截图：末行文字从浮框后透出）。
    _CONTENT_BOTTOM_MARGIN = 72

    # 顶层容器判定为"宽幅"的右缘阈值比例：设计右缘 ≥ 内容设计宽的 85%。
    _WIDE_CHILD_RIGHT_RATIO = 0.85

    def sync_content_min_height(self) -> None:
        content = self.widget()
        if content is None:
            return
        # 议题 #82：layout 驱动的内容（如 NFO 表单 QFormLayout）不能按 childrenRect
        # 算最小高——Expanding 行（简介/标签多行框）在超高容器里会分得额外空间，
        # childrenRect 随之膨胀，最小高一旦抬高就自锁（还原后永远降不回紧凑态，
        # 保存按钮被推出视口）。layout.sizeHint() 是紧凑排布尺寸，与容器拉伸无关。
        content_layout = content.layout()
        if content_layout is not None:
            content_layout.invalidate()
            size_hint = content_layout.sizeHint()
            if size_hint.height() <= 0:
                return
            min_width = size_hint.width()
            # layout 驱动内容同样补底部余量：sizeHint 是紧凑排布高度，
            # 不加余量时滚动到底最后一行贴视口底、被浮框带盖住 63px
            min_height = size_hint.height() + self._CONTENT_BOTTOM_MARGIN
        else:
            children_rect = content.childrenRect()
            if children_rect.height() <= 0:
                return
            # 无布局内容：min_width 不能以「可能被拉宽过的」childrenRect 为准——
            # 最大化后子控件被拉宽，childrenRect.right() 锁在高位，还原窗口时
            # widgetResizable 受 minimumWidth 阻挡无法把内容缩回视口，右侧被裁剪。
            # 以登记的设计宽为上界：拉宽场景内容宽由 viewport 决定（>min 不冲突），
            # 还原场景 min_width 回落到设计宽，内容随之缩回。
            design_w = getattr(content, "_wide_children_design_width", 0)
            measured_w = children_rect.right() + 1
            min_width = min(measured_w, design_w) if design_w > 0 else measured_w
            min_height = children_rect.bottom() + self._CONTENT_BOTTOM_MARGIN
        if content.minimumWidth() != min_width or content.minimumHeight() != min_height:
            content.setMinimumWidth(min_width)
            content.setMinimumHeight(min_height)
            content.updateGeometry()

    def setWidget(self, widget) -> None:
        """登记内容设计几何（setupUi 阶段调用，此时全部为设计器几何）。"""
        super().setWidget(widget)
        if widget is not None:
            self._register_design_geometry(widget)

    # 输入类控件：横向自适应的标准控件，无论宽窄一律拉伸跟随
    _STRETCH_WIDGET_CLASSES = (
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QTextBrowser",
        "QComboBox",
        "QTreeWidget",
        "QListWidget",
        "QTableWidget",
        "QTreeWidget",
    )

    def _classify_inner(self, sub: QWidget, inner_w: int, box_w: int) -> str | None:
        """groupBox 内部子项分类：拉伸 / 右缘锚定 / None（不登记保持原位）。"""
        if sub.layout() is not None:
            return _STRETCH  # 布局容器：拉宽后 invalidate+activate 重排列宽
        meta = sub.metaObject()
        if meta is not None and meta.className() in self._STRETCH_WIDGET_CLASSES:
            return _STRETCH  # 输入类控件（输入框/下拉/列表/树）跟随拉宽
        sg = sub.geometry()
        if sg.width() >= inner_w * 0.5:
            return _STRETCH  # 其他宽幅控件（标签/分组框）跟随拉宽
        if sg.right() + 1 >= box_w * 0.9:
            return _DOCK_RIGHT  # 右缘控件（浏览/选择按钮）右缘锚定
        return None

    def _register_design_geometry(self, content: QWidget) -> None:
        """按设计几何登记宽幅顶层容器与内容基准宽。

        登记发生在 setupUi 的 setWidget 时刻，几何必然是设计器值；
        之后 widgetResizable/本类的拉伸不会覆盖登记数据，同步幂等。

        登记结构：顶层宽幅 QGroupBox + 其内部全部直接子项（布局容器与
        绝对定位控件并存的设计器产物）按设计几何分类——布局容器（内含
        QGridLayout）与宽幅输入框拉伸、右缘贴 groupBox 内缘的控件锚定
        右缘、其余保持原位。
        """
        design_w = content.width()
        threshold = int(design_w * self._WIDE_CHILD_RIGHT_RATIO)
        from PyQt6.QtWidgets import QGroupBox

        registry: list[_WideChildEntry] = []
        for child in content.findChildren(QGroupBox):
            if child.parentWidget() is not content:
                continue
            g = child.geometry()
            if g.width() <= 0 or g.right() + 1 < threshold:
                continue
            entry = _WideChildEntry(widget=child, geometry=(g.x(), g.y(), g.width(), g.height()))
            inner_w = g.width() - 20  # groupBox 内可用宽（左右各 ~10 边距）
            for sub in child.findChildren(QWidget):
                if sub.parentWidget() is not child:
                    continue
                sg = sub.geometry()
                if sg.width() <= 0 or sg.height() <= 0:
                    continue
                kind = self._classify_inner(sub, inner_w, g.width())
                if kind is None:
                    continue
                entry.inner.append(
                    _InnerItem(widget=sub, geometry=(sg.x(), sg.y(), sg.width(), sg.height()), kind=kind)
                )
            registry.append(entry)
        setattr(content, "_wide_children_design", registry)
        setattr(content, "_wide_children_design_width", design_w)

    def sync_wide_children_width(self) -> None:
        """宽幅顶层容器宽度跟随视口：视口宽于设计宽时拉宽，窄于设计宽时缩回。

        按登记的设计几何计算 extra = 视口宽 - 设计宽，各容器宽度 = 设计宽 + extra，
        保持设计左边距与右缘边距。groupBox 内部子项按分类跟随：
        布局容器与宽幅输入框拉伸（布局容器另需 invalidate+activate 强制重排，
        否则 QGridLayout 内输入框列宽不变）；右缘控件右缘锚定平移；其余保持原位。
        无宽幅容器的滚动区（如 NFO 库 360 宽表单）登记为空自动跳过。

        议题 #82：extra<=0 必须按同一公式缩回（旧实现直接 return 只增不减）——
        否则最大化后容器宽度锁死在高位，childrenRect 撑大 → content minimumWidth
        被永久抬高 → 还原窗口后内容右侧被视口裁剪（设置/工具页内容右缘消失）。
        固定「设计几何 + extra」公式双向幂等，无累积漂移。
        """
        content = self.widget()
        if content is None:
            return
        registry: list[_WideChildEntry] | None = getattr(content, "_wide_children_design", None)
        if not registry:
            return
        viewport = self.viewport()
        if viewport is None:
            return
        design_w = getattr(content, "_wide_children_design_width", 0)
        extra = viewport.width() - design_w
        for entry in registry:
            x, y, w, h = entry.geometry
            box = entry.widget
            box.setGeometry(x, y, max(w + extra, w // 2), h)
            for item in entry.inner:
                sub = item.widget
                sx, sy, sw, sh = item.geometry
                if item.kind == _STRETCH:
                    sub.setGeometry(sx, sy, max(sw + extra, sw // 2), sh)
                    inner_layout = sub.layout()
                    if inner_layout is not None:
                        # 布局系统对休眠/未重绘 widget 不自动激活，容器拉宽后
                        # 必须显式重排，否则 QGridLayout 内输入框列宽不变
                        inner_layout.invalidate()
                        inner_layout.activate()
                else:  # _DOCK_RIGHT
                    sub.move(sx + extra, sy)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 先同步宽幅容器（含缩回），再按最新 childrenRect 补内容最小尺寸——
        # 顺序颠倒会让 min_width 吃到拉伸后的旧包围盒，还原路径锁死（议题 #82）
        self.sync_wide_children_width()
        self.sync_content_min_height()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_wide_children_width()
        self.sync_content_min_height()

