"""LogBuffer 任务树归因回归测试（H2）。

背景（实测复现，2026-08-29）：
get() 原拼接【全局所有】任务的 buffer（c089eaf 为聚合子协程日志引入），
但并发刮削的兄弟影片任务（scraper.py:110 每片一个 process_one_file）
task_id 互不相干，导致：
1. 跨影片错误污染——毫不相干任务的 error().get() 混入别的影片失败原因，
   写入 Flags.failed_list 与 SQLite 断点缓存；
2. buffer 无界残留——clear_task 只清当前 task_id，兄弟与子任务 buffer 全残留。

修复：contextvar 任务树归因——write 惰性 settle root（create_task 子任务
经 context 拷贝自动继承），get 只聚合同 root 的 buffer，clear_task 整树回收。
四条性质由本文件锁定。
"""

import asyncio
import threading

import pytest

from mdcx.models.log_buffer import LogBuffer

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_buffers():
    """每个测试前后清空 all_buffers，避免用例间串扰。"""
    LogBuffer.all_buffers.clear()
    LogBuffer.global_buffer = None
    yield
    LogBuffer.all_buffers.clear()
    LogBuffer.global_buffer = None


async def test_sibling_tasks_do_not_cross_pollute():
    """性质1：兄弟任务互不污染——B 的失败原因不得出现在 A 树的 get() 里。"""
    LogBuffer.new_root()  # 兄弟 A 自立门户

    async def sibling_b_fail():
        LogBuffer.new_root()  # 兄弟 B 自立门户
        LogBuffer.error().write("\n [B] 影片B失败原因：所有来源均无数据")
        await asyncio.sleep(0.05)  # 保持在途，与 A 并发

    async def sibling_a_read():
        await asyncio.sleep(0.02)  # B 已写入错误的窗口
        return LogBuffer.error().get()  # A 自己从未写错误

    b = asyncio.create_task(sibling_b_fail(), name="scrape-B")
    a = asyncio.create_task(sibling_a_read(), name="scrape-A")
    await asyncio.gather(b, a)

    polluted = "[B]" in a.result()
    assert not polluted, f"A 树读到了 B 的失败原因（跨影片污染）: {a.result()!r}"


async def test_descendant_logs_still_aggregated():
    """性质2：c089eaf 意图保留——create_task 子协程的日志仍聚合进本任务 get()。"""
    LogBuffer.new_root()
    LogBuffer.log().write("\n [main] 影片刮削开始")

    async def fanart_subtask():
        LogBuffer.log().write("\n [sub] fanart 下载完成")

    sub = asyncio.create_task(fanart_subtask(), name="fanart")
    await sub

    # 子任务有自己的 task_id，但经 context 继承同一 root，必须被聚合
    got = LogBuffer.log().get()
    assert "[main]" in got
    assert "[sub]" in got, f"子协程日志未被聚合（c089eaf 场景回归）: {got!r}"


async def test_to_thread_writes_readable_by_spawning_task():
    """性质3：to_thread 线程内写入的日志，发起任务的 get() 必须能读到。

    现状依赖全局拼接才能读到；改为树归因后靠 root contextvar
    在 to_thread 内可见（ctx.run 语义）保持该能力。
    """
    LogBuffer.new_root()

    def thread_write(msg: str):
        # 线程内 current_task 为 None——归因必须落到发起者的 root
        LogBuffer.log().write(msg)

    await asyncio.to_thread(thread_write, "\n [from-thread] 线程写入的诊断")
    got = LogBuffer.log().get()
    assert "[from-thread]" in got, f"线程写入丢失: {got!r}"


async def test_clear_task_recycles_whole_tree():
    """性质4：clear_task 整树回收——兄弟任务结束后其 buffer 不得残留。"""
    LogBuffer.new_root()

    async def sibling_c():
        LogBuffer.new_root()
        LogBuffer.log().write("\n [C] 兄弟任务的日志")
        LogBuffer.clear_task()  # 模拟 process_one_file finally

    async def child_sub():
        LogBuffer.log().write("\n [A-sub] 子任务日志")

    await asyncio.create_task(sibling_c(), name="scrape-C")
    await asyncio.create_task(child_sub(), name="sub")
    LogBuffer.clear_task()  # A 自身结束

    leftovers = [
        (tid, [n for n, b in cats.items() if isinstance(b, LogBuffer) and b.buffer])
        for tid, cats in LogBuffer.all_buffers.items()
    ]
    non_empty = [x for x in leftovers if x[1]]
    assert not non_empty, f"任务结束后 buffer 残留（无界增长）: {non_empty}"


async def test_thread_write_in_bare_thread_falls_back_safely():
    """边界：无协程上下文的裸线程写入不得崩溃（GUI 线程等场景）。"""
    result: dict = {}

    def bare_thread():
        try:
            LogBuffer.log().write("\n [bare-thread] 裸线程日志")
            result["ok"] = True
        except Exception as e:  # noqa: BLE001
            result["ok"] = False
            result["err"] = repr(e)

    t = threading.Thread(target=bare_thread)
    t.start()
    t.join()
    assert result.get("ok") is True, f"裸线程写入崩溃: {result.get('err')}"


async def test_single_task_write_get_roundtrip():
    """兼容性：工具页/测试的单任务场景（无显式 new_root）自聚自读。"""
    LogBuffer.log().write("\n [tool] 工具页单任务日志")
    got = LogBuffer.log().get()
    assert "[tool]" in got
    LogBuffer.clear_task()
    assert "[tool]" not in LogBuffer.log().get()


def test_error_get_only_self_excludes_log_channel():
    """error 通道 get(only_self=True) 不聚合本组 log 通道（全库审查 B3）。

    修复前 error().get() 把本组几十行正常刮削日志拼进失败原因，
    随 Flags.failed_list 与 SQLite error 列持久化，失败报告被污染。
    """
    LogBuffer.new_root()
    LogBuffer.log().write("字段获取: title 来自 javdb\n")
    LogBuffer.log().write("下载封面: xxx.jpg 完成\n")
    LogBuffer.error().write("刮削失败: 所有刮削来源均未返回可用数据\n")

    err = LogBuffer.error().get(only_self=True)
    assert err == "刮削失败: 所有刮削来源均未返回可用数据\n"
    assert "字段获取" not in err
    assert "下载封面" not in err

    # log 通道聚合行为保持不变（含本组其他通道）
    combined = LogBuffer.log().get()
    assert "字段获取" in combined


def test_get_default_behavior_unchanged():
    """默认 get() 聚合行为不变（log 通道跨子任务聚合语义保留）。"""
    LogBuffer.new_root()
    LogBuffer.log().write("正常日志A\n")
    LogBuffer.error().write("错误B\n")

    combined = LogBuffer.log().get()
    assert "正常日志A" in combined
    assert "错误B" in combined
