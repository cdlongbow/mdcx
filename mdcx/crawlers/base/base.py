import time
import traceback
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Never
from urllib.parse import urlparse

from parsel import Selector

from mdcx.config.models import Website
from mdcx.models.model_types import CrawlerInput, CrawlerResponse, CrawlerResult
from mdcx.utils.domain_rotate import DomainRotator

from .base_types import Context, CrawlerData, CrawlerException

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class GenericBaseCrawler[T: Context = Context](ABC):
    """
    爬虫基类. 所有具体爬虫均应继承此类并实现其抽象方法.

    Crawler 实例的生命周期是一次刮削任务, 即刮削一批文件. 此次任务内对同一网站的请求将使用同一实例.
    所有与单次爬取相关的数据均应存储在 `Context` 中, 可在所有方法中通过 `ctx` 参数访问.

    `Context` 是默认类型, 必要时可实现子类并通过泛型参数 T 指定.

    由于爬取逻辑因网站而异, 在最极端情况下可以重写 `_run` 方法以完全自定义爬取流程.

    子类定义后会自动注册到 crawler_registry, 无需手动调用 register_crawler().
    """

    # 站点镜像域名列表（可选）。声明后请求失败（连接/SSL/超时等）会自动切到下一域名重试。
    # 留空表示不轮询。子类可调用 _init_rotator() 用 custom_url 初始化。
    _domains: list[str] = []

    # 站点定位说明（供 UI 列表 tooltip 展示）。如"免 CF 通道"、"综合站（有码+无码）"、
    # "仅覆盖本厂作品"等。留空则不显示说明。
    description: str = ""

    # 网络检测用的探针番号。默认用全局 SCRAPE_PROBE_NUMBER；
    # 站点有收录类型限制时（如欧美/无码站搜不到有码探针番号），子类可覆盖为适用的番号。
    probe_number: str = ""

    @classmethod
    def known_hosts(cls) -> frozenset[str]:
        """该站点已知的全部请求域名（默认主域 + 镜像 + 用户自定义 URL），供代理路由按站点归属判断。

        议题 #83：「走代理网站」下拉框按 crawler 站点值（如 missav）选择，但实际请求按
        host 路由，站点值→域名的映射只来自 WEB_DIC + 六个 TLD 兜底，missav.ai /
        7tv022.com / madou.club / mywife.cc 等实际域名全部失配，UI 选了代理仍直连。
        权威数据源就在爬虫自身声明里：base_url_()（含用户自定义 URL）与 _domains 镜像。

        返回小写 host，统一去 `www.` 前缀并存两形态（is_proxy_host 的子域后缀匹配
        依赖不带 www 的形态）。子类若有额外静态镜像或运行时学习的域名，override 补充。
        """
        hosts: set[str] = set()
        urls: list[str] = [*cls._domains]
        try:
            base = cls.base_url_()
        except Exception:
            base = ""
        if base:
            urls.append(base)
        for url in urls:
            host = urlparse(str(url)).netloc.lower().split(":", 1)[0]
            if host:
                hosts.add(host)
                if host.startswith("www."):
                    hosts.add(host[4:])
        return frozenset(hosts)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        try:
            site = cls.site()
            if site is not None and not getattr(cls, "_skip_auto_register", False):
                crawler_registry[site] = cls  # type: ignore[assignment]
        except (TypeError, NotImplementedError):
            pass

    def __init__(self, client: "AsyncWebClient", base_url: str = "", browser=None):
        """
        初始化爬虫实例.

        Args:
            client (AsyncWebClient): 异步 HTTP 客户端, 用于发送请求.
            base_url (str, optional): 基础 URL, 用于支持自定义 URL. 不提供则使用默认值.
            browser (_type_, optional): 保留的兼容参数, 当前主流程不再使用浏览器请求.
        """
        self.async_client = client
        self.base_url: str = base_url or self.base_url_()
        self.browser = browser

    def _init_rotator(self, domains: list[str], custom_url: str) -> None:
        """初始化镜像域名轮询器（含用户自定义 URL 优先）。"""
        self._rotator = DomainRotator(domains, custom_url=custom_url)

    async def _get_text_with_rotate(
        self,
        ctx: T,
        url: str,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        *,
        max_rotations: int | None = None,
    ) -> tuple[str | None, str]:
        """请求文本；连接失败/SSL/超时等可重试错误时自动轮询镜像域名重试。

        未声明 _domains 或已用自定义 URL 时，行为与普通 get_text 一致（单次请求）。
        轮询路径传 retry_count=1：重试交给轮询层（每个镜像只试一次，失败立即切下一个），
        避免「镜像数 × 内部重试」相乘放大请求次数。
        """
        rotator = getattr(self, "_rotator", None)
        if rotator is None or not rotator.domains:
            return await self.async_client.get_text(url, headers=headers, cookies=cookies)
        max_rotations = max_rotations or len(rotator.domains)
        for _ in range(max_rotations):
            htmlcode, error = await self.async_client.get_text(url, headers=headers, cookies=cookies, retry_count=1)
            if htmlcode is not None:
                return htmlcode, ""
            if "404" in str(error):
                return None, error
            if rotator.current_is_custom():
                return None, error
            self.base_url = rotator.rotate()
            url = rotator.rebuild_url(url)
            ctx.debug(f"{type(self).__name__} 请求失败，切换镜像域名重试: {url} ({error})")
        return None, "所有镜像域名均失败"

    async def close(self):
        """释放资源."""
        return

    @classmethod
    @abstractmethod
    def site(cls) -> Website:
        """此爬虫对应的网站枚举值."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def base_url_(cls) -> str:
        """默认 URL, 结尾无斜杠. 可以通过 self.base_url 访问实际值."""
        raise NotImplementedError

    @classmethod
    def display_name(cls) -> str:
        """前端展示名称, 默认使用网站枚举值."""
        return cls.site().value

    @classmethod
    def site_description(cls) -> str:
        """站点定位说明（用于 UI tooltip/列表标注）。

        子类可覆写类属性 `description`（如"免 CF 通道"、"综合站（有码+无码）"、
        "仅覆盖本厂作品"等），供站点列表悬停提示。留空则不显示说明。
        """
        return cls.description

    @classmethod
    def hidden_in_ui(cls) -> bool:
        """是否在前端站点枚举中隐藏."""
        return False

    @classmethod
    async def check_urls(cls) -> list[str]:
        """返回网络检测用的 URL 列表.

        默认返回声明了镜像域名（_domains）时的全部镜像地址，否则返回 base_url_() 单个地址；
        动态域名站点可覆写此方法返回动态解析地址（如 avmoo/avheat/avsox/javlibrary）。
        """
        domains = list(getattr(cls, "_domains", None) or [])
        if domains:
            return domains
        return [cls.base_url_()]

    @classmethod
    def supports_custom_url(cls) -> bool:
        """是否支持在前端配置自定义网址."""
        return True

    @abstractmethod
    def new_context(self, input: CrawlerInput) -> T:
        raise NotImplementedError

    async def run(self, input: CrawlerInput) -> CrawlerResponse:
        """
        执行爬虫任务.

        此方法负责初始化 `Context`, 处理异常, 记录调试信息等. 具体执行流程应在 `_run` 方法中实现.
        """
        start_time = time.time()
        ctx = self.new_context(input)
        ctx.debug(f"{input=}")

        try:
            data = await self._run(ctx)
            return CrawlerResponse(data=data, debug_info=ctx.debug_info)
        except Exception as e:
            ctx.debug(traceback.format_exc())
            ctx.debug_info.error = e
            return CrawlerResponse(debug_info=ctx.debug_info)
        finally:
            ctx.debug_info.execution_time = time.time() - start_time

    async def _run(self, ctx: T):
        if not ctx.input.appoint_url:
            search_urls = await self._generate_search_url(ctx)
            if not search_urls:
                raise CrawlerException("生成搜索页 URL 失败")
            if isinstance(search_urls, str):
                search_urls = [search_urls]
            ctx.debug(f"搜索页 URL: {search_urls}")
            ctx.debug_info.search_urls = search_urls

            detail_urls = await self._search(ctx, search_urls)
            if not detail_urls:
                raise CrawlerException("搜索失败")
        else:
            detail_urls = [ctx.input.appoint_url]
            ctx.debug(f"使用指定详情页 URL: {ctx.input.appoint_url}")

        ctx.debug_info.detail_urls = detail_urls
        data = await self._detail(ctx, detail_urls)
        if not data:
            raise CrawlerException("获取详情页数据失败")
        data.source = self.site().value  # todo use Enum directly
        result = data.to_result()
        return await self.post_process(ctx, result)

    async def _search(self, ctx: T, search_urls: list[str]) -> list[str] | None:
        for search_url in search_urls:
            html, error = await self._fetch_search(ctx, search_url)
            if html is None:
                ctx.debug(f"搜索页请求失败: {error=}")
                continue
            ctx.debug(f"搜索页请求成功: {search_url=}")
            selector = Selector(text=html)
            detail_urls = await self._parse_search_page(ctx, selector, search_url)
            if detail_urls:
                ctx.debug(f"详情页 URL: {detail_urls}")
                return detail_urls if isinstance(detail_urls, list) else [detail_urls]

    async def _detail(self, ctx: T, detail_urls: list[str]) -> CrawlerData | None:
        for detail_url in detail_urls:
            html, error = await self._fetch_detail(ctx, detail_url)
            if html is None:
                ctx.debug(f"详情页请求失败: {error=}")
                continue
            ctx.debug(f"详情页请求成功: {detail_url=}")
            selector = Selector(text=html)
            scraped_data = await self._parse_detail_page(ctx, selector, detail_url)
            if not scraped_data:
                ctx.debug(f"详情页解析失败: {detail_url=}")
                continue
            if not scraped_data.external_id:
                scraped_data.external_id = detail_url
            return scraped_data
        return None

    @abstractmethod
    async def _generate_search_url(self, ctx: T) -> list[str] | str | None:
        """
        生成搜索 URL. 如果重写 `_run` 则无须实现此方法.
        """
        raise NotImplementedError

    @abstractmethod
    async def _parse_search_page(self, ctx: T, html: Selector, search_url: str) -> list[str] | str | None:
        """
        解析搜索结果页, 获取详情页 URL. 如果重写 `_search` 则无须实现此方法.

        此方法应返回完整 URL, 当解析页面获取到相对 URL 时需进行处理.

        Args:
            html (Selector): 包含搜索结果页 HTML 的 parsel Selector 对象.
            search_url (str): 搜索页 URL.

        Returns:
            detail_urls: 一个或多个详情页的 URL, 如果找不到则返回 None.
        """
        raise NotImplementedError

    @abstractmethod
    async def _parse_detail_page(self, ctx: T, html: Selector, detail_url: str) -> CrawlerData | None:
        """
        解析详情页获取数据. 如果重写 `_detail` 则无须实现此方法.

        Args:
            html (Selector): 包含详情页 HTML 的 parsel Selector 对象.
            detail_url (str): 详情页 URL.

        Returns:
            爬取数据对象, 如果解析失败则返回 None.
        """
        raise NotImplementedError

    async def post_process(self, ctx: T, res: CrawlerResult) -> CrawlerResult:
        """
        爬取并解析完成后对结果进行后处理.

        Args:
            res (CrawlerResult): 爬取结果对象.
        """
        return res

    async def _fetch_search(self, ctx: T, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        """
        获取搜索页. 此方法不应抛出异常.
        """
        return await self._fetch(ctx, url, use_browser)

    async def _fetch_detail(self, ctx: T, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        """
        获取详情页. 此方法不应抛出异常.
        """
        return await self._fetch(ctx, url, use_browser)

    async def _fetch(self, ctx: T, url: str, use_browser: bool | None) -> tuple[str | None, str]:
        if use_browser is True:
            return None, "当前版本已移除浏览器请求模式"
        return await self._get_text_with_rotate(ctx, url, self._get_headers(ctx), self._get_cookies(ctx))

    def _get_cookies(self, ctx: T) -> dict[str, str] | None:
        return None

    def _get_headers(self, ctx: T) -> dict[str, str] | None:
        return None


class BaseCrawler[T: Context = Context](GenericBaseCrawler[T]):
    def new_context(self, input: CrawlerInput) -> T:
        return Context(input=input)  # type: ignore[return-value]


crawler_registry: dict[Website, type[GenericBaseCrawler[Never]]] = {}


def register_crawler(crawler_cls: type[GenericBaseCrawler[Any]]):
    crawler_registry[crawler_cls.site()] = crawler_cls


def get_crawler(site: Website) -> type[GenericBaseCrawler[Never]] | None:
    """
    获取指定网站的爬虫类.

    注意: 出于类型安全的目的, 将返回类型标注为 `GenericBaseCrawler[Never]`.
    由于允许子类继承 `Context` 作为泛型, 因此实际上没有类型可以准确标注此方法的返回值.

    在应用内部, 只有 `run` 被视为公开 API 调用, `Context` 实际上是内部实现细节, 因此这种标注不会导致问题.
    在测试等情况下, 如果需要调用具有 `ctx` 参数的方法, 必须使用返回类的 `new_context` 类方法创建具体使用的泛型类并传入.
    """
    return crawler_registry.get(site)


def get_registered_crawler_sites(*, include_hidden: bool = False) -> list[Website]:
    """返回已注册刮削器的网站列表, 供前端和配置 schema 枚举使用."""
    sites: list[Website] = []
    for site, crawler_cls in crawler_registry.items():
        if include_hidden or not crawler_cls.hidden_in_ui():
            sites.append(site)
    return sites


# 已废弃但保留在 Website 枚举中的站点值（为兼容旧配置文件而保留，
# 对应站点的爬虫已被移除，不应再有爬虫注册）。见 config/migrations.py 的
# _is_removed_airav_site 与 manual.py 的 SUPPORTED_WEBSITES 排除逻辑。
_DEPRECATED_WEBSITES: frozenset[str] = frozenset({Website.AIRAV.value})


def validate_crawler_registry() -> list[str]:
    """检查所有 Website 枚举值是否都有对应的已注册爬虫, 返回缺失的网站值列表.

    已废弃的枚举值（见 _DEPRECATED_WEBSITES）不算缺失——它们仅用于兼容
    旧配置文件, 对应的爬虫已被移除, 不应再要求注册.
    """
    missing = []
    for site in Website:
        if site.value in _DEPRECATED_WEBSITES:
            continue
        if site not in crawler_registry:
            missing.append(site.value)
    return missing
