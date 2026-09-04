"""javbus/javlibrary 搜索兜底 FC2 番号匹配回归测试。

历史缺陷（全库审查 A5，经人工质疑降级为 B）：两站 get_real_url 归一化不对称——
站侧 URL/标题剥了 "PPV"（/fc2-ppv-123456 → FC2PPV123456），番号侧没剥
（FC2-123456 → FC2123456），比较恒 False，搜索兜底必然报"未匹配到番号"。

正常分类路径 FC2 番号走 website_fc2 组（不含这两站），触发面限于：
单站模式手选 javbus/javlibrary、指定 URL 重刮贴这两站链接、用户自定义
website_fc2 列表加入这两站。

修复后：两侧归一对齐（番号侧同样剥 PPV）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdcx.crawlers.javbus import is_match as javbus_is_match
from mdcx.crawlers.javlibrary import is_match as javlibrary_is_match


def test_javbus_fc2_match():
    """javbus 搜索结果 href 形如 /fc2-ppv-123456，FC2 番号必须能命中。"""
    # FC2 形态（修复前恒 False）
    assert javbus_is_match("/fc2-ppv-123456", "FC2-123456") is True
    assert javbus_is_match("/FC2PPV-1234567", "FC2-PPV-1234567") is True
    # 普通番号行为不变
    assert javbus_is_match("/SSIS-538", "SSIS-538") is True
    assert javbus_is_match("/SSIS-538", "SSIS-539") is False


def test_javlibrary_fc2_match():
    """javlibrary 页面标题形如 FC2-PPV-1234567，FC2 番号必须能命中。"""
    assert javlibrary_is_match("FC2-PPV-1234567 个体撮影", "FC2-1234567") is True
    # 普通番号行为不变
    assert javlibrary_is_match("SSIS-538 Title", "SSIS-538") is True
    assert javlibrary_is_match("SSIS-538 Title", "SSIS-539") is False
