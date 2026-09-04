"""NFO 合并策略测试：验证 5 种 MergeStrategy 的合并行为。"""

import pytest

from mdcx.config.enums import NfoMergeStrategy
from mdcx.core.nfo_merger import _is_empty, _merge_array, _merge_scalar, merge_nfo_fields
from mdcx.models.model_types import CrawlersResult


def _make_result(**kwargs) -> CrawlersResult:
    """构造带指定字段的 CrawlersResult。"""
    result = CrawlersResult.empty()
    for k, v in kwargs.items():
        setattr(result, k, v)
    return result


# ---------- _is_empty ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", True),
        ("  ", True),
        (None, True),
        ([], True),
        ({}, True),
        ("text", False),
        (["a"], False),
        (0, False),
    ],
)
def test_is_empty(value, expected):
    assert _is_empty(value) is expected


# ---------- _merge_scalar ----------


class TestMergeScalar:
    def test_both_empty(self):
        val, src = _merge_scalar("outline", "", "", NfoMergeStrategy.PREFER_NFO)
        assert val == ""
        assert src == "empty"

    def test_scraped_empty_nfo_has_value(self):
        val, src = _merge_scalar("outline", "", "本地简介", NfoMergeStrategy.PREFER_NFO)
        assert val == "本地简介"
        assert src == "nfo"

    def test_nfo_empty_scraped_has_value(self):
        val, src = _merge_scalar("outline", "新简介", "", NfoMergeStrategy.PREFER_NFO)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_prefer_scraper(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PREFER_SCRAPER)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_prefer_nfo(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PREFER_NFO)
        assert val == "本地简介"
        assert src == "nfo"

    def test_both_have_value_preserve_existing(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PRESERVE_EXISTING)
        assert val == "本地简介"
        assert src == "nfo"

    def test_both_have_value_fill_missing_only(self):
        """fill_missing_only："仅填空字段"——新数据为主，两源都有值时取新数据。

        原实现误与 preserve_existing 同分支（取本地旧值），与 UI 名称
        "仅填空字段"/models 描述/docstring 语义矛盾，导致两个选项行为完全重复
        （全库审查 A3，测试原断言锁定的是 bug 行为，随修复反转）。
        """
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.FILL_MISSING_ONLY)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_merge_arrays(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.MERGE_ARRAYS)
        assert val == "新简介"
        assert src == "scraper"

    def test_critical_field_both_empty_falls_back(self):
        """关键字段（title）两源都空时返回空但标记为 empty。"""
        val, src = _merge_scalar("title", "", "", NfoMergeStrategy.PREFER_NFO)
        assert val == ""
        assert src == "empty"

    def test_critical_field_scraped_empty_uses_nfo(self):
        val, src = _merge_scalar("title", "", "本地标题", NfoMergeStrategy.PREFER_SCRAPER)
        assert val == "本地标题"
        assert src == "nfo"


# ---------- _merge_array ----------


