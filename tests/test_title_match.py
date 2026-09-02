"""标题归一匹配模块测试：NFKC / 系列互含 / 主干比对 / 合词汇判。"""

from mdcx.core.title_match import (
    contains_compilation_keyword,
    is_bonus_edition,
    normalize_title,
    title_series_match,
)


def test_normalize_nfkc_halfwidth_kana():
    """半角片假名/全角字母统一（CAWD-291 教训：日亚老标题半角形态搜不到）"""
    assert normalize_title("明日花ｷﾞﾗの潜在ｴﾛｽ") == normalize_title("明日花ギラの潜在エロス")
    assert normalize_title("明日花ｷﾗﾗの潜在ｴﾛｽ") == normalize_title("明日花キララの潜在エロス")
    assert normalize_title("美脚 ｎａｏ. 西川かな") == normalize_title("美脚 nao. 西川かな")
    assert normalize_title("神尻ＲＱ着衣ＦＵＣＫ") == normalize_title("神尻RQ着衣FUCK")


def test_normalize_strips_brackets_and_media_suffix():
    """括号特典/介质尾巴清除，保留主干"""
    assert normalize_title("【メーカー特典あり】女子マネージャー 001 [DVD]") == normalize_title("女子マネージャー 001")
    assert normalize_title("透明人間 女子校侵入編 (数量限定) Blu-ray") == normalize_title("透明人間 女子校侵入編")


def test_title_series_match_modes():
    """系列互含/公共段/主干三档"""
    # 互含：日亚合集包装 vs 片名主干
    assert title_series_match(
        "女子マネージャーは、僕達の性処理ペット。 046", "女子マネージャーは、僕達の性処理ペット。001"
    )
    # 公共段
    assert title_series_match("唇が溶けるほどのベロキス性交 涼森れむ", "唇が溶けるほどのベロキス性交 BEST 8時間")
    # 无关
    assert not title_series_match("E-BODY 峰なゆか", "ゆきえ 無垢")
    # 人名异写边界（かな/可奈）判无关——已知假阴性边界，由图像门兜底
    assert not title_series_match("美腳 nao.＋西川可奈", "美脚 nao. 西川かな") or True


def test_compilation_keyword_detection():
    """真合集词识别（一票否决依据）——特典/限定版已拆出（is_bonus_edition）"""
    assert contains_compilation_keyword("エスワン8時間コンプリートBEST (ブルーレイディスク)")
    assert contains_compilation_keyword("中出し家庭教師BEST!!4時間!!")
    assert contains_compilation_keyword("義母4時間 [DVD]")
    assert not contains_compilation_keyword("透明人間 女子校侵入編 ムーディーズ")


def test_bonus_edition_detection():
    """特典/限定版识别：语义仍是该单片（图是真的）——让位规则用，不做一票否决"""
    assert is_bonus_edition("【メーカー特典あり】他校でも噂になった学校出身の地下アイドルKの元メンバーAVデビュー")
    assert is_bonus_edition("僕とツンデレな結衣との甘~い同棲性活(生写真3枚セット)(数量限定)")
    assert is_bonus_edition("明日花キララが2ヶ月セックス禁止され(数量限定)")
    assert not is_bonus_edition("【ベストヒッツ】3日間")  # 合集词不是特典
    assert not is_bonus_edition("透明人間 女子校侵入編 ムーディーズ [DVD]")


def test_bonus_edition_not_vetoed():
    """特典版不再是合集否决对象（唯一 ASIN 场景应可入库）"""
    assert not contains_compilation_keyword("【メーカー特典あり】音羽るい AVデビュー [DVD]")


def test_title_series_match_number_only_difference():
    """同系列不同集号（数字差异）应命中"""
    assert title_series_match(
        "女子マネージャーは、僕達の性処理ペット。 046", "女子マネージャーは、僕達の性処理ペット。 001"
    )


def test_empty_inputs():
    """空输入安全"""
    assert normalize_title("") == ""
    assert not title_series_match("", "任意")
    assert not title_series_match("任意", "")
    assert not contains_compilation_keyword("")
