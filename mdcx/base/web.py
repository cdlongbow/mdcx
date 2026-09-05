#!/usr/bin/env python3
import asyncio
import re
import threading
import time
from concurrent.futures import CancelledError
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, overload
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiofiles
import aiofiles.os
import httpx
from lxml import etree
from PIL import Image

from ..config.manager import manager
from ..consts import GITHUB_RELEASES_API_LIST
from ..models.log_buffer import LogBuffer
from ..network_fingerprint import build_amazon_headers, build_fingerprint_headers, select_fingerprint
from ..signals import signal
from ..utils import executor
from ..utils.file import check_pic_async
from ..utils.rate_limit import AdaptiveRequestThrottle

_AdaptiveRequestThrottle = AdaptiveRequestThrottle

_amazon_request_throttle = _AdaptiveRequestThrottle(
    base_spacing=0.18,
    max_spacing=1.6,
    cooldown_base=1.4,
    cooldown_max=8.0,
)

_DMM_IMAGE_BAD_URL_KEYS = ("now_printing", "nowprinting", "noimage", "nopic", "media_violation")
_DMM_IMAGE_PROBE_PARAMS = (("w", "120"), ("h", "90"))
_JDBSTATIC_HOST_SUFFIXES = ("jdbstatic.com",)
_IMAGE_DOWNLOAD_MAX_BYTES = 50 * 1024 * 1024  # 图片下载大小上限：50MB，防异常大文件拖死磁盘


def normalize_media_url(url: str, *, strip_dmm_probe_params: bool = False) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return ""

    try:
        split_result = urlsplit(normalized)
    except Exception:
        return normalized.rstrip("?&")

    query_items = parse_qsl(split_result.query, keep_blank_values=True)
    if strip_dmm_probe_params:
        query_items = [(k, v) for k, v in query_items if (k, v) not in _DMM_IMAGE_PROBE_PARAMS]

    path = split_result.path
    if split_result.netloc.lower().endswith(("dmm.co.jp", "dmm.com")):
        path = re.sub(r"/{2,}", "/", path)

    query = urlencode(query_items, doseq=True)
    cleaned = urlunsplit(
        (
            split_result.scheme,
            split_result.netloc,
            path,
            query,
            split_result.fragment,
        )
    )
    return cleaned.rstrip("?&")


def is_dmm_image_url(url: str) -> bool:
    normalized = normalize_media_url(url)
    if normalized.startswith("//"):
        normalized = "https:" + normalized
    try:
        split_result = urlsplit(normalized)
    except Exception:
        return False

    host = split_result.netloc.lower()
    path = split_result.path.lower()
    if not host or not (host.endswith("dmm.co.jp") or host.endswith("dmm.com")):
        return False
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"))


def _build_dmm_probe_url(url: str) -> tuple[str, bool]:
    normalized = normalize_media_url(url)
    if not normalized:
        return "", False

    if "awsimgsrc.dmm.co.jp" not in normalized:
        return normalized, False

    split_result = urlsplit(normalized)
    query_items = list(parse_qsl(split_result.query, keep_blank_values=True))
    added_probe = False
    for key, value in _DMM_IMAGE_PROBE_PARAMS:
        if not any(existing_key == key and existing_value == value for existing_key, existing_value in query_items):
            query_items.append((key, value))
            added_probe = True

    query = urlencode(query_items, doseq=True)
    return (
        urlunsplit(
            (
                split_result.scheme,
                split_result.netloc,
                split_result.path,
                query,
                split_result.fragment,
            )
        ),
        added_probe,
    )


def _is_invalid_image_redirect_url(url: str) -> bool:
    normalized = normalize_media_url(url).lower()
    return any(each_key in normalized for each_key in _DMM_IMAGE_BAD_URL_KEYS)


def is_jdbstatic_image_url(url: str) -> bool:
    normalized = normalize_media_url(url)
    if normalized.startswith("//"):
        normalized = "https:" + normalized
    try:
        split_result = urlsplit(normalized)
    except Exception:
        return False

    host = split_result.netloc.lower()
    path = split_result.path.lower()
    if not host or not host.endswith(_JDBSTATIC_HOST_SUFFIXES):
        return False
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"))


# JavDB App 专用图片 CDN：返回单字节 XOR 加密流，解密后为无水印原图
# 判定按域名而非完整路径——路径中段（如 rhe951l4q）可能随服务端调整变更
_SPFCAS_IMAGE_HOST = "tp.spfcas.com"


def is_spfcas_image_url(url: str) -> bool:
    normalized = normalize_media_url(url)
    if normalized.startswith("//"):
        normalized = "https:" + normalized
    try:
        split_result = urlsplit(normalized)
    except Exception:
        return False

    if split_result.netloc.lower() != _SPFCAS_IMAGE_HOST:
        return False
    return split_result.path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"))


def decrypt_spfcas_image(data: bytes) -> bytes | None:
    """解密 App CDN 加密流：首字节为 XOR key，其余字节与 key 异或；明文应为 JPEG（FF D8 起始）。

    格式不符（含空输入）返回 None，由调用方判下载失败。
    """
    if not data or len(data) < 2:
        return None
    key = data[0]
    table = bytes(i ^ key for i in range(256))
    plain = data[1:].translate(table)
    return plain if plain.startswith(b"\xff\xd8") else None


def decode_spfcas_image_content(url: str, content: bytes) -> bytes | None:
    """按 URL 判定解密 App CDN 加密流；非 App CDN 内容原样透传。返回 None 表示解密失败。"""
    if not is_spfcas_image_url(url):
        return content
    return decrypt_spfcas_image(content)


# 当前 App CDN 路径中段（可能随服务端调整变更），javdb_app 响应持续学习自愈
_JDBSTATIC_PRIMARY_HOST = "c0.jdbstatic.com"
_spfcas_segment_value = "rhe951l4q"


def _spfcas_segment() -> str:
    return _spfcas_segment_value


def reset_spfcas_segment_for_test(value: str) -> None:
    global _spfcas_segment_value
    _spfcas_segment_value = value


