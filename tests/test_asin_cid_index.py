"""ASIN cid 索引测试：装载 / 反查 / 裁决三态。"""

from mdcx.core.asin_cid_index import (
    asin_matches_number,
    cid_to_number,
    get_asin_cids,
    reset_index_cache_for_test,
)


def test_get_asin_cids_known_and_missing():
    reset_index_cache_for_test()
    # 索引内已知映射（抽验正确过的样例）
    cids = get_asin_cids("B081DYPZ13")
    assert cids == ["mifd00093"]
    # ASIN 大小写不敏感
    assert get_asin_cids("b081dypz13") == ["mifd00093"]
    # 无映射返回空
    assert get_asin_cids("B000TEST00") == []
    assert get_asin_cids("") == []


def test_cid_to_number_forms():
    """cid → 番号解析：5 位补零 digital / 3 位 mono / 带厂商前缀"""
    assert cid_to_number("mifd00093") == "MIFD-093"
    assert cid_to_number("13gvg564") == "GVG-564"
    assert cid_to_number("24ped00030") == "PED-030"
    assert cid_to_number("ipzz00020") == "IPZZ-020"
    assert cid_to_number("garbage") is None
    assert cid_to_number("") is None


def test_asin_matches_number_three_states():
    reset_index_cache_for_test()
    # 一致 → True（实锤）
    assert asin_matches_number("B081DYPZ13", "MIFD-93") is True
    assert asin_matches_number("B081DYPZ13", "mifd093") is True
    # 有映射但不一致 → False（强警示）
    assert asin_matches_number("B081DYPZ13", "SSIS-001") is False
    # 无映射 → None（移交标题门）
    assert asin_matches_number("B000TEST00", "MIFD-093") is None
    # 空番号 → None
    assert asin_matches_number("B081DYPZ13", "") is None


def test_index_reload_after_reset():
    """reset 后重新装载（缓存隔离有效性）"""
    reset_index_cache_for_test()
    assert get_asin_cids("B082PVYPVK") == ["mifd00096"]
