import asyncio
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from mdcx.config.manager import manager
from mdcx.signals import signal_qt
from mdcx.utils import executor, get_current_time


class _GfriendsSignals(QObject):
    done = pyqtSignal(bool, str)


_gfriends_signal = _GfriendsSignals()


def pushButton_cover_backfill_start_clicked(self):
    from scripts.cover_backfill import backfill_cover

    self.pushButton_show_log_clicked()
    numbers = self.Ui.lineEdit_cover_backfill_numbers.text().strip()
    if not numbers:
        signal_qt.show_log_text("🔴 请输入番号")
        return
    number_list = [n.strip() for n in numbers.split() if n.strip()]
    overwrite = self.Ui.checkBox_cover_backfill_overwrite.isChecked()
    watermark = self.Ui.checkBox_cover_backfill_watermark.isChecked()

    async def run_backfill():
        results = []
        for number in number_list:
            signal_qt.show_log_text(f"开始补图: {number}")
            try:
                result = await backfill_cover(
                    number,
                    output_dir=manager.data_folder,
                    overwrite=overwrite,
                    watermark=watermark,
                )
                results.append(result)
                signal_qt.show_log_text(f"  ✅ {result.number}: thumb={result.thumb_path}, poster={result.poster_path}")
            except Exception as e:
                signal_qt.show_log_text(f"  🔴 {number}: {e}")
        signal_qt.show_log_text("=" * 60)
        signal_qt.show_log_text(f"封面补图完成: {len(results)}/{len(number_list)} 成功")
        self.pushButton_cover_backfill_start.emit("开始补图")

    self.pushButton_cover_backfill_start.emit("补图中...")
    executor.submit(run_backfill())


def pushButton_emby_actor_manager_clicked(self):
    """打开 Emby 演员管理器（单例）。议题 #61：原版每次点击新建 dialog →
    可同时开多个，"提交或获取数据相互干扰/请求过载"。改为单例复用 +
    destroyed 信号清引用。"""
    try:
        from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

        existing = getattr(self, "_emby_dialog", None)
        if existing is not None:
            try:
                # 已存在且未销毁 → 提前台复用（含从最小化还原）
                if existing.isMinimized():
                    existing.showNormal()
                else:
                    existing.show()
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                # C++ 对象已被销毁（WA_DeleteOnClose 释放），换新的
                self._emby_dialog = None

        dialog = EmbyActorManagerDialog()
        # 主窗口侧只保存弱存在语义：destroyed 时清引用，避免悬空指针
        dialog.destroyed.connect(lambda *_: setattr(self, "_emby_dialog", None))
        self._emby_dialog = dialog
        dialog.show()
    except Exception as e:
        signal_qt.show_log_text(f"❌ Emby 演员管理器打开失败: {e}\n{traceback.format_exc()}")


# ============= 设置-演员 =============


def pushButton_select_gfriends_local_clicked(self):
    gfriends_path = self._get_select_folder_path(self.Ui.lineEdit_gfriends_local_path)
    if gfriends_path:
        self.Ui.lineEdit_gfriends_local_path.setText(gfriends_path)
        self.pushButton_save_config_clicked()


def pushButton_sync_gfriends_clicked(self):
    local_path = self.Ui.lineEdit_gfriends_local_path.text().strip()
    if not local_path:
        QMessageBox.warning(self, "提示", "请先选择 Gfriends 本地仓库目录")
        return
    from mdcx.tools.sync_gfriends import sync_gfriends as do_sync

    # git pull 走后台线程，避免同步阻塞 UI（超时最长 5 分钟）
    self.Ui.pushButton_sync_gfriends.setEnabled(False)
    self.Ui.pushButton_sync_gfriends.setText("更新中...")

    def _done(success: bool, msg: str):
        self.Ui.pushButton_sync_gfriends.setEnabled(True)
        self.Ui.pushButton_sync_gfriends.setText("同步 Gfriends")
        if success:
            signal_qt.show_scrape_info(f"✅ {msg}")
        else:
            QMessageBox.warning(self, "更新失败", msg)
        self.Ui.label_gfriends_update_time.setText(f"最后更新: {get_current_time()}")

    try:
        _gfriends_signal.done.disconnect()
    except TypeError:
        pass
    _gfriends_signal.done.connect(_done)

    async def _run():
        success, msg = await asyncio.to_thread(do_sync, local_path)
        _gfriends_signal.done.emit(success, msg)

    executor.submit(_run())


