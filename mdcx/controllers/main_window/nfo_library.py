"""NFO 库管理页面的工具处理函数。

借鉴 NFO.Editor 的目录浏览 + 批量编辑理念，在 mdcx 内做成独立导航页。
复用 core/nfo.py 的 get_nfo_data / write_nfo 读写能力，不重复造轮子。
"""

from __future__ import annotations

import copy
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from mdcx.core.nfo import get_nfo_data, write_nfo
from mdcx.models.model_types import CrawlersResult, FileInfo
from mdcx.signals import signal_qt
from mdcx.utils import executor, get_current_time
from mdcx.utils.file import delete_file_sync, open_file_thread

if TYPE_CHECKING:
    from .main_window import MyMAinWindow

# NFO 列表项中存储的 data role
NFO_PATH_ROLE = Qt.ItemDataRole.UserRole + 1

# diff 对比的字段：(属性名, 显示名, 是否列表类型)
_DIFF_FIELDS: list[tuple[str, str, bool]] = [
    ("number", "番号", False),
    ("title", "标题", False),
    ("actor", "演员", False),
    ("release", "发行日", False),
    ("year", "年份", False),
    ("runtime", "时长", False),
    ("directors", "导演", True),
    ("studio", "制作商", False),
    ("publisher", "发行商", False),
    ("series", "系列", False),
    ("score", "评分", False),
    ("outline", "简介", False),
    ("tags", "标签", True),
    ("thumb", "封面URL", False),
    ("poster", "海报URL", False),
]


