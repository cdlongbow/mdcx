import pytest

from mdcx.config.models import Website

# 爬虫测试默认针对线上站点做真实抓取，按 P2 测试质量专项要求统一标记为
# integration，使 CI 默认 `-m "not network and not integration"` 跳过它们。
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _offline_check_url(request: pytest.FixtureRequest):
    """爬虫单测默认把 check_url 断网（返回 None = 候选不可用，升级链直接跳过）。

    背景：DMM 图床升级链对 pics.dmm.co.jp 逐候选 GET 验证，测试未 mock 时
    会真实联网（本环境/CI 对 DMM 域超时或封锁），单条用例平均多耗 3.6s，
    15+ 条集体拖慢全量检查约 55s，且结果随网络环境抖动。

    - 测试内显式 `monkeypatch.setattr("mdcx.base.web.check_url", ...)` 优先生效
      （monkeypatch 为属性级覆盖，本 fixture 先行设置后可被其替换）
    - 真网络验证走 marker: `@pytest.mark.network`（CI 默认跳过）
    """

    if request.node.get_closest_marker("network"):
        yield
        return

    async def _offline(url, *args, **kwargs):
        return None

    import mdcx.base.web as base_web

    original = base_web.check_url
    base_web.check_url = _offline
    yield
    base_web.check_url = original


def pytest_addoption(parser: pytest.Parser):
    """添加自定义命令行参数"""
    g1 = parser.getgroup("parsers", "parser test options")
    g1.addoption("--overwrite", action="store_true", help="覆盖现有的测试结果")
    g1.addoption("--parser-name", nargs="+", help="指定解析器名称")
    g2 = parser.getgroup("crawler", "crawler test options")
    g2.addoption("--network", action="store_true", help="允许网络请求")
    g2.addoption("--site", nargs="+", help="指定网站")


@pytest.fixture
def overwrite(request: pytest.FixtureRequest) -> bool:
    """通过命令行参数 --overwrite 以覆盖现有的测试结果"""
    return request.config.getoption("--overwrite", default=False)


@pytest.fixture
def parser_names(request: pytest.FixtureRequest) -> list[str]:
    """通过命令行参数 --parser-name 指定只在部分解析器上运行测试"""
    names = request.config.getoption("--parser-name", default=[])
    return names


@pytest.fixture
def network(request: pytest.FixtureRequest) -> bool:
    """通过命令行参数 --network 允许网络请求"""
    return request.config.getoption("--network", default=False)


@pytest.fixture
def sites(request: pytest.FixtureRequest) -> list[Website]:
    """通过命令行参数 --site 指定网站"""
    sites = request.config.getoption("--site", default=[])
    sites = sites if isinstance(sites, list) else [sites] if sites else []
    for site in sites:
        if site.upper() not in Website.__members__:
            raise ValueError(f"Invalid site: {site}. Available sites: {[s.name for s in Website]}")
    return [Website[site.upper()] for site in sites]
