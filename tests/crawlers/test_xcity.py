"""xcity.jp HTML 备用路径解析回归测试（议题 #77）。

背景：tc.xcity.jp 是 JSON API（受 Accept-Language 控制语言），xcity.jp 是 HTML 展示站，
没有 /api/search，但有 /result/?q= + /avod/detail/?id= 完整 HTML 刮削链路。
tc API 挂掉时爬虫应通过 HTML 路径出数据。fixture 为两页真实抓取样本（ABF-050）。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.xcity import XcityContext, XcityCrawler
from mdcx.models.model_types import CrawlerInput

DATA_DIR = Path(__file__).resolve().parent / "data" / "xcity"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _make_crawler():
    return XcityCrawler(client=SimpleNamespace(), base_url="https://tc.xcity.jp")


def _make_input(number: str) -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url="",
        file_path=None,
        mosaic="",
        number=number,
        short_number="",
        language=Language.UNDEFINED,
        org_language=Language.UNDEFINED,
    )


def test_generate_search_url_apis_then_html():
    crawler = _make_crawler()
    ctx = XcityContext(input=_make_input("ABF-050"))
    import asyncio

    urls = asyncio.run(crawler._generate_search_url(ctx))
    assert urls[0] == "https://tc.xcity.jp/api/search?q=ABF050"
    assert urls[1] == "https://xcity.jp/result/?q=ABF050"


def test_parse_html_search_finds_detail_link():
    from parsel import Selector

    crawler = _make_crawler()
    ctx = XcityContext(input=_make_input("ABF-050"))
    html = (DATA_DIR / "abf050_search.html").read_text(encoding="utf-8")
    import asyncio

    result = asyncio.run(crawler._parse_search_page(ctx, Selector(text=html), "https://xcity.jp/result/?q=ABF050"))
    assert result == ["https://xcity.jp/avod/detail/?id=187796"]
    assert ctx.cached_program is None


@pytest.mark.anyio
async def test_parse_html_detail_extracts_all_fields():
    from parsel import Selector

    crawler = _make_crawler()
    ctx = XcityContext(input=_make_input("ABF-050"))
    html = (DATA_DIR / "abf050_detail.html").read_text(encoding="utf-8")
    data = await crawler._parse_html_detail(ctx, Selector(text=html), "https://xcity.jp/avod/detail/?id=187796")

    assert data is not None
    assert data.number == "ABF-050"  # 输入番号优先（页面记载为无横杠 ABF050）
    assert "美ノ嶋めぐり" in data.title
    assert data.originaltitle == data.title
    assert "美ノ嶋めぐり" in data.actors
    assert data.release == "2023-12-08"
    assert data.runtime == "214"
    assert data.series == "完全主観×鬼イカせ"
    assert data.studio == "プレステージ"
    assert "ABSOLUTELY FANTASIA" in data.publisher
    assert "人気AV女優" in data.tags
    assert "f_1715304859_1.jpg" in data.poster
    assert "/large/" in data.poster
    assert data.outline  # og:description 有内容
    assert data.mosaic == "有码"
    assert data.external_id == "https://xcity.jp/avod/detail/?id=187796"
