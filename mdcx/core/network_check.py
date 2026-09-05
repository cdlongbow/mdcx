import asyncio
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urljoin

from mdcx.config.enums import Website
from mdcx.utils import mask_proxy_url

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class NetworkCheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class NetworkCheckSpec:
    name: str
    group: str
    url: str
    site: Website | None = None
    method: str = "GET"
    use_proxy: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    json_data: dict[str, Any] | None = None
    encoding: str = "utf-8"
    note: str = ""
    warning_if_missing: str = ""
    enable_cf_bypass: bool = False
    validator: str = ""


@dataclass(frozen=True)
class NetworkCheckResult:
    spec: NetworkCheckSpec
    status: NetworkCheckStatus
    message: str
    status_code: int | None = None
    elapsed_ms: int | None = None
    final_url: str = ""
    error: str = ""
    used_proxy: bool | None = None


# 连通性检测通过后，用该番号实际探测爬虫搜索能力，避免"能连≠能刮"误导用户
SCRAPE_PROBE_NUMBER = "SSNI-647"
SCRAPE_PROBE_TIMEOUT = 8.0


ProgressCallback = Callable[[str], None]


def _manager():
    from mdcx.config.manager import manager

    return manager


SPECIAL_CHECK_PATHS: dict[Website, str] = {
    Website.AIRAV_CC: "/playon.aspx?hid=44733",
    Website.JAVDB: "/v/D16Q5?locale=zh",
    Website.JAVBUS: "/FSDSS-660",
    Website.JAVLIBRARY: "/cn/?v=javme2j2tu",
    Website.JAVDB_APP: "/api/v2/search?q=SSNI-647&page=1",
}

DEFAULT_SITE_URLS: dict[Website, str] = {
    Website.DMM: "https://www.dmm.co.jp",
    Website.AVSOX: "https://avsox.click",
    Website.AVMOO: "https://avmoo.shop",
    Website.AVHEAT: "https://avheat.shop",
    Website.OFFICIAL: "",
}

GROUP_ORDER = ("基础环境", "基础连通性", "刮削站点", "账号/API", "辅助服务")
STATUS_ORDER = {
    NetworkCheckStatus.FAILED: 0,
    NetworkCheckStatus.WARNING: 1,
    NetworkCheckStatus.OK: 2,
    NetworkCheckStatus.SKIPPED: 3,
    NetworkCheckStatus.CANCELLED: 4,
}


def _status_icon(status: NetworkCheckStatus) -> str:
    return {
        NetworkCheckStatus.OK: "✅",
        NetworkCheckStatus.WARNING: "⚠️",
        NetworkCheckStatus.FAILED: "❌",
        NetworkCheckStatus.SKIPPED: "ℹ️",
        NetworkCheckStatus.CANCELLED: "⛔️",
    }[status]


def _elapsed_text(elapsed_ms: int | None) -> str:
    return "-" if elapsed_ms is None else f"{elapsed_ms} ms"


def _status_code_text(status_code: int | None) -> str:
    return "-" if status_code is None else str(status_code)


def _join_url(base_url: str, path: str) -> str:
    if not path:
        return base_url
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _configured_or_default_url(site: Website, default_url: str) -> tuple[str, bool]:
    manager = _manager()
    custom_url = manager.config.get_site_url(site)
    if custom_url:
        return custom_url, True
    return default_url.rstrip("/"), False


def _diagnostic_timeout() -> float:
    manager = _manager()
    return max(float(manager.config.timeout or 5), 2.0)


def _is_cloudflare_challenge(text: str) -> bool:
    lowered = text.lower()
    strong_markers = (
        "cdn-cgi/challenge-platform/h/b/",
        "cf-chl",
        "challenges.cloudflare.com",
    )
    if any(marker in lowered for marker in strong_markers):
        return True
    weak_markers = (
        "cf-browser-verification",
        "just a moment",
        "attention required",
        "enable javascript and cookies",
        "checking your browser before accessing",
    )
    return "cloudflare" in lowered and any(marker in lowered for marker in weak_markers)


def _is_proxy_error(error: str) -> bool:
    lowered = error.lower()
    return "proxy" in lowered or "socks" in lowered or "tunnel" in lowered


def _message_for_error(error: str) -> str:
    if not error:
        return "请求失败"
    if _is_proxy_error(error):
        return "代理连接失败，请检查代理地址或代理软件"
    if "超时" in error or "timeout" in error.lower():
        return "连接超时，请检查网络或代理节点"
    if "dns" in error.lower() or "resolve" in error.lower():
        return "DNS 解析失败"
    return error


def _clean_error(error: str) -> str:
    error = str(error or "").strip()
    if ": " not in error:
        return error
    left, right = error.split(": ", 1)
    if left.startswith(("GET ", "POST ", "HEAD ")) and right.startswith(left):
        return right
    return error


