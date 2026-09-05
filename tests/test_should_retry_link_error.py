"""链接错误重试判定的回归测试。"""

from mdcx.base.web import _should_retry_link_error


class TestShouldRetryLinkError:
    def test_no_retry_on_curl_cffi_ctype_race(self):
        """curl_cffi 内部 ctype 竞态错误不是网络问题，重试只会反复失败并拖慢。"""
        assert not _should_retry_link_error(
            "curl-cffi 异常: initializer for ctype 'void *' must be a cdata pointer, not NoneType"
        )

    def test_no_retry_on_404(self):
        assert not _should_retry_link_error("HTTP 404")

    def test_no_retry_on_410(self):
        assert not _should_retry_link_error("HTTP 410")

    def test_retry_on_timeout(self):
        assert _should_retry_link_error("连接超时")

    def test_retry_on_429(self):
        assert _should_retry_link_error("HTTP 429")

    def test_retry_on_generic_network_error(self):
        """普通网络错误保持可重试（语义不被本修复破坏）。"""
        assert _should_retry_link_error("curl-cffi 异常: Timeout")

    def test_empty_error_no_retry(self):
        assert not _should_retry_link_error("")
