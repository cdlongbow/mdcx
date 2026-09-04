import json
import re
from typing import override

from ..config.manager import manager
from ..config.models import Website
from ..models.model_types import CrawlerResult
from .base import BaseCrawler, CrawlerData

_API_BASE = "https://r18.dev"

_content_id_prefixes = {
    "abf": ["118"],
    "abp": ["118"],
    "abs": ["118"],
    "abw": ["118"],
    "aky": ["118"],
    "ap": ["", "1"],
    "apak": ["118"],
    "bf": ["118"],
    "bjd": ["118"],
    "bkd": ["118"],
    "blk": ["118"],
    "cawd": ["118"],
    "cnd": ["118"],
    "cre": ["118"],
    "dldss": ["118"],
    "dmow": ["118"],
    "dok": ["118"],
    "ebod": ["118"],
    "eyan": ["118"],
    "fb": ["118"],
    "gbs": ["118"],
    "gvh": ["118"],
    "hnd": ["118"],
    "hunt": ["118"],
    "husr": ["118"],
    "hzn": ["118"],
    "ipx": ["118"],
    "ipvr": ["118"],
    "ism": ["118"],
    "joe": ["118"],
    "jul": ["118"],
    "kawd": ["118"],
    "kire": ["118"],
    "kiss": ["118"],
    "ksb": ["118"],
    "laf": ["118"],
    "lilu": ["118"],
    "lulu": ["118"],
    "mczt": ["118"],
    "md": ["118"],
    "mey": ["118"],
    "mgt": ["118"],
    "midv": ["118"],
    "miim": ["118"],
    "mimk": ["118"],
    "mism": ["118"],
    "mkmp": ["118"],
    "mmgh": ["118"],
    "mmsl": ["118"],
    "mvsd": ["118"],
    "nkk": ["118"],
    "nsps": ["118"],
    "nvh": ["118"],
    "ofje": ["118"],
    "okb": ["118"],
    "onhr": ["118"],
    "pbd": ["118"],
    "pd": ["118"],
    "pgd": ["118"],
    "pkse": ["118"],
    "ppbd": ["118"],
    "pppe": ["118"],
    "pred": ["118"],
    "prtd": ["118"],
    "rbd": ["118"],
    "rbk": ["118"],
    "rctd": ["118"],
    "reys": ["118"],
    "royz": ["118"],
    "sac": ["118"],
    "sdab": ["118"],
    "sdam": ["118"],
    "sdde": ["118"],
    "sdmf": ["118"],
    "sdmua": ["118"],
    "shic": ["118"],
    "shkd": ["118"],
    "siv": ["118"],
    "skhj": ["118"],
    "sma": ["118"],
    "soe": ["118"],
    "sone": ["118"],
    "sqis": ["118"],
    "ssis": ["118"],
    "stars": ["118"],
    "start": ["118"],
    "svis": ["118"],
    "tbf": ["118"],
    "tkt": ["118"],
    "tmn": ["118"],
    "tora": ["118"],
    "tt": ["118"],
    "und": ["118"],
    "vnds": ["118"],
    "vv": ["118"],
    "wanz": ["118"],
    "wss": ["118"],
    "xvsr": ["118"],
    "ymdd": ["118"],
}


def _normalize_id(id_str: str) -> str:
    id_str = id_str.lower().replace("-", "").replace(" ", "")
    m = re.match(r"^([a-z]+)(\d+)$", id_str)
    if not m:
        return id_str
    series, num = m.group(1), m.group(2)
    num_int = int(num)
    return f"{series}{num_int:05d}"


def _generate_content_id_variations(id_str: str) -> list[str]:
    id_str = id_str.lower().replace("-", "").replace(" ", "")
    m = re.match(r"^([a-z]+)(\d+)$", id_str)
    if not m:
        return []
    series, num = m.group(1), m.group(2)
    num_int = int(num)
    padded3 = f"{num_int:03d}"
    padded5 = f"{num_int:05d}"
    prefixes = _content_id_prefixes.get(series, ["", "1"])
    seen: set[str] = set()
    variations: list[str] = []
    for p in prefixes:
        for v in [f"{p}{series}{padded5}", f"{p}{series}{padded3}"]:
            if v not in seen:
                seen.add(v)
                variations.append(v)
    return variations


def _series_number(id_str: str) -> tuple[str, str]:
    id_str = id_str.lower().replace("-", "").replace(" ", "")
    m = re.match(r"^([a-z]+)(\d+)$", id_str)
    if m:
        return m.group(1), m.group(2)
    return "", ""


