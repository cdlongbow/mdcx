"""软校验裁决链 v2 测试：cid 旁证 → 标题门 → 图像兜底（路径 D 软匹配专用）。

判定矩阵（设计 r2）：
- cid 一致 → 实锤（跳过后续）
- cid 不一致 → 强警示失败（阻止入库）
- cid miss → 标题门（NFKC 系列互含；合集词一票否决）
- 标题 miss（无片名/无文本）→ 图像门兜底（现逻辑）
"""

from __future__ import annotations

import pytest

import mdcx.core.web as core_web


class _FakeResult:
    """携带软校验所需上下文的最小对象。"""

    def __init__(self, number="TEST-001", reason="soft", title="", asin=""):
        self.number = number
        self.amazon_match_reason = reason
        self.title = title
        self.amazon_asin = asin


@pytest.mark.asyncio
async def test_cid_match_passes_without_image_verification(monkeypatch, tmp_path):
    """cid 旁证一致 → 实锤通过，不再走图像比对"""
    called = []

    async def fake_verify(*a, **k):
        called.append(1)
        return False  # 若被调用且返回 False, 用图像结果无法翻案

    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: True)

    # 验证 v2 裁决链入口: cid 命中短路
    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B081DYPZ13",
        number="MIFD-093",
        amazon_title="任意标题",
        movie_title="任意片名",
        match_reason="soft",
        verify_image=fake_verify,
    )
    assert verdict is True
    assert not called  # 图像验证被短路


@pytest.mark.asyncio
async def test_cid_mismatch_blocks(monkeypatch):
    """cid 不一致 → 强警示失败"""
    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: False)

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B081DYPZ13",
        number="SSIS-001",
        amazon_title="同系列标题",
        movie_title="同系列标题",
        match_reason="soft",
        verify_image=None,  # 不应被调用
    )
    assert verdict is False


@pytest.mark.asyncio
async def test_compilation_keyword_veto(monkeypatch):
    """合集词一票否决：cid miss + 标题含 BEST/コンプリート → 阻止"""
    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: None)

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B000TEST00",
        number="SSIS-001",
        amazon_title="エスワン8時間コンプリートBEST",
        movie_title="SSIS-001 的片名",
        match_reason="soft",
        verify_image=None,
    )
    assert verdict is False


@pytest.mark.asyncio
async def test_title_series_match_passes(monkeypatch):
    """cid miss + 标题系列互含 → 通过（零图像请求）"""
    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: None)

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B000TEST00",
        number="MIFD-093",
        amazon_title="女子マネージャーは、僕達の性処理ペット。 046",
        movie_title="女子マネージャーは、僕達の性処理ペット。 001",
        match_reason="soft",
        verify_image=None,
    )
    assert verdict is True


@pytest.mark.asyncio
async def test_title_unrelated_blocks(monkeypatch):
    """cid miss + 标题无关 → 阻止（大概率真错挂）"""
    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: None)

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B000TEST00",
        number="EBOD-081",
        amazon_title="ゆきえ 無垢",
        movie_title="E-BODY 峰なゆか",
        match_reason="soft",
        verify_image=None,
    )
    assert verdict is False


@pytest.mark.asyncio
async def test_fallback_to_image_when_no_title_evidence(monkeypatch):
    """cid miss + 无片名可比 → 图像门兜底（沿用现有验证函数）"""
    monkeypatch.setattr(core_web, "asin_matches_number", lambda asin, number: None)

    async def fake_image(*a, **k):
        return True

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B000TEST00",
        number="TEST-001",
        amazon_title="只有日亚标题",
        movie_title="",  # 无爬虫片名
        match_reason="actor_fallback",
        verify_image=fake_image,
    )
    assert verdict is True  # 图像兜底通过

    # 图像兜底失败 → 整体失败
    async def fake_image_fail(*a, **k):
        return False

    verdict = await core_web.verify_soft_amazon_candidate(
        asin="B000TEST00",
        number="TEST-001",
        amazon_title="只有日亚标题",
        movie_title="",
        match_reason="actor_fallback",
        verify_image=fake_image_fail,
    )
    assert verdict is False
