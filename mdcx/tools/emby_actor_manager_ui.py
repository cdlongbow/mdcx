from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from pydantic import HttpUrl
from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.manager import manager
from ..config.resources import resources
from ..utils import executor
from .emby_actor_manager import (
    ActorInfo,
    build_local_avatar_index,
    fetch_actor_detail,
    fetch_actor_info_from_source,
    fetch_all_actors,
    from_gfriends,
    from_graphis,
    from_local_avatar,
    from_minnano_image,
    get_gfriends_index,
    get_media_folders,
    search_actor_info,
    sync_batch,
)


class LibrarySelectDialog(QDialog):
    def __init__(self, libraries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择媒体库")
        self.setMinimumWidth(420)
        self.setMinimumHeight(320)
        self._libraries = libraries
        self._checkboxes: list[QCheckBox] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        count = len(self._libraries)
        label = QLabel(f"选择要获取演员的媒体库（共 {count} 个，默认全选）：")
        layout.addWidget(label)
        self.list_widget = QListWidget()
        for lib in self._libraries:
            name = lib.get("Name", "未知")
            ctype = lib.get("CollectionType", "")
            display = f"{name}  [{ctype}]" if ctype else name
            cb = QCheckBox(display)
            cb.setChecked(True)
            self._checkboxes.append(cb)
            item = QListWidgetItem()
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, cb)
        layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("取消全选")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool):
        for cb in self._checkboxes:
            cb.setChecked(checked)

    def get_selected_ids(self) -> list[str]:
        selected = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked() and i < len(self._libraries):
                selected.append(self._libraries[i].get("Id", ""))
        return selected


class FetchActorsThread(QThread):
    progress = Signal(int, int, str)
    fetch_done = Signal(list)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library_ids = None

    def run(self):
        try:
            actors = executor.run(
                fetch_all_actors(
                    filter_actor_only=manager.config.actor_filter_only,
                    deduplicate=manager.config.actor_deduplicate,
                    parent_ids=self.library_ids,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                )
            )
            self.fetch_done.emit(actors)
        except Exception as e:
            self.error.emit(str(e))


class PreparePreviewThread(QThread):
    progress = Signal(int, int, str)
    preview_done = Signal(list)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []
        self.mode = "missing_all"
        self.gfriends_index = None
        self.cache_dir = resources.u("emby_actor_cache")
        self.image_sources = ["gfriends", "graphis", "minnano", "local"]
        self.local_avatar_dir = ""
        self._local_avatar_index: dict[str, str] | None = None
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from .minnano_crawler import load_cache as minnano_load_cache

            minnano_load_cache()
            total = len(self.actors)
            if total == 0:
                self.preview_done.emit(self.actors)
                return
            need_image = self.mode in ("missing_all", "missing_image", "force_all", "force_image")
            need_info = self.mode in ("missing_all", "missing_info", "force_all", "force_info")
            force = "force" in self.mode
            cancelled = False
            cancelled = executor.run(self._process_all(need_image, need_info, force, total))
            if not cancelled:
                self.progress.emit(total, total, "预览数据准备完成")
            self.preview_done.emit(self.actors)
        except Exception:
            import traceback

            self.error.emit(f"获取数据失败: {traceback.format_exc()}")

    async def _process_all(self, need_image: bool, need_info: bool, force: bool, total: int) -> bool:
        """在单个 event loop 内并发处理所有演员，避免多线程多 loop 并发共享 async_client。"""
        if need_image and "local" in self.image_sources and self.local_avatar_dir:
            self.progress.emit(0, total, "扫描本地头像目录...")
            self._local_avatar_index = await asyncio.to_thread(build_local_avatar_index, self.local_avatar_dir)

        sem = asyncio.Semaphore(10)

        async def guarded(actor: ActorInfo) -> ActorInfo:
            async with sem:
                try:
                    if need_image:
                        await self._try_fetch_image(actor, force)
                    if need_info:
                        await self._try_fetch_info(actor, force)
                except Exception:
                    import traceback

                    from ..signals import signal

                    signal.show_log_text(f"🔶 演员处理异常: {actor.name}: {traceback.format_exc()}")
                return actor

        completed = 0
        cancelled = False
        tasks = [guarded(actor) for actor in self.actors]
        for coro in asyncio.as_completed(tasks):
            if self._cancel:
                cancelled = True
                break
            completed += 1
            actor = await coro
            self.progress.emit(completed, total, f"处理中: {actor.name} ({completed}/{total})")
        return cancelled

    async def _try_fetch_image(self, actor: ActorInfo, force: bool):
        if not force and actor.has_image:
            return
        graphis_attempted = False
        graphis_backdrop: str | None = None
        # 头像：按配置源顺序第一个命中即采用（保留用户设置优先级）
        for src in self.image_sources:
            if src == "graphis":
                graphis_attempted = True
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[0]:
                    actor.new_image_path = graphis_result[0]
                    actor.need_update_image = True
                    graphis_backdrop = graphis_result[1]
                    break
                continue
            result = await self._fetch_avatar_from(actor, src)
            if result:
                actor.new_image_path = result
                actor.need_update_image = True
                break
        # 背景图：头像命中不代表有背景（gfriends/local/minnano 均无背景），
        # 若仍缺背景，用 graphis 补——避免头像先命中导致背景永远无法补齐。
        # graphis 若已在头像循环尝试过，直接复用其结果，不重复请求。
        if not actor.has_backdrop and not actor.need_update_backdrop and "graphis" in self.image_sources:
            if graphis_backdrop:
                actor.new_backdrop_path = graphis_backdrop
                actor.need_update_backdrop = True
            elif not graphis_attempted:
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[1]:
                    actor.new_backdrop_path = graphis_result[1]
                    actor.need_update_backdrop = True

    async def _fetch_avatar_from(self, actor: ActorInfo, src: str) -> str | None:
        """从单个图源尝试获取头像路径；未命中返回 None。graphis 由 _try_fetch_image 特判处理。"""
        if src == "gfriends" and self.gfriends_index:
            return await from_gfriends(actor, self.gfriends_index, self.cache_dir)
        if src == "minnano":
            return await from_minnano_image(actor, self.cache_dir)
        if src == "local":
            return from_local_avatar(actor, self.local_avatar_dir, self._local_avatar_index)
        return None

    async def _try_fetch_info(self, actor: ActorInfo, force: bool):
        if not force and actor.has_overview:
            detail = await fetch_actor_detail(actor.name)
            if detail:
                overview = (detail.get("Overview") or "").strip()
                if overview and "无维基百科信息" not in overview:
                    return
        result = await search_actor_info(actor)
        if result:
            actor.need_update_info = True


class SyncThread(QThread):
    progress = Signal(int, int, str)
    actor_done = Signal(str, str, bool, str)  # (actor_id, name, success, msg)
    sync_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []

    def run(self):
        try:
            success, fail = sync_batch(
                self.actors,
                progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                actor_callback=lambda actor, ok, msg: self.actor_done.emit(actor.actor_id, actor.name, ok, msg),
            )
            self.sync_done.emit(success, fail)
        except Exception as e:
            self.error.emit(str(e))


