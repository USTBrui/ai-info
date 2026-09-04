# -*- coding: utf-8 -*-
"""
厂商官网抓取器：给没有 RSS 的页面用的「快照对比」方案

Author: wr

适合这些场景：
  - 厂商的更新日志页（changelog）
  - 价格页、活动页、公告页
  - 任何「内容会变、但没有 RSS」的页面

怎么用：在 配置/数据源清单.json 里这样写一条
  {
    "id": "deepseek_changelog",
    "名称": "DeepSeek · 更新日志",
    "类型": "html_diff",
    "网址": "https://...",
    "分类": "更新日志",
    "厂商": "DeepSeek",
    "启用": true,
    "选择器": [".changelog-item", ".update-list li", "article"]
  }

「选择器」是字符串数组，程序从左到右依次尝试：
第一个抓不到内容，就试第二个，以此类推。
网站改版时只要换一下选择器就行，不用改代码。
"""

from __future__ import annotations

import re
import urllib.parse

from .. import snapshot
from ..utils import strip_html
from .base import BaseFetcher, FetchError, RawItem

# 没有装 beautifulsoup4 时，用这个宽松方案兜底：
# 直接把页面上的链接都捡起来，过滤掉太短的（多半是导航菜单）
_MIN_TITLE_LEN = 6


class HtmlSnapshotFetcher(BaseFetcher):
    """没有 RSS 的网页：抓条目 → 跟上次快照比对 → 只吐出新增的部分"""

    type_name = "html_diff"

    def fetch(self) -> list[RawItem]:
        if not self.source.selectors:
            raise FetchError(
                "这个源没有填「选择器」，程序不知道该从页面上取哪一块内容。"
                "请在配置里补上，例如 [\"div.changelog-item\", \"li\"]。"
            )

        html = self.http_get(self.source.url)

        entries: list[dict] = []
        used_index = -1

        for index, selector in enumerate(self.source.selectors):
            entries = self._extract_by_selector(html, selector)
            if entries:
                used_index = index
                break

        # 一个选择器都没命中：要么是网站改版了，要么写错了选择器。
        # 这种情况绝不产出内容，避免把整个页面当成新东西刷屏。
        if not entries:
            raise FetchError(
                "所有选择器都没抓到内容，疑似网站改版或选择器写错了。"
                "可以先用浏览器打开这个页面，右键「检查」看看内容用的是什么标签。"
            )

        fresh, is_baseline = snapshot.diff_and_update(self.source.id, entries)

        # 把回退情况记下来，方便你回头维护配置
        if used_index > 0:
            self._warning = f"⚠️ 主选择器失效，已切至 fallback-{used_index}（{self.source.selectors[used_index]}）"

        if is_baseline:
            self._warning = "首次运行，已建立基线快照，本次不产出内容"
            return []

        limit = int(self.settings.get("每个源最多条数", 50))
        items = []
        for entry in fresh[:limit]:
            items.append(RawItem(
                title=entry.get("title") or "(无标题)",
                url=entry.get("url") or self.source.url,
                summary_raw=entry.get("summary") or "",
                published_at=None,  # 静态页面通常没有可靠时间，交给抓取时间兜底
                extra={"snapshot": True},
            ))

        self._warning = f"新增 {len(fresh)} 条" if fresh else "本次没有新内容"
        return items

    # BaseFetcher.run 会读取这个属性，塞进健康面板
    _warning = ""

    def run(self):
        self._warning = ""
        result = super().run()
        result.warning = self._warning
        return result

    # ---------------------------------------------------------------- 内部实现

    def _extract_by_selector(self, html: str, selector: str) -> list[dict]:
        """用 CSS 选择器提取条目。装了 bs4 就精确提取，没装就宽松兜底。"""
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError:
            return self._fallback_extract(html)

        try:
            soup = BeautifulSoup(html, "html.parser")
            nodes = soup.select(selector)
        except Exception:  # noqa: BLE001 - 选择器写得不对时 bs4 会抛异常
            return []

        limit = int(self.settings.get("每个源最多条数", 50))
        entries: list[dict] = []
        seen: set[str] = set()

        for node in nodes:
            if len(entries) >= limit:
                break

            title = node.get_text(" ", strip=True)
            title = strip_html(title, 200)
            if len(title) < _MIN_TITLE_LEN:
                continue

            # 找链接：节点自己是 <a> 就用自己，否则用它内部第一个 <a>
            url = ""
            if node.name == "a" and node.get("href"):
                url = node.get("href")
            else:
                anchor = node.find("a", href=True)
                if anchor:
                    url = anchor.get("href")

            url = urllib.parse.urljoin(self.source.url, url) if url else self.source.url

            key = snapshot.make_key(title, url)
            if key in seen:
                continue
            seen.add(key)

            entries.append({
                "key": key,
                "title": title,
                "url": url,
                "summary": strip_html(node.get_text(" ", strip=True), 300),
            })

        return entries

    def _fallback_extract(self, html: str) -> list[dict]:
        """
        没有 beautifulsoup4 时的兜底方案：
        把页面上的链接都捡起来，过滤掉太短的（多半是导航）。
        精度不如 CSS 选择器，但配合快照比对依然能用。
        """
        limit = int(self.settings.get("每个源最多条数", 50))
        entries: list[dict] = []
        seen: set[str] = set()

        for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                                 html, re.IGNORECASE | re.DOTALL):
            if len(entries) >= limit:
                break
            href, inner = match.group(1), match.group(2)
            title = strip_html(inner, 200)
            if len(title) < _MIN_TITLE_LEN:
                continue
            if href.startswith("#") or href.lower().startswith("javascript:"):
                continue

            url = urllib.parse.urljoin(self.source.url, href)
            key = snapshot.make_key(title, url)
            if key in seen:
                continue
            seen.add(key)

            entries.append({
                "key": key,
                "title": title,
                "url": url,
                "summary": "",
            })

        return entries