def _classify_http_result(spec: NetworkCheckSpec, status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if _is_cloudflare_challenge(text):
        return NetworkCheckStatus.WARNING, "被 Cloudflare 挑战页拦截"

    if spec.site == Website.JAVDB:
        manager = _manager()
        if "The owner of this website has banned your access based on your browser's behaving" in text:
            ip_address = re.findall(r"(\d+\.\d+\.\d+\.\d+)", text)
            ip_text = f"{ip_address[0]} " if ip_address else ""
            return (
                NetworkCheckStatus.FAILED,
                f"当前节点出口 IP {ip_text}被 JavDB 封禁（走代理时是代理节点 IP，请更换节点）",
            )
        if "Due to copyright restrictions" in text or "Access denied" in text:
            return NetworkCheckStatus.FAILED, "当前节点 IP 被 JavDB 限制（版权区域限制），请使用非日本节点"
        if "/logout" in text:
            return NetworkCheckStatus.OK, "连接正常，Cookie 有效"
        if manager.config.javdb:
            return NetworkCheckStatus.WARNING, "站点可访问，但 JavDB Cookie 可能无效"
        return NetworkCheckStatus.OK, "连接正常"

    if spec.site == Website.JAVBUS:
        manager = _manager()
        if "lostpasswd" in text and manager.config.javbus:
            return NetworkCheckStatus.WARNING, "站点可访问，但 JavBus Cookie 可能无效"
        if "lostpasswd" in text:
            return NetworkCheckStatus.WARNING, "当前节点可能需要 JavBus Cookie"
        return NetworkCheckStatus.OK, "连接正常"

    if spec.site == Website.DMM:
        if "このページはお住まいの地域からご利用になれません" in text:
            return NetworkCheckStatus.FAILED, "DMM 地域限制，请使用日本节点"

    if spec.site == Website.MGSTAGE and not text.strip():
        return NetworkCheckStatus.FAILED, "MGStage 返回空页面，通常是地域限制，请使用日本节点"

    if status_code == 401:
        return NetworkCheckStatus.WARNING, "HTTP 401 鉴权失败：请在设置 → 网络中配置该站的 Cookie 或 API Token"
    if status_code == 403:
        return NetworkCheckStatus.WARNING, "HTTP 403 请求被拒绝：多为反爬或地域限制，请更换代理节点或配置 CF Bypass"
    if status_code == 429:
        return NetworkCheckStatus.WARNING, "HTTP 429 请求被限流：请稍等几分钟再重试，或在设置中降低并发数"
    if 200 <= status_code < 400:
        return NetworkCheckStatus.OK, "连接正常"
    if 500 <= status_code:
        return NetworkCheckStatus.FAILED, f"站点服务异常 HTTP {status_code}"
    return NetworkCheckStatus.FAILED, f"HTTP {status_code}"


def _compute_used_proxy(spec: NetworkCheckSpec) -> bool:
    """计算该检测项实际是否走代理.

    与 AsyncWebClient.request 的真实路由判定保持一致：
    走代理需同时满足 全局代理启用、spec 允许代理、host 命中 proxy_sites。
    """
    if not spec.use_proxy or not spec.url:
        return False
    manager = _manager()
    if not (manager.config.use_proxy and manager.config.proxy):
        return False
    try:
        from httpx import URL

        host = URL(spec.url).host or ""
    except Exception:
        host = ""
    if not host:
        return False
    try:
        from mdcx.web_async import is_proxy_host

        return is_proxy_host(host, manager.config.proxy_hosts_list())
    except Exception:
        return False


async def _probe_crawler_by_run(
    crawler: Any,
    input_data: Any,
) -> tuple[NetworkCheckStatus | None, str]:
    """对重写 `_run` 的 API 类爬虫，用真实刮削路径探测能力."""
    try:
        response = await asyncio.wait_for(crawler.run(input_data), timeout=SCRAPE_PROBE_TIMEOUT)
    except TimeoutError:
        return NetworkCheckStatus.WARNING, "站点可达但刮削探测超时"
    except Exception as exc:
        return NetworkCheckStatus.WARNING, f"站点可达但刮削探测异常: {exc}"

    if response is None or response.data is None:
        error = getattr(getattr(response, "debug_info", None), "error", None) if response else None
        probe_number = str(getattr(input_data, "number", "") or SCRAPE_PROBE_NUMBER)
        message = (
            f"刮削探测失败: {error}"
            if error
            else f"站点可达，但测试番号 {probe_number} 未被该站点收录（单厂牌/收录有限站点常见，属正常情况，若实际刮削正常可忽略本警告）"
        )
        return NetworkCheckStatus.WARNING, message
    return NetworkCheckStatus.OK, "连接正常，刮削正常"


async def _probe_crawler_capability(
    client: Any,
    spec: NetworkCheckSpec,
) -> tuple[NetworkCheckStatus | None, str]:
    """连通性检测通过后，用真实爬虫搜索路径探测刮削能力.

    返回 (None, "") 表示该站点无需/无法探测；否则返回探测状态与说明。
    """
    site = spec.site
    if site is None:
        return None, ""
    try:
        from parsel import Selector

        from mdcx.config.enums import Language
        from mdcx.crawlers import get_crawler
        from mdcx.crawlers.base.base_types import CrawlerException
        from mdcx.models.model_types import CrawlerInput
    except Exception:
        return None, ""

    try:
        crawler_cls = get_crawler(site)
        if crawler_cls is None:
            return None, ""
        crawler = crawler_cls(client=client, base_url=spec.url.rstrip("/"), browser=None)
        probe_number = getattr(crawler_cls, "probe_number", "") or SCRAPE_PROBE_NUMBER
        input_data = CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number=probe_number,
            short_number="",
            language=Language.UNDEFINED,
            org_language=Language.UNDEFINED,
        )
        ctx: Any = crawler.new_context(input_data)
        try:
            search_urls = await crawler._generate_search_url(ctx)
        except NotImplementedError:
            search_urls = None
        if not search_urls:
            # 重写 _run 的爬虫（aio 系列/fc2 等）不走标准搜索流程，
            # 统一回退真实刮削路径探测。
            return await _probe_crawler_by_run(crawler, input_data)
        if isinstance(search_urls, str):
            search_urls = [search_urls]

        headers = crawler._get_headers(ctx) or None
        cookies = crawler._get_cookies(ctx) or None

        for search_url in search_urls:
            response, error = await client.request(
                "GET",
                search_url,
                headers=headers,
                cookies=cookies,
                use_proxy=spec.use_proxy,
                timeout=SCRAPE_PROBE_TIMEOUT,
                retry_count=1,
            )
            if response is None:
                return NetworkCheckStatus.WARNING, f"站点可达但搜索页请求失败: {error}"
            search_text = ""
            try:
                response.encoding = spec.encoding
                search_text = response.text or ""
            except Exception:
                search_text = ""
            if _is_cloudflare_challenge(search_text):
                return NetworkCheckStatus.WARNING, "站点可达但搜索页被 Cloudflare 拦截"
            selector = Selector(text=search_text)
            detail_urls = await crawler._parse_search_page(ctx, selector, search_url)
            if detail_urls:
                return NetworkCheckStatus.OK, "连接正常，刮削正常"
            # 重写 _search（POST 搜索）的爬虫 GET 探测拿不到结果，
            # 回退真实刮削路径再确认一次。
            return await _probe_crawler_by_run(crawler, input_data)
    except NotImplementedError:
        return NetworkCheckStatus.WARNING, "站点可达但无法自动探测刮削，可用设置页指定网址实测"
    except CrawlerException as exc:
        return NetworkCheckStatus.WARNING, f"站点可达但刮削探测失败: {exc}"
    except Exception as exc:
        return NetworkCheckStatus.WARNING, f"站点可达但刮削探测异常: {exc}"