def _future_result_or(future, default):
    """取 Future 结果；协程异常时返回 default，避免异常传播到后台 loop 线程。"""
    try:
        return future.result()
    except Exception:
        return default


class EmbyActorManagerDialog(QDialog):
    _connect_result = Signal(object)
    _media_folders_result = Signal(object)
    _gfriends_result = Signal(object)

    def __init__(self, parent=None):
        # 不传 parent：始终保持独立顶层窗口。议题 #61——以主窗口为 parent 时，
        # 主窗口 hide 会级联隐藏 dialog，最大化 dialog 又会把主窗口带出。
        super().__init__(None)
        self.setWindowTitle("Emby 演员管理器")
        self.setMinimumSize(1100, 700)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象，主窗口侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 初始落在最小尺寸上体验局促，默认取屏幕可用区 80%（离屏/无屏环境回退最小尺寸）
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.resize(max(1100, int(geo.width() * 0.8)), max(700, int(geo.height() * 0.8)))
        else:
            self.resize(1100, 700)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(self._load_stylesheet())
        self.cache_dir = resources.u("emby_actor_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._actors: list[ActorInfo] = []
        self._gfriends_index = None
        self._preview_thread = None
        self._sync_thread = None
        self._fetch_thread = None
        self._failed_names: set[str] = set()
        self._log_file: Path | None = None
        self._init_ui()
        self._connect_signals()
        self._open_log_file()

    def _load_stylesheet(self) -> str:
        return """
        QGroupBox { font-weight: bold; border: 1px solid #cccccc; border-radius: 4px; margin-top: 8px; padding-top: 14px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QTableWidget { gridline-color: #e0e0e0; selection-background-color: #bbdefb; }
        QTableWidget::item:selected { background-color: #42a5f5; color: #ffffff; }
        QPushButton#btnSync { background-color: #2e7d32; color: #ffffff; font-weight: bold; }
        QPushButton#btnSync:hover { background-color: #388e3c; }
        QPushButton#btnDanger { background-color: #c62828; color: #ffffff; }
        QPushButton#btnDanger:hover { background-color: #d32f2f; }
        QPushButton#btnPrimary { background-color: #1565c0; color: #ffffff; }
        QPushButton#btnPrimary:hover { background-color: #1976d2; }
        """

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)
        self._build_connection_section(main_layout)
        splitter = QSplitter(Qt.Orientation.Vertical)
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self._build_actor_list(list_layout)
        splitter.addWidget(list_widget)
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self._build_log_section(log_layout)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        # 底部状态栏：当前状态 + Emby 连接状态
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("未连接")
        main_layout.addWidget(self.status_bar)

    def _set_status(self, message: str):
        connected = hasattr(self, "_connected") and self._connected
        prefix = "已连接" if connected else "未连接"
        self.status_bar.showMessage(f"{prefix} | {message}")

    def _build_connection_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("Emby 连接设置")
        grid = QGridLayout(group)
        grid.setSpacing(8)
        grid.addWidget(QLabel("Emby 地址:"), 0, 0)
        self.txt_url = QLineEdit(str(manager.config.emby_url or ""))
        self.txt_url.setPlaceholderText("http://192.168.1.100:8096")
        grid.addWidget(self.txt_url, 0, 1)
        grid.addWidget(QLabel("API 密钥:"), 0, 2)
        self.txt_api_key = QLineEdit(manager.config.api_key or "")
        self.txt_api_key.setPlaceholderText("Emby 管理后台 → 高级 → API 密钥")
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self.txt_api_key, 0, 3)
        btn_layout = QHBoxLayout()
        self.btn_connect = QPushButton("连接 Emby")
        self.btn_connect.setObjectName("btnPrimary")
        btn_layout.addWidget(self.btn_connect)
        self.btn_fetch = QPushButton("获取演员列表")
        self.btn_fetch.setObjectName("btnPrimary")
        self.btn_fetch.setEnabled(False)
        btn_layout.addWidget(self.btn_fetch)
        self.cmb_fetch_mode = QComboBox()
        self.cmb_fetch_mode.addItems(
            [
                "仅全部缺失头像+简介",
                "仅全部缺失头像",
                "仅全部缺失简介",
                "全部头像+简介（重新获取）",
                "全部头像（重新获取）",
                "全部简介（重新获取）",
            ]
        )
        self.cmb_fetch_mode.setCurrentIndex(0)
        self.cmb_fetch_mode.setFixedWidth(220)
        btn_layout.addWidget(self.cmb_fetch_mode)
        self.btn_preview = QPushButton("根据设定获取数据")
        self.btn_preview.setObjectName("btnPrimary")
        self.btn_preview.setEnabled(False)
        btn_layout.addWidget(self.btn_preview)
        self.btn_sync = QPushButton("开始全部更新同步")
        self.btn_sync.setObjectName("btnSync")
        self.btn_sync.setEnabled(False)
        btn_layout.addWidget(self.btn_sync)
        btn_layout.addStretch()
        self.btn_test_source = QPushButton("数据源测试")
        btn_layout.addWidget(self.btn_test_source)
        self.btn_clear_cache = QPushButton("清空缓存文件夹")
        btn_layout.addWidget(self.btn_clear_cache)
        self.btn_settings = QPushButton("设置")
        btn_layout.addWidget(self.btn_settings)
        grid.addLayout(btn_layout, 1, 0, 1, 4)
        help_label = QLabel(
            "使用说明：① 填写地址和密钥 → ② 连接/获取演员列表 → ③ 选择模式获取数据 → "
            "④ 绿色行=待更新 → ⑤ 开始同步到 Emby。双击行可查看当前头像/简介/出生日期/影片数等详情。"
        )
        help_label.setStyleSheet("color: #888888; font-size: 12px; padding: 2px 0;")
        grid.addWidget(help_label, 2, 0, 1, 4)
        parent_layout.addWidget(group)

    def _build_actor_list(self, parent_layout: QVBoxLayout):
        stats_layout = QHBoxLayout()
        self.lbl_total = QLabel("总数: -")
        self.lbl_has_both = QLabel("完整: -")
        self.lbl_missing_image = QLabel("缺头像: -")
        self.lbl_missing_info = QLabel("缺简介: -")
        self.lbl_missing_all = QLabel("全缺: -")
        self.lbl_backdrop = QLabel("有背景图: -")
        for lbl in (
            self.lbl_total,
            self.lbl_has_both,
            self.lbl_missing_image,
            self.lbl_missing_info,
            self.lbl_missing_all,
            self.lbl_backdrop,
        ):
            lbl.setStyleSheet("padding: 2px 8px;")
            stats_layout.addWidget(lbl)
        stats_layout.addStretch()
        parent_layout.addLayout(stats_layout)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("筛选:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(["全部", "待同步", "缺头像", "缺背景", "缺简介", "缺头像和简介", "完整"])
        self.cmb_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.cmb_filter)
        filter_layout.addWidget(QLabel("  搜索:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("输入演员名搜索...")
        self.txt_search.setMaximumWidth(200)
        self.txt_search.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.txt_search)
        hint = QLabel("双击行可编辑")
        hint.setStyleSheet("color: #888888; font-size: 12px;")
        filter_layout.addWidget(hint)
        filter_layout.addStretch()
        parent_layout.addLayout(filter_layout)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        parent_layout.addWidget(self.progress_bar)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["状态", "姓名", "头像", "简介", "详情", "标签", "影片数"])
        horizontal_header = self.table.horizontalHeader()
        assert horizontal_header is not None
        horizontal_header.setStretchLastSection(False)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        vertical_header = self.table.verticalHeader()
        assert vertical_header is not None
        vertical_header.setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(4, 350)
        self.table.setColumnWidth(5, 200)
        self.table.setColumnWidth(6, 60)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        parent_layout.addWidget(self.table)

    def _build_log_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        layout.addWidget(self.log_text)
        parent_layout.addWidget(group)

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_fetch.clicked.connect(self._on_fetch)
        self.btn_preview.clicked.connect(self._on_prepare_preview)
        self.btn_sync.clicked.connect(self._on_sync)
        self.btn_settings.clicked.connect(self._on_open_settings)
        self.btn_test_source.clicked.connect(self._on_open_test_source)
        self.btn_clear_cache.clicked.connect(self._on_clear_cache)
        self._connect_result.connect(self._on_connect_result)
        self._media_folders_result.connect(self._on_media_folders_result)
        self._gfriends_result.connect(self._on_gfriends_result)

    def _on_open_settings(self):
        dialog = EmbyActorSettingsDialog(self)
        dialog.exec()

    def _on_open_test_source(self):
        dialog = ActorSourceTestDialog(self)
        dialog.exec()

    def _on_clear_cache(self):
        from ..config.resources import resources

        cache_dirs = [self.cache_dir, resources.u("actor")]
        reply = QMessageBox.question(
            self,
            "确认清空缓存",
            "将删除已下载的演员头像缓存（下次获取时会重新下载）。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        import shutil

        for cache_dir in cache_dirs:
            if not cache_dir.is_dir():
                continue
            for f in cache_dir.iterdir():
                try:
                    if f.is_dir():
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        f.unlink()
                    removed += 1
                except Exception:
                    continue
        self.log(f"🧹 已清空 {len(cache_dirs)} 个缓存目录，删除 {removed} 个文件/目录")

    def _open_log_file(self):
        """打开演员管理器日志文件（追加模式）"""
        try:
            log_dir = resources.u("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file = log_dir / "actor_manager.log"
        except Exception:
            self._log_file = None

    def _close_log_file(self):
        """关闭日志文件（由 Qt 在窗口关闭时自动调用）"""
        self._log_file = None

    def log(self, msg: str):
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] {msg}"
        self.log_text.appendPlainText(formatted)
        if self._log_file is not None:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_connect.setEnabled(enabled)
        self.btn_fetch.setEnabled(enabled and hasattr(self, "_connected") and self._connected)
        actors = getattr(self, "_actors", None) or []
        self.btn_preview.setEnabled(enabled and len(actors) > 0)
        pending = any(a.need_update_info or a.need_update_image or a.need_update_backdrop for a in actors)
        self.btn_sync.setEnabled(enabled and pending)

    def _on_connect(self):
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请输入 Emby 地址和 API 密钥")
            return
        from .emby_shared import _build_jellyfin_headers

        if "emby" in str(manager.config.server_type):
            headers = {"Authorization": f'MediaBrowser Token="{key}"'}
        else:
            # Jellyfin 10.11+/12.x 要求完整 MediaBrowser 设备标识, 复用统一构造器
            headers = _build_jellyfin_headers(token=key)
        self._emby_url = url
        self._emby_key = key

        async def test():
            async with manager.acquire_computed() as computed:
                test_url = (
                    f"{url.rstrip('/')}/emby/System/Info?api_key={key}"
                    if "emby" in str(manager.config.server_type)
                    else f"{url.rstrip('/')}/System/Info"
                )
                resp, err = await computed.async_client.get_json(test_url, headers=headers, use_proxy=False)
                if resp:
                    name = resp.get("ServerName", "Emby")
                    version = resp.get("Version", "")
                    return True, f"连接成功！{name} v{version}"
                return False, f"连接失败: {err}"

        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("连接中...")
        self._set_status("连接中...")
        try:
            future = executor.submit(test())
        except Exception as e:
            future = None
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("连接 Emby")
            self._set_status("连接失败")
            self.log(f"❌ 连接失败: {e}")
            return
        future.add_done_callback(lambda fut: self._connect_result.emit(_future_result_or(fut, (False, "连接失败"))))

    def _on_connect_result(self, result: tuple[bool, str]):
        ok, msg = result
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("已连接" if ok else "连接 Emby")
        if ok:
            self._connected = True
            self.btn_fetch.setEnabled(True)
            self._set_status("连接成功")
            self.log(f"✅ {msg}")
            self._persist_connection()
        else:
            self._set_status("连接失败")
            self.log(f"❌ {msg}")
            QMessageBox.critical(self, "连接失败", msg)

    def _persist_connection(self):
        """把 UI 填写的地址/密钥写回全局配置，保证后续请求与界面一致。"""
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.api_key = self._emby_key
            cfg.emby_url = HttpUrl(self._emby_url)
            manager._replace_config(cfg)
            # 写盘移后台线程，避免主线程同步 IO 卡顿
            threading.Thread(target=manager.save, daemon=True).start()
            self.log("💾 已保存连接设置到配置")
        except Exception as e:
            self.log(f"🔶 连接设置保存失败，继续使用当前配置: {e}")

    def _on_fetch(self):
        if not hasattr(self, "_connected") or not self._connected:
            QMessageBox.warning(self, "提示", "请先连接 Emby 服务器")
            return
        self.btn_fetch.setEnabled(False)
        self._set_status("获取媒体库列表...")
        try:
            future = executor.submit(get_media_folders())
        except Exception as e:
            self.btn_fetch.setEnabled(True)
            self._set_status("获取媒体库列表失败")
            self.log(f"❌ 获取媒体库列表失败: {e}")
            return
        future.add_done_callback(lambda fut: self._media_folders_result.emit(_future_result_or(fut, [])))

    def _on_media_folders_result(self, libraries: list[dict]):
        self.btn_fetch.setEnabled(True)
        if not libraries:
            self._set_status("获取媒体库列表失败")
            self.log("❌ 无法获取媒体库列表")
            return
        dlg = LibrarySelectDialog(libraries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.log("⏹ 用户取消")
            return
        selected_ids = dlg.get_selected_ids()
        if not selected_ids:
            QMessageBox.warning(self, "提示", "请至少选择一个媒体库")
            return
        library_ids = None if len(selected_ids) == len(libraries) else selected_ids
        self._current_library_ids = library_ids  # 供同步后自动刷新复用，避免丢媒体库过滤
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("获取演员列表...")
        self.log("📜 开始获取演员列表...")
        self._fetch_thread = FetchActorsThread(self)
        self._fetch_thread.library_ids = library_ids
        self._fetch_thread.progress.connect(self._on_fetch_progress)
        self._fetch_thread.fetch_done.connect(self._on_fetch_finished)
        self._fetch_thread.error.connect(self._on_thread_error)
        self._fetch_thread.start()

    def _on_fetch_progress(self, current: int, total: int, msg: str):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        self.setWindowTitle(f"Emby 演员管理器 - {msg}")

    def _on_fetch_finished(self, actors: list[ActorInfo]):
        self._actors = actors
        self._set_status("获取完成")
        self.log(f"获取完成，共 {len(actors)} 个演员")
        self._populate_table(actors)
        self._update_statistics(actors)
        self.btn_preview.setEnabled(len(actors) > 0)
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        try:
            future = executor.submit(get_gfriends_index())
        except Exception as e:
            self.log(f"🔶 Gfriends 索引加载失败: {e}")
            return
        future.add_done_callback(lambda fut: self._gfriends_result.emit(_future_result_or(fut, None)))

    def _on_gfriends_result(self, index):
        self._gfriends_index = index
        if index:
            self.log(f"✅ Gfriends 头像库加载完成，共 {len(index)} 个头像")

    def _on_prepare_preview(self):
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.cancel()
            self.log("⏹️ 用户取消")
            self.btn_preview.setText("根据设定获取数据")
            return
        mode_map = {
            "仅全部缺失头像+简介": "missing_all",
            "仅全部缺失头像": "missing_image",
            "仅全部缺失简介": "missing_info",
            "全部头像+简介（重新获取）": "force_all",
            "全部头像（重新获取）": "force_image",
            "全部简介（重新获取）": "force_info",
        }
        mode = mode_map.get(self.cmb_fetch_mode.currentText(), "missing_all")
        self._set_buttons_enabled(False)
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("停止获取")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("获取数据中...")
        self.log(f"📥 正在获取数据（模式: {self.cmb_fetch_mode.currentText()}）")
        self._preview_thread = PreparePreviewThread(self)
        self._preview_thread.actors = self._actors
        self._preview_thread.mode = mode
        self._preview_thread.gfriends_index = self._gfriends_index
        self._preview_thread.cache_dir = self.cache_dir
        self._preview_thread.image_sources = list(manager.config.actor_image_sources)

        self._preview_thread.local_avatar_dir = (
            manager.config.actor_photo_folder if hasattr(manager.config, "actor_photo_folder") else ""
        )
        self._preview_thread.progress.connect(self._on_fetch_progress)
        self._preview_thread.preview_done.connect(self._on_preview_finished)
        self._preview_thread.error.connect(self._on_thread_error)
        self._preview_thread.start()

    def _on_preview_finished(self, actors: list[ActorInfo]):
        self._actors = actors
        self._populate_table(actors)
        self._update_statistics(actors)
        to_sync = [a for a in actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        self.btn_sync.setEnabled(len(to_sync) > 0)
        self.btn_sync.setText(f"开始全部更新同步({len(to_sync)} 项)")
        self._set_status("数据准备完成")
        self.log(f"✅ 预览准备完成，{len(to_sync)} 项待同步")
        self.btn_preview.setText("根据设定获取数据")
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)

    def _on_sync(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        if not to_sync:
            QMessageBox.information(self, "提示", "没有需要同步的项")
            return
        reply = QMessageBox.question(
            self,
            "确认同步",
            f"将同步 {len(to_sync)} 个演员的信息/头像/背景图到 Emby，\n此操作不可撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_sync.setText("同步中...")
        self._set_status("同步中...")
        self.log(f"📛 开始同步 {len(to_sync)} 个演员...")
        self._failed_names.clear()
        self._sync_thread = SyncThread(self)
        self._sync_thread.actors = to_sync
        self._sync_thread.progress.connect(self._on_sync_progress)
        self._sync_thread.actor_done.connect(self._on_sync_actor_done)
        self._sync_thread.sync_done.connect(self._on_sync_finished)
        self._sync_thread.error.connect(self._on_thread_error)
        self._sync_thread.start()

    def _on_sync_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.setWindowTitle(f"Emby 演员管理器 - {msg}")

    def _on_sync_actor_done(self, actor_id: str, name: str, success: bool, msg: str):
        # 用 actor_id 匹配，避免同名演员（未去重时）按名字错位更新状态
        actor = next((a for a in self._actors if a.actor_id == actor_id), None)
        if success:
            if actor is not None:
                self._apply_sync_success(actor)
            self.log(f"✅ {name} 同步成功")
        else:
            # 失败的演员保留 need_update 标记，可在下次同步重试
            self._failed_names.add(name)
            self.log(f"❌ {name} 同步失败: {msg}")

    def _apply_sync_success(self, a: ActorInfo):
        if a.need_update_image:
            a.has_image = bool(a.new_image_path)
            a.need_update_image = False
        if a.need_update_info:
            a.has_overview = bool(a.new_overview and a.new_overview.strip())
            a.existing_overview = a.new_overview or a.existing_overview
            a.existing_taglines = list(a.new_taglines)
            a.existing_production_year = a.new_production_year
            a.existing_premiere_date = a.new_premiere_date
            a.existing_production_locations = list(a.new_production_locations)
            a.need_update_info = False
        if a.need_update_backdrop:
            a.has_backdrop = bool(a.new_backdrop_path)
            a.need_update_backdrop = False

    def _on_sync_finished(self, success: int, fail: int):
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        self.btn_sync.setText("开始全部更新同步")
        self._set_status("同步完成")
        self.log(f"同步完成！成功: {success}, 失败: {fail}")
        QMessageBox.information(self, "同步完成", f"✅ 成功: {success}\n❌ 失败: {fail}")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        # 同步完成后 3 秒自动重新获取演员列表，确保与 Emby 完全一致
        self.log("⏳ 3 秒后自动刷新演员列表...")
        QTimer.singleShot(3000, self._on_auto_refresh)

    def _on_auto_refresh(self):
        if not hasattr(self, "_connected") or not self._connected:
            return
        self._set_buttons_enabled(False)
        self.log("🔄 正在自动刷新演员列表...")
        self._refresh_thread = FetchActorsThread(self)
        self._refresh_thread.library_ids = getattr(self, "_current_library_ids", None)
        self._refresh_thread.progress.connect(self._on_fetch_progress)
        self._refresh_thread.fetch_done.connect(self._on_auto_refresh_finished)
        self._refresh_thread.error.connect(self._on_thread_error)
        self._refresh_thread.start()

    def _on_auto_refresh_finished(self, actors: list[ActorInfo]):
        if self._failed_names:
            failed_old = {a.name: a for a in self._actors if a.name in self._failed_names}
            if failed_old:
                merged = []
                for new in actors:
                    old = failed_old.get(new.name)
                    if old is None:
                        merged.append(new)
                        continue
                    # 失败演员保留待同步状态与本地新数据，仅用刷新结果更新服务器侧状态
                    old.has_image = new.has_image
                    old.has_overview = new.has_overview
                    old.has_backdrop = new.has_backdrop
                    old.existing_overview = new.existing_overview
                    old.movie_count = new.movie_count
                    old.movie_titles = new.movie_titles
                    merged.append(old)
                actors = merged
                self.log(f"🔁 已保留 {len(failed_old)} 个同步失败演员的待同步状态，可直接重试")
        self._actors = actors
        self._populate_table(actors)
        self._update_statistics(actors)
        self.btn_preview.setEnabled(len(actors) > 0)
        self._set_status("自动刷新完成")
        self.log(f"✅ 自动刷新完成，共 {len(actors)} 个演员")
        self._set_buttons_enabled(True)

    def _on_thread_error(self, msg: str):
        self.progress_bar.setVisible(False)
        # 线程已结束，恢复按钮文本与状态，避免"停止/同步中..."残留
        self.btn_preview.setText("根据设定获取数据")
        self.btn_sync.setText("开始全部更新同步")
        self._set_buttons_enabled(True)
        self.log(f"🔶 错误: {msg}")
        QMessageBox.critical(self, "错误", msg)

    def closeEvent(self, event):
        # 线程运行中关闭窗口会触发 "QThread: Destroyed while thread is still running" 崩溃，
        # 关闭前先取消并等待各后台线程结束。
        for attr in ("_fetch_thread", "_preview_thread", "_sync_thread"):
            thread = getattr(self, attr, None)
            if thread is not None and thread.isRunning():
                if hasattr(thread, "cancel"):
                    thread.cancel()
                thread.wait(5000)
        super().closeEvent(event)

    def _on_filter_changed(self):
        self._populate_table(self._actors)

    def _on_table_double_clicked(self, row: int, col: int):
        # 表格启用排序后视觉行序 != _get_filtered_actors() 索引，用演员名反查，避免打开错误演员
        item = self.table.item(row, 1)
        if item is None:
            return
        name = item.text()
        actor = next((a for a in self._actors if a.name == name), None)
        if actor is None:
            return
        dialog = ActorDetailDialog(actor, self, on_synced=self._on_detail_synced)
        dialog.exec()

    def _on_detail_synced(self, actor: ActorInfo):
        # 同步单个演员后刷新主窗口表格与统计
        self.log(f"✅ {actor.name} 同步完成，刷新列表")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        self._update_sync_button()

    def _get_filtered_actors(self) -> list[ActorInfo]:
        filter_mode = self.cmb_filter.currentText()
        search_text = self.txt_search.text().strip().lower()
        filtered = []
        for a in self._actors:
            if filter_mode == "缺头像" and a.has_image:
                continue
            elif filter_mode == "缺背景" and a.has_backdrop:
                continue
            elif filter_mode == "缺简介" and a.has_overview:
                continue
            elif filter_mode == "缺头像和简介" and a.has_image and a.has_overview:
                continue
            elif filter_mode == "完整" and not (a.has_image and a.has_overview):
                continue
            elif filter_mode == "待同步" and not (a.need_update_info or a.need_update_image or a.need_update_backdrop):
                continue
            if search_text and search_text not in a.name.lower():
                continue
            filtered.append(a)
        return filtered

    def _populate_table(self, actors: list[ActorInfo]):
        self.table.setSortingEnabled(False)
        filtered = self._get_filtered_actors() if actors else []
        self.table.setRowCount(len(filtered))
        for row, actor in enumerate(filtered):
            icon_item = QTableWidgetItem(actor.status_icon)
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, icon_item)
            name_item = QTableWidgetItem(actor.name)
            name_item.setToolTip(f"ID: {actor.actor_id}")
            self.table.setItem(row, 1, name_item)
            img_item = QTableWidgetItem("✅" if actor.has_image else "❌")
            img_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_image:
                img_item.setText("🔄")
            img_item.setToolTip(
                f"头像: {'有' if actor.has_image else '无'} | 背景图: {'有' if actor.has_backdrop else '无'}"
            )
            self.table.setItem(row, 2, img_item)
            info_item = QTableWidgetItem("✅" if actor.has_overview else "❌")
            info_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_info:
                info_item.setText("🔄")
            self.table.setItem(row, 3, info_item)
            overview_text = (
                actor.existing_overview[:80] + "..."
                if len(actor.existing_overview) > 80
                else (actor.existing_overview or "（无）")
            )
            self.table.setItem(row, 4, QTableWidgetItem(overview_text))
            tags = ", ".join(actor.existing_taglines[:2]) if actor.existing_taglines else ""
            self.table.setItem(row, 5, QTableWidgetItem(tags))
            mc_item = QTableWidgetItem(str(actor.movie_count) if actor.movie_count > 0 else "0")
            mc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.movie_titles:
                mc_item.setToolTip("\n".join(actor.movie_titles[:20]))
            self.table.setItem(row, 6, mc_item)
            if actor.need_update_info or actor.need_update_image:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor("#c8e6c9"))
        self.table.setSortingEnabled(True)
        self._update_sync_button()

    def _update_statistics(self, actors: list[ActorInfo]):
        total = len(actors)
        has_both = sum(1 for a in actors if a.has_image and a.has_overview)
        has_image_only = sum(1 for a in actors if a.has_image and not a.has_overview)
        has_info_only = sum(1 for a in actors if not a.has_image and a.has_overview)
        has_none = sum(1 for a in actors if not a.has_image and not a.has_overview)
        backdrop_count = sum(1 for a in actors if a.has_backdrop)
        self.lbl_total.setText(f"总数: {total}")
        self.lbl_has_both.setText(f"完整: {has_both}")
        self.lbl_missing_image.setText(f"缺头像: {has_info_only}")
        self.lbl_missing_info.setText(f"缺简介: {has_image_only}")
        self.lbl_missing_all.setText(f"全缺: {has_none}")
        self.lbl_backdrop.setText(f"有背景图: {backdrop_count}")

    def _update_sync_button(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        sync_count = len(to_sync)
        self.btn_sync.setEnabled(sync_count > 0)
        self.btn_sync.setText(f"开始全部更新同步({sync_count} 项)" if sync_count > 0 else "开始全部更新同步")


IMAGE_SOURCE_NAMES = {
    "gfriends": "Gfriends 头像库",
    "graphis": "graphis 头像/背景",
    "minnano": "minnano-av 头像",
    "local": "本地头像",
}
INFO_SOURCE_NAMES = {
    "local": "本地演员库",
    "wiki": "维基百科",
    "minnano": "minnano-av 信息",
    "database": "本地数据库",
}


class _SourceQuickSettingsPanel(QGroupBox):
    """快速设置面板：头像/信息数据源拖拽排序 + 本地头像目录，改动即自动保存。

    数据源测试窗口与演员详情窗口共用，避免两处重复实现。
    """

    def __init__(self, parent=None):
        super().__init__("快速设置", parent)
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("头像数据源（拖拽排序）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.image_list, manager.config.actor_image_sources, IMAGE_SOURCE_NAMES)
        layout.addWidget(self.image_list)
        layout.addWidget(QLabel("信息数据源（拖拽排序）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.info_list, manager.config.actor_info_sources, INFO_SOURCE_NAMES)
        layout.addWidget(self.info_list)
        layout.addWidget(QLabel("本地头像目录:"))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(manager.config.actor_photo_folder)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        img_model = self.image_list.model()
        if img_model:
            img_model.rowsMoved.connect(self._save)
        info_model = self.info_list.model()
        if info_model:
            info_model.rowsMoved.connect(self._save)
        self.folder_edit.textChanged.connect(self._save)

    @staticmethod
    def _fill_list(list_widget: QListWidget, sources: list[str], names: dict[str, str]):
        list_widget.clear()
        for src in sources:
            item = QListWidgetItem(f"{src}（{names.get(src, src)}）")
            item.setData(Qt.ItemDataRole.UserRole, src)
            list_widget.addItem(item)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择本地头像目录", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def _save(self, *args):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = [
            self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())
        ]
        cfg.actor_info_sources = [
            self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())
        ]
        cfg.actor_photo_folder = self.folder_edit.text().strip()
        manager._replace_config(cfg)
        manager.save()


class EmbyActorSettingsDialog(QDialog):
    """Emby 演员数据源设置：数据源优先级排序 + 本地目录 + Gfriends + 数据库开关。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Emby 演员设置")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        filter_group = QGroupBox("Emby 演员获取过滤")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_only_check = QCheckBox("只获取演员类型（不含导演/编剧/制片人）")
        self.filter_only_check.setChecked(manager.config.actor_filter_only)
        filter_layout.addWidget(self.filter_only_check)
        self.deduplicate_check = QCheckBox("重复演员去重（按名称合并）")
        self.deduplicate_check.setChecked(manager.config.actor_deduplicate)
        filter_layout.addWidget(self.deduplicate_check)
        layout.addWidget(filter_group)

        layout.addWidget(QLabel("头像数据源优先级（拖拽排序，上=优先）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_image_sources:
            item = QListWidgetItem(f"{src}（{IMAGE_SOURCE_NAMES.get(src, src)}）")
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.image_list.addItem(item)
        layout.addWidget(self.image_list)

        layout.addWidget(QLabel("信息数据源优先级（拖拽排序，上=优先）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_info_sources:
            item = QListWidgetItem(f"{src}（{INFO_SOURCE_NAMES.get(src, src)}）")
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.info_list.addItem(item)
        layout.addWidget(self.info_list)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("本地头像目录:"))
        self.photo_folder_edit = QLineEdit(manager.config.actor_photo_folder)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_photo_folder)
        dir_row.addWidget(self.photo_folder_edit)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        layout.addWidget(QLabel("Gfriends GitHub 地址:"))
        self.gfriends_edit = QLineEdit(str(manager.config.gfriends_github))
        layout.addWidget(self.gfriends_edit)

        self.use_db_check = QCheckBox("使用本地信息数据库")
        self.use_db_check.setChecked(manager.config.use_database)
        layout.addWidget(self.use_db_check)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _browse_photo_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择本地头像目录", self.photo_folder_edit.text())
        if path:
            self.photo_folder_edit.setText(path)

    def _save(self):
        image_sources = [self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())]
        info_sources = [self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())]
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = image_sources
        cfg.actor_info_sources = info_sources
        cfg.actor_filter_only = self.filter_only_check.isChecked()
        cfg.actor_deduplicate = self.deduplicate_check.isChecked()
        cfg.actor_photo_folder = self.photo_folder_edit.text().strip()
        cfg.use_database = self.use_db_check.isChecked()
        try:
            cfg.gfriends_github = self.gfriends_edit.text().strip()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"Gfriends 地址无效: {e}")
            return
        manager._replace_config(cfg)
        manager.save()
        self.accept()


class ActorSourceTestThread(QThread):
    """数据源测试线程：在后台执行网络请求，通过信号回传结果。"""

    result = Signal(list, object, object)  # logs, avatar_path, info_dict
    error = Signal(str)

    def __init__(self, parent, name: str, need_image: bool, need_info: bool):
        super().__init__(parent)
        self._name = name
        self._need_image = need_image
        self._need_info = need_info

    def run(self):
        try:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logs, avatar_path, info = loop.run_until_complete(
                    _actor_source_test_execute(self._name, self._need_image, self._need_info)
                )
                self.result.emit(logs, avatar_path, info)
            finally:
                loop.close()
        except Exception as e:
            self.error.emit(str(e))


async def _actor_source_test_execute(
    name: str, need_image: bool, need_info: bool
) -> tuple[list[str], str | None, object]:
    """纯数据版本：不操作 UI，返回 (logs, avatar_path, info)。"""

    logs: list[str] = []
    avatar_path: str | None = None
    info: object = None
    actor = ActorInfo(name=name, actor_id="", server_id="")

    if need_image:
        gfriends_index = None
        try:
            gfriends_index = await get_gfriends_index()
        except Exception:
            pass
        for src in manager.config.actor_image_sources:
            result: object = None
            try:
                if src == "gfriends" and gfriends_index:
                    result = await from_gfriends(actor, gfriends_index, resources.u("emby_actor_cache"))
                elif src == "graphis":
                    result = await from_graphis(actor, resources.u("emby_actor_cache"))
                elif src == "minnano":
                    result = await from_minnano_image(actor, resources.u("emby_actor_cache"))
                elif src == "local":
                    result = from_local_avatar(actor, manager.config.actor_photo_folder)
                else:
                    logs.append(f"头像[{src}]: 未知数据源")
                    continue
            except Exception as e:
                logs.append(f"头像[{src}]: 异常 {e}")
                continue
            if result:
                logs.append(f"头像[{src}]: ✅ 命中")
                if isinstance(result, (str, Path)) and Path(result).exists():
                    avatar_path = str(result)
                elif isinstance(result, tuple) and result and Path(result[0]).exists():
                    avatar_path = str(result[0])
            else:
                logs.append(f"头像[{src}]: 未命中")

    if need_info:
        for src in manager.config.actor_info_sources:
            try:
                ok, desc, data = await fetch_actor_info_from_source(actor, src)
            except Exception as e:
                logs.append(f"信息[{src}]: 异常 {e}")
                continue
            logs.append(f"信息[{src}]: {'✅' if ok else '❌'} {desc}")
            if ok and data:
                info = data
    return logs, avatar_path, info


class ActorSourceTestDialog(QDialog):
    """数据源测试窗口：按配置的数据源优先级逐源尝试获取头像/简介，展示各源结果。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据源测试")
        self.setMinimumSize(760, 560)
        root = QVBoxLayout(self)

        # 顶部：演员名输入 + 获取头像和简介
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("演员名:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入演员名（如：三上悠亚）")
        self.name_edit.returnPressed.connect(lambda: self._run(True, True))
        name_row.addWidget(self.name_edit)
        self.btn_both = QPushButton("获取头像和简介")
        self.btn_both.setObjectName("btnPrimary")
        name_row.addWidget(self.btn_both)
        root.addLayout(name_row)

        # 主体：左(头像) + 中(信息字段表) + 右(快速设置面板)
        main_row = QHBoxLayout()

        # 左列：头像预览 + 获取头像
        left_col = QVBoxLayout()
        self.avatar_label = QLabel("头像预览")
        self.avatar_label.setFixedSize(140, 190)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_col.addWidget(self.avatar_label)
        self.btn_image = QPushButton("获取头像")
        self.btn_image.setObjectName("btnPrimary")
        left_col.addWidget(self.btn_image)
        main_row.addLayout(left_col)

        # 中列：详细信息预览（字段/值）+ 获取信息
        info_col = QVBoxLayout()
        info_col.addWidget(QLabel("详细信息预览:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        info_col.addWidget(self.info_table)
        self.btn_info = QPushButton("获取信息")
        self.btn_info.setObjectName("btnPrimary")
        info_col.addWidget(self.btn_info)
        main_row.addLayout(info_col, stretch=1)

        # 右列：快速设置面板（改即自动保存）
        panel = _SourceQuickSettingsPanel(self)
        main_row.addWidget(panel)

        root.addLayout(main_row)

        # 底部：各数据源结果
        root.addWidget(QLabel("各数据源结果:"))
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(150)
        root.addWidget(self.result_text)

        self.btn_both.clicked.connect(lambda: self._run(True, True))
        self.btn_image.clicked.connect(lambda: self._run(True, False))
        self.btn_info.clicked.connect(lambda: self._run(False, True))

    def _run(self, need_image: bool, need_info: bool):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入演员名")
            return
        self._thread = ActorSourceTestThread(self, name, need_image, need_info)
        self._thread.result.connect(self._on_result)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_result(self, logs: list[str], avatar_path: str | None, info: object):
        self.result_text.clear()
        for log in logs:
            self.result_text.append(log)
        if avatar_path and Path(avatar_path).exists():
            self._show_avatar(avatar_path)
        if info:
            self._populate_info_table(info)

    def _on_error(self, msg: str):
        self.result_text.append(f"❌ 错误: {msg}")

    def _populate_info_table(self, info: object):
        from ..models.emby import EMbyActressInfo

        if not isinstance(info, EMbyActressInfo):
            return
        rows = [
            ("生日", info.birthday),
            ("年份", str(info.year) if info.year else ""),
            ("出生地", ", ".join(info.locations or [])),
            ("标签", ", ".join(info.taglines or [])),
            ("简介", info.overview or ""),
        ]
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            self.info_table.setItem(r, 1, QTableWidgetItem(str(value)))

    def _show_avatar(self, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            self.avatar_label.setPixmap(pix.scaled(self.avatar_label.size(), Qt.AspectRatioMode.KeepAspectRatio))


class ActorDetailDialog(QDialog):
    """演员详情编辑对话框：左栏现有数据，右栏新数据（可编辑），右侧快速设置面板。"""

    _detail_done = Signal(str, object)

    def __init__(self, actor: ActorInfo, parent=None, on_synced=None):
        super().__init__(parent)
        self.actor = actor
        self.on_synced = on_synced
        self.setWindowTitle(f"演员详情 - {actor.name}")
        self.setMinimumSize(900, 580)
        root = QHBoxLayout(self)

        # 左栏：现有数据（Emby 当前）
        left = QGroupBox("现有数据")
        left_layout = QVBoxLayout(left)
        self.existing_avatar_label = QLabel("头像预览")
        self.existing_avatar_label.setFixedSize(130, 180)
        self.existing_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.existing_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_layout.addWidget(self.existing_avatar_label)
        self.existing_info = QTextEdit()
        self.existing_info.setReadOnly(True)
        self.existing_info.setPlainText(
            "简介: "
            + (actor.existing_overview or "无")
            + "\n生日: "
            + (actor.existing_premiere_date[:10] if actor.existing_premiere_date else "无")
            + "\n出生地: "
            + (", ".join(actor.existing_production_locations) if actor.existing_production_locations else "无")
            + "\n标签: "
            + (", ".join(actor.existing_taglines) if actor.existing_taglines else "无")
        )
        left_layout.addWidget(self.existing_info)
        root.addWidget(left)

        # 右栏：新数据（可编辑）
        right = QGroupBox("新数据（同步前可编辑）")
        right_layout = QVBoxLayout(right)
        self.new_avatar_label = QLabel("新头像预览")
        self.new_avatar_label.setFixedSize(130, 180)
        self.new_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.new_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        right_layout.addWidget(self.new_avatar_label)
        right_layout.addWidget(QLabel("简介（可编辑）:"))
        self.overview_edit = QTextEdit()
        self.overview_edit.setPlainText(actor.new_overview)
        right_layout.addWidget(self.overview_edit)
        right_layout.addWidget(QLabel("信息（右键增删行，可编辑）:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_table.customContextMenuRequested.connect(self._info_table_menu)
        self._populate_info_table()
        right_layout.addWidget(self.info_table)

        btn_row = QHBoxLayout()
        self.btn_fetch_image = QPushButton("获取头像")
        self.btn_fetch_info = QPushButton("获取信息")
        self.btn_sync_both = QPushButton("同步头像+简介")
        self.btn_sync_image = QPushButton("只同步头像")
        self.btn_sync_info = QPushButton("只同步简介")
        for b in (
            self.btn_fetch_image,
            self.btn_fetch_info,
            self.btn_sync_both,
            self.btn_sync_image,
            self.btn_sync_info,
        ):
            b.setObjectName("btnPrimary")
            btn_row.addWidget(b)
        right_layout.addLayout(btn_row)
        root.addWidget(right, stretch=1)

        # 右侧快速设置面板（改即保存）
        panel = _SourceQuickSettingsPanel(self)
        root.addWidget(panel)

        self.btn_fetch_image.clicked.connect(lambda: self._run_fetch_image())
        self.btn_fetch_info.clicked.connect(lambda: self._run_fetch_info())
        self.btn_sync_both.clicked.connect(lambda: self._run_sync("both"))
        self.btn_sync_image.clicked.connect(lambda: self._run_sync("image"))
        self.btn_sync_info.clicked.connect(lambda: self._run_sync("info"))

        self._detail_done.connect(self._on_detail_done)
        self._load_existing_avatar()
        if actor.new_image_path:
            self._show_new_avatar(actor.new_image_path)

    def _populate_info_table(self):
        actor = self.actor
        provider_ids = ", ".join(f"{k}:{v}" for k, v in actor.new_provider_ids.items())
        rows = [
            ("标签", ", ".join(actor.new_taglines)),
            ("年份", str(actor.new_production_year) if actor.new_production_year else ""),
            ("生日", actor.new_premiere_date),
            ("出生地", ", ".join(actor.new_production_locations)),
            ("外部ID", provider_ids),
        ]
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            self.info_table.setItem(r, 1, QTableWidgetItem(value))

    def _info_table_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        add_action = menu.addAction("增加行")
        del_action = menu.addAction("删除行")
        chosen = menu.exec(self.info_table.viewport().mapToGlobal(pos))
        if chosen == add_action:
            row = self.info_table.rowCount()
            self.info_table.insertRow(row)
            self.info_table.setItem(row, 0, QTableWidgetItem(""))
            self.info_table.setItem(row, 1, QTableWidgetItem(""))
        elif chosen == del_action:
            self.info_table.removeRow(self.info_table.currentRow())

    def _load_existing_avatar(self):
        if not self.actor.has_image:
            self.existing_avatar_label.setText("无头像")
            return
        self.existing_avatar_label.setText("加载中...")
        try:
            future = executor.submit(self._download_existing_avatar())
        except Exception as e:
            self.existing_avatar_label.setText("头像加载失败")
            self.log(f"🔶 加载现有头像失败: {e}")
            return
        future.add_done_callback(lambda fut: self._detail_done.emit("existing_avatar", _future_result_or(fut, None)))

    async def _download_existing_avatar(self) -> str | None:
        from .emby_shared import _build_jellyfin_headers, _generate_server_url

        _, _, pic_url, _, _, _ = _generate_server_url(
            {"Name": self.actor.name, "Id": self.actor.actor_id, "ServerId": self.actor.server_id}
        )
        headers = _build_jellyfin_headers()
        async with manager.acquire_computed() as computed:
            body, err = await computed.async_client.get_content(pic_url, headers=headers, use_proxy=False)
        if not body:
            return None
        tmp = resources.u("emby_actor_cache") / f"emby_existing_{self.actor.actor_id}.jpg"
        tmp.write_bytes(body)
        return str(tmp)

    def _run_fetch_image(self):
        try:
            future = executor.submit(self._fetch_image())
        except Exception as e:
            self.log(f"🔶 获取头像失败: {e}")
            return
        future.add_done_callback(
            lambda fut: self._detail_done.emit("fetch_image", _future_result_or(fut, (False, None)))
        )

    async def _fetch_image(self) -> tuple[bool, str | None]:
        from .emby_actor_manager import from_gfriends, from_graphis, from_local_avatar, from_minnano_image

        gfriends_index = None
        try:
            gfriends_index = await get_gfriends_index()
        except Exception:
            pass
        for src in manager.config.actor_image_sources:
            result: object = None
            try:
                if src == "gfriends" and gfriends_index:
                    result = await from_gfriends(self.actor, gfriends_index, resources.u("emby_actor_cache"))
                elif src == "graphis":
                    result = await from_graphis(self.actor, resources.u("emby_actor_cache"))
                elif src == "minnano":
                    result = await from_minnano_image(self.actor, resources.u("emby_actor_cache"))
                elif src == "local":
                    result = from_local_avatar(self.actor, manager.config.actor_photo_folder)
            except Exception:
                continue
            if result:
                path = result[0] if isinstance(result, tuple) and result else result
                if isinstance(path, (str, Path)) and Path(path).exists():
                    self.actor.new_image_path = str(path)
                    self.actor.need_update_image = True
                    return True, str(path)
        return False, None

    def _run_fetch_info(self):
        try:
            future = executor.submit(search_actor_info(self.actor))
        except Exception as e:
            self.log(f"🔶 获取简介失败: {e}")
            return
        future.add_done_callback(lambda fut: self._detail_done.emit("fetch_info", _future_result_or(fut, False)))

    def _on_detail_done(self, action: str, result: object):
        if action == "existing_avatar":
            if result:
                self._show_pixmap(self.existing_avatar_label, str(result))
            else:
                self.existing_avatar_label.setText("无头像")
        elif action == "fetch_image":
            ok, path = result if isinstance(result, tuple) and len(result) == 2 else (False, None)
            if ok and path:
                self._show_new_avatar(path)
            else:
                self.new_avatar_label.setText("未获取到新头像")
        elif action == "fetch_info":
            if result:
                self.overview_edit.setPlainText(self.actor.new_overview)
                self._populate_info_table()
        elif action == "sync":
            ok, msg = result if isinstance(result, tuple) and len(result) == 2 else (False, str(result))
            self.btn_sync_both.setEnabled(True)
            self.btn_sync_image.setEnabled(True)
            self.btn_sync_info.setEnabled(True)
            QMessageBox.information(self, "同步结果", msg)
            if ok and self.on_synced:
                self.on_synced(self.actor)

    def _run_sync(self, sync_type: str):
        from .emby_actor_manager import sync_actor

        self._apply_edits()
        self.btn_sync_both.setEnabled(False)
        self.btn_sync_image.setEnabled(False)
        self.btn_sync_info.setEnabled(False)

        def _worker():
            try:
                result = sync_actor(self.actor, sync_type)
            except Exception:
                import traceback

                result = (False, f"同步异常: {traceback.format_exc()}")
            self._detail_done.emit("sync", result)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_edits(self):
        actor = self.actor
        actor.new_overview = self.overview_edit.toPlainText().strip()
        actor.new_taglines = []
        actor.new_production_locations = []
        actor.new_production_year = None
        actor.new_premiere_date = ""
        for r in range(self.info_table.rowCount()):
            field_item = self.info_table.item(r, 0)
            value_item = self.info_table.item(r, 1)
            if not field_item or not value_item:
                continue
            field = field_item.text().strip()
            value = value_item.text().strip()
            if field == "标签":
                actor.new_taglines = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "年份":
                actor.new_production_year = int(value) if value.isdigit() else None
            elif field == "生日":
                actor.new_premiere_date = value
            elif field == "出生地":
                actor.new_production_locations = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "外部ID":
                provider_ids: dict[str, str] = {}
                for part in value.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if ":" in part:
                        k, v = part.split(":", 1)
                        provider_ids[k.strip()] = v.strip()
                actor.new_provider_ids = provider_ids
        if (
            actor.new_overview
            or actor.new_taglines
            or actor.new_production_year
            or actor.new_premiere_date
            or actor.new_provider_ids
        ):
            actor.need_update_info = True

    def _show_new_avatar(self, path: str):
        self._show_pixmap(self.new_avatar_label, path)

    @staticmethod
    def _show_pixmap(label: QLabel, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            label.setPixmap(pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio))
