"""7mmtv 爬虫解析逻辑测试（纯函数，无网络依赖）."""

import asyncio
from importlib import import_module

import pytest
from lxml import etree

mmtv = import_module("mdcx.crawlers.7mmtv")


def _html(body: str) -> etree._Element:
    return etree.fromstring(f"<html><body>{body}</body></html>", etree.HTMLParser())


# ---------- get_title ----------


def test_get_title_multiline_and_number_strip():
    html = _html('<h1 class="fullvideo-title h5 mb-2">200GANA-3327 第一段標題\n第二段標題 2259</h1>')
    assert mmtv.get_title(html, "200GANA-3327") == "第一段標題 第二段標題 2259"


def test_get_title_empty():
    assert mmtv.get_title(_html("<div>x</div>"), "") == ""


def test_get_title_no_web_number_keeps_full():
    html = _html('<h1 class="fullvideo-title">HEYZO 0865 標題</h1>')
    assert mmtv.get_title(html, "") == "HEYZO 0865 標題"


# ---------- get_outline ----------


def test_get_outline_nested_paragraph_and_br():
    html = _html('<div class="video-introduction-images-text"><p>第一行<br/>第二行<br/>第三行</p></div>')
    outline, originalplot = mmtv.get_outline(html)
    assert outline == "第一行\n第二行\n第三行"
    assert originalplot == outline


def test_get_outline_empty():
    outline, originalplot = mmtv.get_outline(_html("<div></div>"))
    assert outline == ""
    assert originalplot == ""


# ---------- get_real_url（搜索结果匹配）----------


def test_get_real_url_matches_exact_number():
    html = _html(
        '<figure class="video-preview"><a href="/zh/chinese_content/46543/HEYZO-0865.html">'
        '<img alt="HEYZO-0865 標題"></a>'
        '<a href="/zh/other/1/SOME-999.html"><img alt="SOME-999 另一個"></a></figure>'
    )
    assert mmtv.get_real_url(html, "HEYZO-0865") == "/zh/chinese_content/46543/HEYZO-0865.html"


def test_get_real_url_fc2_prefix_normalization():
    html = _html(
        '<figure class="video-preview"><a href="/zh/fc2/77/FC2-PPV-1234567.html">'
        '<img alt="FC2-PPV 1234567 素人"></a></figure>'
    )
    assert mmtv.get_real_url(html, "FC2-1234567") == "/zh/fc2/77/FC2-PPV-1234567.html"


def test_get_real_url_no_match_returns_empty():
    html = _html('<figure class="video-preview"><a href="/x.html"><img alt="OTHER-001 標題"></a></figure>')
    assert mmtv.get_real_url(html, "HEYZO-0865") == ""


# ---------- get_number / get_release / get_runtime ----------


def test_get_number_parses_release_and_runtime():
    html = _html(
        '<div class="d-flex mb-4"><span>HEYZO 0865</span><span> : 2016-05-25 </span><span>01:35:00</span></div>'
    )
    number, release, runtime, web_number = mmtv.get_number(html, "HEYZO-0865")
    assert number == "HEYZO 0865"
    assert release == "2016-05-25"
    assert runtime == "95"
    assert web_number == "HEYZO 0865"


def test_get_number_fc2_prefix_normalized():
    html = _html('<div class="d-flex mb-4"><span>FC2-PPV 1234567</span></div>')
    number, release, runtime, _ = mmtv.get_number(html, "FC2-1234567")
    assert number == "FC2-1234567"
    assert release == ""


def test_get_number_falls_back_to_input():
    number, release, runtime, _ = mmtv.get_number(_html("<div></div>"), "HEYZO-0865")
    assert number == "HEYZO-0865"
    assert release == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01:35:00", "95"),
        ("0:55:00", "55"),
        ("35:00", "35"),
        ("35分", "35"),
        ("35min", "35"),
        ("", ""),
        ("無", ""),
    ],
)
def test_get_runtime_variants(raw, expected):
    assert mmtv.get_runtime(raw) == expected


def test_get_year():
    assert mmtv.get_year("2016-05-25") == "2016"
    assert mmtv.get_year("") == ""


# ---------- get_mosaic ----------


@pytest.mark.parametrize(
    ("breadcrumb", "number", "expected"),
    [
        ("首頁 / 無碼AV / HEYZO 0865", "HEYZO-0865", "无码"),
        ("首頁 / 國產影片 / 國產", "MDX-0001", "无码"),
        ("首頁 / 有碼AV / 作品", "SSIS-742", "有码"),
        ("首頁 / 素人AV / 作品", "SIRO-5000", "有码"),
    ],
)
def test_get_mosaic_breadcrumb(breadcrumb, number, expected):
    html = _html(f'<ol class="breadcrumb"><li>{breadcrumb}</li></ol>')
    assert mmtv.get_mosaic(html, number) == expected


def test_get_mosaic_fallback_by_number_type():
    # 面包屑缺失时按番号特征回退：FC2 → 无码；HEYZO 官网无码系列（is_uncensored 判定）
    assert mmtv.get_mosaic(_html("<div></div>"), "FC2-1234567") == "无码"


# ---------- get_cover / get_extrafanart / get_actor / get_tag ----------


