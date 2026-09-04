#!/usr/bin/env python3
import re
from datetime import date
from typing import override

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..core.mosaic import is_plain_uncensored_mosaic
from .base import BaseCrawler, Context, CrawlerData, CrawlerException
from .base.base_types import split_csv

# javbus 镜像域名列表（主站 + 备用，按可用性排列；用户配置 custom_url 时优先使用）
# 2026-08-25 实测：busjav.bond/seejav.cyou/buscdn.bond/javbus.bond SSL 连接失效已移除；
# busdmm.bond 持续 CF 挑战未纳入。
_JAVBUS_DOMAINS = [
    "https://www.dmmsee.cyou",
    "https://www.javsee.cyou",
    "https://www.cdnbus.bond",
    "https://www.cdnbus.cyou",
    "https://www.fanbus.bond",
    "https://www.dmmbus.bond",
    "https://www.javbus.com",
]


def get_title(html):
    result = html.xpath("//h3/text()")
    return result[0].strip() if result else ""


def getWebNumber(html, number):
    result = html.xpath('//span[@class="header"][contains(text(), "識別碼:")]/../span[2]/text()')
    return result[0] if result else number


def getActor(html):
    try:
        result = html.xpath('//div[@class="star-name"]/a/text()')
        return ",".join(result).strip() if result else ""
    except Exception:
        return ""


def getCover(html, url):  # 获取封面链接
    result = html.xpath('//a[@class="bigImage"]/@href')
    return (url + result[0] if "http" not in result[0] else result[0]) if result else ""


def get_poster_url(cover_url):  # 获取小封面链接
    if "/pics/" in cover_url:
        return cover_url.replace("/cover/", "/thumb/").replace("_b.jpg", ".jpg")
    if "/imgs/" in cover_url:
        return cover_url.replace("/cover/", "/thumbs/").replace("_b.jpg", ".jpg")
    return ""


def getRelease(html):  # 获取发行日期
    result = html.xpath('//span[@class="header"][contains(text(), "發行日期:")]/../text()')
    return result[0].strip() if result else ""


