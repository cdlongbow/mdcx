import contextlib
import os
import re
import unicodedata

from .manual import ManualConfig

UNCENSORED_DIGIT_NUMBER_PATTERN = re.compile(r"^(?P<head>\d{6})(?P<sep>[-_])(?P<tail>\d{2,4})$", re.IGNORECASE)
UNCENSORED_DIGIT_NUMBER_PREFIX_PATTERN = re.compile(
    r"^(?P<prefix>1pondo|1pon|10musume|caribbeancom|caribbeancompr|carib|pacopacomama|pacoma|paco)[-_ ]*"
    r"(?P<head>\d{6})(?P<sep>[-_])(?P<tail>\d{2,4})$",
    re.IGNORECASE,
)


_DOMAIN_PATTERN = re.compile(
    r"\b(?:[a-zA-Z0-9]+\.)*[a-zA-Z0-9]+\.(?:com|cn|net|org|gov|edu|info|io|xyz|cc|tk|me)\b",
    re.IGNORECASE,
)


def remove_disturb(value: str) -> str:
    """去除文件名中嵌入的域名干扰（如 489155.com@、www.xxx.cn 等）。

    与 escape_string_list 互补：escape_string_list 处理用户配置的特定干扰词，
    本函数用通用正则自动匹配任意域名，减少用户配置负担。

    只在去除域名后仍有剩余内容时才去除——避免把整个文件名（恰好就是域名）
    全部吃掉导致空结果。
    """
    cleaned = _DOMAIN_PATTERN.sub("", value or "")
    return cleaned if cleaned.strip("@ /_-.") else value


def strip_escape_strings(filename: str, escape_string_list: list[str], replace_char: str = "") -> str:
    filename = filename.upper()
    # 长字符串优先替换，避免 ".COM@" 抢先命中后破坏 "489155.COM@" 这类更具体的规则。
    sorted_escape_strings = sorted((string for string in escape_string_list if string), key=len, reverse=True)
    for string in sorted_escape_strings:
        filename = filename.replace(string.upper(), replace_char)
    return filename


def normalize_uncensored_digit_number(number: str) -> str:
    raw_number = (number or "").strip().strip("-_. ")
    if not raw_number:
        return ""

    if match := UNCENSORED_DIGIT_NUMBER_PATTERN.fullmatch(raw_number):
        return f"{match['head']}{match['sep']}{match['tail']}"

    if match := UNCENSORED_DIGIT_NUMBER_PREFIX_PATTERN.fullmatch(raw_number):
        # 保留站点前缀：route_uncensored_official 按前缀精确路由；
        # 剥掉前缀会让 1pondo(尾号>=100) 误路由 pacopacomama、
        # pacopacomama(尾号 001-099) 误路由 1pondo（尾号长度猜测不可靠）。
        # 用 "-" 连接前缀与数字段，与 official_uncensored 的
        # DIGIT_NUMBER_WITH_PREFIX_RE（[-_ ]* 分隔）兼容。
        return f"{match['prefix']}-{match['head']}{match['sep']}{match['tail']}"

    return ""


def is_uncensored(number: str) -> bool:
    if (
        re.match(r"n\d{4}", number)
        or re.search(r"[^.]+\.\d{2}\.\d{2}\.\d{2}", number)
        or normalize_uncensored_digit_number(number)
    ):
        return True

    # 无码车牌BT,CT,EMP,CCDV,CWP,CWPBD,DSAM,DRC,DRG,GACHI,heydouga,JAV,LAF,LAFBD,HEYZO,KTG,KP,KG,LLDV,MCDV,MKD,MKBD,MMDV,NIP,PB,PT,QE,RED,RHJ,S2M,SKY,SKYHD,SMD,SSDV,SSKP,TRG,TS,xxx-av,YKB
    key_start_word = [
        "BT-",
        "CT-",
        "EMP-",
        "CCDV-",
        "CWP-",
        "CWPBD-",
        "DSAM-",
        "DRC-",
        "DRG-",
        "GACHI-",
        "heydouga",
        "JAV-",
        "LAF-",
        "LAFBD-",
        "HEYZO-",
        "KTG-",
        "KP-",
        "KG-",
        "LLDV-",
        "MCDV-",
        "MKD-",
        "MKBD-",
        "MMDV-",
        "NIP-",
        "PB-",
        "PT-",
        "QE-",
        "RED-",
        "RHJ-",
        "S2M-",
        "SKY-",
        "SKYHD-",
        "SMD-",
        "SSDV-",
        "SSKP-",
        "TRG-",
        "TS-",
        "xxx-av-",
        "YKB-",
        "bird",
        "bouga",
    ]
    return any(number.upper().startswith(each.upper()) for each in key_start_word)