def _is_bypass_capable_client(client: Any) -> bool:
    return callable(getattr(client, "_try_bypass_cloudflare", None))


async def _try_bypass_for_check(
    client: Any,
    spec: NetworkCheckSpec,
) -> tuple[Any | None, str]:
    if not spec.enable_cf_bypass:
        return None, "此检测项未启用 CF Bypass"
    manager = _manager()
    if not manager.config.cf_bypass_url.strip():
        return None, "未配置 CF Bypass"
    if not _is_bypass_capable_client(client):
        return None, "当前客户端不支持 CF Bypass"

    try:
        from httpx import URL
    except Exception as exc:
        return None, f"URL 解析依赖不可用: {exc}"

    try:
        host = URL(spec.url).host or ""
    except Exception as exc:
        return None, f"URL 解析失败: {exc}"
    if not host:
        return None, "URL 缺少 host"

    return await client._try_bypass_cloudflare(
        host=host,
        method=spec.method,
        target_url=spec.url,
        headers=spec.headers or None,
        cookies=spec.cookies or None,
        data=None,
        json_data=None,
        # CF Bypass 往往需要启动浏览器、刷新 Cookie 或等待挑战页完成, 使用 AsyncWebClient 内置的
        # _cf_bypass_timeout, 不用普通诊断请求的短超时覆盖。
        timeout=None,
        allow_redirects=True,
        use_proxy=spec.use_proxy,
    )


