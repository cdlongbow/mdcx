import re
from typing import Any

from .enums import DownloadableFile, HDPicSource, Website

CURRENT_CONFIG_VERSION = 2


def _str_to_list(v: str | list[Any] | None, sep: str = ",", unique: bool = True) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        items = [str(item).strip() for item in v]
    else:
        items = [item.strip() for item in v.replace("，", sep).split(sep)]
    items = [item for item in items if item]
    if unique:
        return list(dict.fromkeys(items))
    return items


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _migrate_download_file_option(value: Any) -> Any:
    value = _enum_value(value)
    if value == "youma_use_poster":
        return None
    if value == DownloadableFile.POSTER_AUTO_BEST.value:
        return DownloadableFile.POSTER_AUTO_BEST.value
    return value


def _is_removed_airav_site(site: object) -> bool:
    return site == Website.AIRAV or site == Website.AIRAV.value


_SITE_RENAMES = {"javdbapi": "dmm_api"}

_VALID_SITE_VALUES = frozenset(site.value for site in Website)


def _rename_site(site: str) -> str:
    return _SITE_RENAMES.get(site, site)


def _is_valid_site(site: object) -> bool:
    """站点值是否仍存在于当前 `Website` 枚举中。

    2026-08 精简了 15 个失效/重复爬虫（cnmdb/hdouban/mdtv/love6/kin8/giga/cableav/
    hscangku/fc2club/fc2hub/jav321/fantastica/dahlia/faleno），旧配置里残留的
    站点值会让 pydantic 校验整体失败，进而使配置被写入 `_failed.json`
    且界面回写被跳过（表现为「保存不生效」，议题 #55）。故在此静默剔除。
    7mmtv 曾在同一批被移除，2026-09 以聚合站爬虫形式回归（移植自 Hazard804/mdcx），
    旧配置中残留的 7mmtv 值因此自动恢复有效。
    """
    value = _enum_value(site)
    return isinstance(value, str) and value in _VALID_SITE_VALUES


def _clean_sites(sites: list[Any]) -> list[str]:
    """重命名 + 剔除已移除站点，保持原有顺序。"""
    return [
        renamed
        for site in sites
        if not _is_removed_airav_site(site) and _is_valid_site(renamed := _rename_site(str(_enum_value(site))))
    ]


