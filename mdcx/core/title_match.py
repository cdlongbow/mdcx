"""标题归一匹配：ASIN 入库门槛的标题证据（软校验裁决链 v2 第 2 步）。

算法源自 2026-09-01 四源校验工程实证（/tmp/opencode/libre_recheck.py）：
- NFKC 归一统一半角片假名/全角字母（CAWD-291 假阴性教训）
- 系列名主干互含/公共段判定（303+34 行翻案零冤案）
- 合集词一票否决（58 行错挂的病灶主体：合集误配入库）

该模块是标题比对的产品化形态，与搜索候选池的 title_confidence（相似度打分）
构成算法互补：title_confidence 抓不住半角/异体字/包装差异，本模块抓不住
人名异写（かな/可奈），两者并行覆盖。
"""

from __future__ import annotations

import re
import unicodedata

# 合集/特典词：语义为"非单片商品"，命中即一票否决入库
_COMPILATION_RE = re.compile(
    r"BEST|コンプリート|COMPLETE|\d+時間|[0-9０-９]+\s*時間|特典|ディレクターズカット|DC版|総集編",
    re.IGNORECASE,
)

# 归一后剥离的噪声
_BRACKET_RE = re.compile(r"【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^)]*\)")
_NOISE_RE = re.compile(r"[\s，、。・！？：；/「」『』" "”" "]+")
_MEDIA_SUFFIX_RE = re.compile(r"\s*(Blu-?ray|ブルーレイディスク|DVD)\b.*$", re.IGNORECASE)

_SEGMENT_RE = re.compile(r"[ぁ-んァ-ヶ一-龥a-zA-Z0-9]+")

# 主干互含/公共段的最小长度门槛
_CORE_MIN = 6
_SEGMENT_MIN = 5
_RUN_MATCH = 8  # 跨标点主干连续片段命中线
_RUN_PARTIAL = 5  # 部分匹配线（判"无关"前给图像门兜底机会的缓冲区）


def normalize_title(text: str) -> str:
    """标题归一：NFKC 全半角统一 + 去括号特典/介质尾巴/标点，保留片名主干字符流。"""
    text = str(text or "")
    text = unicodedata.normalize("NFKC", text)
    text = _BRACKET_RE.sub(" ", text)
    text = _MEDIA_SUFFIX_RE.sub("", text)
    return _NOISE_RE.sub(" ", text).strip()


def contains_compilation_keyword(text: str) -> bool:
    """合集/特典词识别（一票否决依据）。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return bool(_COMPILATION_RE.search(normalized))


def _segments(text: str) -> set[str]:
    """归一文本的连续字词段（日文/字母/数字），≥ _SEGMENT_MIN 参与公共段比对。"""
    return {s for s in _SEGMENT_RE.findall(normalize_title(text)) if len(s) >= _SEGMENT_MIN}


def _core(text: str) -> str:
    """去数字后的主干（分集号差异消除）。"""
    return re.sub(r"\d+", "", normalize_title(text)).replace(" ", "")


def _longest_common_run(a: str, b: str) -> int:
    """最长公共连续子串长度（标题量级下 O(n²) 足够）。"""
    if len(a) > len(b):
        a, b = b, a
    best = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a) + 1):
            if a[i:j] in b:
                best = max(best, j - i)
            else:
                break
    return best


def title_series_match(amazon_title: str, movie_title: str) -> bool:
    """日亚商品标题 vs 番号片名是否同系列（三档判定：互含 → 公共段 → 主干连续）。

    已知边界：人名异写（かな/可奈）不命中——由裁决链第 3 步图像门兜底。
    """
    la, lz = normalize_title(amazon_title), normalize_title(movie_title)
    if not la or not lz:
        return False

    # 第 1 档：主干互含（去数字后，分集号/包装差异不影响）
    ca, cz = _core(amazon_title), _core(movie_title)
    if (len(ca) >= _CORE_MIN and ca in cz) or (len(cz) >= _CORE_MIN and cz in ca):
        return True

    # 第 2 档：公共段（≥5 连续字词段交集）
    if _segments(amazon_title) & _segments(movie_title):
        return True

    # 第 3 档：跨标点主干连续片段
    run = _longest_common_run(la.replace(" ", ""), lz.replace(" ", ""))
    return run >= _RUN_MATCH


def title_partial_match(amazon_title: str, movie_title: str) -> bool:
    """部分匹配（主干连续 5-7 字）：不足定罪但值得图像门联合判定的缓冲区。"""
    la, lz = normalize_title(amazon_title), normalize_title(movie_title)
    if not la or not lz:
        return False
    run = _longest_common_run(la.replace(" ", ""), lz.replace(" ", ""))
    return _RUN_PARTIAL <= run < _RUN_MATCH
