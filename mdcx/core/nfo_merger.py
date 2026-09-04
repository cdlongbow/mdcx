"""NFO 合并引擎：重新刮削时按策略合并新数据与本地已有 NFO 数据。

借鉴 javinizer-go internal/nfo 的 MergeStrategy 设计，适配 mdcx 的 CrawlersResult 数据结构。

5 种策略：
- prefer_scraper: 新数据覆盖（当前默认行为）
- prefer_nfo: 本地 NFO 优先，新数据仅填空
- merge_arrays: 数组字段合并去重，标量字段用新数据
- preserve_existing: 本地有值就不动，只写本地没有的字段
- fill_missing_only: 只填完全空的字段（新数据为主，空字段从本地 NFO 补）
"""

import copy

from ..config.enums import NfoMergeStrategy
from ..models.model_types import CrawlersResult

# 关键字段：两源都为空时也不允许空，回退到另一源。
# 注：number 不在此集——合并循环只遍历 _SCALAR_FIELDS（不含 number），
# 且上游 file_crawler 总会用文件番号覆盖 res.number，为其写保护回退
# 是永不触发的死代码，移除防误导（全库审查 M8）
_CRITICAL_FIELDS = {"title"}

# 标量字段列表（字符串）
_SCALAR_FIELDS = (
    "title",
    "originaltitle",
    "originalplot",
    "outline",
    "release",
    "runtime",
    "score",
    "series",
    "studio",
    "publisher",
    "trailer",
    "wanted",
    "year",
    "thumb",
    "poster",
    "mosaic",
)

# 数组字段列表
_ARRAY_FIELDS = ("actors", "all_actors", "tags", "directors", "extrafanart")


