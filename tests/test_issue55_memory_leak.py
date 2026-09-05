"""议题 #55 回归测试：内存占满卡死的两条链路。

链路一（租约泄漏 → 旧网络栈永不回收）：
  `ComputedLease.__exit__` 通过 executor 异步提交 `Computed.release()`。
  点「停止刮削」调用 `executor.cancel_async()` 无差别取消所有 pending future，
  排队中的 release 被取消 → 租约计数永久 +1 → `_is_idle()` 永远为假 →
  旧网络栈的 `close_when_idle()` 陷入 0.2 秒死轮询且永不释放连接池。
  每轮「刮削→停止→保存」泄漏一个完整网络栈，线性累积至卡死。

链路二（已移除站点值 → 配置校验整体失败）：
  2026-08 精简 15 个爬虫后，旧配置残留的站点值触发 pydantic 校验失败，
  `load_config` 走失败分支，保存目标被改指 `_failed.json` 且界面回写被跳过。
"""

import asyncio
import time
from pathlib import Path

import pytest

from mdcx.config.enums import Website
from mdcx.config.migrations import migrate_config_data
from mdcx.config.models import Config
from mdcx.utils import AsyncBackgroundExecutor

MDCX_ROOT = Path(__file__).resolve().parents[1] / "mdcx"

# 2026-08 精简掉的爬虫站点值
REMOVED_SITES = [
    "cnmdb",
    "hdouban",
    "mdtv",
    "love6",
    "kin8",
    "giga",
    "cableav",
    # 7mmtv 2026-09 以聚合站爬虫回归（见 mdcx/crawlers/7mmtv.py），不再剔除
    "hscangku",
    "fc2club",
    "fc2hub",
    "jav321",
    "fantastica",
    "dahlia",
    "faleno",
]


class _FakeLeaseHolder:
    """复刻 AsyncWebClient / LLMClient 的租约语义。"""

    def __init__(self) -> None:
        self._leases = 0

    def retain(self) -> None:
        self._leases += 1

    async def release(self) -> None:
        if self._leases > 0:
            self._leases -= 1


# ---------------------------------------------------------------- 链路一：租约


def test_submit_critical_survives_cancel():
    """关键通道提交的 release 不被 cancel_async 取消，租约必须归零。"""
    executor = AsyncBackgroundExecutor()
    try:
        holder = _FakeLeaseHolder()
        for _ in range(5):
            holder.retain()
            executor.submit_critical(holder.release())
        executor.cancel_async()
        # 等关键任务跑完
        deadline = time.monotonic() + 5
        while holder._leases > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert holder._leases == 0, (
            f"关键通道的 release 被取消，残留 {holder._leases} 个租约；"
            "租约永不归零会让旧网络栈的 close_when_idle 无限轮询（议题 #55）"
        )
    finally:
        executor._cleanup()


def test_submit_critical_survives_sync_cancel():
    """同步 cancel() 同样不得取消关键任务。"""
    executor = AsyncBackgroundExecutor()
    try:
        holder = _FakeLeaseHolder()
        for _ in range(3):
            holder.retain()
            executor.submit_critical(holder.release())
        executor.cancel()
        deadline = time.monotonic() + 5
        while holder._leases > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert holder._leases == 0, f"cancel() 取消了关键任务，残留 {holder._leases} 个租约"
    finally:
        executor._cleanup()


def test_normal_submit_still_cancellable():
    """普通通道保持可取消语义，停止刮削仍须能中断刮削任务。"""
    executor = AsyncBackgroundExecutor()
    try:
        started = asyncio.Event()

        async def _long_task():
            await asyncio.sleep(30)
            return "finished"

        future = executor.submit(_long_task())
        time.sleep(0.2)
        executor.cancel()
        deadline = time.monotonic() + 5
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert future.cancelled() or future.done(), "普通任务应仍可被 cancel 中断"
        assert not started.is_set()
    finally:
        executor._cleanup()