def _make_file_info(nfo_path: Path) -> FileInfo:
    """根据 NFO 路径构造最小可用 FileInfo（write_nfo 需要 file_path 和 cd_part）。"""
    video_path = nfo_path.with_suffix("")
    # 尝试找到同目录下同名的视频文件
    for ext in (".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".ts", ".rmvb", ".iso"):
        candidate = nfo_path.with_suffix(ext)
        if candidate.is_file():
            video_path = candidate
            break
    else:
        video_path = nfo_path.with_suffix(".mp4")

    return FileInfo(
        number="",
        mosaic="",
        appoint_number="",
        appoint_url="",
        c_word="",
        cd_part="",
        destroyed="",
        file_ex=video_path.suffix,
        file_name=video_path.stem,
        file_path=video_path,
        file_show_name=video_path.stem,
        file_show_path=video_path,
        folder_path=nfo_path.parent,
        has_sub=False,
        leak="",
        letters="",
        short_number="",
        sub_list=[],
        website_name="",
        wuma="",
        youma="",
        definition="",
        codec="",
    )


def pushButton_nfo_library_clicked(self: MyMAinWindow) -> None:
    """左侧导航：切换到 NFO 库管理页面。"""
    self.Ui.left_backgroud_widget.setStyleSheet(
        f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;"
        f"border-bottom-left-radius: {self.window_radius}px;"
    )
    self.Ui.stackedWidget.setCurrentIndex(6)
    self.set_left_button_style()
    self.Ui.pushButton_nfo_library.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
    if self.Ui.listWidget_nfo_lib.count() == 0:
        _add_empty_hint(self, "请先选择上方目录加载 NFO")


def pushButton_nfo_lib_select_dir_clicked(self: MyMAinWindow) -> None:
    """选择目录并扫描 NFO 文件。"""
    folder = self._get_select_folder_path(None)
    if not folder:
        return
    self.Ui.lineEdit_nfo_lib_dir.setText(folder)
    _scan_nfo_directory(self, Path(folder))


def pushButton_nfo_lib_select_all_clicked(self: MyMAinWindow) -> None:
    """全选 NFO 列表（议题 #61：列表右侧缺全选快捷键）。

    只选可见项（筛选后剩下行），避免误把筛选时隐藏的条目批量提交。"""
    self.Ui.listWidget_nfo_lib.selectAll()


def pushButton_nfo_lib_select_none_clicked(self: MyMAinWindow) -> None:
    """清空 NFO 列表选择。"""
    self.Ui.listWidget_nfo_lib.clearSelection()


def pushButton_nfo_lib_refresh_clicked(self: MyMAinWindow) -> None:
    """刷新当前目录的 NFO 列表。"""
    dir_text = self.Ui.lineEdit_nfo_lib_dir.text().strip()
    if not dir_text:
        signal_qt.show_log_text("请先选择目录")
        return
    _scan_nfo_directory(self, Path(dir_text))


def _scan_nfo_directory(self: MyMAinWindow, folder: Path) -> None:
    """扫描目录下所有 .nfo 文件并填充列表。"""
    self.Ui.listWidget_nfo_lib.clear()
    if not folder.is_dir():
        signal_qt.show_log_text(f"目录不存在: {folder}")
        return

    nfo_files = sorted(folder.rglob("*.nfo"), key=lambda p: p.name.lower())
    count = 0
    for nfo_path in nfo_files:
        item = QListWidgetItem(nfo_path.stem)
        item.setData(NFO_PATH_ROLE, str(nfo_path))
        item.setToolTip(str(nfo_path))
        self.Ui.listWidget_nfo_lib.addItem(item)
        count += 1

    self.Ui.label_nfo_lib_count.setText(f"共 {count} 个")
    if count == 0:
        _add_empty_hint(self, "该目录下未找到 NFO 文件")
    else:
        signal_qt.show_log_text(f"NFO 库管理: 扫描到 {count} 个 NFO 文件")


def _add_empty_hint(self: MyMAinWindow, text: str) -> None:
    """列表为空时添加一行不可选的占位提示。"""
    item = QListWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
    item.setData(NFO_PATH_ROLE, "")
    self.Ui.listWidget_nfo_lib.addItem(item)


def listWidget_nfo_lib_item_clicked(self: MyMAinWindow) -> None:
    """列表项选中：读取 NFO 并填充表单。"""
    items = self.Ui.listWidget_nfo_lib.selectedItems()
    if not items:
        return
    nfo_path = Path(items[0].data(NFO_PATH_ROLE))
    if not nfo_path.is_file():
        signal_qt.show_log_text(f"NFO 文件不存在: {nfo_path}")
        return

    self._nfo_lib_current_path = nfo_path

    async def _load():
        try:
            data, info = await get_nfo_data(nfo_path.with_suffix(""), nfo_path.stem)
            if data is None:
                signal_qt.show_log_text(f"读取失败: {nfo_path.name}")
                return
            # 在主线程更新 UI（get_nfo_data 在后台线程，需要通过信号回传）
            self._nfo_lib_pending_data = data
            self._nfo_lib_pending_info = info
            self.nfo_lib_data_loaded.emit(str(nfo_path))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    executor.submit(_load())


def on_nfo_lib_data_loaded(self: MyMAinWindow, nfo_path_str: str) -> None:
    """后台读取 NFO 完成后，在主线程填充表单（线程安全）。"""
    data: CrawlersResult | None = getattr(self, "_nfo_lib_pending_data", None)
    info = getattr(self, "_nfo_lib_pending_info", None)
    if data is None:
        return

    self.Ui.lineEdit_nfo_lib_number.setText(data.number or "")
    self.Ui.lineEdit_nfo_lib_title.setText(data.title or "")
    self.Ui.lineEdit_nfo_lib_actor.setText(data.actor or "")
    self.Ui.lineEdit_nfo_lib_release.setText(data.release or "")
    self.Ui.lineEdit_nfo_lib_year.setText(data.year or "")
    self.Ui.lineEdit_nfo_lib_runtime.setText(data.runtime or "")
    self.Ui.lineEdit_nfo_lib_director.setText(",".join(data.directors) if data.directors else "")
    self.Ui.lineEdit_nfo_lib_studio.setText(data.studio or "")
    self.Ui.lineEdit_nfo_lib_publisher.setText(data.publisher or "")
    self.Ui.lineEdit_nfo_lib_series.setText(data.series or "")
    self.Ui.lineEdit_nfo_lib_score.setText(data.score or "")
    self.Ui.plainTextEdit_nfo_lib_outline.setPlainText(data.outline or "")
    self.Ui.plainTextEdit_nfo_lib_tag.setPlainText(data.tag or "")
    self.Ui.lineEdit_nfo_lib_cover_url.setText(data.thumb or "")
    self.Ui.lineEdit_nfo_lib_poster_url.setText(data.poster or "")

    # 加载本地封面预览
    poster_path = info.poster_path if info else None
    thumb_path = info.thumb_path if info else None
    if poster_path and poster_path.is_file():
        pix = QPixmap(str(poster_path))
        if not pix.isNull():
            self.Ui.label_nfo_lib_poster_preview.setPixmap(
                pix.scaled(200, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
    else:
        self.Ui.label_nfo_lib_poster_preview.setText("无海报")
    if thumb_path and thumb_path.is_file():
        pix = QPixmap(str(thumb_path))
        if not pix.isNull():
            self.Ui.label_nfo_lib_thumb_preview.setPixmap(
                pix.scaled(200, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
    else:
        self.Ui.label_nfo_lib_thumb_preview.setText("无缩略图")

    # 保留原始数据副本作为保存前 diff 的基准
    self._nfo_lib_original_data = copy.deepcopy(data)

    # 清理临时状态
    self._nfo_lib_pending_data = None
    self._nfo_lib_pending_info = None


def _collect_form_data(self: MyMAinWindow) -> CrawlersResult:
    """从表单控件收集数据构造 CrawlersResult。
    补充表单没有但每次保存会丢失的字段（originalplot, external_ids 等），从原数据中继承。"""
    data = CrawlersResult.empty()
    data.number = self.Ui.lineEdit_nfo_lib_number.text().strip()
    data.title = self.Ui.lineEdit_nfo_lib_title.text().strip()
    data.actor = self.Ui.lineEdit_nfo_lib_actor.text().strip()
    data.all_actor = data.actor
    data.release = self.Ui.lineEdit_nfo_lib_release.text().strip()
    data.year = self.Ui.lineEdit_nfo_lib_year.text().strip()
    data.runtime = self.Ui.lineEdit_nfo_lib_runtime.text().strip()
    director_text = self.Ui.lineEdit_nfo_lib_director.text().strip()
    data.directors = [d.strip() for d in director_text.split(",") if d.strip()] if director_text else []
    data.studio = self.Ui.lineEdit_nfo_lib_studio.text().strip()
    data.publisher = self.Ui.lineEdit_nfo_lib_publisher.text().strip()
    data.series = self.Ui.lineEdit_nfo_lib_series.text().strip()
    data.score = self.Ui.lineEdit_nfo_lib_score.text().strip()
    data.outline = self.Ui.plainTextEdit_nfo_lib_outline.toPlainText().strip()
    tag_text = self.Ui.plainTextEdit_nfo_lib_tag.toPlainText().strip()
    data.tag = tag_text
    data.tags = [t.strip() for t in tag_text.replace("，", ",").split(",") if t.strip()] if tag_text else []
    data.thumb = self.Ui.lineEdit_nfo_lib_cover_url.text().strip()
    data.poster = self.Ui.lineEdit_nfo_lib_poster_url.text().strip()

    # 表单没有但 write_nfo 会读取的字段：从原数据继承，避免保存后丢失
    original: CrawlersResult | None = getattr(self, "_nfo_lib_original_data", None)
    if original is not None:
        data.originalplot = original.originalplot
        data.external_ids = original.external_ids.copy() if original.external_ids else {}
        data.wanted = original.wanted
        data.letters = original.letters
        data.mosaic = original.mosaic
        data.outline_from = original.outline_from
        data.original_actors = original.original_actors
        data.actor_tmdb_ids = original.actor_tmdb_ids.copy() if original.actor_tmdb_ids else {}

    return data


def _build_field_diff(original: CrawlersResult, new_data: CrawlersResult) -> str:
    """对比原始数据和新数据，返回字段级 diff 文本（无差异返回空串）。"""
    lines: list[str] = []
    for attr, label, is_list in _DIFF_FIELDS:
        old_val = getattr(original, attr, "")
        new_val = getattr(new_data, attr, "")
        if is_list:
            old_val = ", ".join(old_val) if old_val else ""
            new_val = ", ".join(new_val) if new_val else ""
        old_str = str(old_val or "")
        new_str = str(new_val or "")
        if old_str != new_str:
            lines.append(f"【{label}】\n  旧: {old_str[:200]}\n  新: {new_str[:200]}")
    return "\n\n".join(lines)


def _show_diff_dialog(self: MyMAinWindow, diff_text: str) -> bool:
    """弹窗显示字段级改动，返回用户是否确认保存。"""
    dialog = QDialog(self)
    dialog.setWindowTitle("确认保存 — 检测到以下改动")
    dialog.setMinimumSize(520, 400)
    layout = QVBoxLayout(dialog)
    text_edit = QPlainTextEdit(diff_text)
    text_edit.setReadOnly(True)
    layout.addWidget(text_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
    cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if save_btn:
        save_btn.setText("保存")
    if cancel_btn:
        cancel_btn.setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QDialog.DialogCode.Accepted


def pushButton_nfo_lib_save_clicked(self: MyMAinWindow) -> None:
    """保存当前编辑的 NFO（保存前弹窗显示字段级 diff）。"""
    nfo_path: Path | None = getattr(self, "_nfo_lib_current_path", None)
    if not nfo_path or not nfo_path.is_file():
        QMessageBox.warning(self, "提示", "请先从列表选择一个 NFO 文件")
        return

    # 从表单收集数据
    data = _collect_form_data(self)

    # 字段级 diff 预览：与加载时的原始数据对比
    original: CrawlersResult | None = getattr(self, "_nfo_lib_original_data", None)
    if original is not None:
        diff_text = _build_field_diff(original, data)
        if not diff_text:
            QMessageBox.information(self, "提示", "没有检测到任何改动")
            return
        if not _show_diff_dialog(self, diff_text):
            return

    button = self.Ui.pushButton_nfo_lib_save
    button.setEnabled(False)
    button.setText("保存中...")

    file_info = _make_file_info(nfo_path)
    nfo_folder = nfo_path.parent

    async def _save():
        try:
            success = await write_nfo(
                file_info, data, nfo_path, nfo_folder, update=True, skip_merge=True, preserve_tag_order=True
            )
            self._nfo_lib_save_result = success
            self.nfo_lib_save_done.emit(str(nfo_path))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self._nfo_lib_save_result = False
            self.nfo_lib_save_done.emit(str(nfo_path))

    executor.submit(_save())


def on_nfo_lib_save_done(self: MyMAinWindow, nfo_path_str: str) -> None:
    """保存完成后恢复按钮状态（线程安全）。"""
    button = self.Ui.pushButton_nfo_lib_save
    success = getattr(self, "_nfo_lib_save_result", False)
    if success:
        button.setText("已保存!")
        signal_qt.show_log_text(f"NFO 已保存: {nfo_path_str}")
    else:
        button.setText("保存失败!")
        signal_qt.show_log_text(f"NFO 保存失败: {nfo_path_str}")

    # 1.5 秒后恢复按钮
    from PyQt6.QtCore import QTimer

    def _restore():
        button.setEnabled(True)
        button.setText("保存当前 NFO")

    QTimer.singleShot(1500, _restore)


def lineEdit_nfo_lib_filter_changed(self: MyMAinWindow) -> None:
    """筛选框文本变化时过滤列表。"""
    keyword = self.Ui.lineEdit_nfo_lib_filter.text().strip().lower()
    for i in range(self.Ui.listWidget_nfo_lib.count()):
        item = self.Ui.listWidget_nfo_lib.item(i)
        item.setHidden(bool(keyword) and keyword not in item.text().lower())


def pushButton_nfo_lib_crop_clicked(self: MyMAinWindow) -> None:
    """裁剪封面：打开裁剪窗口。"""
    nfo_path: Path | None = getattr(self, "_nfo_lib_current_path", None)
    if not nfo_path:
        QMessageBox.warning(self, "提示", "请先选择一个 NFO 文件")
        return

    # 尝试找到同目录的封面图
    poster_path = nfo_path.with_name(nfo_path.stem + "-poster.jpg")
    if not poster_path.is_file():
        poster_path = nfo_path.parent / "poster.jpg"
    if not poster_path.is_file():
        # 尝试 thumb
        thumb_path = nfo_path.with_name(nfo_path.stem + "-thumb.jpg")
        if thumb_path.is_file():
            poster_path = thumb_path
        else:
            poster_path = nfo_path.parent / "thumb.jpg"

    if not poster_path.is_file():
        QMessageBox.warning(self, "提示", "未找到可裁剪的封面图文件")
        return

    self.cutwindow.showimage(str(poster_path), None)
    self.cutwindow.show()


def _get_selected_nfo_paths(self: MyMAinWindow) -> list[Path]:
    """获取列表中所有选中的 NFO 路径。"""
    return [Path(item.data(NFO_PATH_ROLE)) for item in self.Ui.listWidget_nfo_lib.selectedItems()]


def _parse_tags(text: str) -> list[str]:
    """解析逗号分隔的标签文本（中英文逗号都支持）。"""
    return [t.strip() for t in text.replace("，", ",").split(",") if t.strip()]


async def _batch_modify(
    self: MyMAinWindow,
    nfo_paths: list[Path],
    modify_fn,
) -> tuple[int, int]:
    """批量读取-修改-写回 NFO 文件。

    Args:
        nfo_paths: NFO 文件路径列表
        modify_fn: 接受 CrawlersResult，原地修改后返回的回调

    Returns:
        (成功数, 失败数)
    """
    success = 0
    failed = 0
    total = len(nfo_paths)
    for i, nfo_path in enumerate(nfo_paths, 1):
        try:
            # 线程安全：进度走信号，由主线程槽更新标签
            self.nfo_lib_batch_progress.emit(f"处理中 {i}/{total}: {nfo_path.stem}")
            data, _info = await get_nfo_data(nfo_path.with_suffix(""), nfo_path.stem)
            if data is None:
                failed += 1
                signal_qt.show_log_text(f"  🔴 读取失败: {nfo_path.name}")
                continue
            modify_fn(data)
            file_info = _make_file_info(nfo_path)
            await write_nfo(
                file_info, data, nfo_path, nfo_path.parent, update=True, skip_merge=True, preserve_tag_order=True
            )
            success += 1
        except Exception:
            failed += 1
            signal_qt.show_log_text(f"  🔴 {nfo_path.name}: {traceback.format_exc()[-200:]}")
    return success, failed


def pushButton_nfo_lib_batch_actor_clicked(self: MyMAinWindow) -> None:
    """批量替换演员名。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_actor = self.Ui.lineEdit_nfo_lib_batch_actor.text().strip()
    if not new_actor:
        QMessageBox.warning(self, "提示", "请输入新演员名")
        return

    def set_actor(data: CrawlersResult):
        data.actor = new_actor
        data.all_actor = new_actor

    _run_batch(self, paths, set_actor)


def pushButton_nfo_lib_batch_add_tag_clicked(self: MyMAinWindow) -> None:
    """批量加标签。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_tags = _parse_tags(self.Ui.lineEdit_nfo_lib_batch_add_tag.text())
    if not new_tags:
        QMessageBox.warning(self, "提示", "请输入要添加的标签")
        return

    def add_tags(data: CrawlersResult):
        existing = set(data.tags) if data.tags else set()
        existing.update(new_tags)
        data.tags = list(existing)
        data.tag = ",".join(existing)

    _run_batch(self, paths, add_tags)


def pushButton_nfo_lib_batch_del_tag_clicked(self: MyMAinWindow) -> None:
    """批量删标签。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    del_tags = set(_parse_tags(self.Ui.lineEdit_nfo_lib_batch_del_tag.text()))
    if not del_tags:
        QMessageBox.warning(self, "提示", "请输入要删除的标签")
        return

    def remove_tags(data: CrawlersResult):
        remaining = [t for t in (data.tags or []) if t not in del_tags]
        data.tags = remaining
        data.tag = ",".join(remaining)

    _run_batch(self, paths, remove_tags)


def pushButton_nfo_lib_batch_series_clicked(self: MyMAinWindow) -> None:
    """批量统一系列名。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_series = self.Ui.lineEdit_nfo_lib_batch_series.text().strip()
    if not new_series:
        QMessageBox.warning(self, "提示", "请输入系列名")
        return

    def set_series(data: CrawlersResult):
        data.series = new_series

    _run_batch(self, paths, set_series)


def pushButton_nfo_lib_batch_save_clicked(self: MyMAinWindow) -> None:
    """批量保存：将当前列表中所有被修改过的 NFO 重新写盘。

    由于批量修改（替换演员/加删标签/统一系列）已经即时写盘，
    本按钮作为"刷新所有选中项"的入口，重新读取并写回当前选中 NFO。
    """
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    _run_batch(self, paths, lambda data: None)


def _run_batch(self: MyMAinWindow, paths: list[Path], modify_fn) -> None:
    """启动后台批量任务。"""
    total = len(paths)
    self.Ui.label_nfo_lib_batch_status.setText(f"开始批量处理 {total} 个文件...")
    signal_qt.show_log_text(f"NFO 库管理: 批量处理 {total} 个文件")

    async def _run():
        try:
            success, failed = await _batch_modify(self, paths, modify_fn)
            self._nfo_lib_batch_result = (success, failed, total)
            self.nfo_lib_batch_done.emit("")
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self._nfo_lib_batch_result = (0, total, total)
            self.nfo_lib_batch_done.emit("")

    executor.submit(_run())


def on_nfo_lib_batch_progress(self: MyMAinWindow, text: str) -> None:
    """批量进度信号槽（主线程）：更新状态标签。"""
    self.Ui.label_nfo_lib_batch_status.setText(text)


def on_nfo_lib_batch_done(self: MyMAinWindow, _arg: str) -> None:
    """批量任务完成后在主线程更新状态（线程安全）。"""
    result = getattr(self, "_nfo_lib_batch_result", (0, 0, 0))
    success, failed, total = result
    self.Ui.label_nfo_lib_batch_status.setText(f"完成: 成功 {success} / 失败 {failed} / 共 {total}")
    signal_qt.show_log_text(f"NFO 库管理: 批量完成 — 成功 {success}，失败 {failed}，共 {total}")


# ============= 右键菜单 =============


def listWidget_nfo_lib_context_menu(self: MyMAinWindow, pos) -> None:
    """NFO 列表右键菜单：重新刮削 / 打开所在目录 / 删除 NFO。"""
    items = self.Ui.listWidget_nfo_lib.selectedItems()
    if not items:
        return
    nfo_paths = [Path(item.data(NFO_PATH_ROLE)) for item in items]

    menu = QMenu(self)
    if len(nfo_paths) == 1:
        title_action = QAction(f"{nfo_paths[0].stem}", self)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
    else:
        count_action = QAction(f"已选择 {len(nfo_paths)} 项", self)
        count_action.setEnabled(False)
        menu.addAction(count_action)
        menu.addSeparator()

    act_rescrape = QAction("重新刮削", self)
    act_open_folder = QAction("打开所在目录", self)
    act_delete = QAction("删除 NFO" + (f"（{len(nfo_paths)} 个）" if len(nfo_paths) > 1 else ""), self)
    menu.addAction(act_rescrape)
    menu.addAction(act_open_folder)
    menu.addSeparator()
    menu.addAction(act_delete)

    chosen = menu.exec(self.Ui.listWidget_nfo_lib.viewport().mapToGlobal(pos))
    if chosen == act_rescrape:
        _nfo_lib_rescrape(self, nfo_paths)
    elif chosen == act_open_folder:
        open_file_thread(nfo_paths[0], True)
    elif chosen == act_delete:
        _nfo_lib_delete_nfo(self, nfo_paths)


def _nfo_lib_rescrape(self: MyMAinWindow, nfo_paths: list[Path]) -> None:
    """重新刮削：把选中 NFO 对应的视频加入重新刮削队列。"""
    from mdcx.core.scraper import again_search
    from mdcx.models.flags import Flags

    added = 0
    for nfo_path in nfo_paths:
        # 找到对应的视频文件
        file_info = _make_file_info(nfo_path)
        video_path = file_info.file_path
        if not video_path.is_file():
            signal_qt.show_log_text(f" 🟡 未找到对应视频文件，跳过: {nfo_path.name}")
            continue
        # 番号默认用 NFO 文件名，可弹窗修改（单个时）
        number = nfo_path.stem.upper()
        if len(nfo_paths) == 1:
            text, ok = _ask_number(self, video_path.name, number)
            if not ok or not text:
                return
            number = text
        Flags.again_dic[video_path] = (number, "", "")
        added += 1

    if added:
        signal_qt.show_log_text(f" 💡 已添加 {added} 个重新刮削任务")
        signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
        if self.Ui.pushButton_start_cap.text() == "开始":
            again_search()


def _ask_number(self: MyMAinWindow, video_name: str, default_number: str):
    from PyQt6.QtWidgets import QInputDialog

    return QInputDialog.getText(self, "输入番号重新刮削", f"文件名: {video_name}\n请输入番号:", text=default_number)


def _nfo_lib_delete_nfo(self: MyMAinWindow, nfo_paths: list[Path]) -> None:
    """删除选中的 NFO 文件（带确认）。"""
    if len(nfo_paths) == 1:
        box_text = f"将要删除文件: \n{nfo_paths[0]}\n\n 你确定要删除吗？"
    else:
        preview = "\n".join(str(p) for p in nfo_paths[:10])
        more = f"\n... 等共 {len(nfo_paths)} 个" if len(nfo_paths) > 10 else ""
        box_text = f"将要删除 {len(nfo_paths)} 个 NFO 文件：\n{preview}{more}\n\n你确定要继续吗？"

    box = QMessageBox(QMessageBox.Icon.Warning, "删除 NFO", box_text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    yes_btn = box.button(QMessageBox.StandardButton.Yes)
    no_btn = box.button(QMessageBox.StandardButton.No)
    if yes_btn:
        yes_btn.setText("删除")
    if no_btn:
        no_btn.setText("取消")
    box.setDefaultButton(QMessageBox.StandardButton.No)
    if box.exec() != QMessageBox.StandardButton.Yes:
        return

    # 删除后从列表移除的项
    removed_names = set()
    success_count = 0
    for nfo_path in nfo_paths:
        result, error_info = delete_file_sync(nfo_path)
        if result:
            success_count += 1
            removed_names.add(nfo_path.stem)
            signal_qt.show_log_text(f" ✅ 已删除: {nfo_path}")
        else:
            reason = error_info or "未知原因"
            signal_qt.show_log_text(f" ❌ 删除失败: {nfo_path}\n    原因: {reason}")

    # 从列表移除已删除的项
    for row in range(self.Ui.listWidget_nfo_lib.count() - 1, -1, -1):
        item = self.Ui.listWidget_nfo_lib.item(row)
        if item.text() in removed_names and Path(item.data(NFO_PATH_ROLE)).stem in removed_names:
            self.Ui.listWidget_nfo_lib.takeItem(row)

    # 更新计数
    remaining = self.Ui.listWidget_nfo_lib.count()
    self.Ui.label_nfo_lib_count.setText(f"共 {remaining} 个")
    signal_qt.show_log_text(f"NFO 库管理: 删除完成 — 成功 {success_count}，失败 {len(nfo_paths) - success_count}")
