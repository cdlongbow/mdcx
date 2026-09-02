"""ASIN → DMM cid 离线索引：软校验裁决链 v2 第 1 步（tenhow 旁证）。

数据源：tenhow.net 全站爬取的 asin↔cid 结构化映射（2026-08-28 抓取，
36441 条，13/13 抽验正确；2026-09-01 四源校验工程中 367 行零误判实证）。
索引随包分发，运行时零请求查询；对新 ASIN（索引快照后上市的片）自然 miss，
由裁决链第 2 步（标题门）接管。
"""

from __future__ import annotations

import re

_CID_RE = re.compile(r"^(\d*)([a-z]+)(\d+)([a-z]?)[a-z]?$")

_index_cache: dict[str, list[str]] | None = None


def _load_index() -> dict[str, list[str]]:
    global _index_cache
    if _index_cache is None:
        import json

        from ..config.resources import resources

        path = resources.r("userdata/tenhow_asin_cids.json")
        if not path.exists():
            _index_cache = {}
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _index_cache = data if isinstance(data, dict) else {}
            except Exception:
                _index_cache = {}
    return _index_cache


def reset_index_cache_for_test() -> None:
    """测试隔离钩子。"""
    global _index_cache
    _index_cache = None


def get_asin_cids(asin: str) -> list[str]:
    """查 ASIN 关联的 DMM cid 列表（无映射返回空）。"""
    key = str(asin or "").strip().upper()
    if not key:
        return []
    return list(_load_index().get(key, []))


def cid_to_number(cid: str) -> str | None:
    """cid 解析番号（与生产 DMM cid 结构规律对齐）：系列字母大写 + 3 位数字。

    形态 `^(\d*)([a-z]+)(\d+)([a-z]?)$`：可选厂商数字前缀 + 系列 + 数字 + 变体。
    """
    m = _CID_RE.match(str(cid or "").strip())
    if not m:
        return None
    series = m.group(2).upper()
    num = int(m.group(3))
    return f"{series}-{num:03d}"


def _number_key(number: str) -> str:
    key = str(number or "").upper().strip().replace("-", "").replace("_", "").replace(" ", "")
    m = re.match(r"^([A-Z]+)(\d+)$", key)
    if not m:
        return key
    return f"{m.group(1)}{int(m.group(2)):03d}"


def asin_matches_number(asin: str, number: str) -> bool | None:
    """裁决链第 1 步：tenhow cid 旁证。

    Returns:
        True  — cid 反查番号与目标一致（实锤证据）
        False — 有 cid 映射但番号全部不一致（强警示，阻止入库但不直接定罪：
                 索引可能过期/多 cid 行）
        None  — 索引无此 ASIN（新片大概率 miss，移交标题门）
    """
    cids = get_asin_cids(asin)
    if not cids:
        return None
    target = _number_key(number)
    if not target:
        return None
    for cid in cids:
        parsed = cid_to_number(cid)
        if parsed and _number_key(parsed) == target:
            return True
    return False