def learn_spfcas_image_segment(url: str) -> str:
    """从 App CDN 图片 URL 学习当前路径中段，供网页版 URL 变换使用；无效 URL 返回空串。"""
    global _spfcas_segment_value
    try:
        path = urlsplit(normalize_media_url(url)).path
    except Exception:
        return ""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] and parts[1] in ("covers", "small_covers", "samples"):
        _spfcas_segment_value = parts[0]
        return parts[0]
    return ""


def jdbstatic_to_spfcas(url: str) -> str:
    """网页版 CDN（带水印）URL 变换为 App CDN（无水印）URL；形态不符返回空串。

    covers/samples 路径保持，thumbs 映射为 small_covers，插入当前学习到的路径中段。
    """
    normalized = normalize_media_url(url)
    if normalized.startswith("//"):
        normalized = "https:" + normalized
    try:
        split_result = urlsplit(normalized)
    except Exception:
        return ""
    if not split_result.netloc.lower().endswith(_JDBSTATIC_HOST_SUFFIXES):
        return ""
    parts = [p for p in split_result.path.split("/") if p]
    if not parts:
        return ""
    if parts[0] == "thumbs":
        parts[0] = "small_covers"
    if parts[0] not in ("covers", "small_covers", "samples"):
        return ""
    return f"https://{_SPFCAS_IMAGE_HOST}/{_spfcas_segment()}/{'/'.join(parts)}"


def spfcas_to_jdbstatic(url: str) -> str:
    """App CDN URL 逆向变换回网页版 CDN URL（供尺寸探测回退）；形态不符返回空串。"""
    try:
        split_result = urlsplit(normalize_media_url(url))
    except Exception:
        return ""
    if split_result.netloc.lower() != _SPFCAS_IMAGE_HOST:
        return ""
    parts = [p for p in split_result.path.split("/") if p]
    if len(parts) < 2 or parts[1] not in ("covers", "small_covers", "samples"):
        return ""
    body = parts[1:]
    if body[0] == "small_covers":
        body[0] = "thumbs"
    return f"https://{_JDBSTATIC_PRIMARY_HOST}/{'/'.join(body)}"


def build_jdbstatic_headers(url: str) -> dict[str, str]:
    fingerprint = select_fingerprint("javdb.com", purpose="asset")
    headers = build_fingerprint_headers(url, fingerprint=fingerprint, purpose="asset")
    headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    headers["Referer"] = "https://javdb.com/"
    headers["Sec-Fetch-Dest"] = "image"
    headers["Sec-Fetch-Mode"] = "no-cors"
    headers["Sec-Fetch-Site"] = "cross-site"
    return headers


def log_jdbstatic_request_headers(url: str, headers: dict[str, str] | None) -> None:
    if not is_jdbstatic_image_url(url):
        return
    safe_headers = headers or {}
    LogBuffer.log().write(
        "\n 🔎 JDBStatic请求头: "
        f"url={url} "
        f"accept={safe_headers.get('Accept', '')} "
        f"referer={safe_headers.get('Referer', '')} "
        f"sec-fetch-dest={safe_headers.get('Sec-Fetch-Dest', '')} "
        f"sec-fetch-mode={safe_headers.get('Sec-Fetch-Mode', '')} "
        f"sec-fetch-site={safe_headers.get('Sec-Fetch-Site', '')}"
    )


def _should_retry_link_error(error: str) -> bool:
    normalized = str(error or "").lower()
    if not normalized:
        return False
    if "http 404" in normalized or "http 410" in normalized:
        return False
    # curl_cffi 内部对象竞态（session 重建/cleanup 阶段的 "initializer for ctype"
    # TypeError），重试必然再次失败——属库内错误而非网络问题，跳过以免浪费时间
    if "ctype" in normalized and ("pointer" in normalized or "cdata" in normalized):
        return False
    return any(
        marker in normalized
        for marker in (
            "http 403",
            "http 408",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "连接超时",
            "连接错误",
            "请求异常",
            "curl-cffi 异常",
        )
    )


def _parse_content_length(value: Any) -> int | None:
    try:
        length = int(value)
    except (TypeError, ValueError):
        return None
    return length if length > 0 else None


# DMM 图床对无效/下架对象可能返回 200 + 极小字节（实测 142B 垃圾响应、约 2.7KB 占位图），
# 真实封面即使最小尺寸也在 10KB 以上，低于该阈值一律视为占位图
_DMM_PLACEHOLDER_MAX_BYTES = 4096


def _is_dmm_placeholder_size(size: int | None) -> bool:
    return size is not None and 0 < size < _DMM_PLACEHOLDER_MAX_BYTES


