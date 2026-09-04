"""无码官网番号前缀保留回归测试。

历史缺陷（全库审查 A2）：normalize_uncensored_digit_number 对带前缀形态
（1pondo-072625_101）把唯一可靠的路由证据——站点前缀——剥掉，仅返回
"072625_101"；route_uncensored_official 只能按分隔符/尾号长度猜测站点，
1pondo（尾号>=100）被误路由到 pacopacomama，pacopacomama 尾号 001-099
被误路由到 1pondo，拿到错误影片的元数据且当成功入库。

修复后：带前缀形态返回时保留前缀，路由按 DIGIT_PREFIX_ALIASES 精确判定。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdcx.crawlers.official_uncensored import (
    normalize_uncensored_official_id,
    route_uncensored_official,
)
from mdcx.number import get_file_number, normalize_uncensored_digit_number


def test_digit_number_with_prefix_keeps_prefix():
    """带前缀形态归一后必须保留前缀（路由证据）。"""
    assert normalize_uncensored_digit_number("1pondo-072625_101") == "1pondo-072625_101"
    assert normalize_uncensored_digit_number("1pondo_072625_101") == "1pondo-072625_101"
    assert normalize_uncensored_digit_number("caribbeancom-072625-01") == "caribbeancom-072625-01"
    # 无前缀形态行为不变
    assert normalize_uncensored_digit_number("072625_101") == "072625_101"
    assert normalize_uncensored_digit_number("072625-01") == "072625-01"


def test_get_file_number_keeps_prefix_for_routing():
    """文件名番号提取保留前缀（get_file_number 主链路，番号大写惯例）。"""
    assert get_file_number("1pondo-072625_101.mp4", []) == "1PONDO-072625_101"
    assert get_file_number("pacopacomama-072625_099.mp4", []) == "PACOPACOMAMA-072625_099"


def test_route_by_prefix_correct_site():
    """前缀路由精确命中，尾号猜测仅作无前缀兜底。"""
    cases = [
        ("1pondo-072625_101", "1pondo"),
        ("pacopacomama-072625_099", "pacopacomama"),
        ("10musume-072625_01", "10musume"),
        ("caribbeancom-072625-01", "caribbeancom"),
        # 无前缀形态维持旧行为（分隔符/尾号猜测）
        ("072625-01", "caribbeancom"),
        ("072625_01", "10musume"),
        ("072625_101", "pacopacomama"),
    ]
    for number, expected in cases:
        assert route_uncensored_official(number) == expected, f"{number} 应路由 {expected}"


def test_normalize_official_id_strips_prefix_for_url():
    """详情页 movie_id 仍是不带前缀形态（URL 拼接语义不变）。"""
    assert normalize_uncensored_official_id("1pondo-072625_101") == "072625_101"
    assert normalize_uncensored_official_id("caribbeancom-072625-01") == "072625-01"
    assert normalize_uncensored_official_id("072625_101") == "072625_101"


def test_full_pipeline_filename_to_correct_site():
    """端到端：文件名 → 番号 → 路由（修复前 1pondo 文件误路由 pacopacomama）。"""
    number = get_file_number("1pondo-072625_101.mp4", [])
    assert route_uncensored_official(number) == "1pondo"
    number = get_file_number("pacopacomama-072625_099.mp4", [])
    assert route_uncensored_official(number) == "pacopacomama"
