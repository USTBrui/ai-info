# -*- coding: utf-8 -*-
r"""
网页源探测器：帮你找出该在配置里填哪个「选择器」

Author: wr

什么时候用它：
  想加一个没有 RSS 的厂商页面（更新日志、价格页、活动页），
  但不知道该填什么选择器 —— 让它帮你试。

它会拿一堆常见的选择器去页面上试，
告诉你每个选择器能抓到几条、前几条长什么样，
你挑一个顺眼的填进「配置/数据源清单.json」就行。

用法（在项目根目录执行）：
  python src\tools\probe_html.py --url https://某厂商.com/changelog
  python src\tools\probe_html.py --all          # 测配置里所有 html_diff 类型的源
  python src\tools\probe_html.py --only=deepseek_changelog
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config_loader import ConfigError, load_config  # noqa: E402
from src.fetchers.base import DEFAULT_HEADERS, install_ipv4_preference  # noqa: E402
from src.utils import setup_console_encoding, strip_html  # noqa: E402

# 常见的更新日志 / 列表类结构，挨个试
CANDIDATE_SELECTORS = [
    ".changelog-item", ".changelog", ".changelog-entry",
    "[class*=changelog] [class*=item]", "[class*=changelog]",
    "[class*=update-]", "[class*=release]",
    ".update-item", ".release-item", ".version-item",
    ".news-item", ".post-item", ".list-item",
    "article", "article h2", "article h3",
    ".markdown-body h2", ".markdown-body h3",
    ".doc-content h2", ".doc-content h3",
    "main h2", "main h3", "main li",
    ".content h2", ".content li",
    "section h3",
    "ul li", "ol li",
    "table tbody tr",
]

# 页面看起来像是「靠 JS 现渲染」的迹象
SPA_HINTS = [
    "noscript", "__NEXT_DATA__", "__NUXT__", "id=\"app\"",
    "id=\"root\"", "window.__INITIAL_STATE__", "nuxt",
]


def fetch_html(url: str, timeout: float = 25.0) -> tuple[str, str]:
    """抓一个页面，返回 (HTML, 出错原因)"""
    try:
        try:
            import requests

            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            if not resp.encoding:
                resp.encoding = "utf-8"
            return resp.text, ""
        except ImportError:
            import urllib.request

            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                charset = r.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace"), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"


def try_selector(html: str, selector: str, limit: int = 5) -> list[str]:
    """用一个选择器试着提取，返回前几条文本"""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        nodes = soup.select(selector)
    except Exception:  # noqa: BLE001
        return []

    out: list[str] = []
    for node in nodes[:limit]:
        text = strip_html(node.get_text(" ", strip=True), 90)
        if text:
            out.append(text)
    return out


def looks_like_spa(html: str) -> bool:
    """判断页面是不是靠 JavaScript 现渲染的（那种静态抓取抓不到内容）"""
    low = html.lower()
    hits = sum(1 for h in SPA_HINTS if h.lower() in low)
    text = strip_html(html)
    # 正文极少，又有 SPA 痕迹，基本可以确定抓不到东西
    return hits >= 2 and len(text) < 800


def probe_url(url: str) -> None:
    print("=" * 76)
    print(f"网址：{url}")
    print("=" * 76)

    html, error = fetch_html(url)
    if error:
        print(f"抓取失败：{error}")
        print("（这台电脑连不上它，不代表云端连不上；GitHub Actions 在国外通常可以）")
        return

    text = strip_html(html)
    print(f"页面大小：{len(html):,} 字符，可见文字约 {len(text):,} 字")

    title = ""
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        if soup.title:
            title = strip_html(soup.title.get_text(" ", strip=True), 80)
    except ImportError:
        pass
    if title:
        print(f"页面标题：{title}")

    if looks_like_spa(html):
        print()
        print("⚠️ 这个页面看着是靠 JavaScript 现渲染的，静态抓取只能拿到空壳，")
        print("   换成 html_diff 类型也抓不到内容。建议：")
        print("   1. 找找它有没有 RSS 或其他静态版本；")
        print("   2. 换个有内容的同类页面（比如它的文档站、GitHub 仓库）。")
        return

    print()
    print("各选择器能抓到的内容（挑一个合适的填进配置）：")
    print("-" * 76)

    found = False
    for selector in CANDIDATE_SELECTORS:
        samples = try_selector(html, selector)
        if not samples:
            continue
        found = True
        print(f"\n  {selector}")
        for s in samples[:3]:
            print(f"      · {s}")

    if not found:
        print("  一个都没抓到 —— 这个页面的结构比较特殊。")
        print("  建议在浏览器里右键检查元素，看看内容包在哪个标签里。")
        return

    print()
    print("-" * 76)
    print("挑一个填进「配置/数据源清单.json」的「选择器」里，")
    print("它是数组，可以同时填好几个备选，抓不到第一个会自动试下一个。")


def main() -> int:
    setup_console_encoding()
    parser = argparse.ArgumentParser(description="探测网页源，找出可用的选择器")
    parser.add_argument("--url", default="", help="要探测的网页地址")
    parser.add_argument("--all", action="store_true", help="探测配置里所有 html_diff 类型的源")
    parser.add_argument("--only", default="", help="只探测指定 id 的源，多个用逗号隔开")
    args = parser.parse_args()

    install_ipv4_preference()

    if args.url:
        probe_url(args.url)
        return 0

    try:
        config = load_config()
    except ConfigError as exc:
        print("配置有问题：\n")
        print(exc)
        return 1

    sources = [s for s in config.sources if s.type == "html_diff"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        sources = [s for s in sources if s.id in wanted]
    elif not args.all:
        sources = [s for s in sources if s.enabled]

    if not sources:
        print("配置里还没有 html_diff 类型的源。")
        print("想加一个的话，先用 --url 探测一下那个页面：")
        print(r"  python src\tools\probe_html.py --url https://某厂商.com/changelog")
        return 0

    print(f"共 {len(sources)} 个网页源\n")
    for source in sources:
        print(f"\n【{source.name}】（id={source.id}）")
        if source.selectors:
            print(f"  当前配置的选择器：{source.selectors}")
        probe_url(source.url)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