def _is_empty(value) -> bool:
    """判断字段值是否为空。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _merge_scalar(
    field_name: str,
    scraped_val,
    nfo_val,
    strategy: NfoMergeStrategy,
) -> tuple:
    """合并标量字段，返回 (合并值, 来源标记)。

    来源标记: "scraper" / "nfo" / "empty"
    """
    scraped_empty = _is_empty(scraped_val)
    nfo_empty = _is_empty(nfo_val)

    # 关键字段保护：两源都空时回退
    if field_name in _CRITICAL_FIELDS:
        if scraped_empty and nfo_empty:
            return scraped_val, "empty"
        if scraped_empty:
            return nfo_val, "nfo"
        if nfo_empty:
            return scraped_val, "scraper"

    # 两源都空
    if scraped_empty and nfo_empty:
        return scraped_val, "empty"

    # 只有一方有值
    if scraped_empty:
        return nfo_val, "nfo"
    if nfo_empty:
        return scraped_val, "scraper"

    # 两源都有值——按策略选择
    match strategy:
        case NfoMergeStrategy.PREFER_SCRAPER | NfoMergeStrategy.MERGE_ARRAYS:
            return scraped_val, "scraper"
        case NfoMergeStrategy.FILL_MISSING_ONLY:
            # "仅填空字段"（UI 名称/models 描述/docstring 三处一致）：新数据为主，
            # 只在刮削结果为空时从本地 NFO 补——与 preserve_existing（本地为主）语义相反。
            # 原实现与 preserve_existing 同分支，导致两策略在 UI 上完全重复且新数据被丢弃。
            return scraped_val, "scraper"
        case NfoMergeStrategy.PREFER_NFO | NfoMergeStrategy.PRESERVE_EXISTING:
            return nfo_val, "nfo"


def _merge_array(
    field_name: str,
    scraped_val: list,
    nfo_val: list,
    strategy: NfoMergeStrategy,
) -> tuple[list, str]:
    """合并数组字段，返回 (合并值, 来源标记)。"""
    scraped_empty = _is_empty(scraped_val)
    nfo_empty = _is_empty(nfo_val)

    if scraped_empty and nfo_empty:
        return list(scraped_val), "empty"

    if scraped_empty:
        return list(nfo_val), "nfo"

    if nfo_empty:
        return list(scraped_val), "scraper"

    # 两源都有值
    match strategy:
        case NfoMergeStrategy.MERGE_ARRAYS:
            # 合并去重，保持 scraped 在前
            merged = list(scraped_val)
            seen = {str(v).strip().lower() for v in merged if not _is_empty(v)}
            for v in nfo_val:
                key = str(v).strip().lower()
                if key and key not in seen:
                    merged.append(v)
                    seen.add(key)
            return merged, "merged"
        case NfoMergeStrategy.PREFER_SCRAPER:
            return list(scraped_val), "scraper"
        case NfoMergeStrategy.PREFER_NFO | NfoMergeStrategy.PRESERVE_EXISTING | NfoMergeStrategy.FILL_MISSING_ONLY:
            return list(nfo_val), "nfo"


def _sync_original_actors(scraped: CrawlersResult, nfo: CrawlersResult, merged: CrawlersResult) -> None:
    """合并后同步 original_actors，使其与 actors 保持位置对应。

    nfo.py 写 `<actor>` 的 tmdbid 时按位置配对 original_actors[i] ↔ actors[i]；
    若合并只改 actors 不改 original_actors（原缺陷），两者错位会把 A 演员的 tmdbid
    写到 B 演员身上。这里按 actors 结果来源对齐 original_actors：
    - actors 完全来自 scraped → original_actors 用 scraped 的
    - actors 完全来自 nfo → original_actors 用 nfo 的（若 nfo 有）
    - 其余（merge 去重等）长度不一致时清空 original_actors，tmdbid 走名字匹配兜底
    """
    merged_actors = merged.actors
    scraped_actors = getattr(scraped, "actors", None) or []
    nfo_actors = getattr(nfo, "actors", None) or []
    scraped_orig = getattr(scraped, "original_actors", None) or []
    nfo_orig = getattr(nfo, "original_actors", None) or []
    if merged_actors == scraped_actors and scraped_orig:
        merged.original_actors = list(scraped_orig)
    elif merged_actors == nfo_actors and nfo_orig:
        merged.original_actors = list(nfo_orig)
    elif len(merged_actors) != len(getattr(merged, "original_actors", None) or []):
        merged.original_actors = []


def merge_nfo_fields(
    scraped: CrawlersResult,
    nfo: CrawlersResult,
    strategy: NfoMergeStrategy,
) -> CrawlersResult:
    """按策略合并 scraped（新抓取数据）和 nfo（本地已有 NFO 数据）。

    返回合并后的 CrawlersResult。当策略为 prefer_scraper 时直接返回 scraped（保持现有行为）。
    """
    if strategy == NfoMergeStrategy.PREFER_SCRAPER:
        return scraped

    if nfo is None:
        return scraped

    merged = copy.deepcopy(scraped)
    stats = {"scraper": 0, "nfo": 0, "merged": 0, "empty": 0}

    # 合并标量字段
    for field_name in _SCALAR_FIELDS:
        scraped_val = getattr(scraped, field_name, "")
        nfo_val = getattr(nfo, field_name, "")
        result_val, source = _merge_scalar(field_name, scraped_val, nfo_val, strategy)
        setattr(merged, field_name, result_val)
        stats[source] = stats.get(source, 0) + 1

    # 合并数组字段
    for field_name in _ARRAY_FIELDS:
        scraped_val = getattr(scraped, field_name, [])
        nfo_val = getattr(nfo, field_name, [])
        result_val, source = _merge_array(field_name, scraped_val, nfo_val, strategy)
        setattr(merged, field_name, result_val)
        stats[source] = stats.get(source, 0) + 1

    # actors 合并后同步 original_actors，避免写入时按位置配对 tmdbid 错配
    _sync_original_actors(scraped, nfo, merged)

    # 合并 actor_tmdb_ids
    if nfo.actor_tmdb_ids:
        for name, tmdb_id in nfo.actor_tmdb_ids.items():
            if name not in merged.actor_tmdb_ids:
                merged.actor_tmdb_ids[name] = tmdb_id

    # 合并 external_ids（保留两源的 external_id）
    if nfo.external_ids:
        for site, ext_id in nfo.external_ids.items():
            if site not in merged.external_ids:
                merged.external_ids[site] = ext_id

    # 更新 field_sources 溯源：被 NFO 覆盖的字段标记来源为 "local"
    for field_name in _SCALAR_FIELDS + _ARRAY_FIELDS:
        scraped_val = getattr(scraped, field_name, None)
        nfo_val = getattr(nfo, field_name, None)
        _, source = (
            _merge_scalar(field_name, scraped_val, nfo_val, strategy)
            if field_name in _SCALAR_FIELDS
            else _merge_array(field_name, scraped_val or [], nfo_val or [], strategy)
        )
        if source in ("nfo", "merged"):
            try:
                from ..gen.field_enums import CrawlerResultFields

                field_enum = (
                    CrawlerResultFields(field_name) if field_name in [f.value for f in CrawlerResultFields] else None
                )
                if field_enum:
                    merged.field_sources[field_enum] = "local"
            except (ValueError, KeyError):
                pass

    from ..models.log_buffer import LogBuffer

    LogBuffer.log().write(
        f"\n 🔄 [NFO合并] 策略: {strategy.value} | "
        f"scraper={stats['scraper']} nfo={stats['nfo']} merged={stats['merged']} empty={stats['empty']}"
    )

    return merged
