# -*- coding: utf-8 -*-
"""
条目归一化：把各路抓取器吐出来的原始条目，整理成统一格式

Author: wr

不同的源给的数据长得五花八门：有的带 HTML 标签，有的时间格式很怪，
有的网址后面拖一串推广参数。这一步把它们全部洗成同一个样子，
后面的去重、打分、网页显示就都能一视同仁了。
"""

from __future__ import annotations

from datetime import datetime

from .config_loader import Keywords, Source
from .fetchers.base import RawItem
from .utils import make_item_id, normalize_url, now_cn, strip_html, to_cn


def detect_vendor(text: str, keywords: Keywords) -> str | None:
    """从文字里认出这是哪一家的消息（认不出来返回 None）"""
    if not text or not keywords.vendors:
        return None
    low = text.lower()
    for vendor, aliases in keywords.vendors.items():
        for alias in aliases:
            if alias and alias in low:
                return vendor
    return None


def detect_promo(text: str, keywords: Keywords) -> list[str]:
    """找出命中的优惠活动关键词"""
    if not text or not keywords.promo:
        return []
    low = text.lower()
    hits: list[str] = []
    for word in keywords.promo:
        if word and word.lower() in low and word not in hits:
            hits.append(word)
    return hits


def match_focus(text: str, keywords: Keywords) -> list[str]:
    """找出命中的关注词"""
    if not text or not keywords.focus:
        return []
    low = text.lower()
    hits: list[str] = []
    for entry in keywords.focus:
        word = entry.get("词", "")
        if word and word.lower() in low and word not in hits:
            hits.append(word)
    return hits


def focus_weight(text: str, keywords: Keywords) -> int:
    """关注词命中的总权重，用来给条目加分"""
    if not text:
        return 0
    low = text.lower()
    total = 0
    for entry in keywords.focus:
        word = entry.get("词", "")
        if word and word.lower() in low:
            total += int(entry.get("权重", 3))
    return total


def normalize_item(
    raw: RawItem,
    source: Source,
    keywords: Keywords,
    settings: dict,
) -> dict:
    """把一个原始条目变成统一格式的字典"""
    title = strip_html(raw.title, 200) or "(无标题)"
    url = (raw.url or "").strip()

    keep = int(settings.get("单条摘要保留字数", 200))
    summary = strip_html(raw.summary_raw, keep)

    published = to_cn(raw.published_at)
    time_known = published is not None
    if published is None:
        # 源没给时间就用抓取时间顶上，但不标记为「已知时间」
        published = now_cn()

    haystack = f"{title} {summary}"
    vendor = source.vendor or detect_vendor(haystack, keywords)
    promo_hits = detect_promo(haystack, keywords)
    focus_hits = match_focus(haystack, keywords)
    categories = list((raw.extra or {}).get("categories") or [])[:3]

    return {
        "id": make_item_id(title, url),
        "title": title,
        "url": url,
        "url_norm": normalize_url(url),
        "source_id": source.id,
        "source_name": source.name,
        "category": source.category,
        "vendor": vendor,
        "author": raw.author or "",
        "published_at": published.isoformat(),
        "time_known": time_known,
        "summary_raw": summary,
        "summary_ai": "",
        "score": 3,                       # 1-5，后面 AI 或规则打分会覆盖
        "heat": dict(raw.heat or {}),      # {"replies": 15, "participants": 11}
        "is_promo": bool(promo_hits),
        "promo_keywords": promo_hits,
        "tags": categories,
        "matched_keywords": focus_hits,
        "cluster_id": "",
        "cluster_size": 1,
        "sources": ([{"name": source.name, "url": url}] if url else []),
        "ai": False,
    }


def normalize_all(
    pairs: list[tuple[Source, RawItem]],
    keywords: Keywords,
    settings: dict,
) -> list[dict]:
    """批量归一化，顺便丢掉既没标题又没链接的垃圾条目"""
    items: list[dict] = []
    for source, raw in pairs:
        item = normalize_item(raw, source, keywords, settings)
        if item["title"] == "(无标题)" and not item["url"]:
            continue
        items.append(item)
    return items


def parse_published(value: str) -> datetime | None:
    """把条目里存的时间字符串读回成时间对象（排序时要用）"""
    from .utils import parse_datetime

    return parse_datetime(value)
