from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file import get_file_info_v2
from mdcx.core.utils import get_video_size
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.number import (
    get_file_number,
    is_uncensored,
    match_number,
    movie_number_lookup_values,
    normalize_movie_number,
    remove_disturb,
)


def test_get_file_number_prefers_longer_escape_strings():
    escape_strings = ["4k2", ".com@", "489155.com@"]

    assert get_file_number(r"D:/test/489155.com@MXGS-992.mp4", escape_strings) == "MXGS-992"


# ============================================================
# remove_disturb — 域名干扰预处理
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("489155.com@MXGS-992", "@MXGS-992"),
        ("www.example.com/ssis00123", "/ssis00123"),
        ("ssis-00123", "ssis-00123"),
        ("ABC-123", "ABC-123"),
        ("100225_001", "100225_001"),
        ("", ""),
        (None, None),
    ],
)
def test_remove_disturb(raw, expected):
    assert remove_disturb(raw) == expected


def test_remove_disturb_preserves_filename_when_only_domain():
    """文件名本身恰好是域名时不去除，避免空结果"""
    assert remove_disturb("ssis00123.com") == "ssis00123.com"
    assert remove_disturb("ssis00123.com.") == "ssis00123.com."


def test_get_file_number_removes_domain_without_escape_string_config():
    """不配置 escape_string_list 也能去除域名干扰"""
    assert get_file_number(r"D:/test/489155.com@MXGS-992.mp4", []) == "MXGS-992"


def test_get_file_number_preserves_number_with_dotcom_extension():
    """文件名含 .com 后缀但不配 escape_string 仍能解析番号"""
    assert get_file_number(r"D:/test/ssis00123.com.mp4", []) == "SSIS-123"


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/100225_100.mp4", "100225_100"),
        (r"D:/test/111111_111.mp4", "111111_111"),
        (r"D:/test/111111-111.mp4", "111111-111"),
        # 无码官网带前缀形态：保留前缀（route_uncensored_official 按前缀精确路由，
        # 剥前缀会让 1pondo/pacopacomama 按尾号长度互相误路由——全库审查 A2）
        (r"D:/test/1pondo_031926_001.mp4", "1PONDO-031926_001"),
        (r"D:/test/caribbeancom-031426-001.mp4", "CARIBBEANCOM-031426-001"),
        (r"D:/test/pacopacomama_031726_100.mp4", "PACOPACOMAMA-031726_100"),
        (r"D:/test/10musume_031426_01.mp4", "10MUSUME-031426_01"),
    ],
)
def test_get_file_number_normalizes_uncensored_digit_numbers(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number
    assert is_uncensored(expected_number) is True


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/LUXU-1488.mp4", "259LUXU-1488"),
        (r"D:/test/SCUTE-953.mp4", "229SCUTE-953"),
        (r"D:/test/MAAN-673.mp4", "300MAAN-673"),
        (r"D:/test/ARA-094.mp4", "261ARA-094"),
    ],
)
def test_get_file_number_normalizes_suren_numbers(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/9SSIS01.mp4", "SSIS-001"),
        (r"D:/test/9ssis01.mp4", "SSIS-001"),
        (r"D:/test/9SSNI001.mp4", "SSNI-001"),
        (r"D:/test/9SSNI10.mp4", "SSNI-010"),
        (r"D:/test/9SSIS-001.mp4", "SSIS-001"),
        (r"D:/test/9SSIS001[中文].mp4", "SSIS-001"),
        (r"D:/test/ABC9MUSK001.mp4", "ABC-001"),
    ],
)
def test_get_file_number_normalizes_dmm_preorder_9_prefix(raw_number: str, expected_number: str):
    """DMM 预约版 9 前缀番号：9ssis01 -> SSIS-001（编号补零到 3 位）；9 必须独立成段不误伤 ABC9。"""
    assert get_file_number(raw_number, []) == expected_number


