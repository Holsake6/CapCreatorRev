"""HTTP with retries, a working CA bundle and errors a person can act on.

Earlier versions called ``urlopen`` directly. Two failure modes looked the same
to the reviewer ("CapCut 连接失败") although they need different fixes:

* python.org builds on macOS ship without CA certificates, so every HTTPS
  request fails certificate verification until ``certifi`` is used;
* sandboxes, company networks or a missing VPN refuse the host outright.

``NetError.kind`` separates those cases and ``advice()`` explains the fix.
"""

import http.client
import os
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")

ADVICE = {
    "dns": "域名无法解析：当前网络无法访问该网站（可能需要 VPN，或该地区屏蔽了 CapCut）。",
    "proxy_blocked": "代理/防火墙拒绝了该域名：如果在 Claude 云端环境运行，需要在环境设置的 Network access 中把该域名加入 Allowed domains；公司网络请联系网管放行。",
    "ssl": "HTTPS 证书校验失败：请运行 `pip install certifi`（或双击 安装依赖.command）；macOS 的 python.org 版本还可以运行 /Applications/Python 3.x/Install Certificates.command。",
    "timeout": "连接超时：网络较慢或被限速，可稍后重试，或检查 VPN 节点。",
    "connection": "连接被重置或拒绝：可能是网络不稳定或该站点限制了访问频率。",
    "http": "网站返回了错误状态码。",
}


class NetError(OSError):
    def __init__(self, kind, url, detail=""):
        self.kind = kind
        self.url = url
        self.detail = detail
        super().__init__(f"[{kind}] {urlparse(url).hostname}: {detail}")

    def advice(self):
        return ADVICE.get(self.kind, "")


def ssl_context():
    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile:
        try:
            import certifi
            cafile = certifi.where()
        except ImportError:
            cafile = None
    context = ssl.create_default_context(cafile=cafile)
    # A proxy that re-terminates TLS publishes its CA through SSL_CERT_FILE or
    # the system store; keep the system defaults too when certifi was chosen.
    if cafile and not os.environ.get("SSL_CERT_FILE"):
        try:
            context.load_default_certs()
        except ssl.SSLError:
            pass
    return context


_OPENER = None


def opener():
    global _OPENER
    if _OPENER is None:
        _OPENER = build_opener(ProxyHandler(), HTTPSHandler(context=ssl_context()))
    return _OPENER


def ascii_url(url):
    """urllib requires an ASCII request target; Japanese explore slugs are common."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=quote(parsed.path, safe="/%:@!$&'()*+,;="),
                                      query=quote(parsed.query, safe="=&%+/:,;@!$'()*?")))


def classify(exc, url):
    if isinstance(exc, NetError):
        return exc
    if isinstance(exc, HTTPError):
        return NetError("http", url, f"HTTP {exc.code}")
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if isinstance(reason, socket.gaierror) or "Name or service not known" in text or "nodename nor servname" in text:
        return NetError("dns", url, text)
    if "Tunnel connection failed" in text or " 403" in text and "Tunnel" in text or "407" in text:
        return NetError("proxy_blocked", url, text)
    if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return NetError("ssl", url, text)
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
        return NetError("timeout", url, text)
    return NetError("connection", url, text)


RETRYABLE = {"timeout", "connection"}


def request(url, *, data=None, headers=None, timeout=20, retries=2, method=None, max_bytes=None):
    """Return ``(final_url, body_bytes, response_headers)`` or raise ``NetError``."""
    merged = {"User-Agent": BROWSER_UA, "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.6"}
    merged.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(ascii_url(url), data=data, headers=merged, method=method)
            with opener().open(req, timeout=timeout) as response:
                if max_bytes is None:
                    body = response.read()
                else:
                    body = response.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        raise NetError("too_large", url, f"超过 {max_bytes // 1024 // 1024}MB")
                return response.url, body, response.headers
        except NetError as exc:
            raise exc
        except HTTPError as exc:
            last = classify(exc, url)
            if exc.code not in (429, 500, 502, 503, 504):
                raise last from exc
        except (URLError, OSError, http.client.HTTPException) as exc:
            last = classify(exc, url)
            if last.kind not in RETRYABLE:
                raise last from exc
        if attempt < retries:
            time.sleep(min(8, 1.5 * 2 ** attempt))
    raise last


def fetch_text(url, **kwargs):
    final_url, body, headers = request(url, **kwargs)
    charset = headers.get_content_charset() if headers else None
    if not charset and urlparse(final_url).hostname == "www.oricon.co.jp":
        charset = "cp932"
    return final_url, body.decode(charset or "utf-8", "replace")


def download(url, target, *, max_bytes=200 * 1024 * 1024, timeout=60, headers=None):
    """Stream a file to ``target``. Returns the final URL."""
    merged = {"User-Agent": BROWSER_UA}
    merged.update(headers or {})
    target = str(target)
    try:
        req = Request(ascii_url(url), headers=merged)
        with opener().open(req, timeout=timeout) as response, open(target, "wb") as out:
            total = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise NetError("too_large", url, f"超过 {max_bytes // 1024 // 1024}MB")
                out.write(chunk)
            return response.url, response.headers
    except NetError:
        raise
    except (HTTPError, URLError, OSError, http.client.HTTPException) as exc:
        raise classify(exc, url) from exc


def probe(url, timeout=12, method="GET", data=None, headers=None):
    """Connectivity check used by ``doctor``. Never raises."""
    started = time.time()
    try:
        final_url, body, _ = request(url, timeout=timeout, retries=0, method=method, data=data,
                                     headers=headers, max_bytes=2 * 1024 * 1024)
        return {"ok": True, "url": url, "final_url": final_url, "bytes": len(body),
                "ms": int((time.time() - started) * 1000)}
    except NetError as exc:
        # An HTTP status still proves the host is reachable.
        reachable = exc.kind == "http"
        return {"ok": reachable, "url": url, "kind": exc.kind, "detail": exc.detail,
                "advice": "" if reachable else exc.advice(), "ms": int((time.time() - started) * 1000)}