def pushButton_select_actor_info_db_clicked(self):
    database_path, _ = QFileDialog.getOpenFileName(
        None, "选择数据库文件", manager.data_folder.as_posix(), options=self.options
    )
    if database_path:
        self.Ui.lineEdit_actor_db_path.setText(database_path)
        self.pushButton_save_config_clicked()


def pushButton_add_actor_info_clicked(self):
    from mdcx.tools.emby_actor_info import update_emby_actor_info

    self.pushButton_save_config_clicked()
    self.pushButton_show_log_clicked()
    try:
        executor.submit(update_emby_actor_info())
    except Exception:
        signal_qt.show_log_text(traceback.format_exc())


def pushButton_add_actor_pic_clicked(self):
    from mdcx.tools.emby_actor_image import update_emby_actor_photo

    self.pushButton_save_config_clicked()
    self.pushButton_show_log_clicked()
    try:
        executor.submit(update_emby_actor_photo())
    except Exception:
        signal_qt.show_log_text(traceback.format_exc())


def pushButton_add_actor_pic_kodi_clicked(self):
    from mdcx.tools.emby_actor_info import creat_kodi_actors

    self.pushButton_save_config_clicked()
    self.pushButton_show_log_clicked()
    try:
        executor.submit(creat_kodi_actors(True))
    except Exception:
        signal_qt.show_log_text(traceback.format_exc())


def pushButton_del_actor_folder_clicked(self):
    from mdcx.tools.emby_actor_info import creat_kodi_actors

    self.pushButton_show_log_clicked()
    try:
        executor.submit(creat_kodi_actors(False))
    except Exception:
        signal_qt.show_log_text(traceback.format_exc())


def pushButton_show_pic_actor_clicked(self):
    from mdcx.tools.emby_actor_info import show_emby_actor_list

    self.pushButton_show_log_clicked()
    try:
        executor.submit(show_emby_actor_list(self.Ui.comboBox_pic_actor.currentIndex()))
    except Exception:
        signal_qt.show_log_text(traceback.format_exc())


# ============= 通用目录选择 =============


def _pick_folder(self, line_edit_attr: str) -> None:
    """选择目录并设置到 lineEdit，同时保存配置。"""
    line_edit = getattr(self.Ui, line_edit_attr)
    path = self._get_select_folder_path(line_edit)
    if path:
        line_edit.setText(path)
        self.pushButton_save_config_clicked()


def pushButton_select_softlink_folder_clicked(self):
    _pick_folder(self, "lineEdit_movie_softlink_path")


def pushButton_select_sucess_folder_clicked(self):
    _pick_folder(self, "lineEdit_success")


def pushButton_select_failed_folder_clicked(self):
    _pick_folder(self, "lineEdit_fail")


def pushButton_select_subtitle_folder_clicked(self):
    _pick_folder(self, "lineEdit_sub_folder")


def pushButton_select_actor_photo_folder_clicked(self):
    _pick_folder(self, "lineEdit_actor_photo_folder")


def pushButton_select_local_library_clicked(self):
    _pick_folder(self, "lineEdit_local_library_path")


def pushButton_select_netdisk_path_clicked(self):
    _pick_folder(self, "lineEdit_netdisk_path")


def pushButton_select_localdisk_path_clicked(self):
    _pick_folder(self, "lineEdit_localdisk_path")