def test_lease_release_uses_critical_channel():
    """ComputedLease.__exit__ 必须走 submit_critical，而非可被取消的 submit。

    conftest 用 dummy 模块替换了 `mdcx.config.manager`，故直接对源文件做 AST 解析。
    """
    import ast

    source = (MDCX_ROOT / "config" / "manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    lease_class = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "ComputedLease"),
        None,
    )
    assert lease_class is not None, "未找到 ComputedLease 类"

    exit_method = next(
        (node for node in lease_class.body if isinstance(node, ast.FunctionDef) and node.name == "__exit__"),
        None,
    )
    assert exit_method is not None, "未找到 ComputedLease.__exit__"

    calls = {
        node.func.attr
        for node in ast.walk(exit_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "submit_critical" in calls, "release 必须走关键通道，否则停止刮削时会被取消导致租约泄漏"
    assert "submit" not in calls, "release 不得使用可被取消的普通 submit 通道"


# ------------------------------------------------------- 链路一：关闭超时兜底


@pytest.mark.asyncio
async def test_web_client_close_when_idle_has_timeout():
    """租约泄漏时 close_when_idle 必须超时强制关闭，不得无限轮询。"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=10)
    client.retain()  # 制造永不释放的租约
    start = time.monotonic()
    await client.close_when_idle(poll_interval=0.01, timeout=0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 5, f"close_when_idle 未在超时后返回（耗时 {elapsed:.1f}s），存在无限轮询风险"
    assert client._closed, "超时后必须强制关闭连接池，否则旧网络栈永久驻留"


@pytest.mark.asyncio
async def test_llm_client_close_when_idle_has_timeout():
    """LLM 客户端同样需要超时兜底。"""
    from httpx import Timeout

    from mdcx.llm import LLMClient

    client = LLMClient(
        api_key="test",
        base_url="https://example.com/v1",
        timeout=Timeout(10),
        rate=(1, 1),
    )
    client.retain()
    start = time.monotonic()
    await client.close_when_idle(poll_interval=0.01, timeout=0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 5, f"LLM close_when_idle 未在超时后返回（耗时 {elapsed:.1f}s）"
    assert client._closed, "超时后必须强制关闭"


@pytest.mark.asyncio
async def test_close_when_idle_returns_promptly_when_idle():
    """无租约时应立即关闭，不受超时参数影响。"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=10)
    start = time.monotonic()
    await client.close_when_idle(poll_interval=0.01, timeout=60)
    assert time.monotonic() - start < 2, "空闲客户端应立即关闭"
    assert client._closed


# ------------------------------------------------- 链路二：已移除站点值迁移


@pytest.mark.parametrize("removed_site", REMOVED_SITES)
def test_removed_site_dropped_from_website_lists(removed_site: str):
    """website_* 列表中的已移除站点必须被静默剔除。"""
    data = {"website_youma": ["dmm", removed_site, "javdb"]}
    migrate_config_data(data)
    assert removed_site not in data["website_youma"], f"{removed_site} 未被剔除，会导致配置校验整体失败"
    assert data["website_youma"] == ["dmm", "javdb"], "剔除后须保持原有顺序且不误删有效站点"


@pytest.mark.parametrize("removed_site", REMOVED_SITES)
def test_removed_site_dropped_from_field_configs(removed_site: str):
    """field_configs 与 type_field_configs 的 site_prority 同样需清洗。"""
    data = {
        "field_configs": {"actors": {"site_prority": ["dmm", removed_site]}},
        "type_field_configs": {"fc2": {"studio": {"site_prority": [removed_site, "fc2"]}}},
    }
    migrate_config_data(data)
    assert data["field_configs"]["actors"]["site_prority"] == ["dmm"]
    assert data["type_field_configs"]["fc2"]["studio"]["site_prority"] == ["fc2"]


def test_removed_site_dropped_from_site_configs():
    """site_configs 中键为已移除站点的条目需剔除，有效条目保留。"""
    data = {
        "site_configs": {
            "javbus": {"custom_url": "https://example.com/"},
            "fc2hub": {"custom_url": "https://removed.example/"},
        }
    }
    migrate_config_data(data)
    assert "fc2hub" not in data["site_configs"]
    assert data["site_configs"]["javbus"]["custom_url"] == "https://example.com/"


def test_removed_website_single_falls_back():
    """website_single 若指向已移除站点，回落到默认值。"""
    data = {"website_single": "fc2hub"}
    migrate_config_data(data)
    assert data["website_single"] == Website.AIRAV_CC.value


def test_site_rename_still_applied():
    """既有的重命名迁移不得被清洗逻辑破坏。"""
    data = {"website_youma": ["javdbapi", "dmm"]}
    migrate_config_data(data)
    assert data["website_youma"] == ["dmm_api", "dmm"]


def test_config_with_all_removed_sites_validates():
    """含全部已移除站点的旧配置，迁移后必须能通过 pydantic 校验。

    否则 load_config 走失败分支，保存目标被改指 _failed.json（表现为「保存不生效」）。
    """
    data = {
        "website_single": "fc2hub",
        "website_youma": ["dmm", *REMOVED_SITES, "javdb"],
        "website_wuma": ["avsox", "kin8"],
        "website_fc2": ["fc2", "fc2club", "fc2hub"],
        "website_guochan": ["madouqu", "cnmdb", "hdouban", "mdtv", "hscangku"],
        "field_configs": {
            "actors": {"site_prority": ["dmm", *REMOVED_SITES]},
        },
        "type_field_configs": {
            "fc2": {"studio": {"site_prority": [*REMOVED_SITES, "fc2"]}},
        },
        "site_configs": {"fc2hub": {"custom_url": "https://removed.example/"}},
    }
    warnings = Config.update(data)
    config = Config.model_validate(data)  # 不抛异常即通过
    assert not any("validation error" in w.lower() for w in warnings)
    assert Website.DMM in config.website_youma
    assert Website.JAVDB in config.website_youma