def _format_header() -> list[str]:
    manager = _manager()
    use_proxy = bool(manager.config.use_proxy and manager.config.proxy)
    cf_bypass_url = manager.config.cf_bypass_url.strip()
    cf_bypass_proxy = manager.config.cf_bypass_proxy.strip()
    trawl_url = manager.config.cf_bypass_trawl_url.strip()
    lines = [time.strftime("%Y-%m-%d %H:%M:%S").center(88, "=")]
    lines.append("基础环境")
    lines.append(f"  {'代理状态':<16}{'已启用' if use_proxy else '未启用'}")
    if use_proxy:
        lines.append(f"  {'代理地址':<16}{mask_proxy_url(manager.config.proxy)}")
    lines.append(f"  {'CF Bypass':<16}{'已配置' if cf_bypass_url else '未配置'}")
    lines.append(f"  {'CF Bypass代理':<16}{'已配置' if cf_bypass_proxy else '未配置'}")
    lines.append(f"  {'外部CF服务':<16}{'已配置' if trawl_url else '未配置'}")
    lines.append(f"  {'诊断超时':<16}{_diagnostic_timeout():.1f}s")
    lines.append("  " + "-" * 84)
    lines.append(f"  {'状态':<4} {'站点':<18} {'状态码':>4}  {'耗时':>8}  {'路由':<4} 信息")
    lines.append("=" * 88)
    return lines


def format_result_line(result: NetworkCheckResult) -> str:
    icon = _status_icon(result.status)
    name = result.spec.name[:18]
    status_code = _status_code_text(result.status_code)
    elapsed = _elapsed_text(result.elapsed_ms)
    used_proxy = result.used_proxy if result.used_proxy is not None else result.spec.use_proxy
    proxy = "代理" if used_proxy else "直连"
    proxy = f"{proxy:<4}"
    message = result.message
    if result.error and result.status == NetworkCheckStatus.FAILED:
        if result.error not in message:
            message = f"{message}: {result.error}"
    return f"  {icon} {name:<18} {status_code:>4}  {elapsed:>8}  {proxy} {message}"


def format_summary(
    results: list[NetworkCheckResult],
    elapsed: float,
    cancelled: bool,
    proxy_unavailable: bool = False,
) -> list[str]:
    failed = sum(1 for result in results if result.status == NetworkCheckStatus.FAILED)
    warning = sum(1 for result in results if result.status == NetworkCheckStatus.WARNING)
    ok = sum(1 for result in results if result.status == NetworkCheckStatus.OK)
    skipped = sum(1 for result in results if result.status == NetworkCheckStatus.SKIPPED)
    status = "已取消" if cancelled else "已完成"
    lines = [
        "-" * 88,
        f"网络检测{status}：正常 {ok}，警告 {warning}，失败 {failed}，跳过 {skipped}，用时 {elapsed:.2f} 秒",
    ]
    if proxy_unavailable:
        lines.append(
            "⚠️ 全局代理不可用（基础连通性两项均因代理失败）。下方站点失败多为代理导致，请先检查代理软件/节点后再重试。"
        )
    if failed or warning:
        lines.append(
            "建议优先查看失败/警告项；若基础连通性失败，先检查代理或系统网络；"
            "代理/Cookie/CF Bypass 等配置请在「设置 → 网络」页调整。"
        )
    lines.append("=" * 88)
    return lines