def test_get_cover_relative_url_gets_site_prefix():
    html = '<div class="player-cover" ><a><img src="/media/cover/123.jpg"></div>'
    assert mmtv.get_cover(html) == "https://www.7mmtv.sx/media/cover/123.jpg"


def test_get_cover_absolute_url_kept():
    html = '<div class="player-cover" ><a><img src="https://img.example.com/a.jpg">'
    assert mmtv.get_cover(html) == "https://img.example.com/a.jpg"


def test_get_cover_empty():
    assert mmtv.get_cover("<div></div>") == ""


def test_get_extrafanart_lazyload_and_hidden_script():
    html = _html(
        '<span><img class="lazyload" data-src="https://img.example.com/a.jpg"></span>'
        '<div class="fullvideo-xxx"><script language="javascript">'
        'var imgs=["https://img.example.com/b.jpg","https://img.example.com/c.jpeg"];</script></div>'
    )
    assert mmtv.get_extrafanart(html) == [
        "https://img.example.com/a.jpg",
        "https://img.example.com/b.jpg",
        "https://img.example.com/c.jpeg",
    ]


def test_get_extrafanart_empty():
    assert mmtv.get_extrafanart(_html("<div></div>")) == ""


def test_get_actor_parses_and_strips_parenthesis():
    html = _html(
        '<div class="fullvideo-idol"><span><a href="/idol/1">愛澄玲花</a></span>'
        '<span><a href="/idol/2">日高ゆりあ（青山ひより） 菜津子 32歳 デザイナー</a></span></div>'
    )
    assert mmtv.get_actor(html, "标题", "") == "愛澄玲花,日高ゆりあ"


def test_get_actor_fallback_when_no_idol(monkeypatch):
    monkeypatch.setattr(mmtv, "get_extra_info", lambda *a, **k: "热门演员A")
    assert mmtv.get_actor(_html("<div></div>"), "含热门演员A的标题", "") == "热门演员A"


def test_get_tag():
    html = _html('<div class="d-flex flex-wrap categories"><a>單體作品</a><a>巨乳</a></div>')
    assert mmtv.get_tag(html) == "單體作品,巨乳"


# ---------- 爬虫注册与搜索 URL ----------


def test_crawler_registered():
    from mdcx.config.models import Website
    from mdcx.crawlers import get_registered_crawler_sites
    from mdcx.crawlers.base import get_crawler

    values = [s.value for s in get_registered_crawler_sites()]
    assert "7mmtv" in values
    crawler = get_crawler(Website.MMTV)
    assert crawler.base_url_() == "https://www.7mmtv.sx"


def test_rotator_domains_and_custom_url_priority():
    from mdcx.utils.domain_rotate import DomainRotator

    crawler = mmtv.MmtvCrawler(client=None)
    # 默认无自定义 URL：轮询列表 = 两个镜像域名
    assert crawler._rotator.domains == ["https://www.7mmtv.sx", "https://7tv022.com"]

    # 自定义 URL 插队优先；爬虫层的「custom 不参与轮询」由 _get_text_with_rotate 保证
    rotator = DomainRotator(mmtv._7MMTV_DOMAINS, custom_url="https://my.7mmtv.example")
    assert rotator.current == "https://my.7mmtv.example"
    assert rotator.current_is_custom()
    assert rotator.domains[0] == "https://my.7mmtv.example"


def test_get_text_with_rotate_switches_domain():
    """镜像轮询：第一个域名失败自动切 7tv022.com 重试."""

    class FakeClient:
        def __init__(self):
            self.seen_urls: list[str] = []

        async def get_text(self, url, headers=None, cookies=None, **kwargs):
            self.seen_urls.append(url)
            if "7mmtv.sx" in url:
                return None, "连接错误: SSL reset"
            return "<html>ok</html>", ""

    class FakeCtx:
        def debug(self, *a, **k):
            pass

    crawler = mmtv.MmtvCrawler(client=FakeClient())
    html, err = asyncio.run(crawler._get_text_with_rotate(FakeCtx(), "https://www.7mmtv.sx/zh/x.html"))
    assert html == "<html>ok</html>"
    assert err == ""
    assert crawler._rotator.current == "https://7tv022.com"
    assert crawler._rotator.domains == ["https://www.7mmtv.sx", "https://7tv022.com"]


def test_proxy_default_contains_7mmtv_domains():
    from mdcx.config.models import Config

    sites = Config().proxy_hosts_list()
    assert "7mmtv.sx" in sites
    assert "7tv022.com" in sites


@pytest.mark.asyncio
async def test_generate_search_url_normal_and_fc2():
    from dataclasses import replace

    from mdcx.models.model_types import CrawlerInput

    crawler = mmtv.MmtvCrawler(client=None)

    ctx = crawler.new_context(replace(CrawlerInput.empty(), number="HEYZO-0865"))
    url = await crawler._generate_search_url(ctx)
    assert url == (
        "https://www.7mmtv.sx/zh/searchform_search/all/index.html"
        "?search_keyword=HEYZO-0865&search_type=searchall&op=search"
    )

    ctx = crawler.new_context(replace(CrawlerInput.empty(), number="FC2-1234567"))
    url = await crawler._generate_search_url(ctx)
    assert "search_keyword=1234567&" in url