class TestMergeArray:
    def test_both_empty(self):
        val, src = _merge_array("tags", [], [], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == []
        assert src == "empty"

    def test_scraped_empty(self):
        val, src = _merge_array("tags", [], ["本地标签"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["本地标签"]
        assert src == "nfo"

    def test_nfo_empty(self):
        val, src = _merge_array("tags", ["新标签"], [], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["新标签"]
        assert src == "scraper"

    def test_merge_arrays_dedup(self):
        val, src = _merge_array("tags", ["推荐", "高清"], ["推荐", "蓝光"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["推荐", "高清", "蓝光"]
        assert src == "merged"

    def test_merge_arrays_dedup_case_insensitive(self):
        val, src = _merge_array("tags", ["Actor"], ["ACTOR", "actor2"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["Actor", "actor2"]
        assert src == "merged"

    def test_prefer_scraper_for_arrays(self):
        val, src = _merge_array("tags", ["新标签"], ["本地标签"], NfoMergeStrategy.PREFER_SCRAPER)
        assert val == ["新标签"]
        assert src == "scraper"

    def test_prefer_nfo_for_arrays(self):
        val, src = _merge_array("tags", ["新标签"], ["本地标签"], NfoMergeStrategy.PREFER_NFO)
        assert val == ["本地标签"]
        assert src == "nfo"


# ---------- merge_nfo_fields ----------


class TestMergeNfoFields:
    def test_prefer_scraper_returns_scraped_directly(self):
        """prefer_scraper 策略直接返回 scraped（保持现有行为）。"""
        scraped = _make_result(title="新标题", outline="新简介", tags=["新标签"])
        nfo = _make_result(title="本地标题", outline="本地简介", tags=["本地标签"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_SCRAPER)

        assert result.title == "新标题"
        assert result.outline == "新简介"
        assert result.tags == ["新标签"]

    def test_prefer_nfo_uses_local_values(self):
        scraped = _make_result(title="新标题", outline="新简介", tags=["新标签"], runtime="120")
        nfo = _make_result(title="本地标题", outline="本地简介", tags=["本地标签"], runtime="")

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        assert result.title == "本地标题"
        assert result.outline == "本地简介"
        assert result.tags == ["本地标签"]
        # runtime 本地为空，用新数据
        assert result.runtime == "120"

    def test_fill_missing_only_preserves_all_existing(self):
        """fill_missing_only 策略：新数据为主，刮削结果为空才从本地补。"""
        scraped = _make_result(title="新标题", outline="", runtime="120", studio="新片商")
        nfo = _make_result(title="本地标题", outline="本地简介", runtime="", studio="")

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.FILL_MISSING_ONLY)

        # 两源都有值：新数据
        assert result.title == "新标题"
        assert result.runtime == "120"
        assert result.studio == "新片商"
        # 刮削结果为空：从本地补
        assert result.outline == "本地简介"

    def test_preserve_existing_differs_from_fill_missing(self):
        """preserve_existing（本地为主）与 fill_missing_only（新数据为主）标量行为相反。"""
        scraped = _make_result(title="新标题", outline="新简介", runtime="120")
        nfo = _make_result(title="本地标题", outline="本地简介", runtime="")

        preserved = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PRESERVE_EXISTING)
        assert preserved.title == "本地标题"
        assert preserved.outline == "本地简介"
        assert preserved.runtime == "120"

        filled = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.FILL_MISSING_ONLY)
        assert filled.title == "新标题"
        assert filled.outline == "新简介"
        assert filled.runtime == "120"

    def test_merge_arrays_combines_tags_and_actors(self):
        """merge_arrays 策略：数组字段合并去重，标量用新数据。"""
        scraped = _make_result(title="新标题", tags=["推荐", "高清"], actors=["演员A"])
        nfo = _make_result(title="本地标题", tags=["推荐", "蓝光"], actors=["演员B"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.MERGE_ARRAYS)

        # 标量用新数据
        assert result.title == "新标题"
        # 数组合并去重
        assert result.tags == ["推荐", "高清", "蓝光"]
        assert result.actors == ["演员A", "演员B"]

    def test_merge_with_none_nfo(self):
        """nfo 为 None 时直接返回 scraped。"""
        scraped = _make_result(title="新标题")

        result = merge_nfo_fields(scraped, None, NfoMergeStrategy.PREFER_NFO)

        assert result.title == "新标题"

    def test_merge_preserves_actor_tmdb_ids(self):
        """合并 actor_tmdb_ids：保留两源的 TMDB ID。"""
        scraped = _make_result()
        scraped.actor_tmdb_ids = {"演员A": 123}
        nfo = _make_result()
        nfo.actor_tmdb_ids = {"演员B": 456}

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        assert result.actor_tmdb_ids == {"演员A": 123, "演员B": 456}

    def test_merge_does_not_mutate_original(self):
        """合并不修改原始 scraped 对象。"""
        scraped = _make_result(title="新标题", tags=["新标签"])
        nfo = _make_result(title="本地标题", tags=["本地标签"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        # 原始 scraped 不变
        assert scraped.title == "新标题"
        assert scraped.tags == ["新标签"]
        # 合并结果是新对象
        assert result.title == "本地标题"
        assert result.tags == ["本地标签"]


# ---------- 配置项测试 ----------


class TestNfoMergeStrategyConfig:
    def test_default_value(self):
        from mdcx.config.models import Config

        config = Config()
        assert config.nfo_merge_strategy == NfoMergeStrategy.PREFER_SCRAPER

    def test_set_strategy(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_strategy = NfoMergeStrategy.FILL_MISSING_ONLY
        assert config.nfo_merge_strategy == NfoMergeStrategy.FILL_MISSING_ONLY

    def test_serialization(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_strategy = NfoMergeStrategy.MERGE_ARRAYS
        data = config.model_dump()
        assert data["nfo_merge_strategy"] == NfoMergeStrategy.MERGE_ARRAYS

    def test_deserialization(self):
        from mdcx.config.models import Config

        data = {"nfo_merge_strategy": NfoMergeStrategy.PREFER_NFO}
        config = Config.model_validate(data)
        assert config.nfo_merge_strategy == NfoMergeStrategy.PREFER_NFO


def test_nfo_merge_strategy_enum_values():
    """NfoMergeStrategy 枚举值与预期一致。"""
    assert NfoMergeStrategy.PREFER_SCRAPER.value == "prefer_scraper"
    assert NfoMergeStrategy.PREFER_NFO.value == "prefer_nfo"
    assert NfoMergeStrategy.MERGE_ARRAYS.value == "merge_arrays"
    assert NfoMergeStrategy.PRESERVE_EXISTING.value == "preserve_existing"
    assert NfoMergeStrategy.FILL_MISSING_ONLY.value == "fill_missing_only"
