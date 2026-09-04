"""v1 ini 加载链路的回归测试。

历史缺陷（全库审查 A1）：load_v1 的特例分支把 `xxx_website`（自定义站点 URL）键
直接放进传给 `ConfigV1(**d)` 的字典，而 ConfigV1 dataclass 未声明这些字段 →
TypeError → import 时模块级 `manager = ConfigManager()` 连锁崩溃，且崩溃前
`self.path = v2path` 已执行导致 MARK_FILE 指向未生成文件，用户 v1 配置永久丢失。

修复后：`xxx_website` 键经 unknown_fields 通道由 `_update()` setattr 消化，
`Config.from_legacy` 把它们转成 site_configs。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdcx.config.enums import Website
from mdcx.config.v1 import ConfigV1, load_v1


def _write_v1_ini(path: Path, extra_lines: str = "") -> None:
    ini = f"""[common]
success_folder = /tmp/movies
{extra_lines}
"""
    path.write_text(ini, encoding="utf-8")


def test_load_v1_with_custom_website_key_no_crash(tmp_path):
    """v1 ini 含 javdb_website 时 load_v1 不产生未声明字段，ConfigV1(**d) 可构造。"""
    ini_path = tmp_path / "config.ini"
    _write_v1_ini(ini_path, "javdb_website = https://javdbcustom.example.com")

    d, errors = load_v1(ini_path)

    # 不再有形如 xxx_website 的 dataclass 未声明键
    website_keys = [k for k in d if k.endswith("_website") and k != "unknown_fields"]
    assert not website_keys, f"load_v1 不应把自定义站点键放进顶层字典: {website_keys}"

    # 真实链路 handle_v1 的构造方式必须可用
    config_v1 = ConfigV1(**d)
    config_v1.init()
    assert config_v1.get_website_base_url(Website.JAVDB) == "https://javdbcustom.example.com"

    # from_legacy 后进入 site_configs
    config = type(config_v1).to_pydantic_model(config_v1)
    assert config.get_site_url(Website.JAVDB) == "https://javdbcustom.example.com"


def test_load_v1_without_website_key_unchanged(tmp_path):
    """无自定义站点键的普通 v1 ini 行为不变。"""
    ini_path = tmp_path / "config.ini"
    _write_v1_ini(ini_path, "folder_name = {{ number }}")

    d, errors = load_v1(ini_path)

    config_v1 = ConfigV1(**d)
    config_v1.init()
    assert config_v1.folder_name == "{{ number }}"
