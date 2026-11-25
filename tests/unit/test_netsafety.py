import pytest
from vp_shared import netsafety


@pytest.mark.parametrize("url", [
    "http://example.com/feed",            # not https
    "https://127.0.0.1/feed",             # loopback
    "https://169.254.169.254/latest/",    # cloud metadata
    "https://10.0.0.5/x",                 # private
    "https://[::1]/x",                    # ipv6 loopback
    "file:///etc/passwd",
    "https://user:pw@example.com/",
])
def test_unsafe_urls_refused(url):
    with pytest.raises(netsafety.UnsafeURL):
        netsafety.check_url(url)


def test_public_ip_allowed():
    assert netsafety.check_url("https://1.1.1.1/feed")
