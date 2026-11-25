"""SSRF protection for every outbound fetch of a user-supplied URL.

* https only (http allowed only with ALLOW_PRIVATE_NETWORK for local dev)
* the host must resolve only to public addresses (no loopback, private,
  link-local / cloud metadata, multicast or reserved ranges)
* redirects are followed manually and every hop is re-checked
"""
from __future__ import annotations

import ipaddress
import socket
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urljoin, urlsplit

import httpx

from vp_shared.config import get_settings

USER_AGENT = "ViralPilotBot/0.1 (+automated authorised-source fetcher)"
MAX_REDIRECTS = 5


class UnsafeURL(ValueError):
    pass


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURL(f"cannot resolve {host}") from e
    return [ipaddress.ip_address(i[4][0]) for i in infos]


def check_url(url: str) -> str:
    cfg = get_settings()
    parts = urlsplit(url)
    allowed_schemes = {"https", "http"} if cfg.allow_private_network else {"https"}
    if parts.scheme not in allowed_schemes:
        raise UnsafeURL(f"scheme {parts.scheme!r} not allowed")
    if not parts.hostname:
        raise UnsafeURL("URL has no host")
    if parts.username or parts.password:
        raise UnsafeURL("credentials in URL not allowed")
    if cfg.allow_private_network:
        return url
    for ip in _resolve(parts.hostname):
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL(f"{parts.hostname} resolves to non-public address {ip}")
    return url


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT})


def safe_get(url: str, timeout: float = 30.0) -> httpx.Response:
    with _client(timeout) as c:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            r = c.get(url)
            if r.is_redirect and "location" in r.headers:
                url = urljoin(url, r.headers["location"])
                continue
            r.read()
            return r
    raise UnsafeURL("too many redirects")


@contextmanager
def safe_stream(url: str, timeout: float = 120.0) -> Iterator[httpx.Response]:
    with _client(timeout) as c:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            req = c.build_request("GET", url)
            r = c.send(req, stream=True)
            if r.is_redirect and "location" in r.headers:
                r.close()
                url = urljoin(url, r.headers["location"])
                continue
            try:
                yield r
            finally:
                r.close()
            return
    raise UnsafeURL("too many redirects")
