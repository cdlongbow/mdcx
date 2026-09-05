"""番号 -> DMM 官方 CDN 高清图直链构造。

DMM 官方高清封面托管在 awsimgsrc CDN，URL 规律:
    https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg   (横版高清, 如 2184x1469)
    https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}ps.jpg   (竖版高清, 如 1032x1469)

cid = {mPrefix}{series}{编号}，mPrefix 由品牌(series)决定，不同品牌有各自的目录前缀。
该 CDN 对不存在的图直接返回 404(区别于 pics.dmm.co.jp 返回占位图)，适合做无爬虫直连兜底。

静态路由种子（resources/userdata/dmm_cid_routes.json，libredmm 全站 23472 页
58.9 万番号↔cid 对归纳）：series -> [{prefix, cid_series, 变体, 补零位数, 路径}]，
覆盖 9627 个系列 96.5% 直构命中；剩余重编号番号走 2 万条白名单逐条映射。
mono 老片路径的图托管在 pics.dmm.co.jp 低清图床（占位图由
_validate_dmm_image_url 的 <4KB 拒收兜底），digital 新片仍走 awsimgsrc 高清。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_DMM_CDN_BASE = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video"
_DMM_PICS_BASE = "https://pics.dmm.co.jp"

_PREFIX_GROUPS: dict[str, list[str]] = {
    "": [
        "adn",
        "bf",
        "cawd",
        "cnd",
        "dasd",
        "dvdms",
        "ebod",
        "eyan",
        "gdhh",
        "hibl",
        "hmn",
        "hnd",
        "hntd",
        "ipit",
        "ipvr",
        "ipx",
        "ipzz",
        "jue",
        "jufd",
        "juk",
        "jul",
        "jux",
        "juy",
        "juq",
        "kawd",
        "meyd",
        "miab",
        "miad",
        "mibd",
        "mide",
        "midv",
        "mifd",
        "mtsp",
        "mudr",
        "mukd",
        "mvsd",
        "mymd",
        "nima",
        "ofje",
        "onsd",
        "pred",
        "rki",
        "sone",
        "sora",
        "ssis",
        "ssni",
        "waaa",
    ],
    "1": [
        "dandy",
        "dism",
        "dldss",
        "dvdes",
        "fcdss",
        "fset",
        "fsdss",
        "gs",
        "hunt",
        "kmhrs",
        "mmgh",
        "rct",
        "rctd",
        "sdab",
        "sdam",
        "sdde",
        "sdjs",
        "sdmf",
        "sdmm",
        "sdms",
        "sdmt",
        "sdmu",
        "sdfk",
        "sdnm",
        "star",
        "stars",
        "start",
        "svdvd",
        "sw",
        "vandr",
    ],
    "3": ["wanz"],
    "13": ["ayb", "gg", "gvg", "gvh", "ovg"],
    "17": ["bkd"],
    "18": ["momj", "ntrd"],
    "41": ["dok"],
    "42": ["sma"],
    "49": ["avop", "madm"],
    "55": ["t28"],
    "77": ["cre"],
    "118": ["onez"],
    "143": ["ppd", "umd"],
    "433": ["mbd"],
    "436": ["abf"],
    "5642": ["hodv"],
    "h_068": ["mxgs"],
    "h_113": ["ggg"],
    "h_205": ["ssnd"],
    "h_491": ["fone"],
    "h_1100": ["hzgd"],
    "h_1240": ["milk"],
    "h_1324": ["skmj"],
    "h_1371": ["zmen"],
    "h_1374": ["ksvr"],
    "h_1454": ["bdsr", "husr"],
    "h_189": ["ymd"],
    "h_237": ["nact"],
    "h_910": ["vrtm"],
    "h_995": ["bokd"],
}

# 同名系列跨厂商/跨编号段前缀不同，附加候选前缀兜底
_EXTRA_PREFIXES: dict[str, list[str]] = {
    "sw": ["h_113"],
    "bdsr": ["57"],
    "husr": ["57"],
    "sma": ["83"],
}

_SPECIAL_THRESHOLDS: dict[str, tuple[int, str, str]] = {
    "avop": (168, "", "1"),
    "gigl": (643, "h_860", ""),
    "ekdv": (655, "49", ""),
}

_COMMON_PREFIXES: list[str] = ["", "1", "13", "49", "436", "118", "55", "57", "83", "5642"]


_DIGIT_SERIES: list[str] = sorted(
    {series for members in _PREFIX_GROUPS.values() for series in members if any(ch.isdigit() for ch in series)},
    key=len,
    reverse=True,
)


def _parse_number(number: str) -> list[tuple[str, int, str]]:
    cleaned = number.lower().strip().replace("-", "").replace(" ", "")
    for series in _DIGIT_SERIES:
        if cleaned.startswith(series):
            rest = cleaned[len(series) :]
            if rest.isdigit() and rest:
                return [(series, int(rest), f"{int(rest):05d}")]
    m = re.match(r"^([a-z]+)(\d+)$", cleaned)
    if not m:
        return []
    series, digits = m.group(1), m.group(2)
    return [(series, int(digits), f"{int(digits):05d}")]


def _prefixes_for(series: str, num: int) -> list[str]:
    extra = _EXTRA_PREFIXES.get(series, [])
    if series in _SPECIAL_THRESHOLDS:
        threshold, small_prefix, large_prefix = _SPECIAL_THRESHOLDS[series]
        prefix = small_prefix if num <= threshold else large_prefix
        return list(dict.fromkeys([prefix] + extra))
    for group_prefix, members in _PREFIX_GROUPS.items():
        if series in members:
            return list(dict.fromkeys([group_prefix, ""] + extra))
    return list(dict.fromkeys(_COMMON_PREFIXES + extra))


def _learned_prefixes_for(series: str) -> tuple[list[str], list[str]]:
    """查询学习表得到 (verified, provisional) 前缀，异常时返回空避免影响主流程。"""
    try:
        from mdcx.crawlers.dmm_prefix_learn import get_learned_prefixes

        return get_learned_prefixes(series)
    except Exception:
        return [], []


# ===== 静态路由种子（libredmm 全站归纳） =====
_routes_lock = threading.Lock()
_routes_loaded = False
_routes_rules: dict[str, list[dict[str, Any]]] = {}
_routes_whitelist: dict[str, dict[str, str]] = {}


def _routes_seed_path() -> Path | None:
    try:
        from mdcx.config.resources import Resources

        resources = Resources()
        path = resources.r("userdata/dmm_cid_routes.json")
        return path if path.is_file() else None
    except Exception:
        return None


def _load_routes() -> None:
    """惰性加载静态路由种子；任何异常静默降级为空表（不影响既有候选链）。"""
    global _routes_loaded
    if _routes_loaded:
        return
    with _routes_lock:
        if _routes_loaded:
            return
        path = _routes_seed_path()
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rules = data.get("rules")
                whitelist = data.get("whitelist")
                if isinstance(rules, dict):
                    _routes_rules.update(rules)
                if isinstance(whitelist, dict):
                    _routes_whitelist.update(whitelist)
            except Exception:
                return
        _routes_loaded = True


def reset_routes_for_testing() -> None:
    """测试复位：清空静态路由表与加载状态。"""
    global _routes_loaded
    with _routes_lock:
        _routes_rules.clear()
        _routes_whitelist.clear()
        _routes_loaded = False


def _route_cids_for(series: str, num: int) -> list[str]:
    """按静态路由规则生成候选 cid（prefix×pads 全枚举）。

    规则键为番号系列大写（归纳口径），生产 _parse_number 返回小写，这里统一大写查表。
    v2 种子规则带 mode：first（未进生产静态表的系列，候选置首位）/ append
    （静态表已精确覆盖的系列，候选追加在静态表候选之后作兜底——老片 3 位
    补零形态静态表给不出，如 GVG-564 真实 cid 是 mono 的 13gvg564）。
    """
    entry = _routes_rules.get(series.upper())
    if not isinstance(entry, dict):
        return []
    cids: list[str] = []
    for combo in entry.get("combos", []):
        prefix = str(combo.get("p", ""))
        cid_series = str(combo.get("s", ""))
        if not cid_series:
            continue
        for pad in combo.get("pads", []):
            if not isinstance(pad, int) or pad <= 0:
                continue
            cids.append(f"{prefix}{cid_series}{num:0{pad}d}")
    return cids


def _route_mode(series: str) -> str:
    """路由模式：first=候选置首（系列未被静态表覆盖），append=追加兜底。"""
    entry = _routes_rules.get(series.upper())
    if not isinstance(entry, dict):
        return "first"
    return str(entry.get("mode", "first"))


def _whitelist_entry(number: str) -> dict[str, str] | None:
    """查白名单（重编号番号 -> cid/path 逐条映射），未命中返回 None。

    白名单键为 libredmm 番号原形态（如 04IDLD-01 / 000_339）；
    调用方传入的番号可能带连字符/空格差异，这里同时尝试原串与规范化形态。
    """
    if not number:
        return None
    _load_routes()
    cleaned = number.strip()
    norm = _normalize_dmm_number(cleaned)
    for key in (cleaned, cleaned.upper(), cleaned.lower(), norm, norm.upper()):
        entry = _routes_whitelist.get(key)
        if isinstance(entry, dict):
            return entry
    return None


def generate_cid_candidates(number: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    # 白名单（重编号番号）优先：全站归纳无法用规则表达，直接逐条映射
    wl = _whitelist_entry(number)
    if wl is not None:
        cid = str(wl.get("cid", ""))
        if cid:
            return [cid]
    _load_routes()
    for series, num, padded in _parse_number(number):
        learned_verified, learned_provisional = _learned_prefixes_for(series)
        static_prefixes = _prefixes_for(series, num)
        route_cids = _route_cids_for(series, num)
        if _route_mode(series) == "first" and route_cids:
            # 未进静态表的系列：路由候选一步直达（静态表盲枚举变直达）
            prefix_order = [*route_cids, *learned_verified, *static_prefixes, *learned_provisional]
        else:
            # 静态表已覆盖系列：静态表候选保序在前，路由候选（老片 3 位等形态）追加兜底
            prefix_order = [*learned_verified, *static_prefixes, *route_cids, *learned_provisional]
        for prefix in prefix_order:
            cid = prefix if route_cids and prefix in route_cids else f"{prefix}{series}{padded}"
            if cid not in seen:
                seen.add(cid)
                candidates.append(cid)
    return candidates


def generate_image_candidates(number: str) -> list[tuple[str, str]]:
    """返回 (orientation, url) 候选。orientation 为 landscape(横版 pl) 或 portrait(竖版 ps)。

    digital 路径（新片）走 awsimgsrc 高清；mono 路径（老片）走 pics.dmm.co.jp 低清
    原图床（占位图由 _validate_dmm_image_url <4KB 拒收兜底）。
    """
    # 白名单命中：直接按记录的真实 cid + 路径生成唯一候选对
    wl = _whitelist_entry(number)
    if wl is not None:
        cid = str(wl.get("cid", ""))
        path = str(wl.get("path", "digital/video")) or "digital/video"
        if cid:
            if path.startswith("digital"):
                base = f"{_DMM_CDN_BASE}/{cid}/{cid}"
            else:
                base = f"{_DMM_PICS_BASE}/{path}/{cid}/{cid}"
            return [("portrait", f"{base}ps.jpg"), ("landscape", f"{base}pl.jpg")]
    _load_routes()
    candidates: list[tuple[str, str]] = []
    for cid in generate_cid_candidates(number):
        candidates.append(("portrait", f"{_DMM_CDN_BASE}/{cid}/{cid}ps.jpg"))
        candidates.append(("landscape", f"{_DMM_CDN_BASE}/{cid}/{cid}pl.jpg"))
    # mono 路径补充：静态路由标记了 mono path 的系列，追加低清图床候选
    # （老片真实图在 pics.dmm.co.jp，awsimgsrc 高清 CDN 仅覆盖 digital）
    for series, num, _padded in _parse_number(number):
        entry = _routes_rules.get(series.upper())
        if not isinstance(entry, dict):
            continue
        for combo in entry.get("combos", []):
            paths = combo.get("paths") or []
            mono_path = next((p for p in paths if str(p).startswith("mono")), None)
            if mono_path is None:
                continue
            prefix = str(combo.get("p", ""))
            cid_series = str(combo.get("s", ""))
            if not cid_series:
                continue
            pads = combo.get("pads", [])
            # mono 组合里 pads 全部 ≤3 时，该 mono 形态归属「老片的 CID 空间」，对新片
            # 毫无意义。SSIS 的 5 条 mono 组合全是 pad=3（纯老片形态），把 742 号
            # 新片映射过去必然 404 且不断重试（议题：刮削变慢，「图片已被网站删除」）。
            # 组合里若同时存在 ≥4 位的 pad（如 GVG 的 pad=3+5 混合真实老片），保留 mono 输出。
            if pads and all(p <= 3 for p in pads if isinstance(p, int)):
                continue
            for pad in pads:
                if not isinstance(pad, int) or pad <= 0:
                    continue
                cid = f"{prefix}{cid_series}{num:0{pad}d}"
                base = f"{_DMM_PICS_BASE}/{mono_path}/{cid}/{cid}"
                candidates.append(("portrait", f"{base}ps.jpg"))
                candidates.append(("landscape", f"{base}pl.jpg"))
    # 去重（保持顺序）
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for orient, url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append((orient, url))
    return unique


_UNCENSORED_PREFIXES = ("FC2", "HEYZO", "1PONDO", "CARIB", "10MUCH", "200GANA", "PACO", "MKD", "MIUM")

_DMM_UPGRADE_CACHE_TTL = 10 * 60
_DMM_UPGRADE_CACHE_MAX = 4096
_dmm_upgrade_cache: dict[str, tuple[float, str | None, str | None]] = {}
_dmm_upgrade_pending: dict[tuple[int, str], asyncio.Future[Any]] = {}
_dmm_cache_lock = threading.Lock()


def _normalize_dmm_number(number: str) -> str:
    return re.sub(r"[^a-z0-9]", "", number.lower())


def _clear_dmm_upgrade_cache() -> None:
    """清空升级缓存与 in-flight 表（测试复位用）。"""
    with _dmm_cache_lock:
        _dmm_upgrade_cache.clear()
        _dmm_upgrade_pending.clear()


def _prune_dmm_upgrade_cache(now: float) -> None:
    if len(_dmm_upgrade_cache) < _DMM_UPGRADE_CACHE_MAX:
        return
    expired = [key for key, (ts, _, _) in _dmm_upgrade_cache.items() if now - ts >= _DMM_UPGRADE_CACHE_TTL]
    for key in expired:
        _dmm_upgrade_cache.pop(key, None)


def is_uncensored_number(number: str) -> bool:
    """DMM 是有码源，判断番号是否为明显无码（含 `_` 或命中无码前缀），用于跳过 DMM 候选."""
    if "_" in number:
        return True
    return (number or "").upper().replace(" ", "").startswith(_UNCENSORED_PREFIXES)


def build_aws_cover_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清封面 (thumb/pl.jpg) 候选 URL 列表.

    复用番号→DMM cid 构造器，取横版 pl 候选。
    """
    return [url for orient, url in generate_image_candidates(number) if orient == "landscape"]