def is_suren(number: str) -> bool:
    if re.search(r"\d{3,}[A-Z]+-\d{2}", number.upper()) or "SIRO" in number.upper():
        return True
    return any(_matches_suren_prefix(number, key) for key in ManualConfig.SUREN_DIC)


def _matches_suren_prefix(number: str, key: str) -> bool:
    number_upper = number.upper()
    key_upper = key.upper()
    if number_upper.startswith(key_upper):
        return True

    # S-Cute 的实际番号是 SCUTE-xxx，历史配置使用 CUTE- 作为补全键。
    return key_upper == "CUTE-" and number_upper.startswith("SCUTE-")


def match_number(text: str, number: str) -> bool:
    """搜索结果番号匹配。

    字母前缀番号（BF、BS 等）严格匹配，避免 BF-002 被 ABF-002 误匹配；
    数字前缀素人番号（252MY-001 等）保持宽松包含匹配。
    """
    if re.match(r"^\d", number):
        return number.upper() in text.upper()
    return re.search(rf"(?<![A-Z0-9]){re.escape(number)}(?![A-Z0-9])", text, re.IGNORECASE) is not None


def get_number_letters(number: str) -> str:
    number_upper = number.upper()
    if r := re.search(r"([A-Za-z0-9-.]{3,})[-_. ]\d{2}\.\d{2}\.\d{2}", number):
        return r[1]
    if number_upper.startswith("FC2"):
        return "FC2"
    if number_upper.startswith("MYWIFE"):
        return "MYWIFE"
    if number_upper.startswith("KIN8"):
        return "KIN8"
    if number_upper.startswith("S2M"):
        return "S2M"
    if number_upper.startswith("T28"):
        return "T28"
    if number_upper.startswith("TH101"):
        return "TH101"
    if number_upper.startswith("XXX-AV"):
        return "XXX-AV"
    if r := re.search(r"(MKY-[A-Z]+)-\d{3,}", number_upper):
        return r[1]
    if re.search(r"(CW3D2D?BD)", number_upper):
        return "CW3D2D"
    if re.search(r"MCB3D[BD]*-\d{2,}", number_upper):
        return "MCB3D"
    if matches := re.findall(r"(H4610|C0930|H0930)-[A-Z]+\d{4,}", number_upper):
        return matches[0]
    result = re.search(r"(\d*[A-Za-z]+)\d*", number)
    return result[1] if result else "未知车牌"


def get_number_first_letter(number: str) -> str:
    if not number:
        return "#"
    result = number.upper()[0]
    # 用 str.isalnum() 而非 bytes.isalnum(): 后者按字节判 ASCII,
    # 会使日/韩/中文等非 ASCII 首字母一律归 "#", 导致归类错误
    return result if result.isalnum() else "#"


def long_name(short_name: str) -> str:
    long_name = ManualConfig.OUMEI_NAME.get(short_name.lower())
    return long_name.lower().replace("-", "").replace(".", "") if long_name else short_name.lower()


