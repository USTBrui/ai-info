# -*- coding: utf-8 -*-
"""抓取器集合

Author: wr
"""

from .base import BaseFetcher, FetchError, FetchResult, RawItem
from .github_atom import GitHubAtomFetcher
from .rss import RSSFetcher


def create_fetcher(source, settings: dict) -> BaseFetcher:
    """根据配置里的「类型」字段，造出对应的抓取器"""
    stype = (source.type or "").strip().lower()

    if stype == "rss":
        return RSSFetcher(source, settings)
    if stype == "atom":
        return GitHubAtomFetcher(source, settings)
    if stype == "html_diff":
        from .html_snapshot import HtmlSnapshotFetcher

        return HtmlSnapshotFetcher(source, settings)

    raise FetchError(
        f"源「{source.name}」的类型是 \"{source.type}\"，程序不认识。"
        f"只能填这几种之一：rss / atom / html_diff。"
    )


__all__ = [
    "BaseFetcher",
    "FetchError",
    "FetchResult",
    "RawItem",
    "RSSFetcher",
    "GitHubAtomFetcher",
    "create_fetcher",
]