def build_aws_poster_candidates(number: str) -> list[str]:
    """从番号构造 DMM 高清海报 (poster/ps.jpg) 候选 URL 列表.

    复用番号→DMM cid 构造器，取竖版 ps 候选。
    """
    return [url for orient, url in generate_image_candidates(number) if orient == "portrait"]


async def find_valid_dmm_cover(number: str) -> str | None:
    """尝试为番号找到一张可用的 DMM 高清横版封面（pl.jpg）.

    全部站点图源失败时作兜底：按番号直构 DMM CDN 候选，逐个校验存在且为高清。
    无码番号或候选全部失效时返回 None。

    复用 check_url（DMM 图自动走 GET 验证）+ _is_dmm_hd_image（分辨率过滤缩略图占位图）。
    """
    from mdcx.base.web import check_url

    if not number or is_uncensored_number(number):
        return None
    for url in build_aws_cover_candidates(number):
        if await check_url(url) and await _is_dmm_hd_image(url):
            return url
    return None


_DMM_HD_MIN_WIDTH = 700


async def _is_dmm_hd_image(url: str) -> bool:
    """校验 DMM 图是否存在且为高清（宽≥700）.

    awsimgsrc 同一 URL 格式下会返回 147x200 缩略图或 745x1081/1032x1469 高清图，
    仅 check_url 验存在无法区分，需读取分辨率过滤缩略图占位图。
    """
    from mdcx.base.web import get_imgsize

    width, _height = await get_imgsize(url)
    return width >= _DMM_HD_MIN_WIDTH


