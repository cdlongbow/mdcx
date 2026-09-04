"""SQLite 刮削状态缓存层。

持久化每个源文件的刮削处理状态，实现断点续刮与失败跨会话重试。
这是轻量状态层：权威元数据仍是 NFO，权威演员库仍是 xlsx，本模块只记录
"谁刮过、结果如何"。数据库损坏或不可用时回退到内存模式，不影响主流程。
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from ..signals import signal

# 失败自动重试的最大次数（设计决策：默认 3 次，达到后不再自动重试，仅手动强制）
MAX_RETRY_COUNT = 3
_BATCH_COMMIT_SIZE = 32


@dataclass
class ScrapeState:
    """单文件的刮削状态记录。"""

    file_path: str  # 源文件绝对路径
    mtime: float  # 处理时的源文件 mtime
    status: str  # "done" / "failed"
    number: str = ""  # 刮到的番号（成功时）
    fail_count: int = 0  # 连续失败次数
    scraped_at: float = 0.0  # 最后处理时间戳
    error: str = ""  # 最后错误信息（失败时）
    origin_path: str = ""  # 失败前的源文件路径（失败文件被移入 failed_folder 时与 file_path 不同）


class ScrapeStateCache:
    """基于 SQLite（标准库 sqlite3，WAL 模式）的刮削状态缓存访问层。"""

    def __init__(self, db_path: Path, log_fn=None):
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()  # 刮削为多协程并发写，SQLite 单写者需串行化
        self._pending_writes = 0
        self._log = log_fn or (lambda msg: signal.add_log(f" [刮削缓存] {msg}"))

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """打开数据库（WAL 模式 + 建表）。失败返回 False（回退内存模式）。"""
        if self._conn is not None:
            return True
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row  # 按列名访问行
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scrape_state (
                    file_path  TEXT PRIMARY KEY,
                    mtime      REAL NOT NULL,
                    status     TEXT NOT NULL,
                    number     TEXT NOT NULL DEFAULT '',
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    scraped_at REAL NOT NULL,
                    error      TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # 迁移：旧表无 summary_json 列时补齐（存相似推荐所需的结果摘要）
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(scrape_state)").fetchall()}
            if "summary_json" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN summary_json TEXT NOT NULL DEFAULT ''")
            # 迁移：origin_path 存失败前的源文件路径（全库审查 B5）——
            # set_failed 的 key 是移入 failed_folder 后的路径，失败目录在扫描
            # 集合之外时 cleanup_missing 会误判"源文件已不存在"删光 failed 记录，
            # 跨会话恢复（list_pending）随之失效
            if "origin_path" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN origin_path TEXT NOT NULL DEFAULT ''")
            conn.commit()
            self._conn = conn
            self._pending_writes = 0
            return True
        except Exception as e:
            self._log(f"数据库打开失败，回退内存模式: {e}")
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

    def close(self) -> None:
        if self._conn is not None:
            try:
                self.flush()
                self._conn.close()
            except Exception as e:
                self._log(f"数据库关闭失败: {e}")
            self._conn = None
            self._pending_writes = 0

    def is_usable(self) -> bool:
        return self._conn is not None

    # ------------------------------------------------------------------
    # 状态读写
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple = (), commit: bool = True) -> bool:
        """执行写 SQL，失败记日志返回 False（尽力而为，不中断主流程）。"""
        if self._conn is None:
            return False
        try:
            with self._lock:
                self._conn.execute(sql, params)
                self._pending_writes += 1
                if commit or self._pending_writes >= _BATCH_COMMIT_SIZE:
                    self._conn.commit()
                    self._pending_writes = 0
            return True
        except Exception as e:
            self._log(f"数据库写入失败: {e}")
            return False

    def flush(self) -> bool:
        """提交刮削期间积累的状态写入。"""
        if self._conn is None:
            return False
        try:
            with self._lock:
                if self._pending_writes:
                    self._conn.commit()
                    self._pending_writes = 0
            return True
        except Exception as e:
            self._log(f"数据库提交失败: {e}")
            return False

    def _fetch(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        if self._conn is None:
            return []
        try:
            with self._lock:
                rows = self._conn.execute(sql, params).fetchall()
            return rows
        except Exception as e:
            self._log(f"数据库查询失败: {e}")
            return []

    def get_state(self, file_path: Path) -> ScrapeState | None:
        rows = self._fetch(
            "SELECT file_path, mtime, status, number, fail_count, scraped_at, error, origin_path "
            "FROM scrape_state WHERE file_path = ?",
            (str(file_path),),
        )
        if not rows:
            return None
        row = rows[0]
        return ScrapeState(
            file_path=row["file_path"],
            mtime=row["mtime"],
            status=row["status"],
            number=row["number"],
            fail_count=row["fail_count"],
            scraped_at=row["scraped_at"],
            error=row["error"],
            origin_path=row["origin_path"],
        )

    def set_done(
        self,
        file_path: Path,
        mtime: float,
        number: str = "",
        summary: dict | None = None,
        commit: bool = True,
    ) -> None:
        import time

        summary_json = json.dumps(summary, ensure_ascii=False) if summary else ""
        self._execute(
            """
            INSERT INTO scrape_state (file_path, mtime, status, number, fail_count, scraped_at, error, summary_json)
            VALUES (?, ?, 'done', ?, 0, ?, '', ?)
            ON CONFLICT(file_path) DO UPDATE SET
                mtime=excluded.mtime,
                status='done',
                number=excluded.number,
                fail_count=0,
                scraped_at=excluded.scraped_at,
                error='',
                summary_json=excluded.summary_json
            """,
            (str(file_path), mtime, number, time.time(), summary_json),
            commit=commit,
        )

    def set_failed(
        self, file_path: Path, mtime: float, error: str = "", commit: bool = True, origin_path: Path | None = None
    ) -> None:
        """记录失败状态。

        origin_path：失败前的源文件路径。文件刮削失败被移入 failed_folder 后
        file_path 是移动后的路径——与扫描集合无交集，cleanup_missing 按
        origin 判存活才能保住 failed 记录（全库审查 B5）。
        """
        import time

        self._execute(
            """
            INSERT INTO scrape_state (file_path, mtime, status, number, fail_count, scraped_at, error, origin_path)
            VALUES (?, ?, 'failed', '', 1, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                mtime=excluded.mtime,
                status='failed',
                fail_count=fail_count + 1,
                scraped_at=excluded.scraped_at,
                error=excluded.error,
                origin_path=excluded.origin_path
            """,
            (str(file_path), mtime, time.time(), error, str(origin_path) if origin_path else ""),
            commit=commit,
        )

    # ------------------------------------------------------------------
    # 判断逻辑
    # ------------------------------------------------------------------

    def should_skip(self, file_path: Path, mtime: float, force: bool = False) -> bool:
        """断点续刮判断：done 且 mtime 未变且未强制 → True（跳过）。

        - force=True：无条件不跳过（手动强制重新刮削）
        - 状态缺失 / failed / mtime 变化 → 不跳过
        """
        if force:
            return False
        state = self.get_state(file_path)
        if state is None or state.status != "done":
            return False
        return abs(state.mtime - mtime) < 1e-6

    def should_retry(self, file_path: Path, max_retries: int = MAX_RETRY_COUNT) -> bool:
        """失败重试判断：fail_count < max_retries → True（重新入队）。

        仅对 failed 状态生效；done 或无记录返回 False。
        """
        state = self.get_state(file_path)
        if state is None or state.status != "failed":
            return False
        return state.fail_count < max_retries

    # ------------------------------------------------------------------
    # 队列恢复与清理
    # ------------------------------------------------------------------

    def list_pending(self, existing: set[Path], max_retries: int = MAX_RETRY_COUNT) -> list[Path]:
        """返回待处理文件列表（failed 且未超限）。

        existing：本次扫描到的源文件集合，仅返回其中仍存在的文件。
        """
        rows = self._fetch(
            "SELECT file_path, fail_count FROM scrape_state WHERE status = 'failed'",
        )
        pending = []
        for row in rows:
            p = Path(row["file_path"])
            if row["fail_count"] < max_retries and p in existing:
                pending.append(p)
        return pending

    def list_success_summaries(self) -> list[dict]:
        """返回全部成功刮削的结果摘要（供跨会话相似推荐等使用）。

        每条摘要包含 number/title/tags/series/studio/actors/release/runtime，
        以及相似推荐特征扩展字段 mosaic/publisher/directors/score。
        无 summary_json 的旧记录会被跳过。
        """
        rows = self._fetch(
            "SELECT summary_json FROM scrape_state WHERE status = 'done' AND summary_json != ''",
        )
        summaries = []
        for row in rows:
            try:
                data = json.loads(row["summary_json"])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data:
                summaries.append(data)
        return summaries

    def cleanup_missing(self, existing: set[Path]) -> int:
        """清理源文件已不存在的过期记录，返回清理条数。

        failed 记录优先按 origin_path（失败前源路径）判存活——key 是移入
        failed_folder 后的路径，独立失败目录配置下与扫描集合无交集，
        按 key 判会把全部 failed 记录误删（跨会话恢复失效，全库审查 B5）。
        """
        rows = self._fetch("SELECT file_path, status, origin_path FROM scrape_state")
        existing_str = {str(p) for p in existing}
        removed = 0
        for row in rows:
            raw_path = row["file_path"]
            if row["status"] == "failed" and row["origin_path"]:
                # failed 记录：源路径（origin）或失败目录内路径（key）任一存活即保留
                if str(Path(raw_path)) in existing_str or row["origin_path"] in existing_str:
                    continue
            else:
                if str(Path(raw_path)) in existing_str:
                    continue
            # commit=False 批量积累，共享一个事务（原逐条独立事务，大库数千条产生数千次 commit）
            if self._execute("DELETE FROM scrape_state WHERE file_path = ?", (raw_path,), commit=False):
                removed += 1
        self.flush()
        return removed

    def clear(self) -> None:
        """清空全部状态（供手动重置用）。"""
        self._execute("DELETE FROM scrape_state")

    # ------------------------------------------------------------------
    # 缓存管理 UI 支撑
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """聚合统计：返回 done/failed/failed_exhausted/total 计数 + db 路径/大小。

        - failed_exhausted：fail_count >= MAX_RETRY_COUNT 的失败记录（已不会自动重试）。
        - db_size_kb：数据库文件大小（KB），不存在或不可读为 0。
        """
        result: dict = {
            "done": 0,
            "failed": 0,
            "failed_exhausted": 0,
            "total": 0,
            "db_path": str(self._db_path),
            "db_size_kb": 0,
        }
        rows = self._fetch("SELECT status, COUNT(*) AS cnt FROM scrape_state GROUP BY status")
        for row in rows:
            s, cnt = row["status"], row["cnt"]
            result["total"] += cnt
            if s == "done":
                result["done"] = cnt
            elif s == "failed":
                result["failed"] = cnt
        ex = self._fetch(
            "SELECT COUNT(*) AS cnt FROM scrape_state WHERE status='failed' AND fail_count >= ?",
            (MAX_RETRY_COUNT,),
        )
        if ex:
            result["failed_exhausted"] = ex[0]["cnt"]
        try:
            result["db_size_kb"] = round(self._db_path.stat().st_size / 1024, 1) if self._db_path.exists() else 0
        except Exception:
            pass
        return result

    def list_failed_detail(self, limit: int = 500) -> list[ScrapeState]:
        """返回失败记录详情（含 error/fail_count），按最后处理时间倒序，限 limit 条。"""
        rows = self._fetch(
            "SELECT file_path, mtime, status, number, fail_count, scraped_at, error, origin_path "
            "FROM scrape_state WHERE status='failed' ORDER BY scraped_at DESC LIMIT ?",
            (limit,),
        )
        return [
            ScrapeState(
                file_path=r["file_path"],
                mtime=r["mtime"],
                status=r["status"],
                number=r["number"],
                fail_count=r["fail_count"],
                scraped_at=r["scraped_at"],
                origin_path=r["origin_path"],
                error=r["error"],
            )
            for r in rows
        ]

    def delete_state(self, file_path: Path) -> bool:
        """删除单文件状态记录（强制下次重刮）。

        删记录后 should_skip/should_retry 均返回 False，下次扫描自然入队重新刮削。
        返回是否删除成功（记录不存在也返回 True，语义为「不再有该记录」）。
        """
        return self._execute("DELETE FROM scrape_state WHERE file_path = ?", (str(file_path),))
