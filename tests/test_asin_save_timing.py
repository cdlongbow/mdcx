"""软校验 v2 入库时序哨兵：soft 路径的入库只发生在 web 采信点，搜索阶段不得提前写库。"""

from __future__ import annotations

import ast


def _load(path: str) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def test_amazon_soft_paths_do_not_save_early():
    """amazon.py 中 soft 路径（barcode_weak/soft/actor_fallback/低清）不再调用 _save_asin_record。

    v2 设计：入库延迟到 web.py 采信点（_save_verified_asin_record），
    通过裁决才写库。barcode hard 两处保留（免验路径，发现即入库）。
    """
    tree = _load("mdcx/core/amazon.py")
    calls = []
    for node in ast.walk(tree):
        call = node.value if isinstance(node, ast.Await) else (node if isinstance(node, ast.Call) else None)
        if (
            call is not None
            and isinstance(call.func, ast.Name)
            and call.func.id == "_save_asin_record"
            and isinstance(node, ast.Await)
        ):
            calls.append(call.lineno)
    assert len(calls) == 2, f"amazon.py 应仅剩 barcode hard 两处入库, 实际 {len(calls)}: {calls}"


def test_web_accept_point_saves_verified_record():
    """web.py 采信分支调用 _save_verified_asin_record（延迟入库挂载点）"""
    tree = _load("mdcx/core/web.py")
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "_save_verified_asin_record":
                found = True
                break
    assert found, "web.py 采信点应调用 _save_verified_asin_record"


def test_match_state_carries_title_and_keyword():
    """_set_amazon_match_state 签名含 title 与 search_keyword（v2 采信入库素材）"""
    tree = _load("mdcx/core/amazon.py")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_set_amazon_match_state":
            args = [a.arg for a in node.args.kwonlyargs]
            assert "title" in args, "match state 应携带 title（标题门证据+入库素材）"
            assert "search_keyword" in args, "match state 应携带 search_keyword（入库素材）"
            return
    raise AssertionError("未找到 _set_amazon_match_state")