def _record_learn_evidence(number: str, candidates: list[str]) -> None:
    """从命中的 DMM 候选 URL 提取 cid 并写入学习表（静默失败不影响主流程）。

    只学习 digital/video 路径的 URL——mono/movie/adult 路径的 cid 前缀
    （如老片的 77ssis/88ssis）属于独立编号空间，学到会污染新片的数字
    前缀探测，表现为每张图多等几次 mono 路径 404。
    """
    try:
        from mdcx.crawlers.dmm_prefix_learn import record_success

        for url in candidates:
            if not url:
                continue
            # https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}ps.jpg
            segments = url.rstrip("/").split("/")
            # digital/video 形如 [...、"digital", "video", "<cid>", "<cid>ps.jpg"]
            if len(segments) >= 4 and segments[-4] == "digital" and segments[-3] == "video":
                cid = segments[-2]
                if cid:
                    record_success(number, cid)
                    return
    except Exception:
        return


async def upgrade_dmm_cover(ctx, number: str, cover_url: str, poster_url: str) -> tuple[str, str]:
    """尝试将爬虫低清/水印图升级为 DMM 高清 ps/pl，返回 (cover, poster).

    复用 dmm_direct 生成 awsimgsrc 高清候选，check_url 验证成功后覆盖，
    失败回退原图。无码番号直接跳过。

    探测结果按规范化番号进程内 TTL 缓存（成功缓存高清 URL，失败缓存 None），
    并对同事件循环的并发调用做 in-flight 合并，避免 javbus/javdb/r18dev 等
    站点并行刮削同一番号时重复探测相同候选。
    """
    from mdcx.base.web import check_url

    number = (number or "").strip()
    if not number or is_uncensored_number(number):
        return cover_url, poster_url
    norm = _normalize_dmm_number(number)
    now = time.monotonic()
    with _dmm_cache_lock:
        cached = _dmm_upgrade_cache.get(norm)
    if cached is not None and now - cached[0] < _DMM_UPGRADE_CACHE_TTL:
        cached_cover, cached_poster = cached[1], cached[2]
        if cached_cover and cached_cover != cover_url:
            ctx.debug(f"封面命中 DMM 升级缓存: {cached_cover}")
        return (cached_cover or cover_url), (cached_poster or poster_url)

    loop = asyncio.get_running_loop()
    key = (id(loop), norm)
    with _dmm_cache_lock:
        pending = _dmm_upgrade_pending.get(key)
    if pending is not None and not pending.done():
        return await pending

    future = loop.create_future()
    with _dmm_cache_lock:
        _dmm_upgrade_pending[key] = future
    try:
        cover_found = ""
        cover_candidates = build_aws_cover_candidates(number)
        for url in cover_candidates:
            if await check_url(url) and await _is_dmm_hd_image(url):
                cover_found = url
                break
        poster_found = ""
        poster_candidates = build_aws_poster_candidates(number)
        for url in poster_candidates:
            if await check_url(url) and await _is_dmm_hd_image(url):
                poster_found = url
                break
        if cover_found:
            _record_learn_evidence(number, cover_candidates)
        if poster_found:
            _record_learn_evidence(number, poster_candidates)
        if cover_found and cover_found != cover_url:
            ctx.debug(f"封面升级为高清: {cover_found}")
        if poster_found and poster_found != poster_url:
            ctx.debug(f"海报升级为高清竖版: {poster_found}")
        result = (cover_found or cover_url), (poster_found or poster_url)
        now = time.monotonic()
        with _dmm_cache_lock:
            _dmm_upgrade_cache[norm] = (now, cover_found or None, poster_found or None)
            _prune_dmm_upgrade_cache(now)
        if not future.done():
            future.set_result(result)
        return result
    except BaseException as exc:
        if not future.done():
            future.set_exception(exc)
        raise
    finally:
        with _dmm_cache_lock:
            _dmm_upgrade_pending.pop(key, None)
