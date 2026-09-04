# -*- coding: utf-8 -*-
"""
RSS / Atom 抓取器

Author: wr

一个解析器同时吃 RSS 2.0 和 Atom 两种格式，覆盖绝大多数博客、论坛、新闻站。

额外本事：Discourse 论坛（大佬说、LinuxDo 都是）的正文里会写
「15 个帖子 - 11 位参与者」，这里会把它解析成热度数据，
网页上就能按「讨论最热烈」排序了。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..utils import parse_datetime
from .base import BaseFetcher, FetchError, RawItem

# Discourse 论坛的热度标记，例如：15 个帖子 - 11 位参与者
_HEAT_RE = re.compile(r"(\d+)\s*个帖子\s*[-–—]\s*(\d+)\s*位参与者")
# 有些源会写点赞数
_LIKE_RE = re.compile(r"(\d+)\s*(?:个)?(?:赞|点赞|喜欢|likes?)", re.IGNORECASE)

_TITLE_TAGS = {"title"}
_LINK_TAGS = {"link"}
_SUMMARY_TAGS = {"description", "summary", "content", "encoded", "subtitle"}
_TIME_TAGS = {"pubdate", "published", "updated", "date", "created", "modified"}
_AUTHOR_TAGS = {"creator", "author", "name"}


def _local(tag: str) -> str:
    """去掉 XML 命名空间前缀，只留标签名。

    RSS 里同一个含义的标签可能被不同的命名空间包着，
    比如 {http://purl.org/dc/elements/1.1/}creator 和 creator，
    统一取最后一段就能一视同仁。
    """
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, names: set[str]) -> str:
    """在子节点里找第一个名字匹配且有文字的节点"""
    for child in node:
        if _local(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return ""


def _child_link(node: ET.Element) -> str:
    """
    找链接。

    RSS 的写法是 <link>网址</link>；
    Atom 的写法是 <link href="网址"/>（可能带 rel="self" 指向自己，那种要跳过）。
    """
    fallback = ""
    for child in node:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if href:
            rel = (child.get("rel") or "alternate").lower()
            if rel in ("alternate", ""):
                return href
            if not fallback and rel != "self":
                fallback = href
        text = (child.text or "").strip()
        if text and not fallback:
            fallback = text
    return fallback


def _parse_heat(summary_html: str) -> dict:
    """从正文里挖热度数据，挖不到就返回空字典"""
    heat: dict = {}
    if not summary_html:
        return heat
    match = _HEAT_RE.search(summary_html)
    if match:
        heat["replies"] = int(match.group(1))
        heat["participants"] = int(match.group(2))
    like = _LIKE_RE.search(summary_html)
    if like:
        heat["likes"] = int(like.group(1))
    return heat


class RSSFetcher(BaseFetcher):
    """RSS / Atom 通用抓取器"""

    type_name = "rss"

    def fetch(self) -> list[RawItem]:
        text = self.http_get(self.source.url)

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise FetchError(
                f"这个地址返回的内容不是有效的 RSS/Atom（{exc}）。"
                f"请打开 {self.source.url} 看看，是不是变成了登录页或者错误页。"
            ) from exc

        nodes = self._collect_entries(root)
        if not nodes:
            raise FetchError(
                "RSS 里一条内容都没找到。可能是格式特殊，或者这个源暂时是空的。"
            )

        limit = int(self.settings.get("每个源最多条数", 50))
        items: list[RawItem] = []
        for node in nodes[:limit]:
            item = self._node_to_item(node)
            if item is not None:
                items.append(item)

        if not items:
            raise FetchError("读到了条目，但都缺少标题或链接，已全部丢弃。")

        return items

    # ---------------------------------------------------------------- 内部实现

    @staticmethod
    def _collect_entries(root: ET.Element) -> list[ET.Element]:
        """不管 RSS 的 item 还是 Atom 的 entry，统统收进来"""
        return [
            node for node in root.iter()
            if _local(node.tag) in ("item", "entry")
        ]

    @staticmethod
    def _node_to_item(node: ET.Element) -> RawItem | None:
        title = _child_text(node, _TITLE_TAGS)
        url = _child_link(node)
        if not title and not url:
            return None

        summary_html = _child_text(node, _SUMMARY_TAGS)
        author = _child_text(node, _AUTHOR_TAGS)

        published = parse_datetime(_child_text(node, _TIME_TAGS))

        categories = [
            (child.text or "").strip()
            for child in node
            if _local(child.tag) == "category" and (child.text or "").strip()
        ]

        extra: dict = {}
        if categories:
            extra["categories"] = categories

        return RawItem(
            title=title or "(无标题)",
            url=url,
            summary_raw=summary_html,
            published_at=published,
            author=author,
            heat=_parse_heat(summary_html),
            extra=extra,
        )
