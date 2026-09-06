#!/usr/bin/python
import re
from typing import Any, override

from ..config.manager import manager
from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData, CrawlerException

_JP_ACTOR_CACHE: dict[str, str] = {}


async def _fetch_jp_actor_name(actor_id: str, client: Any) -> str | None:
    """从 xcity.jp 源站抓取演员日文名。"""
    if actor_id in _JP_ACTOR_CACHE:
        return _JP_ACTOR_CACHE[actor_id]
    url = f"https://xcity.jp/idol/detail/{actor_id}/"
    html, error = await client.get_text(url)
    if html is None:
        return None
    m = re.search(r"<title>([^(]+?)(?:\s*\(|無料|\||$)", html)
    if m:
        name = m.group(1).strip()
        _JP_ACTOR_CACHE[actor_id] = name
        return name
    return None


class XcityContext(Context):
    cached_program: dict[str, Any] | None = None


class XcityCrawler(BaseCrawler[XcityContext]):
    description = "Xcity 综合（仅能有码）"
    # xcity.jp 缺 SSNI-647（用户实测），ABF-050 已确认收录
    probe_number = "ABF-050"
    # xcity 镜像域名（主站 + 备用；用户配置 custom_url 时优先使用）
    _domains: list[str] = [
        "https://tc.xcity.jp",
        "https://xcity.jp",
    ]

    @override
    def __init__(self, client, base_url: str = "", browser=None):
        super().__init__(client, base_url=base_url, browser=browser)
        self._init_rotator(self._domains, custom_url=manager.config.get_site_url(Website.XCITY, ""))

    @override
    def new_context(self, input: CrawlerInput) -> XcityContext:
        return XcityContext(input=input)

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.XCITY

    @override
    def _get_headers(self, ctx: Context) -> dict[str, str] | None:
        return {"Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en;q=0.5"}

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.XCITY, "https://tc.xcity.jp")

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        number_no_dash = ctx.input.number.replace("-", "")
        # API 路径（tc 子域）失败时回退 HTML 搜索页（xcity.jp 无 /api/search，只有 /result/）
        return [
            f"{self.base_url}/api/search?q={number_no_dash}",
            f"https://xcity.jp/result/?q={number_no_dash}",
        ]

    @override
    async def _parse_search_page(self, ctx: XcityContext, html: Any, search_url: str) -> list[str] | str | None:
        data = html.get()
        if isinstance(data, dict):
            # tc API JSON 响应
            program_list = (data.get("frontprogramlist") or {}).get("program") or []
            if not program_list:
                ctx.debug("xcity 搜索没有匹配结果")
                return None

            ctx.cached_program = program_list[0]

            program_id = program_list[0].get("id")
            if program_id:
                return [f"{self.base_url}/avod/detail?id={program_id}"]

            ctx.debug("xcity 搜索结果缺少 id")
            return None

        # xcity.jp HTML 回退：/result/?q= 页面解析详情页链接
        detail_links = html.xpath("//a[contains(@href, '/avod/detail/?id=')]/@href").getall()
        if not detail_links:
            ctx.debug("xcity HTML 搜索没有匹配结果")
            return None
        href = detail_links[0]
        detail_url = href if href.startswith("http") else f"https://xcity.jp{href}"
        ctx.debug(f"xcity HTML 搜索命中: {detail_url}")
        return [detail_url]

    def _li_value(self, sel: Any, label: str) -> str:
        """详情页 koumoku 字段值：取 label 所在 li 的全部文本后剥掉字段名。"""
        li = sel.xpath(f"//li[span[@class='koumoku' and normalize-space(text())='{label}']]")
        raw = re.sub(r"\s+", " ", li.xpath("string()").get() or "")
        return raw.replace(label, "", 1).strip()

    def _li_link_text(self, sel: Any, label_contains: str, span_id: str) -> str:
        return (
            sel.xpath(f"//li[contains(span[@class='koumoku'],'{label_contains}')]//span[@id='{span_id}']/text()").get()
            or ""
        ).strip()

    async def _parse_html_detail(self, ctx: XcityContext, html: Any, detail_url: str) -> CrawlerData | None:
        """xcity.jp HTML 备用路径解析（tc API 挂时兜底）。

        title/originaltitle 只能拿到日文原标题（HTML 站无中文翻译）。
        """
        from parsel import Selector

        sel = html if isinstance(html, Selector) else Selector(text=str(html))

        title = (sel.xpath("//title/text()").get() or "").strip()
        title = re.sub(r"\s*\|.*$", "", title).strip()
        if not title:
            raise CrawlerException("数据获取失败: 未获取到title")

        actors = [
            a.strip()
            for a in sel.xpath("//li[span[@class='koumoku' and normalize-space(text())='出演']]//a/text()").getall()
            if a.strip()
        ]

        release = self._li_value(sel, "発売日").replace("/", "-")
        runtime = re.sub(r"\D", "", self._li_value(sel, "収録時間"))
        series_name = self._li_value(sel, "シリーズ")
        maker_name = self._li_link_text(sel, "メーカー", "program_detail_maker_name")
        label_name = self._li_link_text(sel, "メーカー", "program_detail_label_name")
        tags = [g.strip() for g in sel.xpath("//a[@class='genre']/text()").getall() if g.strip()]

        outline = (sel.xpath("//meta[@property='og:description']/@content").get() or "").strip()
        cover = sel.xpath("//meta[@property='og:image']/@content").get() or ""
        front_image = cover.replace("/medium/", "/large/")

        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        back_image, front_image2 = await upgrade_dmm_cover(ctx, ctx.input.number, "", front_image)
        return CrawlerData(
            # 页面里的「メーカー品番」无横杠（如 ABF050），保留输入的规范番号
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=outline,
            originalplot=outline,
            tags=tags,
            release=release,
            year=release[:4] if len(release) >= 4 else "",
            runtime=runtime,
            series=series_name,
            studio=maker_name,
            publisher=label_name,
            thumb=back_image,
            poster=front_image2,
            image_download=False,
            mosaic="有码",
            external_id=detail_url,
        )

    @override
    async def _parse_detail_page(self, ctx: XcityContext, html: Any, detail_url: str) -> CrawlerData | None:
        program = ctx.cached_program
        if not program:
            # HTML 备用路径（xcity.jp /result/ → /avod/detail/?id=）：cached_program 为空
            return await self._parse_html_detail(ctx, html, detail_url)

        title = program.get("title") or ""
        originaltitle = program.get("titleKana") or title
        if not title:
            raise CrawlerException("数据获取失败: 未获取到title")

        actors = []
        for person in program.get("person") or []:
            name = person.get("name")
            actor_id = person.get("id")
            if name and actor_id:
                jp_name = await _fetch_jp_actor_name(actor_id, self.async_client)
                actors.append(jp_name or name)
            elif name:
                actors.append(name)

        genre = program.get("genre") or []

        release = (program.get("releaseDate") or "").replace("/", "-")

        runtime = str(program.get("duration") or "")

        series_name = ""
        series_data = program.get("series")
        if isinstance(series_data, dict):
            series_name = series_data.get("name") or ""

        maker_name = ""
        maker_data = program.get("maker")
        if isinstance(maker_data, dict):
            maker_name = maker_data.get("name") or ""

        label_name = ""
        label_data = program.get("label")
        if isinstance(label_data, dict):
            label_name = label_data.get("name") or ""

        front_image = (program.get("frontPackageImage") or "").replace("/medium/", "/large/")
        back_image = (program.get("backPackageImage") or "").replace("/medium/", "/large/")

        # DMM 高清直链升级（横版+竖版，无码番号内部跳过）
        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        back_image, front_image = await upgrade_dmm_cover(ctx, ctx.input.number, back_image, front_image)
        return CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=originaltitle,
            actors=actors,
            all_actors=actors,
            outline=program.get("synopsis") or "",
            originalplot=program.get("synopsis") or "",
            tags=genre,
            release=release,
            year=release[:4] if len(release) >= 4 else "",
            runtime=runtime,
            series=series_name,
            studio=maker_name,
            publisher=label_name,
            thumb=back_image,
            poster=front_image,
            image_download=False,
            mosaic="有码",
            external_id=detail_url,
        )