def get_file_number(filepath: str, escape_string_list: list[str]) -> str:
    real_name = os.path.splitext(os.path.split(filepath)[1])[0].strip() + "."

    # 去除域名干扰（489155.com@、www.xxx.cn 等），减少对 escape_string_list 配置的依赖
    real_name = remove_disturb(real_name) + "."

    # 去除多余字符
    file_name = remove_escape_string1(real_name, escape_string_list) + "."

    # 替换cd_part、EP、-C
    filename = (
        file_name.replace("-C.", ".")
        .replace(".PART", "-CD")
        .replace("-PART", "-CD")
        .replace(" EP.", ".EP")
        .replace("-CD-", "")
    )

    # 去除分集
    filename = re.sub(r"[-_ .]CD\d{1,2}", "", filename)  # xxx-CD1.mp4
    filename = re.sub(r"[-_ .][A-Z0-9]\.$", "", filename)  # xxx_1.mp4, xxx.1.mp4, xxx.A.mp4, xxx A.mp4
    filename = filename.replace(" ", "-").strip("-_. ")
    oumei_filename = filename

    # 去除时间
    filename = re.sub(r"\d{4}[-_.]\d{1,2}[-_.]\d{1,2}", "", filename)  # 去除文件名中时间
    filename = re.sub(r"[-\[]\d{2}[-_.]\d{2}[-_.]\d{2}]?", "", filename)  # 去除文件名中时间

    # 转换番号
    filename = (
        filename.replace("FC2-PPV", "FC2-").replace("FC2PPV", "FC2-").replace("--", "-").replace("GACHIPPV", "GACHI")
    )

    # 处理 111111-111、111111_111、1pondo_111111_111、10musume_111111_01 这类无码数字番号
    if uncensored_digit_number := normalize_uncensored_digit_number(filename):
        return uncensored_digit_number

    # 提取番号
    if "MYWIFE" in filename and re.search(r"NO\.\d*", filename):  # 提取 mywife No.1111
        temp_nums = re.findall(r"NO\.(\d*)", filename)
        if temp_nums:
            return f"Mywife No.{temp_nums[0]}"

    elif r := re.search(r"CW3D2D?BD-?\d{2,}", filename):  # 提取番号 CW3D2DBD-11
        file_number = r.group()
        return file_number

    elif r := re.search(r"MMR-?[A-Z]{2,}-?\d+[A-Z]*", filename):  # 提取番号 mmr-ak089sp
        file_number = r.group()
        return file_number.replace("MMR-", "MMR")

    elif (
        r := re.search(r"([^A-Z]|^)(MD[A-Z-]*\d{4,}(-\d)?)", file_name)
    ) and "MDVR" not in file_name:  # 提取番号 md-0165-1
        file_number = r.group(2)
        return file_number

    elif re.findall(
        r"([A-Z0-9_]{2,})[-.]2?0?(\d{2}[-.]\d{2}[-.]\d{2})", oumei_filename
    ):  # 提取欧美番号 sexart.11.11.11
        result = re.findall(r"([A-Z0-9-]{2,})[-_.]2?0?(\d{2}[-.]\d{2}[-.]\d{2})", oumei_filename)
        return (long_name(result[0][0].strip("-")) + "." + result[0][1].replace("-", ".")).capitalize()

    elif (
        (r := re.search(r"XXX-AV-\d{4,}", filename))  # MKY-A-11111
        or (r := re.search(r"MKY-[A-Z]+-\d{3,}", filename))  # 提取xxx-av-11111
    ):
        file_number = r.group()

    elif "FC2" in filename or "HEYZO" in filename:
        prefix = "FC2" if "FC2" in filename else "HEYZO"
        cleaned = filename.replace("PPV", "").replace("_", "-").replace("--", "-")
        min_digits = 5 if prefix == "FC2" else 3
        if r := re.search(rf"{prefix}-(\d{{{min_digits},}})", cleaned):
            file_number = f"{prefix}-{r.group(1)}"
        elif r := re.search(rf"{prefix}(\d{{{min_digits},}})", cleaned):
            file_number = f"{prefix}-{r.group(1)}"
        else:
            file_number = cleaned

    elif r := re.search(
        r"(H4610|C0930|H0930)-[A-Z]+\d{4,}", filename
    ):  # 提取H4610-ki111111 c0930-ki221218 h0930-ori1665
        file_number = r.group()

    elif r := re.search(r"KIN8(TENGOKU)?-?\d{3,}", filename):  # 提取S2MBD-002 或S2MBD-006
        file_number = r.group().replace("TENGOKU", "-").replace("--", "-")

    elif (
        (r := re.search(r"S2M[BD]*-\d{3,}", filename))  # MCB3DBD-33
        or (r := re.search(r"MCB3D[BD]*-\d{2,}", filename))  # S2MBD-002
    ):
        file_number = r.group()

    elif r := re.search(r"T28-?\d{3,}", filename):  # 提取T28-223
        file_number = r.group().replace("T2800", "T28-")

    elif r := re.search(r"TH101-\d{3,}-\d{5,}", filename):  # 提取th101-140-112594
        file_number = r.group().lower()

    elif r := re.search(r"(?<![A-Z0-9])9([A-Z]{2,})(\d{2,3})(?![A-Z0-9])", filename):
        # 提取 DMM 预约版番号 9ssis01 -> SSIS-001（9 前缀 + 厂牌 + 编号，编号补零到 3 位）
        # lookbehind 保证 9 必须是番号段开头（前面不是字母数字），防误伤 ABC9XXX 这类
        file_number = f"{r.group(1)}-{int(r.group(2)):03d}"

    elif r := re.search(r"([A-Z]{2,})00(\d{3})", filename):  # 提取ssni00644为ssni-644
        file_number = r[1] + "-" + r[2]

    elif r := re.search(r"\d{2,}[A-Z]{2,}-\d{2,}[A-Z]?", filename):  # 提取类似259luxu-1456番号
        file_number = r.group()

    elif r := re.search(r"[A-Z]{2,}-\d{2,}[Z]?", filename):  # 提取类似mkbd-120番号
        file_number = r.group()
        for key, value in ManualConfig.SUREN_DIC.items():
            if _matches_suren_prefix(file_number, key):
                file_number = value + file_number
                break

    elif (
        (r := re.search(r"[A-Z]+-[A-Z]\d+", filename))  # mkbd-s120
        or (r := re.search(r"\d{2,}[-_]\d{2,}", filename))  # 111111-000 111111_000
        or (r := re.search(r"\d{3,}-[A-Z]{3,}", filename))  # 111111-MMMM
    ):
        file_number = r.group()

    elif r := re.search(r"([^A-Z]|^)(N\d{4})(\D|$)", filename):  # 提取n1111
        file_number = r.group(2).lower()

    elif r := re.search(r"H_\d{3,}([A-Z]{2,})(\d{2,})", filename):  # 提取类似h_173mega05番号
        a, b = r.groups()
        file_number = a + "-" + b

    elif (
        (r_findall := re.findall(r"([A-Z]{3,}).*?(\d{2,})", filename))  # 3个及以上字母，2个及以上数字
        or (r_findall := re.findall(r"([A-Z]{2,}).*?(\d{3,})", filename))  # 2个及以上字母，3个及以上数字
    ):
        temp = r_findall[0]
        file_number = temp[0] + "-" + temp[1]

    else:
        temp_name = re.sub(r"[【(（\[].+?[]）)】]", "", file_name).strip("@. ")  # 去除[]
        temp_name = unicodedata.normalize("NFC", temp_name)  # Mac 把会拆成两个字符，即 NFD，而网页请求使用的是 NFC
        with contextlib.suppress(Exception):
            temp_name = temp_name.encode("cp932").decode("shift_jis")  # 转换为常见日文，比如～ 转换成 〜
        file_number = temp_name

    if file_number.startswith("FC-"):
        file_number = file_number.replace("FC-", "FC2-")
    return file_number.strip("-_. ")