def getValidRelease(release):
    release = release.replace("/", "-").replace(".", "-").strip()
    if not release:
        return ""
    if not (match := re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", release)):
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def getYear(release):
    release = getValidRelease(release)
    return release[:4] if release else ""


def getMosaic(html):
    select_tab = (
        ",".join(html.xpath('//li[@class="active"]/a/text()')) if html.xpath('//li[@class="active"]/a/text()') else ""
    )
    return "有码" if "有碼" in select_tab else "无码"


def getRuntime(html):
    result = html.xpath('//span[@class="header"][contains(text(), "長度:")]/../text()')
    if result:
        result = re.findall(r"\d+", result[0].strip())
        return result[0] if result else ""
    return ""


def getStudio(html):
    result = html.xpath('//a[contains(@href, "/studio/")]/text()')
    return result[0].strip() if result else ""


def getPublisher(html, studio):  # 获取发行商
    result = html.xpath('//a[contains(@href, "/label/")]/text()')
    return result[0].strip() if result else studio


def getDirector(html):  # 获取导演
    result = html.xpath('//a[contains(@href, "/director/")]/text()')
    return result[0].strip() if result else ""


def getSeries(html):
    result = html.xpath('//a[contains(@href, "/series/")]/text()')
    return result[0].strip() if result else ""


def getExtraFanart(html, url):  # 获取封面链接
    result = html.xpath("//div[@id='sample-waterfall']/a/@href")
    if not result:
        return []
    new_list = []
    for each in result:
        if "http" not in each:
            each = url + each
        new_list.append(each)
    return new_list


def getTag(html):  # 获取标签
    result = html.xpath('//span[@class="genre"]/label/a[contains(@href, "/genre/")]/text()')
    return ",".join(result).strip() if result else ""


def get_actress_video_list(html: etree._Element, base_url: str) -> dict:
    """
    从JAVBus演员详情页解析作品列表

    Args:
        html: 已解析的HTML元素
        base_url: JAVBus基础URL

    Returns:
        包含视频信息的字典，格式为：
        {
            "videos": [
                {
                    "number": "番号",
                    "title": "标题",
                    "date": "发行日期",
                    "url": "详情页URL"
                },
                ...
            ],
            "has_next": True/False
        }
    """
    videos_result: list[dict] = []
    result: dict[str, list[dict] | bool] = {"videos": videos_result, "has_next": False}

    # 基于JAVBus搜索页面的模式，推测演员详情页可能使用类似结构
    # 可能的XPath模式（按优先级排序）
    video_xpath_patterns = [
        # 模式1：类似搜索结果页的movie-box
        "//a[@class='movie-box']",
        # 模式2：演员详情页特有的容器
        "//div[@class='photo-frame']/a",
        # 模式3：通用视频框
        "//div[contains(@class, 'item-box')]/a",
        # 模式4：参考JAVDB的box类
        "//a[@class='box']",
        # 模式5：匹配特定番号模式的链接（备选）
        "//a[contains(@href, '/SSIS-')]",
        # 模式6：所有相对链接（最后备选）
        "//a[starts-with(@href, '/')]",
    ]

    videos = []
    for pattern in video_xpath_patterns:
        video_elements = html.xpath(pattern)
        if video_elements:
            videos = video_elements
            break

    if not videos:
        return result

    for video in videos:
        try:
            # 尝试多种XPath模式提取视频信息
            video_data = _extract_actress_video_info(video, base_url)
            if video_data and video_data.get("number"):
                videos_result.append(video_data)
        except Exception:
            # 单个视频解析失败不影响其他视频
            continue

    # 检查是否有下一页
    next_page = html.xpath("//a[@class='next' or contains(text(), '下一页')]")
    result["has_next"] = len(next_page) > 0

    return result


def _extract_actress_video_info(video: etree._Element, base_url: str) -> dict:
    """
    从单个视频元素中提取信息

    Args:
        video: 视频元素
        base_url: 基础URL

    Returns:
        视频信息字典
    """
    # 获取视频URL
    href = video.get("href", "")
    if not href:
        return {}

    # 补全URL
    if not href.startswith("http"):
        url = base_url + href if href.startswith("/") else base_url + "/" + href
    else:
        url = href

    # 优先从URL提取番号（最可靠）
    number = None
    number_match = re.search(r"/([A-Z]{2,6}-?\d{3,})", url, re.IGNORECASE)
    if number_match:
        number = number_match.group(1).replace("-", "")

    # 如果URL中没有找到，尝试从HTML元素提取
    if not number:
        number_patterns = [
            ".//div[@class='photo-info']/span/text()",
            ".//div[contains(@class, 'video-number')]/text()",
            ".//h3/text()",
            ".//date/text()",  # 最后才尝试date标签
            ".//span[@class='date']/text()",
        ]

        for pattern in number_patterns:
            number_elements = video.xpath(pattern)
            if number_elements:
                number = str(number_elements[0]).strip()
                if number:
                    break

    # 尝试提取标题
    title = ""
    title_patterns = [
        ".//div[@class='photo-info']/text()",
        ".//h3/text()",
        ".//div[contains(@class, 'title')]/text()",
        ".//span[@class='title']/text()",
    ]

    for pattern in title_patterns:
        title_elements = video.xpath(pattern)
        if title_elements:
            title = str(title_elements[0]).strip()
            if title:
                break

    # 尝试提取日期
    date_str = ""
    date_patterns = [
        ".//div[@class='info']/date/text()",
        ".//div[contains(@class, 'meta')]/text()",
        ".//span[@class='date']/text()",
    ]

    for pattern in date_patterns:
        date_elements = video.xpath(pattern)
        if date_elements:
            date_str = str(date_elements[0]).strip()
            if date_str:
                break

    return {"number": number, "title": title, "date": date_str, "url": url}


def get_actress_list(html: etree._Element, base_url: str) -> list:
    """
    从JAVBus演员列表页解析演员信息

    Args:
        html: 已解析的HTML元素
        base_url: JAVBus基础URL

    Returns:
        演员信息列表，格式为：
        [
            {
                "name": "演员姓名",
                "url": "演员详情页URL",
                "id": "演员ID"
            },
            ...
        ]
    """
    actresses = []

    # 尝试多种XPath模式提取演员列表
    actress_patterns = [
        "//a[@class='actress-item']",
        "//div[@class='actress-box']/a",
        "//div[contains(@class, 'actress')]/a",
        "//div[@class='photo-frame']/a",
    ]

    actress_elements = []
    for pattern in actress_patterns:
        elements = html.xpath(pattern)
        if elements:
            actress_elements = elements
            break

    for actress in actress_elements:
        try:
            href = actress.get("href", "")
            if not href:
                continue

            # 补全URL
            if not href.startswith("http"):
                url = base_url + href if href.startswith("/") else base_url + "/" + href
            else:
                url = href

            # 提取演员ID
            id_match = re.search(r"/actresses/(\d+)", url)
            actor_id = id_match.group(1) if id_match else ""

            # 提取演员姓名
            name_patterns = [
                ".//div[@class='actress-name']/text()",
                ".//div[@class='name']/text()",
                ".//h3/text()",
                ".//span[@class='name']/text()",
                ".//text()",  # 最后尝试所有文本
            ]

            name = ""
            for pattern in name_patterns:
                name_elements = actress.xpath(pattern)
                if name_elements:
                    name = str(name_elements[0]).strip()
                    if name:
                        break

            if name and actor_id:
                actresses.append({"name": name, "url": url, "id": actor_id})
        except Exception:
            continue

    return actresses


def _should_skip_dmm_upgrade(number: str) -> bool:
    """DMM 是有码源，跳过明显无码番号，避免无效候选请求."""
    from mdcx.crawlers.dmm_direct import is_uncensored_number

    return is_uncensored_number(number)


def _build_aws_cover_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清封面 (thumb/pl.jpg) 候选 URL 列表."""
    from mdcx.crawlers.dmm_direct import build_aws_cover_candidates

    return build_aws_cover_candidates(number)


def _build_aws_poster_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清海报 (poster/ps.jpg) 候选 URL 列表."""
    from mdcx.crawlers.dmm_direct import build_aws_poster_candidates

    return build_aws_poster_candidates(number)


async def _upgrade_dmm_cover(ctx, number: str, cover_url: str, poster_url: str) -> tuple[str, str]:
    """尝试将 javbus 低清图升级为 DMM 高清 ps/pl，返回 (cover, poster)."""
    from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

    return await upgrade_dmm_cover(ctx, number, cover_url, poster_url)


def is_match(each_url: str, number: str) -> bool:
    """搜索结果 href 与番号匹配判定。

    两侧归一对齐：站侧 href 形如 /fc2-ppv-123456（剥横杠/PPV 后 /FC2123456），
    FC2 番号侧同样剥 "PPV"（FC2-123456 → /FC2123456）——否则恒不匹配，
    搜索兜底对 FC2 番号必然报"未匹配到番号"（全库审查 A5）。
    """

    def _normalize(value: str, strip_ppv: bool) -> str:
        upper = value.upper().replace("-", "")
        if strip_ppv and upper.lstrip("/").startswith("FC2"):
            upper = upper.replace("PPV", "", 1)
        return upper

    each_upper = _normalize(each_url, strip_ppv=True)
    normalized = _normalize(number, strip_ppv=True)
    number_1 = "/" + normalized
    number_2 = number_1 + "_"
    return each_upper.endswith(number_1) or number_2 in each_upper


async def get_real_url(client, ctx: Context, number, url_type, javbus_url, headers):  # 获取详情页链接
    # 搜索走镜像轮换: 优先当前 javbus_url, 失败/未命中时依次尝试其他镜像
    if url_type == "us":  # 欧美
        base_candidates = ["https://www.javbus.hair", javbus_url]
    else:
        base_candidates = [javbus_url]

    for base in base_candidates:
        if url_type == "us":
            url_search = base + "/search/" + number
        elif url_type == "censored":  # 有码
            url_search = base + "/search/" + number + "&type=&parent=ce"
        else:  # 无码
            url_search = base + "/uncensored/search/" + number + "&type=0&parent=uc"

        ctx.debug(f"搜索地址: {url_search}")
        ctx.debug_info.search_urls.append(url_search)
        html_search, error = await client.get_text(url_search, headers=headers)
        if html_search is None:
            ctx.debug(f"搜索请求失败: {error}, 尝试下一镜像")
            continue
        if "lostpasswd" in html_search:
            raise CrawlerException("Cookie 无效！请重新填写 Cookie 或更新节点！")

        html = etree.fromstring(html_search, etree.HTMLParser())
        url_list = html.xpath("//a[@class='movie-box']/@href")
        for each in url_list:
            if is_match(each, number):
                ctx.debug(f"番号地址: {each}")
                # 搜索结果 href 可能是根相对路径（如 /SSIS-538），直接请求会因 host 为空而失败，需补全为绝对 URL
                if each.startswith("/"):
                    each = base + each
                return each
        ctx.debug(f"镜像 {base} 未匹配到番号, 尝试下一镜像")
    raise CrawlerException("搜索结果: 未匹配到番号！")


class JavbusCrawler(BaseCrawler):
    description = "有码/无码分类搜索，12 镜像轮询（综合：有码+无码）"
    _domains: list[str] = _JAVBUS_DOMAINS

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVBUS

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVBUS, _JAVBUS_DOMAINS[0])

    @override
    def __init__(self, client, base_url: str = "", browser=None):
        super().__init__(client, base_url=base_url, browser=browser)
        self._init_rotator(self._domains, custom_url=manager.config.get_site_url(Website.JAVBUS, ""))

    @override
    async def _run(self, ctx: Context):
        number = ctx.input.number
        mosaic = ctx.input.mosaic
        real_url = ctx.input.appoint_url
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
            "cookie": manager.config.javbus,
        }
        image_download = False

        if not real_url:
            if "." in number or re.search(r"[-_]\d{2}[-_]\d{2}[-_]\d{2}", number):
                number = number.replace("-", ".").replace("_", ".")
                real_url = await get_real_url(self.async_client, ctx, number, "us", self.base_url, headers)
            else:
                real_url = self.base_url + "/" + number
                if number.upper().startswith(("CWP", "LAF")):
                    temp_number = number.replace("-0", "-")
                    if temp_number[-2] == "-":
                        temp_number = temp_number.replace("-", "-0")
                    real_url = self.base_url + "/" + temp_number

        ctx.debug(f"番号地址: {real_url}")
        htmlcode, error = await self._get_text_with_rotate(ctx, real_url, headers)
        if htmlcode is None:
            if "404" not in str(error) or "." in number:
                raise CrawlerException(f"网络请求错误: {error}")
            if is_plain_uncensored_mosaic(mosaic):
                real_url = await get_real_url(self.async_client, ctx, number, "uncensored", self.base_url, headers)
            else:
                real_url = await get_real_url(self.async_client, ctx, number, "censored", self.base_url, headers)
            htmlcode, error = await self._get_text_with_rotate(ctx, real_url, headers)
            if htmlcode is None:
                raise CrawlerException("未匹配到番号！")
        if "lostpasswd" in htmlcode:
            raise CrawlerException("Cookie 无效！请重新填写 Cookie 或更新节点！")

        ctx.debug_info.detail_urls = [real_url]
        html_info = etree.fromstring(htmlcode, etree.HTMLParser())
        title = get_title(html_info)
        if not title:
            raise CrawlerException("数据获取失败: 未获取到title")

        number = getWebNumber(html_info, number)
        title = title.replace(number, "").strip()
        actor = getActor(html_info)
        cover_url = getCover(html_info, self.base_url)
        poster_url = get_poster_url(cover_url)
        release_raw = getRelease(html_info)
        release = getValidRelease(release_raw)
        if release_raw and not release:
            ctx.debug(f"发行日期无效，已忽略: {release_raw}")
        tag = getTag(html_info)
        mosaic = getMosaic(html_info)
        if is_plain_uncensored_mosaic(mosaic):
            if (
                "_" in number
                and poster_url
                or "HEYZO" in number
                and len(poster_url.replace(self.base_url + "/imgs/thumbs/", "")) == 7
            ):
                image_download = True
            else:
                poster_url = ""
        studio = getStudio(html_info)
        extrafanart = getExtraFanart(html_info, self.base_url)
        if "KMHRS" in number:
            image_download = True
            if extrafanart:
                poster_url = extrafanart[0]

        cover_url, poster_url = await _upgrade_dmm_cover(ctx, number, cover_url, poster_url)

        data = CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            outline="",
            originalplot="",
            tags=split_csv(tag),
            release=release,
            year=getYear(release),
            runtime=getRuntime(html_info),
            score="",
            series=getSeries(html_info),
            directors=split_csv(getDirector(html_info)),
            studio=studio,
            publisher=getPublisher(html_info, studio),
            thumb=cover_url,
            poster=poster_url,
            extrafanart=extrafanart,
            trailer="",
            image_download=image_download,
            mosaic=mosaic,
            external_id=real_url,
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