async def _build_site_specs() -> list[NetworkCheckSpec]:
    from mdcx.crawlers import get_crawler, get_registered_crawler_sites

    manager = _manager()
    specs: list[NetworkCheckSpec] = []
    for site in get_registered_crawler_sites(include_hidden=False):
        if site == Website.THEPORNDB:
            continue
        crawler_cls = get_crawler(site)
        if crawler_cls is None:
            continue

        default_url = DEFAULT_SITE_URLS.get(site)
        if default_url is None:
            try:
                default_url = crawler_cls.base_url_()
            except Exception:
                default_url = ""

        base_url, customized = _configured_or_default_url(site, default_url or "")
        if not base_url:
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="刮削站点",
                    url="",
                    site=site,
                    note="该站无固定检测入口（按番号动态检测），跳过属正常情况，不用处理",
                )
            )
            continue

        # 动态域名/镜像站点可返回多个检测地址；其余站点默认单地址。
        try:
            check_urls = await crawler_cls.check_urls()
        except Exception:
            check_urls = []
        # 用户未自定义 URL 时，动态域名站优先用动态解析出的地址作为主检测地址。
        # 过滤空串：base_url_() 返回空的站点（如 dmm）check_urls 会返回 [""]，
        # 此时应回退到 DEFAULT_SITE_URLS 的默认地址，而不是覆盖成空导致误报"无固定入口"。
        if not customized and check_urls:
            non_empty_urls = [u.rstrip("/") for u in check_urls if u and u.strip()]
            if non_empty_urls:
                base_url = non_empty_urls[0]

        path = SPECIAL_CHECK_PATHS.get(site, "")
        url = _join_url(base_url, path)
        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}
        # 代理路由统一交给全局 proxy_sites 配置决策；强制直连会让被墙环境下
        # 检测与真实刮削路径脱节（如 javlibrary 自定义 URL + CF Bypass 场景）。
        use_proxy = True
        if site == Website.JAVDB and manager.config.javdb:
            headers["cookie"] = manager.config.javdb
        elif site == Website.JAVBUS:
            headers["Accept-Language"] = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6"
            if manager.config.javbus:
                headers["cookie"] = manager.config.javbus
        elif site == Website.MGSTAGE:
            cookies["adc"] = "1"
        elif site == Website.DMM_API:
            from mdcx.crawlers.dmm_api import DmmApiCrawler

            # v3 ItemList 必需 site/service/floor，缺失直接 400 BAD REQUEST；
            # keyword 用厂牌词（实测命中 content_id），验证凭据有效性与搜索能力。
            api_url = DmmApiCrawler._build_api_url(
                site="FANZA",
                service="digital",
                floor="videoa",
                keyword="SSIS",
                sort="match",
                hits="1",
            )
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="账号/API",
                    url=api_url,
                    site=site,
                    headers={"Accept": "application/json"},
                    validator="dmm_api",
                )
            )
            continue
        elif site == Website.THEJAVDB_API:
            url = f"{url.rstrip('/')}/movies?q=ssni-200"
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="账号/API",
                    url=url,
                    site=site,
                    headers={"Accept": "application/json"},
                    validator="thejavdb_api",
                )
            )
            continue
        elif site == Website.GETCHU:
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="刮削站点",
                    url=url,
                    site=site,
                    use_proxy=use_proxy,
                    encoding="euc-jp",
                )
            )
            continue
        elif site == Website.JAVDB_APP:
            # javdb_app API 需要 jdsignature header
            from ..crawlers.javdb_app import make_signature

            headers["jdsignature"] = make_signature()
            headers["accept-language"] = "zh"
            headers["User-Agent"] = "Dart/3.5 (dart:io)"
        elif site == Website.MISSAV_API:
            # Recombee search 端点只接受 POST（GET 返回 405），用真实搜索路径检测；
            # 公开 token 仅授权部分端点，签名逻辑与爬虫刮削共用 _sign_path。
            from ..crawlers.missav_api import MissavApiCrawler

            base_url = f"https://{MissavApiCrawler.RECOMBEE_HOST}"
            signed_path = MissavApiCrawler._sign_path("/search/users/anonymous/items/")
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="账号/API",
                    url=f"{base_url}{signed_path}",
                    site=site,
                    method="POST",
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json_data={
                        "searchQuery": "ssni-647",
                        "count": 3,
                        "cascadeCreate": True,
                        "returnProperties": True,
                    },
                    use_proxy=False,
                    validator="missav_api",
                )
            )
            continue

        specs.append(
            NetworkCheckSpec(
                name=site.value,
                group="刮削站点",
                url=url,
                site=site,
                use_proxy=use_proxy,
                headers=headers,
                cookies=cookies,
                enable_cf_bypass=True,
            )
        )

        # 动态域名/镜像站点的额外检测地址：每个站点只保留 1 个镜像作抽样，
        # 避免 javbus 等 5-6 个镜像逐个检测刷屏拖慢；主站失败时仍能看到镜像是否可用。
        if len(check_urls) > 1:
            main_host = url.split("://")[-1].split("/")[0]
            extra_sampled = False
            for extra_url in check_urls:
                extra_url = extra_url.rstrip("/")
                if not extra_url:
                    continue
                extra_host = extra_url.split("://")[-1].split("/")[0]
                if extra_host == main_host:
                    continue
                if extra_sampled:
                    continue
                extra_sampled = True
                specs.append(
                    NetworkCheckSpec(
                        name=f"{site.value}·镜像",
                        group="刮削站点",
                        url=extra_url,
                        site=site,
                        use_proxy=use_proxy,
                        headers=dict(headers),
                        cookies=dict(cookies),
                        enable_cf_bypass=True,
                    )
                )
    return specs


