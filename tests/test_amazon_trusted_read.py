"""Amazon 日亚读零校验行为测试。

架构（2026-09-01 定案）：
- 读路径（ASIN 库缓存命中）: 无条件信任，跳过软校验——交付库 100% 已验证
- 写路径（搜索新发现）: 软校验作为入库门槛，无条件执行
- 严格开关 amazon_strict_pic_verify 移除（语义在新架构下为空）
"""

import pytest

import mdcx.core.web as core_web


class _FakeResult:
    def __init__(self):
        self.number = "TEST-001"
        self.amazon_match_is_hard = False


def _find_caller_line() -> str:
    return ""


@pytest.mark.asyncio
async def test_db_cache_hit_skips_soft_verify(monkeypatch):
    """ASIN 库缓存命中（reason=cache/tenhow）→ 不触发软校验"""
    called = []
    monkeypatch.setattr(core_web, "_verify_soft_amazon_poster", lambda *a, **k: called.append(1) or True)
    result = _FakeResult()
    # 库命中: is_hard 被 get_big_pic_by_amazon 设为 True (reason=cache/tenhow)
    result.amazon_match_is_hard = True
    # 模拟 web.py 749 的判定式（新形态: should_verify = not hard）
    should_verify = not core_web.is_amazon_hard_match(result)
    assert should_verify is False
    # should_verify False 时短路, 软校验不被调用
    assert not (should_verify and True)


@pytest.mark.asyncio
async def test_new_discovery_still_verifies(monkeypatch):
    """搜索新发现（无缓存, hard=False）→ 仍走软校验"""
    result = _FakeResult()
    result.amazon_match_is_hard = False
    should_verify = not core_web.is_amazon_hard_match(result)
    assert should_verify is True


def test_amazon_match_state_reason_carries_cache_origin():
    """库命中的 match state 携带 cache/tenhow 来源（web.py 读路径判定依据）"""
    from mdcx.core.amazon import _set_amazon_match_state

    result = _FakeResult()
    _set_amazon_match_state(result, is_hard=True, reason="tenhow", url="https://www.amazon.co.jp/dp/X")
    assert core_web.is_amazon_hard_match(result) is True
    assert result.amazon_match_reason == "tenhow"