def _build_aws_cover_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清封面 (thumb/pl.jpg) 候选 URL 列表."""
    from mdcx.crawlers.dmm_direct import build_aws_cover_candidates

    return build_aws_cover_candidates(number)


def _build_aws_poster_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清海报 (poster/ps.jpg) 候选 URL 列表."""
    from mdcx.crawlers.dmm_direct import build_aws_poster_candidates

    return build_aws_poster_candidates(number)


async def _upgrade_dmm_cover(ctx, data: CrawlerData) -> None:
    """尝试将 r18 返回的 DMM 低清图升级为 awsimgsrc 高清 ps/pl.

    r18 的 jacket_full_url 是 pics.dmm.co.jp 低清图，部分系列还是 mono 路径且 cid 未补零
    （如 SSIS-538 -> ssis538pl.jpg），真实 DMM 高清图为 ssis00538（digital 路径）。
    """
    number = data.number if isinstance(data.number, str) else ""
    number = number.strip()
    if not number:
        number = str(ctx.input.number or "").strip()
    if not number:
        return
    from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

    cover, poster = await upgrade_dmm_cover(ctx, number, str(data.thumb or ""), str(data.poster or ""))
    data.thumb = cover
    data.poster = poster


class R18devCrawler(BaseCrawler):
    description = "R18.dev JSON API 直连（仅能有码，免 CF）"
    _last_request_at: float = 0.0

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.R18DEV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.R18DEV, _API_BASE)

    @override
    def _get_headers(self, ctx) -> dict[str, str] | None:
        return {
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            "Referer": "https://r18.dev/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
        }

    @override
    async def _generate_search_url(self, ctx) -> list[str]:
        number = ctx.input.number.strip()
        normalized = _normalize_id(number)
        url = f"{_API_BASE}/videos/vod/movies/detail/-/dvd_id={normalized}/json"
        ctx.debug(f"R18dev 搜索地址: {url} (原始番号: {number})")
        return [url]

    @override
    async def _parse_search_page(self, ctx, html, search_url: str) -> list[str] | None:
        # 输入三态：str（重写 _search 内部路径）、Selector（基类通用探测）、
        # dict（parsel 对纯 JSON 文本的 .get() 结果会直接反序列化）
        if not isinstance(html, str | dict):
            html = html.get()
        try:
            data = html if isinstance(html, dict) else json.loads(html)
        except json.JSONDecodeError:
            return None
        content_id = data.get("content_id") or data.get("dvd_id")
        if not content_id:
            return None
        dvd_id = data.get("dvd_id", "")
        if dvd_id:
            normalized = _normalize_id(ctx.input.number)
            returned = _normalize_id(dvd_id)
            if returned == normalized:
                combined_url = f"{_API_BASE}/videos/vod/movies/detail/-/combined={content_id}/json"
                ctx.debug(f"R18dev 精确匹配: {combined_url}")
                return [combined_url]
        if content_id:
            # content_id 兜底命中也须校验 dvd_id：变体 cid 可能恰好是另一影片的
            # 真实 cid，无校验会张冠李戴返回错误影片元数据（全库审查 C5，
            # dmm_api 同类逻辑有 _match_score 打分，此处对齐防护）
            returned_dvd = _normalize_id(data.get("dvd_id", "") or "")
            if returned_dvd and returned_dvd == _normalize_id(ctx.input.number):
                combined_url = f"{_API_BASE}/videos/vod/movies/detail/-/combined={content_id}/json"
                ctx.debug(f"R18dev content_id 匹配: {combined_url}")
                return [combined_url]
        return None

    @override
    async def _parse_detail_page(self, ctx, html, detail_url: str) -> CrawlerData | None:
        if not isinstance(html, str | dict):
            html = html.get()
        try:
            data = html if isinstance(html, dict) else json.loads(html)
        except json.JSONDecodeError:
            return None
        return self._parse_json(data, ctx)

    def _parse_json(self, data: dict, ctx) -> CrawlerData:
        dvd_id = data.get("dvd_id", "") or ""
        number = dvd_id.upper().replace("-", "")
        m = re.match(r"^([A-Z]+)\d+$", number)
        if m:
            series, num_str = _series_number(dvd_id)
            if series and num_str:
                num_int = int(num_str)
                number = f"{series.upper()}-{num_int:03d}"

        title_ja = data.get("title_ja") or ""
        title_en = data.get("title_en_uncensored") or data.get("title_en") or ""
        title = title_ja or title_en

        actors = [a.get("name_kanji") or a.get("name_romaji", "") for a in data.get("actresses") or []]
        actors = [a for a in actors if a]

        all_actors = list(actors)
        if data.get("actress") and data["actress"] not in actors:
            all_actors.append(data["actress"])

        studio = data.get("maker_name_ja") or data.get("maker_name_en") or ""
        publisher = data.get("label_name_ja") or data.get("label_name_en") or ""
        series = data.get("series_name_ja") or data.get("series_name_en") or data.get("series_name") or ""

        release = data.get("release_date", "") or ""
        runtime = data.get("runtime_mins")
        runtime_str = str(runtime) if runtime is not None else ""

        tags = [c.get("name_ja") or c.get("name_en", "") for c in data.get("categories") or []]
        tags = [t for t in tags if t]

        thumb = data.get("jacket_full_url") or ""
        if not thumb:
            images = data.get("images", {})
            ji = images.get("jacket_image", {})
            thumb = ji.get("large2") or ji.get("large", "")

        extrafanart = []
        for item in data.get("gallery") or []:
            url = item.get("image_full") or ""
            if url:
                extrafanart.append(url)

        trailer = data.get("sample_url") or ""
        if not trailer:
            sample = data.get("sample", {})
            trailer = sample.get("high") or sample.get("low", "")

        directors = []
        for d in data.get("directors") or []:
            name = d.get("name_kanji") or d.get("name_romaji", "")
            if name:
                directors.append(name)

        year = release[:4] if len(release) >= 4 else ""

        content_id = data.get("content_id", "") or ""

        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title_ja or title,
            actors=actors,
            all_actors=all_actors,
            studio=studio,
            publisher=publisher,
            series=series,
            release=release,
            year=year,
            runtime=runtime_str,
            tags=tags,
            thumb=thumb,
            poster=thumb,
            extrafanart=extrafanart,
            trailer=trailer,
            directors=directors,
            external_id=content_id,
        )

    @override
    async def _fetch_search(self, ctx, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        data, error = await self.async_client.get_json(
            url,
            headers=self._get_headers(ctx),
            use_proxy=False,
        )
        if data is None:
            return None, error or "R18dev: 搜索请求失败"
        return json.dumps(data, ensure_ascii=False), ""

    @override
    async def _fetch_detail(self, ctx, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        data, error = await self.async_client.get_json(
            url,
            headers=self._get_headers(ctx),
            use_proxy=False,
        )
        if data is None:
            return None, error or "R18dev: 详情请求失败"
        return json.dumps(data, ensure_ascii=False), ""

    @override
    async def _detail(self, ctx, detail_urls: list[str]) -> CrawlerData | None:
        for detail_url in detail_urls:
            html, error = await self._fetch_detail(ctx, detail_url)
            if html is None:
                ctx.debug(f"R18dev 详情页请求失败: {error=}")
                continue
            try:
                data = json.loads(html)
            except json.JSONDecodeError:
                continue
            scraped_data = self._parse_json(data, ctx)
            if scraped_data:
                await _upgrade_dmm_cover(ctx, scraped_data)
                if not scraped_data.external_id:
                    scraped_data.external_id = detail_url
            return scraped_data

    @override
    async def _search(self, ctx, search_urls: list[str]) -> list[str] | None:
        for search_url in search_urls:
            html, error = await self._fetch_search(ctx, search_url)
            if html is None:
                ctx.debug(f"R18dev dvd_id 搜索失败: {error}")
                continue
            ctx.debug("R18dev dvd_id 搜索成功")
            detail_urls = await self._parse_search_page(ctx, html, search_url)
            if detail_urls:
                return detail_urls

        number = ctx.input.number.strip()
        variations = _generate_content_id_variations(number)
        if not variations:
            ctx.debug("R18dev 无法生成 content_id 变体")
            return None

        ctx.debug(f"R18dev 尝试 {len(variations)} 个 content_id 变体")
        for cid in variations:
            url = f"{_API_BASE}/videos/vod/movies/detail/-/combined={cid}/json"
            html, error = await self._fetch_search(ctx, url)
            if html is None:
                continue
            try:
                data = json.loads(html)
            except json.JSONDecodeError:
                continue
            content_id = data.get("content_id", "")
            if content_id and (data.get("dvd_id") or data.get("title_ja")):
                # 变体命中须 dvd_id 等值校验（防跨影片 cid 碰撞，全库审查 C5）
                returned_dvd = _normalize_id(data.get("dvd_id", "") or "")
                if not returned_dvd or returned_dvd != _normalize_id(number):
                    continue
                combined_url = f"{_API_BASE}/videos/vod/movies/detail/-/combined={content_id}/json"
                ctx.debug(f"R18dev content_id 变体命中: {combined_url}")
                return [combined_url]

        return None

    @override
    async def post_process(self, ctx, res: CrawlerResult) -> CrawlerResult:
        if not res.originaltitle:
            res.originaltitle = res.title
        if res.trailer and res.trailer.startswith("//"):
            res.trailer = "https:" + res.trailer
        return res

    @classmethod
    @override
    def display_name(cls) -> str:
        return "R18.dev"

    @classmethod
    @override
    def supports_custom_url(cls) -> bool:
        return True