async def _validate_dmm_image_url(url: str, length: bool = False, real_url: bool = False):
    normalized = normalize_media_url(url)
    request_url, added_probe = _build_dmm_probe_url(normalized)
    max_retries = max(int(manager.config.retry), 1)
    last_error = ""

    async with manager.acquire_computed() as computed:
        client = computed.async_client
        for retry_attempt in range(max_retries):
            try:
                response, error = await client.request("GET", request_url, retry_count=1)
                if response is None:
                    last_error = error
                    if retry_attempt < max_retries - 1 and _should_retry_link_error(error):
                        signal.add_log(f"🟡 检测链接失败，正在重试 ({retry_attempt + 1}/{max_retries}): {error}")
                        await asyncio.sleep(0.6 * (retry_attempt + 1))
                        continue
                    signal.add_log(f"🔴 检测链接失败: {error}")
                    return None

                true_url = normalize_media_url(str(response.url), strip_dmm_probe_params=added_probe)
                if real_url:
                    return true_url

                if "login" in true_url:
                    signal.add_log(f"🔴 检测链接失败: 需登录 {true_url}")
                    return None

                if _is_invalid_image_redirect_url(true_url):
                    signal.add_log(f"🔴 检测链接失败: 图片已被网站删除 {true_url}")
                    return None

                if content_length := _parse_content_length(response.headers.get("Content-Length")):
                    if _is_dmm_placeholder_size(content_length):
                        last_error = f"疑似占位图({content_length}B) {true_url}"
                        signal.add_log(f"🔴 检测链接失败: {last_error}")
                        return None
                    signal.add_log(f"✅ 检测链接通过: 返回大小({content_length}) {true_url}")
                    return content_length if length else true_url

                if response.content and len(response.content) > 0:
                    downloaded_size = len(response.content)
                    if _is_dmm_placeholder_size(downloaded_size):
                        last_error = f"疑似占位图({downloaded_size}B) {true_url}"
                        signal.add_log(f"🔴 检测链接失败: {last_error}")
                        return None
                    signal.add_log(f"✅ 检测链接通过: 预下载成功 {true_url}")
                    return downloaded_size if length else true_url

                last_error = f"未返回大小且预下载失败 {true_url}"
                if retry_attempt < max_retries - 1:
                    signal.add_log(f"🟡 检测链接失败，正在重试 ({retry_attempt + 1}/{max_retries}): {last_error}")
                    await asyncio.sleep(0.6 * (retry_attempt + 1))
                    continue
                signal.add_log(f"🔴 检测链接失败: {last_error}")
                return None
            except Exception as e:
                last_error = str(e)
                if retry_attempt < max_retries - 1:
                    signal.add_log(f"🟡 检测链接异常，正在重试 ({retry_attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(0.6 * (retry_attempt + 1))
                    continue
                signal.add_log(f"🔴 检测链接失败: 未知异常 {e} {normalized}")
                return None

    if last_error:
        signal.add_log(f"🔴 检测链接失败: {last_error}")
    return None


async def get_url_content_length(url: str) -> int | None:
    normalized = normalize_media_url(url)
    if not normalized:
        return None

    retry_delays = [0.5, 1.0, 1.5]

    async with manager.acquire_computed() as computed:
        client = computed.async_client
        if is_dmm_image_url(normalized):
            for attempt, delay in enumerate(retry_delays, start=1):
                response, error = await client.request("GET", normalized, retry_count=1)
                if response is None:
                    if not _should_retry_link_error(error) or attempt == len(retry_delays):
                        return None
                    await asyncio.sleep(delay)
                    continue

                true_url = normalize_media_url(str(response.url))
                if _is_invalid_image_redirect_url(true_url):
                    return None

                if content_length := _parse_content_length(response.headers.get("Content-Length")):
                    return content_length
                if response.content and len(response.content) > 0:
                    return len(response.content)

                if attempt < len(retry_delays):
                    await asyncio.sleep(delay)
            return None

        for attempt, delay in enumerate(retry_delays, start=1):
            response, error = await client.request("HEAD", normalized, retry_count=1)
            if response is not None:
                if content_length := _parse_content_length(response.headers.get("Content-Length")):
                    return content_length
            elif "HTTP 405" in str(error):
                break
            elif not _should_retry_link_error(error) or attempt == len(retry_delays):
                return None

            if attempt < len(retry_delays):
                await asyncio.sleep(delay)

        for attempt, delay in enumerate(retry_delays, start=1):
            response, error = await client.request("GET", normalized, retry_count=1)
            if response is None:
                if not _should_retry_link_error(error) or attempt == len(retry_delays):
                    return None
                await asyncio.sleep(delay)
                continue

            if content_length := _parse_content_length(response.headers.get("Content-Length")):
                return content_length
            if response.content and len(response.content) > 0:
                return len(response.content)

            if attempt < len(retry_delays):
                await asyncio.sleep(delay)
    return None


@overload
async def check_url(url: str, length: Literal[False] = False, real_url: bool = False) -> str | None: ...
@overload
async def check_url(url: str, length: Literal[True] = True, real_url: bool = False) -> int | None: ...
async def check_url(url: str, length: bool = False, real_url: bool = False):
    """
    检测下载链接. 失败时返回 None.

    Args:
        url (str): 要检测的 URL
        length (bool, optional): 是否返回文件大小. Defaults to False.
        real_url (bool, optional): 直接返回真实 URL 不进行后续检查. Defaults to False.
    """
    if not url:
        return None

    if "http" not in url:
        signal.add_log(f"🔴 检测链接失败: 格式错误 {url}")
        return None

    normalized_url = normalize_media_url(url)
    if is_dmm_image_url(normalized_url):
        return await _validate_dmm_image_url(normalized_url, length=length, real_url=real_url)

    max_retries = 3

    async with manager.acquire_computed() as computed:
        client = computed.async_client
        for retry_attempt in range(max_retries):
            try:
                response, error = await client.request("HEAD", normalized_url)

                # 处理请求失败的情况
                if response is None:
                    if retry_attempt < max_retries - 1:
                        signal.add_log(f"🟡 检测链接失败，正在重试 ({retry_attempt + 1}/{max_retries}): {error}")
                        await asyncio.sleep(1 + retry_attempt)  # 指数退避
                        continue
                    else:
                        signal.add_log(f"🔴 检测链接失败: {error}")
                        return None

                # 不输出获取 dmm预览视频(trailer) 最高分辨率的测试结果到日志中
                if response.status_code == 404 and "_w.mp4" in url:
                    return None

                # 返回重定向的url
                true_url = normalize_media_url(str(response.url))
                if real_url:
                    return true_url

                # 检查是否需要登录
                if "login" in true_url:
                    signal.add_log(f"🔴 检测链接失败: 需登录 {true_url}")
                    return None

                # 检查是否带有图片不存在的关键词
                bad_url_keys = ["now_printing", "nowprinting", "noimage", "nopic", "media_violation"]
                for each_key in bad_url_keys:
                    if each_key in true_url:
                        signal.add_log(f"🔴 检测链接失败: 图片已被网站删除 {url}")
                        return None

                # 获取文件大小
                content_length = response.headers.get("Content-Length")
                if not content_length:
                    # 如果没有获取到文件大小，尝试下载数据
                    content, error = await client.get_content(true_url)

                    if content is not None and len(content) > 0:
                        signal.add_log(f"✅ 检测链接通过: 预下载成功 {true_url}")
                        return 10240 if length else true_url
                    signal.add_log(f"🔴 检测链接失败: 未返回大小且预下载失败 {true_url}")
                    return None
                # 如果返回内容的文件大小 < 8k，视为不可用
                if int(content_length) < 8192:
                    signal.add_log(f"🔴 检测链接失败: 返回大小({content_length}) < 8k {true_url}")
                    return None

                signal.add_log(f"✅ 检测链接通过: 返回大小({content_length}) {true_url}")
                return int(content_length) if length else true_url

            except Exception as e:
                if retry_attempt < max_retries - 1:
                    signal.add_log(f"🟡 检测链接异常，正在重试 ({retry_attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(1 + retry_attempt)
                    continue
                else:
                    signal.add_log(f"🔴 检测链接失败: 未知异常 {e} {url}")
                    return None


# tellme.pw AIO 导航页: 同时提供 avmoo(jav)/avsox(javu)/avheat(wav) 三个站点的最新直连地址。
# 页面含 `window.__AIO_SITE_URLS__ = {"jav": "...", "javu": "...", "wav": "..."}`,
# 任一站点路径返回的导航页都包含三站地址, 可互相兜底。
_AIO_SITE_KEYS = {
    "avmoo": ("jav", "https://avmoo.shop"),
    "avsox": ("javu", "https://avsox.click"),
    "avheat": ("wav", "https://avheat.shop"),
}

_AIO_DOMAIN_CACHE: dict[str, tuple[str, float]] = {}
_AIO_DOMAIN_CACHE_LOCK = threading.Lock()
_AIO_DOMAIN_CACHE_TTL = 24 * 3600.0  # 1 天


def _get_cached_aio_domain(site: str) -> str:
    now = time.time()
    with _AIO_DOMAIN_CACHE_LOCK:
        entry = _AIO_DOMAIN_CACHE.get(site)
        if entry and now - entry[1] < _AIO_DOMAIN_CACHE_TTL:
            return entry[0]
    return ""


def _cache_aio_domain(site: str, domain: str) -> None:
    with _AIO_DOMAIN_CACHE_LOCK:
        _AIO_DOMAIN_CACHE[site] = (domain, time.time())


def _parse_aio_site_urls(response: str) -> dict[str, str]:
    """从 tellme.pw 导航页解析 __AIO_SITE_URLS__ 中的站点直连地址。"""
    if not response:
        return {}
    matched = re.findall(r"window\.__AIO_SITE_URLS__\s*=\s*\{([^}]+)\}", response)
    if not matched:
        return {}
    result: dict[str, str] = {}
    for key, value in re.findall(r'"(\w+)"\s*:\s*"((?:\\"|[^"])*)"', matched[0]):
        url = value.replace("\\/", "/").strip()
        if url.startswith("https://"):
            result[key] = url.rstrip("/")
    return result


# madouqu 官方发布页（bitbucket fabuye/madouqu 公告指向）的域名配置，
# 域名变更时官方只需更新 config.js，客户端实时解析即可跟进。
_WANGZHI_CONFIG_URL = "https://wangzhi.icu/config.js"
_MADOUQU_FALLBACK_DOMAINS = ("https://madouqu.shop", "https://madouqu2.sbs", "https://madouqu.sbs")
_MADOUQU_DOMAINS_CACHE: dict[str, tuple[float, list[str]]] = {}
_MADOUQU_DOMAINS_CACHE_LOCK = threading.Lock()
_MADOUQU_DOMAINS_CACHE_TTL = 24 * 3600.0  # 1 天


def _parse_madouqu_domains(response: str) -> list[str]:
    """从发布页 config.js 解析麻豆区 urls 列表，结构见 domainConfig['md']."""
    if not response:
        return []
    block = re.search(r"id:\s*['\"]md['\"].*?urls:\s*\[(.*?)\]", response, re.S)
    if not block:
        return []
    return [url.rstrip("/") for url in re.findall(r"https?://[^\s'\"]+", block.group(1))]


async def get_madouqu_domains() -> list[str]:
    """获取麻豆站当前可用域名列表（发布页实时解析，失败回退静态列表）。"""
    now = time.time()
    with _MADOUQU_DOMAINS_CACHE_LOCK:
        cached = _MADOUQU_DOMAINS_CACHE.get("domains")
        if cached and now - cached[0] < _MADOUQU_DOMAINS_CACHE_TTL:
            return cached[1]
    try:
        async with manager.acquire_computed() as computed:
            response, _ = await computed.async_client.get_text(_WANGZHI_CONFIG_URL)
    except Exception:
        response = None
    domains = _parse_madouqu_domains(response or "")
    with _MADOUQU_DOMAINS_CACHE_LOCK:
        _MADOUQU_DOMAINS_CACHE["domains"] = (now, domains or list(_MADOUQU_FALLBACK_DOMAINS))
    return domains or list(_MADOUQU_FALLBACK_DOMAINS)


async def get_aio_domain(site: str) -> str:
    """获取 tellme.pw AIO 系列站点（avmoo/avsox/avheat）的最新直连地址。

    通过 `tellme.pw/{site}` 导航页解析 `__AIO_SITE_URLS__`，失败时依次尝试
    其它两个站点的导航页兜底；最终回退到已知默认域名。结果带 1 天内存缓存。
    """
    key, fallback = _AIO_SITE_KEYS[site]
    cached = _get_cached_aio_domain(site)
    if cached:
        return cached

    other_sites = [s for s in _AIO_SITE_KEYS if s != site]
    for attempt in (site, *other_sites):
        issue_url = f"https://tellme.pw/{attempt}"
        try:
            async with manager.acquire_computed() as computed:
                response, _ = await computed.async_client.get_text(issue_url)
        except Exception:
            response = None
        if response:
            sites = _parse_aio_site_urls(response)
            domain = sites.get(key)
            if domain:
                _cache_aio_domain(site, domain)
                return domain
    return fallback


# javlibrary 最新直连地址的内存缓存（避免每次刮削都抓 GitHub）
_JAVLIBRARY_DOMAIN_CACHE: dict[str, tuple[str, float]] = {}
_JAVLIBRARY_DOMAIN_CACHE_LOCK = threading.Lock()
_JAVLIBRARY_DOMAIN_CACHE_TTL = 24 * 3600.0  # 1 天

# javlibrary 已知镜像域名（动态获取失败时的回退列表）
_JAVLIBRARY_DOMAINS = [
    "https://www.f101w.com",
    "https://www.c97k.com",
]


def _get_cached_javlibrary_domain() -> str:
    now = time.time()
    with _JAVLIBRARY_DOMAIN_CACHE_LOCK:
        entry = _JAVLIBRARY_DOMAIN_CACHE.get("domain")
        if entry and now - entry[1] < _JAVLIBRARY_DOMAIN_CACHE_TTL:
            return entry[0]
    return ""


def _cache_javlibrary_domain(domain: str) -> None:
    with _JAVLIBRARY_DOMAIN_CACHE_LOCK:
        _JAVLIBRARY_DOMAIN_CACHE["domain"] = (domain, time.time())


def _parse_javlibcom_domain(response: str) -> str:
    """从 github.com/javlibcom 主页提取 `rel="nofollow me"` 链接作为最新直连地址。"""
    if not response:
        return ""
    matched = re.findall(r'rel="nofollow me"[^>]*href="(https?://[^"]+)"', response)
    if not matched:
        matched = re.findall(r'href="(https?://[^"]+)"[^>]*rel="nofollow me"', response)
    for url in matched:
        if "github.com" in url or "githubusercontent" in url:
            continue
        return url.rstrip("/")
    return ""


async def get_javlibrary_domain() -> str:
    """获取 javlibrary 最新直连地址。

    优先从 github.com/javlibcom 用户主页的 `rel="nofollow me"` 链接动态获取，
    带 1 天内存缓存；获取失败时回退到已知镜像域名列表的第一个可用项。
    """
    cached = _get_cached_javlibrary_domain()
    if cached:
        return cached

    domain = ""
    try:
        async with manager.acquire_computed() as computed:
            response, error = await computed.async_client.get_text(
                "https://github.com/javlibcom", headers={"Accept": "text/html"}
            )
        if response is not None:
            domain = _parse_javlibcom_domain(response)
    except Exception:
        domain = ""

    if domain:
        _cache_javlibrary_domain(domain)
        return domain

    # 回退：依次尝试已知镜像域名，返回首个可用的
    for candidate in _JAVLIBRARY_DOMAINS:
        try:
            async with manager.acquire_computed() as computed:
                probe, probe_error = await computed.async_client.request("GET", candidate, timeout=8)
            if probe is not None:
                _cache_javlibrary_domain(candidate)
                return candidate
        except Exception:
            continue
    return _JAVLIBRARY_DOMAINS[0]


async def get_amazon_data(req_url: str) -> tuple[bool, str]:
    """
    获取 Amazon 数据
    """

    def _is_amazon_rate_limited(html_content: str | None, error_text: str | None) -> bool:
        combined = f"{error_text or ''}\n{html_content or ''}".lower()
        if "429" in combined:
            return True
        if "too many requests" in combined:
            return True
        if "http 503" in combined:
            return True
        if "automated access" in combined:
            return True
        return False

    async def _request_with_amazon_throttle(request_headers: dict[str, str]) -> tuple[str | None, str]:
        waited = await _amazon_request_throttle.wait_turn()
        html_info, error = await client.get_text(req_url, headers=request_headers, encoding="utf-8")
        throttled = _is_amazon_rate_limited(html_info, error)
        cooldown, penalty_level, escalated = await _amazon_request_throttle.register_result(throttled=throttled)
        if throttled:
            if escalated:
                signal.add_log(f"🟡 Amazon 命中限流，动态退避 {cooldown:.2f}s (level={penalty_level}) {req_url}")
            elif cooldown >= 0.8:
                signal.add_log(f"🟡 Amazon 限流冷却延续 {cooldown:.2f}s {req_url}")
        elif waited >= 0.6:
            signal.add_log(f"🟡 Amazon 请求自适应等待 {waited:.2f}s {req_url}")
        return html_info, error

    async with manager.acquire_computed() as computed:
        client = computed.async_client
        headers = build_amazon_headers(req_url)
        # 最多重试 3 次。此处之前有一个"失败后用响应体提取 session 再带 cookie 重试"的
        # 分支，但它在 html_info is None 时对空串做 findall 恒返回空，从未生效，已删除。
        html_info, error = await _request_with_amazon_throttle(headers)
        if html_info is None:
            html_info, error = await _request_with_amazon_throttle(headers)
        if html_info is None:
            html_info, error = await _request_with_amazon_throttle(headers)
        if html_info is None:
            return False, error
        if "HTTP 503" in html_info:
            headers = build_amazon_headers(req_url)
            html_info, error = await _request_with_amazon_throttle(headers)
        if html_info is None:
            return False, error
        return True, html_info


async def get_imgsize(url) -> tuple[int, int]:
    async with manager.acquire_computed() as computed:
        client = computed.async_client
        response, _ = await client.request("GET", url, stream=True)
        if response is None:
            return 0, 0
        file_head = BytesIO()
        chunk_size = 1024 * 10
        try:
            if response.status_code != 200:
                return 0, 0
            async for chunk in response.aiter_content(chunk_size):
                file_head.write(chunk)
                try:

                    def _get_size():
                        with Image.open(file_head) as img:
                            return img.size

                    return await asyncio.to_thread(_get_size)
                except Exception:
                    # 如果解析失败，继续下载更多数据
                    continue
        except Exception:
            return 0, 0
        finally:
            await client._close_response(response)

        return 0, 0


async def get_dmm_trailer(trailer_url: str) -> str:
    """
    尝试获取 dmm 最高分辨率预告片.

    Returns:
        str: 有效的最高分辨率预告片 URL.
    """
    # 如果不是 DMM 域名则直接返回
    if ".dmm.co" not in trailer_url:
        return trailer_url

    # 将相对URL转换为绝对URL
    if trailer_url.startswith("//"):
        trailer_url = "https:" + trailer_url

    # 处理临时链接格式（/pv/{temp_key}/{filename}），转换为标准格式
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/asfb00192_mhb_w.mp4
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/1start4814k.mp4
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/n_707agvn001_dmb_w.mp4
    # 标准格式示例: https://cc3001.dmm.co.jp/litevideo/freepv/a/asf/asfb00192/asfb00192_mhb_w.mp4
    if "/pv/" in trailer_url:
        signal.add_log("🔄 检测到临时预告片链接，开始转换...")
        filename_match = re.search(r"/pv/[^/]+/(.+?)(?:\.mp4)?$", trailer_url)
        if filename_match:
            filename_base = filename_match.group(1).replace(".mp4", "")
            # 去掉质量标记后缀
            # 1) 旧格式: _mhb_w / _hhb_w / _4k_w / _dmb_h / _sm_s 等
            # 2) 新格式: hhb / mhb / dmb / dm / sm（无 _w/_s 后缀）
            cid = re.sub(r"(_[a-z0-9]+_[a-z])?$", "", filename_base, flags=re.IGNORECASE)
            cid = re.sub(r"(hhb|mhb|dmb|dm|sm|4k)$", "", cid, flags=re.IGNORECASE)
            # 确保提取到的是有效的产品ID（包含字母和数字）
            if re.search(r"[a-z]", cid, re.IGNORECASE) and re.search(r"\d", cid):
                prefix = cid[0]
                three_char = cid[:3]
                converted_url = (
                    f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
                )
                signal.add_log(f"📝 转换后的URL: {converted_url}")
                # 尝试验证转换后的URL，最多重试3次（仅对非404错误重试）
                async with manager.acquire_computed() as computed:
                    client = computed.async_client
                    for attempt in range(3):
                        try:
                            # 进行HEAD请求检测
                            response, error = await client.request("HEAD", converted_url, retry_count=1)

                            if response is not None:
                                # 请求成功
                                if response.status_code == 404:
                                    # 404错误说明转换后的URL不存在，回退到原始URL
                                    signal.add_log("⚠️ 转换后的URL返回404，回退到原始链接")
                                    break
                                elif 200 <= response.status_code < 300:
                                    # 2xx成功，使用转换后的URL
                                    signal.add_log(f"✅ 转换后的URL验证成功 (HTTP {response.status_code})")
                                    trailer_url = converted_url
                                    break
                                else:
                                    # 其他4xx/5xx错误，继续重试
                                    retry_msg = (
                                        f"🟡 转换后的URL检测失败 (HTTP {response.status_code})，"
                                        f"准备重试 ({attempt + 1}/3)..."
                                    )
                                    signal.add_log(retry_msg)
                                    if attempt < 2:
                                        await asyncio.sleep(0.5 * (attempt + 1))
                                        continue
                                    else:
                                        # 重试3次仍失败，回退到原始URL
                                        signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                                        break
                            else:
                                # 检查是否为 404 错误
                                if "404" in str(error):
                                    # 404错误说明转换后的URL不存在，直接回退
                                    signal.add_log("⚠️ 转换后的URL返回404，回退到原始链接")
                                    break
                                else:
                                    # 其他网络错误、超时等，重试
                                    signal.add_log(f"🟡 转换后的URL网络错误: {error}，准备重试 ({attempt + 1}/3)...")
                                    if attempt < 2:
                                        await asyncio.sleep(0.5 * (attempt + 1))
                                        continue
                                    else:
                                        # 重试3次仍失败，回退到原始URL
                                        signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                                        break
                        except Exception as e:
                            # 异常处理，继续重试
                            signal.add_log(f"🟡 转换后的URL异常: {e}，准备重试 ({attempt + 1}/3)...")
                            if attempt < 2:
                                await asyncio.sleep(0.5 * (attempt + 1))
                                continue
                            else:
                                # 重试3次仍失败，回退到原始URL
                                signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                                break

    """
    DMM 预览片分辨率对应关系（旧格式）:
    '_sm_w.mp4': 320*180, 3.8MB     # 最低分辨率
    '_dm_w.mp4': 560*316, 10.1MB    # 中等分辨率
    '_dmb_w.mp4': 720*404, 14.6MB   # 次高分辨率
    '_mhb_w.mp4': 720*404, 27.9MB
    '_hhb_w.mp4': 更高码率（常见约 60MB）
    '_4k_w.mp4': 最高分辨率

    旧格式其他可能的后缀: _s, _h（如 _sm_s.mp4, _dmb_h.mp4）

    DMM 预览片分辨率对应关系（新格式）:
    'sm.mp4'  < 'dm.mp4' < 'dmb.mp4' < 'mhb.mp4' < 'hhb.mp4' < '4k.mp4'
    常见示例: nima00070sm.mp4 / nima00070dm.mp4 / nima00070dmb.mp4 / nima00070mhb.mp4 / nima00070hhb.mp4 / nima000704k.mp4

    示例:
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_sm_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_dm_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_dmb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_mhb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_hhb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_4k_w.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima00070mhb.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima00070hhb.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima000704k.mp4
    """

    # 旧格式：..._sm_w.mp4 / ..._dmb_h.mp4
    if matched := re.search(r"(.+)_([a-z0-9]+)_([a-z])\.mp4$", trailer_url, flags=re.IGNORECASE):
        base_url, quality_level, suffix_char = matched.groups()
        quality_level = quality_level.lower()
        suffix_char = suffix_char.lower()
        quality_levels = ("sm", "dm", "dmb", "mhb", "hhb", "4k")

        if quality_level in quality_levels:
            current_index = quality_levels.index(quality_level)
            suffix_candidates = (suffix_char,) + tuple(s for s in ("w", "s", "h") if s != suffix_char)
            for i in range(len(quality_levels) - 1, current_index, -1):
                higher_quality = quality_levels[i]
                for test_suffix_char in suffix_candidates:
                    test_url = base_url + f"_{higher_quality}_{test_suffix_char}.mp4"
                    if await check_url(test_url):
                        signal.add_log(
                            f"🎬 DMM trailer 升级(旧格式): {quality_level}_{suffix_char} -> "
                            f"{higher_quality}_{test_suffix_char}"
                        )
                        signal.add_log(f"🎬 DMM trailer URL: {trailer_url} -> {test_url}")
                        return test_url
            signal.add_log(f"🎬 DMM trailer 保持原质量(旧格式): {quality_level}_{suffix_char} {trailer_url}")
        return trailer_url

    # 新格式：...nima00070mhb.mp4 / ...nima00070hhb.mp4（无 _w/_s 后缀）
    if matched := re.search(r"(.+?)(sm|dm|dmb|mhb|hhb|4k)\.mp4$", trailer_url, flags=re.IGNORECASE):
        base_url, quality_level = matched.groups()
        quality_level = quality_level.lower()
        quality_levels = ("sm", "dm", "dmb", "mhb", "hhb", "4k")

        if quality_level in quality_levels:
            current_index = quality_levels.index(quality_level)
            for i in range(len(quality_levels) - 1, current_index, -1):
                higher_quality = quality_levels[i]
                test_url = base_url + f"{higher_quality}.mp4"
                if await check_url(test_url):
                    signal.add_log(f"🎬 DMM trailer 升级(新格式): {quality_level} -> {higher_quality}")
                    signal.add_log(f"🎬 DMM trailer URL: {trailer_url} -> {test_url}")
                    return test_url
            signal.add_log(f"🎬 DMM trailer 保持原质量(新格式): {quality_level} {trailer_url}")

    return trailer_url


def check_version() -> int | None:
    if manager.config.update_check:
        url = GITHUB_RELEASES_API_LIST
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mdcx-update-check",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            timeout = max(float(manager.config.timeout), 5.0)
        except (TypeError, ValueError):
            timeout = 5.0
        configured_proxy = manager.config.proxy.strip() if manager.config.use_proxy and manager.config.proxy else ""
        request_proxies = [configured_proxy] if configured_proxy else []
        request_proxies.append("")

        last_error = ""
        for proxy in dict.fromkeys(request_proxies):
            try:
                client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
                if proxy:
                    client_kwargs["proxy"] = proxy
                with httpx.Client(**client_kwargs) as client:
                    response = client.get(url, headers=headers)
            except Exception as e:
                last_error = str(e)
                continue

            if response.status_code != 200:
                if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                    reset_raw = response.headers.get("x-ratelimit-reset", "")
                    if reset_raw.isdigit():
                        reset_at = time.strftime("%H:%M:%S", time.localtime(int(reset_raw)))
                        last_error = f"GitHub API 限流（403，剩余 0，预计重置 {reset_at}）"
                    else:
                        last_error = "GitHub API 限流（403，剩余 0）"
                else:
                    last_error = f"HTTP {response.status_code}"
                continue

            try:
                releases = response.json()
                if not isinstance(releases, list):
                    last_error = "响应格式异常（非数组）"
                    continue
                for release in releases:
                    tag = str(release.get("tag_name", "")).strip()
                    if tag.isdigit():
                        return int(tag)
                tags = [str(r.get("tag_name", "?")) for r in releases[:5]]
                signal.add_log(f"❌ 未找到 MDCx 版本发布（最近发布: {', '.join(tags)}）")
                return None
            except Exception:
                signal.add_log("❌ 获取最新版本失败！响应解析异常")
                return None

        if last_error:
            signal.add_log(f"❌ 获取最新版本失败！{last_error}")
    return None


def check_theporndb_api_token() -> str:
    tips = "✅ 连接正常! "
    api_token = manager.config.theporndb_api_token
    url = "https://api.theporndb.net/scenes/hash/8679fcbdd29fa735"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if not api_token:
        tips = "❌ 未填写 API Token，影响欧美刮削！可在「设置」-「网络」添加！"
    else:
        try:
            with manager.acquire_computed() as computed:
                response, err = executor.run(computed.async_client.request("GET", url, headers=headers))
        except CancelledError:
            tips = "❌ ThePornDB 连接检查已取消"
            signal.show_log_text(tips)
            return tips
        if response is None:
            tips = f"❌ ThePornDB 连接失败: {err}"
            signal.show_log_text(tips)
            return tips
        if response.status_code == 401 and "Unauthenticated" in str(response.text):
            tips = "❌ API Token 错误！影响欧美刮削！请到「设置」-「网络」中修改。"
        elif response.status_code == 200:
            tips = "✅ 连接正常！" if response.json().get("data") else "❌ 返回数据异常！"
        else:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {response.status_code} {response.text}"
    signal.show_log_text(tips.replace("❌", " ❌ ThePornDB").replace("✅", " ✅ ThePornDB"))
    return tips


async def get_actorname(number: str) -> tuple[bool, str]:
    # 获取真实演员名字
    url = f"https://av-wiki.net/?s={number}"
    async with manager.acquire_computed() as computed:
        res, error = await computed.async_client.get_text(url)
    # 空串会穿透 is None 判定，etree.fromstring("") 返回 None 后 .xpath
    # 抛 AttributeError 打穿 translate_actor（无 try）使整片刮削失败——
    # 演员真名查询是非致命辅助步骤，失败只应降级记日志（全库审查 B2）
    if not res:
        return False, f"Error: 未获取到页面内容 {error or '(空响应)'}"
    html_detail = etree.fromstring(res, etree.HTMLParser(encoding="utf-8"))
    if html_detail is None:
        return False, "Error: 页面内容解析失败"
    actor_box = html_detail.xpath('//ul[@class="post-meta clearfix"]')
    for each in actor_box:
        actor_name = each.xpath('li[@class="actress-name"]/a/text()')
        actor_number = each.xpath('li[@class="actress-name"]/following-sibling::li[last()]/text()')
        if actor_number and (
            actor_number[0].upper().endswith(number.upper()) or number.upper().endswith(actor_number[0].upper())
        ):
            return True, ",".join(actor_name)
    return False, "No Result!"


async def download_file_with_filepath(url: str, file_path: Path, folder_new_path: Path) -> bool:
    if not url:
        return False

    # exist_ok 直接吸收并发竞态（多协程同时建同一目录时 check-then-act 必然 FileExistsError）
    await aiofiles.os.makedirs(folder_new_path, exist_ok=True)
    try:
        if is_spfcas_image_url(url):
            # App CDN 返回加密流，无法流式直写：取回字节解密后再落盘
            async with manager.acquire_computed() as computed:
                content, error = await computed.async_client.get_content(url)
            if not content:
                LogBuffer.log().write(f"\n 🥺 Download failed! {url} {error}")
                return False
            if len(content) > _IMAGE_DOWNLOAD_MAX_BYTES:
                LogBuffer.log().write(f"\n 🥺 Download failed! 图片超过大小上限: {url}")
                return False
            decrypted = decode_spfcas_image_content(url, content)
            if decrypted is None:
                LogBuffer.log().write(f"\n 🥺 Download failed! App CDN 图片解密失败: {url}")
                return False
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(decrypted)
            return True

        async with manager.acquire_computed() as computed:
            if await computed.async_client.download(url, file_path, max_bytes=_IMAGE_DOWNLOAD_MAX_BYTES):
                return True
    except Exception as e:
        LogBuffer.log().write(f"\n 🥺 Download failed! {url}\n    原因: {type(e).__name__}: {e}")
        return False
    LogBuffer.log().write(f"\n 🥺 Download failed! {url}")
    return False


async def download_content_with_filepath(url: str, file_path: Path, folder_new_path: Path) -> bool:
    if not url:
        return False

    # exist_ok 直接吸收并发竞态（多协程同时建同一目录时 check-then-act 必然 FileExistsError）
    await aiofiles.os.makedirs(folder_new_path, exist_ok=True)

    try:
        headers = build_jdbstatic_headers(url) if is_jdbstatic_image_url(url) else None
        log_jdbstatic_request_headers(url, headers)
        async with manager.acquire_computed() as computed:
            content, error = await computed.async_client.get_content(url, headers=headers)
        if not content:
            LogBuffer.log().write(f"\n 🥺 Download failed! {url} {error}")
            return False
        if len(content) > _IMAGE_DOWNLOAD_MAX_BYTES:
            LogBuffer.log().write(f"\n 🥺 Download failed! 图片超过大小上限: {url}")
            return False

        content = decode_spfcas_image_content(url, content)
        if content is None:
            LogBuffer.log().write(f"\n 🥺 Download failed! App CDN 图片解密失败: {url}")
            return False

        is_webp = file_path.suffix.lower() == ".jpg" and ".webp" in url.lower()
        if not is_webp:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)
            return True

        byte_stream = BytesIO(content)
        img = Image.open(byte_stream)
        try:
            if img.mode == "RGBA":
                img = img.convert("RGB")  # type: ignore[assignment]
            img.save(file_path, quality=95, subsampling=0)
        finally:
            img.close()
        return True
    except Exception as e:
        LogBuffer.log().write(f"\n 🥺 Download failed! {url}\n    原因: {type(e).__name__}: {e}")
        return False


async def download_dmm_extrafanart_with_filepath(url: str, file_path: Path, folder_new_path: Path) -> bool:
    if not url:
        return False

    # exist_ok 直接吸收并发竞态（多协程同时建同一目录时 check-then-act 必然 FileExistsError）
    await aiofiles.os.makedirs(folder_new_path, exist_ok=True)

    normalized_url = normalize_media_url(url)
    if _is_invalid_image_redirect_url(normalized_url):
        LogBuffer.log().write(f"\n 💡 DMM image invalid! {url}")
        return False

    try:
        async with manager.acquire_computed() as computed:
            response, error = await computed.async_client.request("GET", normalized_url)
        if response is None:
            LogBuffer.log().write(f"\n 🥺 Download failed! {url} {error}")
            return False

        true_url = normalize_media_url(str(response.url))
        if _is_invalid_image_redirect_url(true_url):
            LogBuffer.log().write(f"\n 💡 DMM image invalid! {true_url}")
            return False

        if not response.content:
            LogBuffer.log().write(f"\n 🥺 Download failed! {url} empty content")
            return False
        if len(response.content) > _IMAGE_DOWNLOAD_MAX_BYTES:
            LogBuffer.log().write(f"\n 🥺 Download failed! 图片超过大小上限: {url}")
            return False

        is_webp = file_path.suffix.lower() == ".jpg" and ".webp" in true_url.lower()
        if not is_webp:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(response.content)
            return True

        byte_stream = BytesIO(response.content)
        img = Image.open(byte_stream)
        try:
            if img.mode == "RGBA":
                img = img.convert("RGB")  # type: ignore[assignment]
            img.save(file_path, quality=95, subsampling=0)
        finally:
            img.close()
        return True
    except Exception as e:
        LogBuffer.log().write(f"\n 🥺 Download failed! {url}\n    原因: {type(e).__name__}: {e}")
        return False


async def download_extrafanart_task(task: tuple[str, Path, Path, str]) -> bool:
    extrafanart_url, extrafanart_file_path, extrafanart_folder_path, extrafanart_name = task
    normalized_url = normalize_media_url(extrafanart_url)
    if is_dmm_image_url(normalized_url):
        downloaded = await download_dmm_extrafanart_with_filepath(
            normalized_url, extrafanart_file_path, extrafanart_folder_path
        )
    else:
        # 优先 App CDN 无水印变体（下载层透明解密），失败（含中段过期 404）回退网页版原图
        downloaded = False
        spfcas_url = jdbstatic_to_spfcas(extrafanart_url)
        if spfcas_url:
            downloaded = await download_content_with_filepath(
                spfcas_url, extrafanart_file_path, extrafanart_folder_path
            )
        if not downloaded:
            downloaded = await download_content_with_filepath(
                extrafanart_url, extrafanart_file_path, extrafanart_folder_path
            )

    if downloaded:
        if await check_pic_async(extrafanart_file_path):
            return True
    else:
        LogBuffer.log().write(f"\n 💡 {extrafanart_name} download failed! ( {extrafanart_url} )")
    return False
