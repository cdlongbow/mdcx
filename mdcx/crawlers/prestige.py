#!/usr/bin/env python3

from typing import override

from ..config.models import Website
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year


def get_actor(page_data):
    actor_new_list = []
    for each in page_data.get("actress", []) or []:
        name = each.get("name", "") if isinstance(each, dict) else ""
        if name:
            actor_new_list.append(name.replace(" ", ""))
    return actor_new_list


def get_extrafanart(page_data):
    result = []
    for each in page_data.get("media", []) or []:
        path = each.get("path", "") if isinstance(each, dict) else ""
        if path:
            result.append("https://www.prestige-av.com/api/media/" + path)
    return result


def get_tag(page_data):
    new_list = []
    for each in page_data.get("genre", []) or []:
        name = each.get("name", "") if isinstance(each, dict) else ""
        if name:
            new_list.append(name)
    return new_list


def get_real_url(html_search, number):
    # .get() 链式取值：API 200 但结构漂移（空结果/错误对象/字段缺失）时
    # 返回 "" 走既有"未匹配到番号"分支，而非裸 KeyError 冒泡成整站失败
    # 且无法诊断（全库审查 C2）
    result = (html_search or {}).get("hits", {}).get("hits", []) or []
    for each in result:
        source = each.get("_source", {}) if isinstance(each, dict) else {}
        product_uuid = source.get("productUuid", "")
        delivery_item_id = source.get("deliveryItemId", "")
        if delivery_item_id.endswith(number.upper()):
            return "https://www.prestige-av.com/api/product/" + product_uuid
    return ""


def get_media_path(page_data, key):
    try:
        path = page_data[key]["path"]
        if path:
            media_url = "https://www.prestige-av.com/api/media/" + path
            return "" if "noimage" in media_url else media_url
    except Exception:
        return ""
    return ""


class PrestigeCrawler(BaseCrawler):
    description = "Prestige 官网 JSON API（仅能有码+素人）"
    probe_number = "ABW-130"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.PRESTIGE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.prestige-av.com"

    @override
    async def _run(self, ctx: Context):
        real_url = ctx.input.appoint_url.replace("goods", "api/product")
        if not real_url:
            search_url = (
                f"{self.base_url}/api/search?isEnabledQuery=true&searchText={ctx.input.number}"
                "&isEnableAggregation=false&release=false&reservation=false&soldOut=false"
                "&from=0&aggregationTermsSize=0&size=20"
            )
            ctx.debug(f"搜索地址: {search_url}")
            ctx.debug_info.search_urls = [search_url]
            html_search, error = await self.async_client.get_json(search_url)
            if html_search is None:
                raise CrawlerException(f"网络请求错误: {error}")
            real_url = get_real_url(html_search, ctx.input.number)
            if not real_url:
                raise CrawlerException("搜索结果: 未匹配到番号！")

        detail_url = real_url.replace("api/product", "goods")
        ctx.debug(f"番号地址: {detail_url}")
        ctx.debug_info.detail_urls = [detail_url]
        page_data, error = await self.async_client.get_json(real_url)
        if page_data is None:
            raise CrawlerException(f"网络请求错误: {error}")

        title = page_data.get("title", "").replace("【配信専用】", "")
        if not title:
            raise CrawlerException("数据获取失败: 未获取到 title！")
        release = ""
        try:
            release = page_data["sku"][0]["salesStartAt"][:10]
        except Exception:
            pass
        try:
            director = page_data["directors"][0]["name"]
        except Exception:
            director = ""
        try:
            series = page_data["series"]["name"]
        except Exception:
            series = ""
        try:
            studio = page_data["maker"]["name"]
        except Exception:
            studio = ""
        try:
            publisher = page_data["label"]["name"]
        except Exception:
            publisher = ""
        try:
            trailer = "https://www.prestige-av.com/api/media/" + page_data["movie"]["path"]
        except Exception:
            trailer = ""

        data = CrawlerData(
            number=ctx.input.number,
            title=title,
            originaltitle=title,
            actors=get_actor(page_data),
            outline=page_data.get("body", ""),
            originalplot=page_data.get("body", ""),
            tags=get_tag(page_data),
            release=release,
            year=get_year(release),
            runtime=str(page_data.get("playTime", "")),
            score="",
            series=series,
            directors=[director] if director else [],
            studio=studio,
            publisher=publisher,
            thumb=get_media_path(page_data, "packageImage"),
            poster=get_media_path(page_data, "thumbnail"),
            extrafanart=get_extrafanart(page_data),
            trailer=trailer,
            image_download=True,
            mosaic="有码",
            external_id=detail_url,
            wanted="",
        )
        result = data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
