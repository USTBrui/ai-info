# -*- coding: utf-8 -*-
"""
抓取器基类：统一负责网络请求、超时重试、域名限速、异常兜底

Author: wr

所有具体抓取器（RSS / Atom / 网页快照）都继承 BaseFetcher，
只用实现 fetch() 一个方法，剩下的脏活累活这里全包了。

核心原则：任何一个源挂掉，都不能影响其他源，更不能让整个程序崩溃。
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

# requests 和 beautifulsoup4 是「可选增强」：装了更好，没装也能跑
try:
    import requests

    HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    HAS_REQUESTS = False


def install_ipv4_preference() -> None:
    """
    让程序优先用 IPv4 建连接（默认开启，可在配置里关掉）。

    为什么需要这个？
    很多网站（尤其套了 Cloudflare 的）同时提供 IPv4 和 IPv6 地址，
    而国内大量家庭的宽带实际并不通 IPv6。
    程序按系统给的顺序会先去连 IPv6，一直等到超时才回头连 IPv4，
    一个本来 2 秒就能拿到的页面，硬生生要等 40 多秒。

    这里不是删掉 IPv6，只是把 IPv4 排到前面：
    IPv4 通就走 IPv4；真遇到只有 IPv6 的站点，照样能连上。
    """
    original = socket.getaddrinfo
    if getattr(original, "_ipv4_preferred", False):
        return  # 已经打过补丁了，别重复打

    def patched(host, port, family=0, type=0, proto=0, flags=0):
        infos = original(host, port, family, type, proto, flags)
        return sorted(infos, key=lambda info: 0 if info[0] == socket.AF_INET else 1)

    patched._ipv4_preferred = True  # type: ignore[attr-defined]
    socket.getaddrinfo = patched  # type: ignore[assignment]


# 伪装成普通浏览器，很多网站会拒绝明显的爬虫
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass
class RawItem:
    """抓取器吐出来的原始条目，还没经过统一整理"""
    title: str
    url: str
    summary_raw: str = ""
    published_at: datetime | None = None
    author: str = ""
    heat: dict = field(default_factory=dict)      # {"replies": 15, "participants": 11}
    extra: dict = field(default_factory=dict)     # 各抓取器自己要带的额外信息


@dataclass
class FetchResult:
    """一个源跑完的结果，无论成功失败都会返回这个对象"""
    source_id: str
    source_name: str
    ok: bool
    items: list[RawItem] = field(default_factory=list)
    error: str = ""
    warning: str = ""
    elapsed_ms: int = 0


class FetchError(Exception):
    """抓取失败。消息会直接显示在网页的「数据源健康面板」上"""


class BaseFetcher:
    """抓取器基类"""

    type_name = "base"

    # 记录每个域名下一次允许请求的时刻，避免把人家网站刷爆
    _next_ok: dict[str, float] = {}
    _lock = threading.Lock()

    def __init__(self, source, settings: dict):
        self.source = source
        self.settings = settings
        self.timeout = float(settings.get("抓取超时秒", 20))
        self.retries = int(settings.get("重试次数", 2))
        self.gap = float(settings.get("同域名请求间隔秒", 1.5))

    # ------------------------------------------------------------ 网络请求

    def _throttle(self, url: str) -> None:
        """同一个域名先后排队，不同域名之间互不影响"""
        host = urllib.parse.urlsplit(url).netloc or "unknown"
        wait = 0.0
        with self._lock:
            now = time.monotonic()
            earliest = self._next_ok.get(host, 0.0)
            if now < earliest:
                wait = earliest - now
            self._next_ok[host] = max(now, earliest) + self.gap
        if wait > 0:
            time.sleep(wait)

    def http_get(self, url: str, timeout: float | None = None) -> str:
        """
        抓取一个网页，返回文本。

        带浏览器请求头、超时、自动重试（失败一次就多等一会儿再试）。
        requests 装了就用 requests，没装就用标准库 urllib，行为一致。
        """
        timeout = timeout or self.timeout
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                if HAS_REQUESTS:
                    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
                    resp.raise_for_status()
                    if not resp.encoding:
                        resp.encoding = "utf-8"
                    return resp.text
                else:
                    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        raw = resp.read()
                        charset = resp.headers.get_content_charset() or "utf-8"
                        return raw.decode(charset, errors="replace")
            except Exception as exc:  # noqa: BLE001 - 任何异常都要兜住
                last_error = exc
                if attempt < self.retries:
                    # 退避等待：1 秒、2 秒、4 秒……
                    time.sleep(min(2 ** attempt, 8))

        raise FetchError(f"连续 {self.retries + 1} 次请求都失败了：{_brief(last_error)}")

    # ------------------------------------------------------------ 子类实现

    def fetch(self) -> list[RawItem]:
        """子类必须实现：真正去抓东西，返回 RawItem 列表"""
        raise NotImplementedError

    # ------------------------------------------------------------ 统一入口

    def run(self) -> FetchResult:
        """执行抓取并打包结果。这个方法永远不会抛异常。"""
        started = time.monotonic()
        try:
            items = self.fetch()
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.monotonic() - started) * 1000)
            return FetchResult(
                source_id=self.source.id,
                source_name=self.source.name,
                ok=False,
                error=f"{_brief(exc)}",
                elapsed_ms=elapsed,
            )

        elapsed = int((time.monotonic() - started) * 1000)
        return FetchResult(
            source_id=self.source.id,
            source_name=self.source.name,
            ok=True,
            items=items,
            elapsed_ms=elapsed,
        )


def _brief(exc: Exception | None) -> str:
    """把异常压缩成一句人话，不堆一长串看不懂的堆栈"""
    if exc is None:
        return "未知错误"
    name = type(exc).__name__
    msg = str(exc).strip()
    if not msg:
        return name
    msg = " ".join(msg.split())
    if len(msg) > 160:
        msg = msg[:160] + "…"
    return f"{name}: {msg}"