def _build_static_specs() -> list[NetworkCheckSpec]:
    manager = _manager()
    specs = [
        NetworkCheckSpec(
            name="GitHub Raw",
            group="基础连通性",
            url="https://raw.githubusercontent.com",
            use_proxy=bool(manager.config.use_proxy and manager.config.proxy),
        ),
        NetworkCheckSpec(
            name="通用 HTTPS",
            group="基础连通性",
            url="https://www.google.com/generate_204",
            use_proxy=bool(manager.config.use_proxy and manager.config.proxy),
        ),
    ]

    cf_bypass_url = manager.config.cf_bypass_url.strip()
    if cf_bypass_url:
        health_url = cf_bypass_url.rstrip("/") + "/cookies?url=http://example.com"
        bypass_proxy = manager.config.cf_bypass_proxy.strip()
        if bypass_proxy:
            health_url += "&proxy=" + quote_plus(bypass_proxy)
        specs.append(NetworkCheckSpec(name="CF Bypass", group="辅助服务", url=health_url, use_proxy=False))
    else:
        specs.append(
            NetworkCheckSpec(
                name="CF Bypass",
                group="辅助服务",
                url="",
                note="未配置，仅遇到 Cloudflare 挑战页时需要",
            )
        )

    trawl_url = manager.config.cf_bypass_trawl_url.strip()
    if trawl_url:
        backend = (manager.config.cf_bypass_trawl_backend or "trawl").strip().lower()
        health_path = "/health" if backend == "trawl" else "/"
        specs.append(
            NetworkCheckSpec(
                name="外部 CF 服务",
                group="辅助服务",
                url=trawl_url.rstrip("/") + health_path,
                use_proxy=False,
            )
        )
    else:
        specs.append(
            NetworkCheckSpec(
                name="外部 CF 服务",
                group="辅助服务",
                url="",
                note="未配置，可选；部分强反爬站点（JavBus/JavDB 等）被 Cloudflare 挑战拦截时用于绕过",
            )
        )

    api_token = manager.config.theporndb_api_token.strip()
    if api_token:
        specs.append(
            NetworkCheckSpec(
                name="ThePornDB Token",
                group="账号/API",
                url="https://api.theporndb.net/scenes/hash/8679fcbdd29fa735",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                validator="theporndb_token",
            )
        )
    else:
        specs.append(
            NetworkCheckSpec(
                name="ThePornDB Token",
                group="账号/API",
                url="",
                warning_if_missing="未填写 API Token，影响欧美刮削",
            )
        )
    return specs


async def build_network_check_specs() -> list[NetworkCheckSpec]:
    return [*_build_static_specs(), *(await _build_site_specs())]


