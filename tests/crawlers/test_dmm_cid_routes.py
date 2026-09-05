"""静态路由种子（dmm_cid_routes.json）集成回归测试。

背景：libredmm 全站 23472 页 58.9 万番号↔cid 对归纳为规则 + 白名单，经
安全过滤（仅 digital 路径 + 5 位补零 + 无变体，弃用与生产静态表冲突的
系列——libredmm 同名番号被 mono 老厂牌占据，直接注入会污染高频系列
候选顺序：SSIS-001 首候选会被错排成老厂牌 ssis001）。
路由把静态表盲枚举（_COMMON_PREFIXES 10 连试）变成一步直达，且不再
需要运行时请求 libredmm。

测试在 conftest 的 dummy resources 下运行，种子经 monkeypatch 指向真实文件。
"""

import json
from pathlib import Path

import pytest

from mdcx.crawlers import dmm_direct

SEED_PATH = Path(__file__).resolve().parents[2] / "resources" / "userdata" / "dmm_cid_routes.json"


@pytest.fixture(autouse=True)
def _real_routes(monkeypatch):
    """注入真实种子文件路径并复位路由表，测试后再次复位。"""
    if not SEED_PATH.is_file():
        pytest.skip("种子文件不存在")
    monkeypatch.setattr(dmm_direct, "_routes_seed_path", lambda: SEED_PATH)
    dmm_direct.reset_routes_for_testing()
    yield
    dmm_direct.reset_routes_for_testing()


def test_seed_file_shape():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["version"] == 2
    # 清理 mono pad3 死链后系列数收敛到 ~6976，持续检查不受随意增减的影响
    assert 6000 < len(data["rules"]) < 10000
    assert isinstance(data["rules"], dict) and len(data["rules"]) > 6000
    assert isinstance(data["whitelist"], dict) and len(data["whitelist"]) > 10000
    # v2 规则条目结构: mode + combos
    letters, entry = next(iter(data["rules"].items()))
    assert isinstance(letters, str) and letters.isupper()
    assert entry["mode"] in ("first", "append")
    combo = entry["combos"][0]
    assert {"p", "s", "pads", "paths"} <= set(combo.keys())
    assert all(isinstance(p, int) and p > 0 for p in combo["pads"])
    assert all(str(p).startswith(("digital", "mono")) for p in combo["paths"])


def test_seed_high_frequency_series_use_append_mode():
    """高频主流系列以 append 模式保留——仅在 mono+pad3 之外（有 digital 或 pad≥4）。

    注：libredmm 实测后发现如 SSIS/SONE/JUQ 等活跃厂牌的 mono pad3 组合
    全部是占位图死链，这类已整条从路由表清除。keep 的是真正含 digital 或
    混合 pad≥4 的有效条目，append 模式只对它们成立。
    """
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for series in ("IPX", "MIDV", "CAWD", "PRED", "SW", "WANZ", "EBOD", "GVG"):
        if series in data["rules"]:
            assert data["rules"][series]["mode"] == "append"
    for number in ("IPX-399", "SONE-006", "ABF-171"):
        assert number not in data["whitelist"], f"{number} 不应留在白名单中"


def test_append_mode_legacy_three_digit_fallback():
    """append 模式兜底：GVG 老片真实 cid 是 mono 3 位 13gvg564，静态表只给 5 位。"""
    cids = dmm_direct.generate_cid_candidates("GVG-564")
    assert cids[0] == "13gvg00564"  # 静态表保序首位
    assert "13gvg564" in cids  # 路由 append 兜底出老片 3 位形态
    # 老片 mono 候选应有 pics.dmm.co.jp 低清图床 URL
    urls = [url for _, url in dmm_direct.generate_image_candidates("GVG-564")]
    assert any(url.startswith("https://pics.dmm.co.jp/mono/movie/adult/13gvg564/") for url in urls)


def test_ssis_pure_pad3_mono_combos_are_skipped():
    """纯 pad≤3 的 mono 组合（老片 CID 空间）不应为新片产生 mono 候选。

    议题反馈：SSIS-742 这类新片被反复尝试 mono 路径（77ssis742 / 88ssis742
    等），全部 404 + 「图片已被网站删除」拖慢刮削。根因：libredmm 归纳把
    老片的 mono 组合错误地关联到了新片系列。这些组合对新片无效，一律跳过。

    对比：GVG-564 的 pads 是混合形态 [3, 5]（数字资源确实存在于 mono 3 位），
    保留不动，test_append_mode_legacy_three_digit_fallback 锁定。
    """
    urls = [url for _, url in dmm_direct.generate_image_candidates("SSIS-742")]
    assert not any("mono/movie/adult" in url for url in urls), (
        "SSIS-742 不应生成 mono 路径候选（其路由条目全是 pad=3 的老片形态）"
    )


def test_route_hit_step_reach():
    """路由系列一步直达：AAJB 真实 cid 是基线盲枚举第 4 位，路由后首候选命中。"""
    cids = dmm_direct.generate_cid_candidates("AAJB-100")
    assert cids[0] == "h_308aajb00100"


def test_whitelist_hit_returns_exact_cid():
    """白名单特例番号：直接返回唯一真实 cid，不落规则枚举。"""
    cids = dmm_direct.generate_cid_candidates("13ID-003")
    assert cids == ["h_113id00003"]


def test_whitelist_image_candidates_use_recorded_path():
    """白名单 digital 路径的图应走 awsimgsrc 高清 CDN。"""
    candidates = dmm_direct.generate_image_candidates("13ID-003")
    urls = [url for _, url in candidates]
    assert urls[0] == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/h_113id00003/h_113id00003ps.jpg"
    assert any("pl.jpg" in u for u in urls)


def test_high_frequency_series_first_candidate_unchanged():
    """高频系列首候选不被路由污染（安全过滤回归保护）。"""
    expected = {
        "SSIS-001": "ssis00001",
        "IPX-535": "ipx00535",
        "SONE-833": "sone00833",
        "MIDV-100": "midv00100",
        "CAWD-500": "cawd00500",
        "ABF-042": "436abf00042",
        "SW-123": "1sw00123",
        "WANZ-100": "3wanz00100",
    }
    for number, first in expected.items():
        cids = dmm_direct.generate_cid_candidates(number)
        assert cids[0] == first, f"{number}: 首候选 {cids[0]} != {first}"


def test_static_candidates_still_work_for_unrouted_series():
    """未收录系列的既有静态表行为不变（回归保护）。"""
    cids = dmm_direct.generate_cid_candidates("SSIS-001")
    assert cids[0] == "ssis00001"


def test_invalid_number_returns_empty():
    assert dmm_direct.generate_cid_candidates("") == []
    assert dmm_direct.generate_cid_candidates("12345") == []


def test_routes_load_failure_degrades_silently(monkeypatch, tmp_path):
    """种子损坏时静默降级为空表，不影响既有候选链。"""
    bad = tmp_path / "bad_routes.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(dmm_direct, "_routes_seed_path", lambda: bad)
    dmm_direct.reset_routes_for_testing()
    try:
        cids = dmm_direct.generate_cid_candidates("SSIS-001")
        assert cids[0] == "ssis00001"
    finally:
        dmm_direct.reset_routes_for_testing()