# pure version of models.base.remove_escape_string
def remove_escape_string1(filename: str, escape_string_list: list[str], replace_char: str = "") -> str:
    filename = strip_escape_strings(filename, escape_string_list, replace_char)
    short_strings = [
        "4K",
        "4KS",
        "8K",
        "HD",
        "LR",
        "VR",
        "DVD",
        "FULL",
        "HEVC",
        "H264",
        "H265",
        "X264",
        "X265",
        "AAC",
        "XXX",
        "PRT",
    ]
    for each in short_strings:
        filename = re.sub(rf"[-_ .\[]{each.upper()}[-_ .\]]", "-", filename)
    return filename.replace("--", "-").strip("-_ .")


def normalize_movie_number(value: str) -> str:
    """番号匹配键：用于两侧同时折叠后比较，不用于落库改写。

    `_` -> `-` 与抹 `PPV-` 都是有损折叠（`072625_001` 一本道与 `072625-001` 加勒比
    是两部不同影片），所以库里的番号永远存 provider 给出的规范原样；本函数只出现在
    "两侧同时折叠后比较"的场景（字幕配对、番号一致性校验、合集前缀判定等）。

    人工输入按番号查库不要用它——会因大小写/分隔符与列的原样形态对不上而 miss，
    统一走 `movie_number_lookup_values` 做等值 IN 查询。
    """
    normalized = (value or "").strip().upper()
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("_", "-")
    normalized = normalized.replace("PPV-", "")
    return normalized


def movie_number_lookup_values(value: str) -> list[str]:
    """人工输入按番号点查的等值候选集（已大写，去重保序）。

    列里存的是 provider 规范原样，用户手输的大小写/分隔符未必一致：大小写交给
    `UPPER()`，分隔符靠候选集把 `_`/`-` 两种形态都列出来。等值 IN 走索引，
    不做模糊匹配，也不改写库值。
    """
    stripped = (value or "").strip().upper()
    if not stripped:
        return []
    candidates = [stripped]
    for swapped in (stripped.replace("_", "-"), stripped.replace("-", "_")):
        if swapped not in candidates:
            candidates.append(swapped)
    return candidates