async def run_network_check_item(
    spec: NetworkCheckSpec,
    *,
    cancel_event: threading.Event | None = None,
    client: "AsyncWebClient | Any | None" = None,
) -> NetworkCheckResult:
    if cancel_event and cancel_event.is_set():
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.CANCELLED, message="已取消")
    if spec.warning_if_missing:
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.WARNING, message=spec.warning_if_missing)
    if not spec.url:
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.SKIPPED, message=spec.note or "无固定检测入口")

    used_proxy = _compute_used_proxy(spec)
    start_time = time.perf_counter()
    try:
        request_client = client or _manager().computed.async_client
        response, error = await request_client.request(
            spec.method,  # type: ignore[arg-type]
            spec.url,
            headers=spec.headers or None,
            cookies=spec.cookies or None,
            json_data=spec.json_data,
            use_proxy=spec.use_proxy,
            timeout=_diagnostic_timeout(),
            enable_cf_bypass=spec.enable_cf_bypass and bool(_manager().config.cf_bypass_url.strip()),
        )
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        if cancel_event and cancel_event.is_set():
            return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.CANCELLED, message="已取消")
        if response is None:
            clean_error = _clean_error(error)
            message = _message_for_error(clean_error)
            return NetworkCheckResult(
                spec=spec,
                status=NetworkCheckStatus.FAILED,
                message=message,
                elapsed_ms=elapsed_ms,
                error=clean_error,
                used_proxy=used_proxy,
            )

        text = ""
        try:
            response.encoding = spec.encoding
            text = response.text or ""
        except Exception as exc:
            return NetworkCheckResult(
                spec=spec,
                status=NetworkCheckStatus.WARNING,
                message=f"响应可达，但文本解析失败: {exc}",
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                final_url=str(getattr(response, "url", "") or ""),
                used_proxy=used_proxy,
            )

        if _is_cloudflare_challenge(text) and spec.enable_cf_bypass and _manager().config.cf_bypass_url.strip():
            bypass_response, bypass_error = await _try_bypass_for_check(request_client, spec)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            if bypass_response is None:
                clean_error = _clean_error(bypass_error)
                return NetworkCheckResult(
                    spec=spec,
                    status=NetworkCheckStatus.FAILED,
                    message="Cloudflare Bypass 失败",
                    status_code=int(response.status_code),
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                    error=clean_error,
                    used_proxy=used_proxy,
                )
            response = bypass_response
            try:
                response.encoding = spec.encoding
                text = response.text or ""
            except Exception as exc:
                return NetworkCheckResult(
                    spec=spec,
                    status=NetworkCheckStatus.WARNING,
                    message=f"Bypass 响应可达，但文本解析失败: {exc}",
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                    used_proxy=used_proxy,
                )
            if not _is_cloudflare_challenge(text):
                bypass_mode = ""
                try:
                    bypass_mode = response.headers.get("x-mdcx-bypass-mode", "")
                except Exception:
                    bypass_mode = ""
                status, message = _classify_http_result(spec, int(response.status_code), text)
                if status == NetworkCheckStatus.OK:
                    mode_text = f"（{bypass_mode}）" if bypass_mode else ""
                    message = f"连接正常，已通过 CF Bypass{mode_text}"
                return NetworkCheckResult(
                    spec=spec,
                    status=status,
                    message=message,
                    status_code=int(response.status_code),
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                    used_proxy=used_proxy,
                )

        status, message = _classify_http_result(spec, int(response.status_code), text)
        if spec.validator == "theporndb_token":
            status, message = _classify_theporndb_token(int(response.status_code), text)
        elif spec.validator == "dmm_api":
            status, message = _classify_dmm_api(int(response.status_code), text)
        elif spec.validator == "thejavdb_api":
            status, message = _classify_thejavdb_api(int(response.status_code), text)
        elif spec.validator == "missav_api":
            status, message = _classify_missav_api(int(response.status_code), text)
        elif spec.name == "CF Bypass" and status == NetworkCheckStatus.OK:
            message = "服务可用"

        if (
            status == NetworkCheckStatus.OK
            and spec.site is not None
            and not spec.validator
            and spec.name != "CF Bypass"
        ):
            probe_status, probe_message = await _probe_crawler_capability(request_client, spec)
            if probe_status is not None:
                status, message = probe_status, probe_message

        return NetworkCheckResult(
            spec=spec,
            status=status,
            message=message,
            status_code=int(response.status_code),
            elapsed_ms=elapsed_ms,
            final_url=str(getattr(response, "url", "") or ""),
            used_proxy=used_proxy,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return NetworkCheckResult(
            spec=spec,
            status=NetworkCheckStatus.FAILED,
            message="检测异常",
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )


def _classify_theporndb_token(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 401 and "Unauthenticated" in text:
        return NetworkCheckStatus.FAILED, "API Token 错误"
    if status_code == 200 and '"data"' in text:
        return NetworkCheckStatus.OK, "API Token 有效"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="ThePornDB Token", group="账号/API", url="", site=Website.THEPORNDB), status_code, text
    )


def _classify_dmm_api(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 200 and '"status":200' in text and ("content_id" in text or "ssis" in text.lower()):
        return NetworkCheckStatus.OK, "API 查询正常"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 可访问，但 SSIS 查询返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="dmm_api", group="账号/API", url="", site=Website.DMM_API), status_code, text
    )


def _classify_thejavdb_api(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 200 and ("universal_id" in text or "SSNI" in text.upper()):
        return NetworkCheckStatus.OK, "API 查询正常"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 可访问，但 ssni-200 查询返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="thejavdb_api", group="账号/API", url="", site=Website.THEJAVDB_API), status_code, text
    )


def _classify_missav_api(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 200 and '"recomms"' in text:
        return NetworkCheckStatus.OK, "API 查询正常"
    if status_code == 401:
        return NetworkCheckStatus.FAILED, "Recombee 公开 token 被拒绝，签名或端点已变更"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 可访问，但搜索返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="missav_api", group="账号/API", url="", site=Website.MISSAV_API), status_code, text
    )