def _migrate_site_list(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_sites(_str_to_list(value, ","))
    if isinstance(value, list | set):
        return _clean_sites(list(value))
    return value


def _migrate_field_config_sites(value: Any) -> None:
    if not isinstance(value, dict):
        return
    sites = value.get("site_prority")
    if isinstance(sites, list):
        value["site_prority"] = _clean_sites(sites)


def _migrate_site_configs(data: dict[str, Any]) -> None:
    """剔除 site_configs 中键为已移除站点的条目。"""
    site_configs = data.get("site_configs")
    if not isinstance(site_configs, dict):
        return
    data["site_configs"] = {key: value for key, value in site_configs.items() if _is_valid_site(key)}


def _migrate_removed_hd_pic_sources(data: dict[str, Any]) -> None:
    valid_values = {HDPicSource.AMAZON.value}
    hd_pics = data.get("download_hd_pics")
    if isinstance(hd_pics, str):
        items: list[Any] = _str_to_list(hd_pics, ",")
    elif isinstance(hd_pics, list | set):
        items = list(hd_pics)
    else:
        return
    data["download_hd_pics"] = [item for item in items if str(_enum_value(item)) in valid_values]


def _migrate_builtin_naming_templates(data: dict[str, Any]) -> None:
    """将旧版内置命名模板迁移为 Jinja2 写法。"""

    mapping = {
        "actor": "{{ actor }}",
        "number actor": "{{ number }} {{ actor }}",
        "number": "{{ number }}",
        "number title": "{{ number }} {{ title }}",
        "[number]title": "[{{ number }}]{% if title and title != number %}{{ title }}{% endif %}",
        "letters/number": "{{ letters }}/{{ number }}",
        "actor/number actor": "{{ actor }}/{{ number }} {{ actor }}",
        "{actor}": "{{ actor }}",
        "{number} {actor}": "{{ number }} {{ actor }}",
        "{number}": "{{ number }}",
        "{number} {title}": "{{ number }} {{ title }}",
        "[{number}]{title}": "[{{ number }}]{% if title and title != number %}{{ title }}{% endif %}",
        "{letters}/{number}": "{{ letters }}/{{ number }}",
        "{actor}/{number} {actor}": "{{ actor }}/{{ number }} {{ actor }}",
    }

    def convert_braced_template(template: str) -> str:
        if "{{" in template or "{%" in template:
            return template

        def replace_field(text: str) -> str:
            return re.sub(r"\{([A-Za-z0-9_]+)\}", r"{{ \1 }}", text)

        while "{?" in template:
            start = template.find("{?")
            colon = template.find(":", start + 2)
            if colon < 0:
                break
            depth = 0
            end = -1
            for index in range(colon + 1, len(template)):
                if template[index] == "{":
                    depth += 1
                elif template[index] == "}":
                    if depth == 0:
                        end = index
                        break
                    depth -= 1
            if end < 0:
                break
            field = template[start + 2 : colon].strip()
            content = replace_field(template[colon + 1 : end])
            optional = f"{{% if {field} %}}{content}{{% endif %}}"
            template = template[:start] + optional + template[end + 1 :]
        return replace_field(template)

    for key in (
        "folder_name",
        "naming_file",
        "naming_media",
        "update_a_folder",
        "update_b_folder",
        "update_c_filetemplate",
        "update_d_folder",
        "update_titletemplate",
    ):
        value = data.get(key)
        if not isinstance(value, str):
            continue
        data[key] = mapping.get(value, convert_braced_template(value))


def migrate_config_data(data: dict[str, Any]) -> list[str]:
    """
    统一处理配置结构变更.

    所有可恢复的旧配置差异都应在这里归一化，再交给 Pydantic 做强校验。
    """
    warnings: list[str] = []

    data.pop("google_used", None)
    data.pop("google_exclude", None)
    # 严格校验开关移除（读零校验架构下语义为空）：旧配置残留键静默清洗
    # 注意: 本函数返回的所有消息均为「迁移警告」而非校验错误, 必须带 [迁移] 前缀——
    # load_config 只把无前缀消息视为致命错误并触发 _failed.json 保护分支,
    # 漏加前缀会让正常迁移的用户配置被误判为「读取配置文件出错」且无法切回(议题 #69)。
    if data.pop("amazon_strict_pic_verify", None) is not None:
        warnings.append("[迁移] 已移除配置项「严格校验 Amazon 图片」：ASIN 库命中即信任，软校验仅用于新 ASIN 入库")
    _migrate_builtin_naming_templates(data)
    _migrate_removed_hd_pic_sources(data)

    if _is_removed_airav_site(data.get("website_single")) or not _is_valid_site(data.get("website_single")):
        data["website_single"] = Website.AIRAV_CC.value
    for key, value in list(data.items()):
        if key.startswith("website_") and key != "website_single":
            data[key] = _migrate_site_list(value)

    if isinstance(field_configs := data.get("field_configs"), dict):
        for value in field_configs.values():
            _migrate_field_config_sites(value)
    if isinstance(type_field_configs := data.get("type_field_configs"), dict):
        for field_configs in type_field_configs.values():
            if not isinstance(field_configs, dict):
                continue
            for value in field_configs.values():
                _migrate_field_config_sites(value)
    _migrate_site_configs(data)

    if "proxy_type" in data:
        data["use_proxy"] = data["proxy_type"] != "no"
    if isinstance(r := data.get("proxy"), str):
        r = r.strip()
        if all(schema not in r for schema in ["http://", "https://", "socks5://", "socks5h://"]):
            data["proxy"] = "http://" + r
    if isinstance(r := data.get("cf_bypass_url"), str):
        r = r.strip().rstrip("/")
        if r and all(schema not in r for schema in ["http://", "https://"]):
            r = "http://" + r
        data["cf_bypass_url"] = r
    if isinstance(r := data.get("cf_bypass_proxy"), str):
        r = r.strip()
        if r and all(schema not in r for schema in ["http://", "https://", "socks4://", "socks5://", "socks5h://"]):
            r = "http://" + r
        data["cf_bypass_proxy"] = r
    if isinstance(r := data.get("cf_bypass_trawl_url"), str):
        r = r.strip().rstrip("/")
        if r and all(schema not in r for schema in ["http://", "https://"]):
            r = "http://" + r
        data["cf_bypass_trawl_url"] = r
    if isinstance(r := data.get("cf_bypass_trawl_backend"), str):
        r = r.strip().lower()
        data["cf_bypass_trawl_backend"] = r if r in ("trawl", "flaresolverr") else "trawl"

    if isinstance(r := data.get("use_database"), int):
        data["use_database"] = bool(r)
    if isinstance(r := data.get("local_library"), str):
        data["local_library"] = _str_to_list(r, ",")

    if isinstance(download_files := data.get("download_files"), str):
        data["download_files"] = [
            item
            for value in _str_to_list(download_files, ",")
            if (item := _migrate_download_file_option(value)) is not None
        ]
    elif isinstance(download_files, list | set):
        data["download_files"] = [
            item for value in download_files if (item := _migrate_download_file_option(value)) is not None
        ]

    if isinstance(translate_config := data.get("translate_config"), dict):
        old_prompt = translate_config.pop("llm_prompt", None)
        if isinstance(old_prompt, str):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)
        if isinstance(translate_by := translate_config.get("translate_by"), list):
            translate_config["translate_by"] = [item for item in translate_by if item != "youdao"]
    if isinstance(old_prompt := data.get("llm_prompt"), str):
        translate_config = data.setdefault("translate_config", {})
        if isinstance(translate_config, dict):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)

    data["config_version"] = CURRENT_CONFIG_VERSION
    return warnings