@pytest.mark.parametrize(
    ("raw_number", "expected_number"),
    [
        (r"D:/test/DANDY-818.mp4", "DANDY-818"),
        (r"D:/test/KIWVR-254.mp4", "KIWVR-254"),
        (r"D:/test/GARA-022.mp4", "GARA-022"),
    ],
)
def test_get_file_number_keeps_non_suren_prefixes(raw_number: str, expected_number: str):
    assert get_file_number(raw_number, []) == expected_number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "file_number", "custom_strings", "expected_definition"),
    [
        (Path("D:/test/4k2.com@MXGS-993.mp4"), "MXGS-993", ["4k2", ".com@"], ""),
        (Path("D:/test/4k3.com@SSNI-1000.mp4"), "SSNI-1000", ["4k3.com@"], ""),
        (Path("D:/test/HUHD-111.mp4"), "HUHD-111", [], ""),
        (Path("D:/test/SSNI-100-1080P.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/1080PSSNI-100.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/SSNI-1001080P.mp4"), "SSNI-100", ["1080p", "720p"], "1080P"),
        (Path("D:/test/SSNI-100-720P.mp4"), "SSNI-100", ["1080p", "720p"], "720P"),
        (Path("D:/test/SSNI-100-HD.mp4"), "SSNI-100", ["-HD"], "720P"),
        (Path("D:/test/SSNI-100-FHD.mp4"), "SSNI-100", ["fhd"], "1080P"),
        (Path("D:/test/SSNI-100-QHD.mp4"), "SSNI-100", ["qhd"], "1440P"),
        (Path("D:/test/SSNI-100-UHD.mp4"), "SSNI-100", ["uhd"], "4K"),
        (Path("D:/test/SSNI-100-8K.mp4"), "SSNI-100", ["8k"], "8K"),
        (Path("D:/test/4k2.com@MXGS-993-4K.mp4"), "MXGS-993", ["4k2", ".com@"], "4K"),
        (Path("D:/test/4k3.com@SSNI-1000-4K.mp4"), "SSNI-1000", ["4k3.com@"], "4K"),
        (Path("D:/test/HUHD-111-UHD.mp4"), "HUHD-111", [], "4K"),
        (Path("D:/test/JUR-615-U4K.mp4"), "JUR-615", [], "4K"),
        (Path("D:/test/JUR-615-UC4K.mp4"), "JUR-615", [], "4K"),
        (Path("D:/test/JUR-615-UC-4K.mp4"), "JUR-615", [], "4K"),
        (Path("D:/test/IPZZ-841_4K60FPS.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4KS.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4k60fps.mp4"), "IPZZ-841", [], "4K"),
        (Path("D:/test/IPZZ-841_4ks.mp4"), "IPZZ-841", [], "4K"),
    ],
)
async def test_get_video_size_path_strips_noise_and_number_tokens(
    monkeypatch: pytest.MonkeyPatch,
    file_path: Path,
    file_number: str,
    custom_strings: list[str],
    expected_definition: str,
):
    monkeypatch.setattr(manager.config, "hd_get", "path")
    monkeypatch.setattr(manager.config, "hd_name", "height")
    monkeypatch.setattr(manager.config, "string", custom_strings)
    monkeypatch.setattr(manager.config, "no_escape", [])

    definition, codec = await get_video_size(file_path, file_number)

    assert definition == expected_definition
    assert codec == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number"),
    [
        (Path("D:/test/100225_100.mp4"), "100225_100"),
        (Path("D:/test/1pondo_031926_001.mp4"), "1PONDO-031926_001"),
        (Path("D:/test/10musume_031426_01.mp4"), "10MUSUME-031426_01"),
    ],
)
async def test_get_file_info_marks_uncensored_digit_numbers(file_path: Path, expected_number: str):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.mosaic == "无码"


@pytest.mark.asyncio
async def test_get_file_info_marks_restored_as_umr_case_insensitive():
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(Path("D:/test/ABF-131.RESTORED.mp4"), copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == "ABF-131"
    assert file_info.destroyed == manager.config.umr_style
    assert file_info.mosaic == "无码破解"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_path",
    [
        Path("D:/test/JUR-615-UC4K.mp4"),
        Path("D:/test/JUR-615-UC-4K.mp4"),
        Path("D:/test/JUR-615-U4K.mp4"),
    ],
)
async def test_get_file_info_marks_umr_when_uc_suffix_is_followed_by_definition(file_path: Path):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == "JUR-615"
    assert file_info.destroyed == manager.config.umr_style
    assert file_info.mosaic == "无码破解"