async def run_network_check(
    *,
    progress: ProgressCallback | None = None,
    on_item_done: "Callable[[int, int], None] | None" = None,
    cancel_event: threading.Event | None = None,
    concurrency: int = 10,
    client: "AsyncWebClient | Any | None" = None,
    emit_header: bool = True,
    specs: list[NetworkCheckSpec] | None = None,
) -> list[NetworkCheckResult]:
    """执行网络检测。

    specs: 指定检测子集（用于"重试失败项"只重测失败/警告项）；None 表示全量构建检测项。
    on_item_done: 每完成一项回调 (done, total) 结构化进度（"基础环境"组不参与计数）；供 UI 显示百分比。
    """
    progress = progress or (lambda line: None)
    if emit_header:
        for line in _format_header():
            progress(line)

    check_specs = specs if specs is not None else await build_network_check_specs()
    results: list[NetworkCheckResult] = []
    total = sum(1 for s in check_specs if s.group != "基础环境")
    grouped_specs = {group: [spec for spec in check_specs if spec.group == group] for group in GROUP_ORDER}
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))

    async def run_one(spec: NetworkCheckSpec) -> NetworkCheckResult:
        async with semaphore:
            return await run_network_check_item(spec, cancel_event=cancel_event, client=client)

    start_time = time.perf_counter()
    proxy_down = False
    for group in GROUP_ORDER:
        group_specs = grouped_specs.get(group, [])
        if not group_specs or group == "基础环境":
            continue
        progress(group)
        # task → spec 映射：单项逃逸异常时定位所属站点（议题 #73）
        tasks = {asyncio.create_task(run_one(spec)): spec for spec in group_specs}
        pending = set(tasks)
        while pending:
            if cancel_event and cancel_event.is_set():
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                elapsed = time.perf_counter() - start_time
                for line in format_summary(results, elapsed, cancelled=True, proxy_unavailable=proxy_down):
                    progress(line)
                return results
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    # 单项任务内部协程被取消（底层连接清理/wait_for 子协程残留等），
                    # 只影响该项，不应炸掉整轮——议题 #73/#74 实证 CancelledError
                    # 从 future.result() 逃逸导致整轮停止。整轮取消由 cancel_event
                    # 分支统一处理，这里把单项记为 CANCELLED 继续跑。
                    result = NetworkCheckResult(
                        spec=tasks[task],
                        status=NetworkCheckStatus.CANCELLED,
                        message="已取消",
                        error="CancelledError",
                    )
                except Exception as exc:
                    # 单项任务逃逸了 run_network_check_item 的兜底（探测链深层异常等）。
                    # 绝不允许一项异常中断整轮检测——转 FAILED 记名续跑。
                    # 空消息异常（裸 TimeoutError 等）必须带类型名，否则用户只见空行。
                    result = NetworkCheckResult(
                        spec=tasks[task],
                        status=NetworkCheckStatus.FAILED,
                        message="检测任务异常",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                results.append(result)
                if on_item_done is not None:
                    on_item_done(len(results), total)
                if result.spec.group == "基础连通性":
                    if result.status == NetworkCheckStatus.FAILED and _is_proxy_error(result.error):
                        proxy_down = True
                elif proxy_down and result.status == NetworkCheckStatus.FAILED and _is_proxy_error(result.error):
                    # 全局代理不可用时，站点失败多为代理导致，简化提示避免误导用户以为站点全挂
                    result = replace(result, message="代理不可用（详见下方检测结果汇总区的提示）", error="")
                progress(format_result_line(result))

    elapsed = time.perf_counter() - start_time
    for line in format_summary(
        results, elapsed, cancelled=bool(cancel_event and cancel_event.is_set()), proxy_unavailable=proxy_down
    ):
        progress(line)
    return sorted(
        results,
        key=lambda result: (
            GROUP_ORDER.index(result.spec.group) if result.spec.group in GROUP_ORDER else len(GROUP_ORDER),
            STATUS_ORDER[result.status],
            result.spec.name,
        ),
    )


# ===== 站点检测结果缓存（持久化到 userdata，供站点选择列表回显） =====

NETWORK_CHECK_CACHE_VERSION = 1


def _site_result_level(status: NetworkCheckStatus) -> str:
    """归一化检测状态：ok/warn/fail/skip。"""
    if status == NetworkCheckStatus.OK:
        return "ok"
    if status == NetworkCheckStatus.WARNING:
        return "warn"
    if status == NetworkCheckStatus.FAILED:
        return "fail"
    return "skip"


def _site_cache_path():
    from mdcx.config.resources import resources

    return resources.u("network_check_cache.json")


def load_site_check_cache() -> dict[str, dict]:
    """加载站点检测缓存（站点值 → {status, route, checked_at}）。坏 JSON/缺失一律返回空。"""
    import json

    try:
        raw = json.loads(_site_cache_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("sites"), dict):
            return raw["sites"]
    except Exception:
        pass
    return {}


def merge_site_check_cache(results: "list[NetworkCheckResult]") -> None:
    """把检测结果中"刮削站点"分组的站点项合并进持久化缓存。

    只收集刮削站点（基础环境/共享平台等项不映射到站点选择列表）；
    重试失败项等部分结果按站点值覆盖更新，其余历史记录保留。
    写文件失败静默降级（缓存仅用于展示标注，不影响功能）。
    """
    import json
    from datetime import datetime

    sites = load_site_check_cache()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for result in results:
        site = result.spec.site
        if result.spec.group != "刮削站点" or site is None:
            continue
        route = ""
        if result.used_proxy is True:
            route = "proxy"
        elif result.used_proxy is False:
            route = "direct"
        sites[site.value] = {"status": _site_result_level(result.status), "route": route, "checked_at": now}
    try:
        path = _site_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": NETWORK_CHECK_CACHE_VERSION, "sites": sites}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception:
        pass
