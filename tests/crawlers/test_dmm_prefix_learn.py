"""dmm_prefix_learn 学习表单元测试。

测试环境下 mdcx.config.resources 被 conftest 替换为 _DummyResources（无
_userdata_base），_cache_path() 返回 None，学习表默认静默跳过。本测试通过
monkeypatch _cache_path 指向临时目录来验证状态机与持久化。
"""

import pytest

from mdcx.crawlers import dmm_prefix_learn


@pytest.fixture
def _isolated_learn(monkeypatch: pytest.MonkeyPatch, tmp_path):
    dmm_prefix_learn.reset_for_testing()
    monkeypatch.setattr(dmm_prefix_learn, "_cache_path", lambda: tmp_path / "dmm_prefix_learned.json")
    yield
    dmm_prefix_learn.reset_for_testing()


def test_dmm_monopath_url_not_learned(monkeypatch: pytest.MonkeyPatch, _isolated_learn):
    """mono/movie/adult 路径的 cid（老片前缀形态）不得写入学习表。

    实证：mono 形态的 cid（如 77ssis742）与新片 digital 形态（ssis00742）
    是两个不同的编号空间；它们混学后旧前缀会被错误应用到新片，造成
    无损每张图的 mono 路径 404 试探。
    """
    from mdcx.crawlers import dmm_direct

    recorded = []
    monkeypatch.setattr(dmm_prefix_learn, "record_success", lambda number, cid: recorded.append((number, cid)))

    # mono 路径（老片）：不应学习
    dmm_direct._record_learn_evidence("ssis-742", ["https://pics.dmm.co.jp/mono/movie/adult/77ssis742/77ssis742ps.jpg"])
    assert recorded == []

    # digital 路径（新片）：正常学习
    dmm_direct._record_learn_evidence(
        "ssis-742", ["https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00742/ssis00742ps.jpg"]
    )
    assert recorded == [("ssis-742", "ssis00742")]


def test_record_success_promotes_after_two_codes(_isolated_learn):
    dmm_prefix_learn.record_success("sone-833", "sone00833")
    assert dmm_prefix_learn.get_learned_prefixes("sone") == ([], [""])  # 空前缀 sone，provisional
    dmm_prefix_learn.record_success("sone-900", "sone00900")
    verified, provisional = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" in verified
    assert "" not in provisional


def test_record_success_learns_prefixed_prefix(_isolated_learn):
    # MILK 的 DMM 前缀是 h_1240
    dmm_prefix_learn.record_success("milk-100", "h_1240milk00100")
    dmm_prefix_learn.record_success("milk-101", "h_1240milk00101")
    verified, _ = dmm_prefix_learn.get_learned_prefixes("milk")
    assert "h_1240" in verified


def test_failure_quarantines_verified_prefix(_isolated_learn):
    dmm_prefix_learn.record_success("sone-833", "sone00833")
    dmm_prefix_learn.record_success("sone-900", "sone00900")
    assert "" in dmm_prefix_learn.get_learned_prefixes("sone")[0]
    for _ in range(3):
        dmm_prefix_learn.record_failure("sone-900", "sone00900")
    verified, _ = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" not in verified


def test_failure_does_not_quarantine_provisional(_isolated_learn):
    dmm_prefix_learn.record_success("sone-833", "sone00833")
    for _ in range(5):
        dmm_prefix_learn.record_failure("sone-833", "sone00833")
    verified, provisional = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" not in verified
    assert "" in provisional


def test_success_resets_quarantine(_isolated_learn):
    dmm_prefix_learn.record_success("sone-833", "sone00833")
    dmm_prefix_learn.record_success("sone-900", "sone00900")
    for _ in range(3):
        dmm_prefix_learn.record_failure("sone-900", "sone00900")
    assert "" not in dmm_prefix_learn.get_learned_prefixes("sone")[0]
    # 新证据重新观察到，解除隔离并重新走 provisional 验证
    dmm_prefix_learn.record_success("sone-901", "sone00901")
    verified, provisional = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" not in verified
    assert "" in provisional
    dmm_prefix_learn.record_success("sone-902", "sone00902")
    verified, _ = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" in verified


def test_persist_and_reload(_isolated_learn):
    dmm_prefix_learn.record_success("sone-833", "sone00833")
    dmm_prefix_learn.record_success("sone-900", "sone00900")
    # 重新加载模拟重启
    dmm_prefix_learn.reset_for_testing()
    dmm_prefix_learn._load()
    verified, _ = dmm_prefix_learn.get_learned_prefixes("sone")
    assert "" in verified


def test_invalid_prefix_ignored(_isolated_learn):
    # 超长/非法前缀不入表
    dmm_prefix_learn.record_success("sone-833", "abcdefghijklmnop1234sone00833")
    assert dmm_prefix_learn.get_learned_prefixes("sone") == ([], [])


def test_unknown_series_prefix_split():
    # 未收录系列：剩余字母段全部当 series，prefix 为空
    series, prefix = dmm_prefix_learn._split_cid("xxzz-100", "xxzz00100")
    assert series == "xxzz"
    assert prefix == ""


def test_mismatched_number_cid_returns_empty():
    assert dmm_prefix_learn._split_cid("sone-833", "other00100") == ("", "")


def test_pics_dmm_cover_evidence_feeds_learn_table(_isolated_learn):
    """主爬虫 pics.dmm 图源应能喂学习表，静态表外新前缀系列（HONB/h_1133）不再死锁."""
    from types import SimpleNamespace

    from mdcx.crawlers.dmm import DmmCrawler

    ctx = SimpleNamespace(input=SimpleNamespace(number="HONB-487"))
    DmmCrawler._record_dmm_cover_evidence(
        ctx, "https://pics.dmm.co.jp/digital/video/h_1133honb00487/h_1133honb00487ps.jpg"
    )
    # 单次证据为 provisional；再积累一个编号后升级 verified
    assert "h_1133" in dmm_prefix_learn.get_learned_prefixes("honb")[1]
    ctx2 = SimpleNamespace(input=SimpleNamespace(number="HONB-498"))
    DmmCrawler._record_dmm_cover_evidence(
        ctx2, "https://pics.dmm.co.jp/digital/video/h_1133honb00498/h_1133honb00498ps.jpg"
    )
    assert "h_1133" in dmm_prefix_learn.get_learned_prefixes("honb")[0]


def test_mono_cid_noise_filtered_by_code_check(_isolated_learn):
    """mono 图 cid 数字段不补零（118abf042），endswith 校验应拒绝其入表."""
    from types import SimpleNamespace

    from mdcx.crawlers.dmm import DmmCrawler

    ctx = SimpleNamespace(input=SimpleNamespace(number="ABF-42"))
    DmmCrawler._record_dmm_cover_evidence(ctx, "https://pics.dmm.co.jp/mono/movie/adult/118abf042/118abf042pl.jpg")
    assert dmm_prefix_learn.get_learned_prefixes("abf") == ([], [])