def pushButton_select_media_folder_clicked(self):
    _pick_folder(self, "lineEdit_movie_path")


# ============= 演员库维护（新三按钮） =============


def pushButton_actor_db_translate_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🔍 开始扫描 actor_database.xlsx：查找已有 TMDB ID 但缺少中文名的条目...")
    self._run_actor_db_tool("translate")


def pushButton_actor_db_link_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🔍 开始扫描 actor_database.xlsx：查找已有 TMDB ID 但缺少 LibreDMM 链接的条目...")
    self._run_actor_db_tool("link")


def pushButton_actor_db_sync_aliases_clicked(self):
    self.pushButton_show_log_clicked()
    source = self.Ui.comboBox_actor_db_alias_source.currentText()
    all_rows = self.Ui.checkBox_actor_db_alias_all.isChecked()
    offset = self.Ui.spinBox_actor_db_sync_offset.value()
    limit = self.Ui.spinBox_actor_db_sync_limit.value()
    slice_hint = f"，起始行={offset}，限量={limit if limit > 0 else '不限'}"
    signal_qt.show_log_text(
        f"🔍 开始扫描 actor_database.xlsx：从 {source} 同步别名到 keyword 列"
        + ("（全量并入" if all_rows else "（仅补缺别名")
        + slice_hint
        + "）..."
    )
    # 下拉项映射：UI "minnano" → 内部 "avwiki"（走みんなのAV）；"JavDB" → "javdb"
    if source == "JavDB":
        alias_source = "javdb"
    elif source == "minnano":
        alias_source = "avwiki"
    else:
        alias_source = "tmdb"
    self._run_actor_db_tool(
        "sync_aliases",
        alias_source=alias_source,
        overwrite=all_rows,
        offset=offset,
        limit=limit,
    )


def pushButton_actor_db_open_clicked(self):
    from mdcx.config.resources import resources

    db_path = Path(resources.u("actor_database.xlsx"))
    if not db_path.exists():
        signal_qt.show_log_text("🔴 actor_database.xlsx 不存在，请先刮削或执行一次演员库维护生成数据库")
        return
    signal_qt.show_log_text(f"📂 正在用系统默认程序打开: {db_path}")
    threading.Thread(target=_open_file_thread, args=(db_path,), daemon=True).start()


def _open_file_thread(db_path):
    from mdcx.utils.file import open_file_thread

    try:
        open_file_thread(Path(db_path), False)
        signal_qt.show_log_text(f"✅ 已打开 actor_database.xlsx: {db_path}")
    except Exception:
        signal_qt.show_log_text(
            f"🔴 无法打开 actor_database.xlsx。\n{traceback.format_exc()}\n请先安装 Excel/WPS 或 LibreOffice 等文字处理软件后重试"
        )


def pushButton_actor_db_clean_male_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🎬 开始剔除男演员（按 tmdbid 校验 TMDB gender，删除男优）...")
    self._run_actor_db_clean_male()


def pushButton_actor_db_verify_tmdbid_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🎬 开始校验 tmdbid 有效性（404 失效 id 清除回无 id 状态）...")
    self._run_actor_db_verify_tmdbid()


def pushButton_actor_db_check_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🔍 开始检查用户库（格式/结构/数据异常）...")
    self._run_actor_db_check()


def pushButton_actor_db_pick_nfo_dir_clicked(self):
    from PyQt6.QtWidgets import QFileDialog

    folder = QFileDialog.getExistingDirectory(
        None,
        "选择 nfo 目录",
        "",
        QFileDialog.Option.ShowDirsOnly,
    )
    if folder:
        self.Ui.lineEdit_actor_db_nfo_dir.setText(folder)


def pushButton_actor_db_update_nfo_tmdbid_clicked(self):
    self.pushButton_show_log_clicked()
    signal_qt.show_log_text("🎬 开始更新 nfo tmdbid（用本地库新 id 覆盖 nfo 旧 id）...")
    self._run_actor_db_update_nfo()