@pytest.mark.asyncio
async def test_get_file_info_does_not_treat_uc_number_prefix_as_umr_marker():
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(Path("D:/test/UC-123.mp4"), copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == "UC-123"
    assert file_info.destroyed == ""
    assert file_info.mosaic == ""


@pytest.mark.asyncio
async def test_get_file_info_does_not_treat_uhd_definition_as_umr_marker():
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(Path("D:/test/JUR-615-UHD.mp4"), copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == "JUR-615"
    assert file_info.destroyed == ""
    assert file_info.mosaic == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number", "expected_short_number"),
    [
        (Path("D:/test/LUXU-1488.mp4"), "259LUXU-1488", "LUXU-1488"),
        (Path("D:/test/SCUTE-953.mp4"), "229SCUTE-953", "SCUTE-953"),
        (Path("D:/test/259LUXU-1488.mp4"), "259LUXU-1488", "LUXU-1488"),
    ],
)
async def test_get_file_info_extracts_suren_short_number(
    file_path: Path, expected_number: str, expected_short_number: str
):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.short_number == expected_short_number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_path", "expected_number"),
    [
        (Path("D:/test/DANDY-818.mp4"), "DANDY-818"),
        (Path("D:/test/KIWVR-254.mp4"), "KIWVR-254"),
    ],
)
async def test_get_file_info_does_not_extract_short_number_for_non_suren_prefixes(
    file_path: Path, expected_number: str
):
    old_file_mode = Flags.file_mode
    Flags.file_mode = FileMode.Default
    try:
        file_info = await get_file_info_v2(file_path, copy_sub=False)
    finally:
        Flags.file_mode = old_file_mode

    assert file_info.number == expected_number
    assert file_info.short_number == ""


@pytest.mark.parametrize(
    ("text", "number", "expected"),
    [
        ("BF-002 中文字幕", "BF-002", True),
        ("ABF-002 中文字幕", "BF-002", False),
        ("ABS-002 中文字幕", "BS-002", False),
        ("BS-002 中文字幕", "BS-002", True),
        ("ABF-002 中文字幕", "ABF-002", True),
        ("252MY-001 素人", "252MY-001", True),
        ("252MY001 素人", "252MY001", True),
        ("ZZZ-999", "ZZZ-999", True),
        ("BF002无码", "BF002", True),
        ("ABF002无码", "BF002", False),
        ("  IPX-535  Title", "IPX-535", True),
    ],
)
def test_match_number(text: str, number: str, expected: bool):
    assert match_number(text, number) is expected


# ============================================================
# normalize_movie_number — 从 sakuramediabe 移植
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ABC-123", "ABC-123"),
        ("abc-123", "ABC-123"),
        ("ABC_123", "ABC-123"),
        ("ABC 123", "ABC123"),
        ("FC2-PPV-1234567", "FC2-1234567"),
        ("FC2PPV-1234567", "FC21234567"),
        ("FC2PPV_1234567", "FC21234567"),
        ("072625_001", "072625-001"),
        ("072625-001", "072625-001"),
        ("  ssis-001  ", "SSIS-001"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_movie_number(raw, expected):
    assert normalize_movie_number(raw) == expected


def test_normalize_movie_number_fold_equivalence():
    """_ 和 - 折叠后相等（两侧同时折叠比较场景）"""
    assert normalize_movie_number("072625_001") == normalize_movie_number("072625-001")
    assert normalize_movie_number("FC2PPV_123") == normalize_movie_number("FC2PPV-123")


# ============================================================
# movie_number_lookup_values — 人工输入按番号点查的候选集
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ABC-123", ["ABC-123", "ABC_123"]),
        ("abc_123", ["ABC_123", "ABC-123"]),
        ("ABC-123-456", ["ABC-123-456", "ABC_123_456"]),
        ("ABC123", ["ABC123"]),
        ("", []),
        (None, []),
    ],
)
def test_movie_number_lookup_values(raw, expected):
    assert movie_number_lookup_values(raw) == expected


def test_movie_number_lookup_values_dedup():
    """分隔符替换后与原值相同时去重"""
    assert movie_number_lookup_values("ABC123") == ["ABC123"]
    assert len(movie_number_lookup_values("ABC-123")) == 2
