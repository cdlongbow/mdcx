"""ASIN 入库让位规则测试：同番号竞争时正品优先，特典唯一时正常入库。

语义（2026-09-02 用户裁定）：
- 特典/限定版图是真的——唯一 ASIN 时正常入库使用
- 同番号已有记录 + 新记录是正品 + 旧记录是特典 → 替换（让位）
- 同番号已有记录 + 新记录是特典 → 跳过（现状先到先得保留）
- 同番号已有记录 + 新旧同类 → 跳过（现状）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mdcx.core.title_match import is_bonus_edition


def _write_row(path: Path, number: str, asin: str, title: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["影片番号", "ASIN 编号", "影片链接", "商品标题", "封面 URL", "搜索关键词"])
    ws.append(
        (
            number,
            asin,
            f"https://www.amazon.co.jp/dp/{asin}",
            title,
            "https://m.media-amazon.com/images/I/TEST.jpg",
            "k",
        )
    )
    wb.save(path)


@pytest.mark.asyncio
async def test_standard_replaces_bonus_existing(monkeypatch, tmp_path):
    """正品替换已入库的特典版（让位方向：正 → 特占位时换正）"""
    db = tmp_path / "asin.xlsx"
    _write_row(db, "IPX-315", "B07QM6BXC5", "【メーカー特典あり】音羽るい AVデビュー [DVD]")

    from mdcx.core import amazon as amazon_mod

    # 直接测 _decide_save_outcome 的三态决策函数（不落盘, 纯判定）
    existing_title = "【メーカー特典あり】音羽るい AVデビュー [DVD]"
    new_title = "音羽るい AVデビュー [DVD]"
    outcome = amazon_mod._decide_save_outcome(existing_title=existing_title, new_title=new_title)
    assert outcome == "replace", "正品应替换特典占位"


@pytest.mark.asyncio
async def test_bonus_skipped_when_standard_exists():
    """特典遇正品占位：跳过（现状保留）"""
    from mdcx.core import amazon as amazon_mod

    outcome = amazon_mod._decide_save_outcome(
        existing_title="音羽るい AVデビュー [DVD]",
        new_title="【メーカー特典あり】音羽るい AVデビュー [DVD]",
    )
    assert outcome == "skip"


@pytest.mark.asyncio
async def test_same_kind_skipped():
    """新旧同类：跳过（先到先得）"""
    from mdcx.core import amazon as amazon_mod

    assert amazon_mod._decide_save_outcome("A片名 [DVD]", "A片名 [DVD]") == "skip"
    assert amazon_mod._decide_save_outcome("【特典】A [DVD]", "【限定版】A [DVD]") == "skip"


def test_bonus_detection_words():
    """让位判定依赖的特典词表"""
    assert is_bonus_edition("【メーカー特典あり】タイトル")
    assert not is_bonus_edition("通常タイトル [DVD]")
