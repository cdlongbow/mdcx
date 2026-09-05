from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QComboBox, QScrollArea, QSlider, QSpinBox, QWidget


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
    _CONTENT_BOTTOM_MARGIN = 60

    # 顶层容器判定为"宽幅"的右缘阈值比例：设计右缘 ≥ 内容设计宽的 85%。
    _WIDE_CHILD_RIGHT_RATIO = 0.85

    def sync_content_min_height(self) -> None:
        content = self.widget()
        if content is None:
            return
        children_rect = content.childrenRect()
        if children_rect.height() <= 0:
            return
        min_width = children_rect.right() + 1
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

    def _register_design_geometry(self, content: QWidget) -> None:
        """按设计几何登记宽幅顶层容器与内容基准宽。

        登记发生在 setupUi 的 setWidget 时刻，几何必然是设计器值；
        之后 widgetResizable/本类的拉伸不会覆盖登记数据，同步幂等。
        """
        design_w = content.width()
        threshold = int(design_w * self._WIDE_CHILD_RIGHT_RATIO)
        from PyQt6.QtWidgets import QGroupBox

        registry = []
        for child in content.findChildren(QGroupBox):
            if child.parentWidget() is not content:
                continue
            g = child.geometry()
            if g.width() <= 0 or g.right() + 1 < threshold:
                continue
            registry.append((child, (g.x(), g.y(), g.width(), g.height())))
        setattr(content, "_wide_children_design", registry)
        setattr(content, "_wide_children_design_width", design_w)

    def sync_wide_children_width(self) -> None:
        """视口宽于内容设计宽时，把宽幅顶层容器拉到视口宽。

        按登记的设计几何计算 extra = 视口宽 - 设计宽，各容器宽度 = 设计宽 + extra，
        保持设计左边距与右缘边距。窄控件（表单项）保持原位；无宽幅容器的
        滚动区（如 NFO 库 360 宽表单）登记为空自动跳过。
        """
        content = self.widget()
        if content is None:
            return
        registry = getattr(content, "_wide_children_design", None)
        if not registry:
            return
        viewport = self.viewport()
        if viewport is None:
            return
        design_w = getattr(content, "_wide_children_design_width", 0)
        extra = viewport.width() - design_w
        for child, (x, y, w, h) in registry:
            child.setGeometry(x, y, max(w + extra, w // 2), h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_content_min_height()
        self.sync_wide_children_width()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_content_min_height()
        self.sync_wide_children_width()
