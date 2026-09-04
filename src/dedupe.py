# -*- coding: utf-8 -*-
"""
去重与聚类：把「同一件事的多个报道」合并成一条

Author: wr

同一个消息往往会在好几个地方出现，比如某家发布新模型，
大佬说、LinuxDo、量子位可能同时都在说。
如果原样全列出来，一屏里全是重复内容，看着累。

这里做两层合并：
  第一层：网址完全一样 → 肯定是同一条
  第二层：标题高度相似 → 判定为同一事件（用中文二元字组比相似度）
合并之后只显示一条，并标注「来自 N 个源」，点开能看到各个来源。
"""

from __future__ import annotations

from .utils import jaccard, tokenize

# 标题相似度达到这个值，就认为是同一件事。
# 0.75 是经验值：调高了会漏合并，调低了会把不相干的新闻揉到一起。
DEFAULT_THRESHOLD = 0.75


def dedupe_and_cluster(items: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """
    输入一堆条目，返回合并后的条目列表。

    合并过程中会保留：
      - 全部来源（sources 数组）
      - 更高的热度（回复数最多的那份）
      - 更长的摘要（信息更全的那份）
      - 所有命中的关注词
    """
    # ---------- 第一层：按网址去重 ----------
    by_url: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        key = item.get("url_norm") or f"__nourl__{item['id']}"
        if key in by_url:
            _merge(by_url[key], item)
        else:
            by_url[key] = item
            order.append(key)
    unique = [by_url[key] for key in order]

    # ---------- 第二层：按标题相似度聚类 ----------
    clusters: list[tuple[dict, list[str]]] = []
    for item in unique:
        tokens = tokenize(item["title"])
        placed = False
        for rep, rep_tokens in clusters:
            if jaccard(tokens, rep_tokens) >= threshold:
                _merge(rep, item)
                placed = True
                break
        if not placed:
            item["cluster_id"] = f"c_{len(clusters):03d}"
            clusters.append((item, tokens))

    result = [rep for rep, _ in clusters]
    for rep, _ in clusters:
        rep["cluster_size"] = len(rep.get("sources") or []) or 1
    return result


def _merge(target: dict, other: dict) -> None:
    """把 other 身上的有用信息并进 target"""
    # 合并来源，同一网址不重复记录
    seen = {s.get("url") for s in target.get("sources") or []}
    for src in other.get("sources") or []:
        if src.get("url") and src["url"] not in seen:
            target.setdefault("sources", []).append(src)
            seen.add(src["url"])

    # 热度取大的那份
    other_replies = int((other.get("heat") or {}).get("replies", 0))
    target_replies = int((target.get("heat") or {}).get("replies", 0))
    if other_replies > target_replies:
        target["heat"] = other["heat"]

    # 摘要取长的那份，同时把链接也换过去（信息更全的更值得点）
    if len(other.get("summary_raw") or "") > len(target.get("summary_raw") or ""):
        target["summary_raw"] = other["summary_raw"]
        if other.get("url"):
            target["url"] = other["url"]

    # 关注词、优惠标记：有就补上
    for word in other.get("matched_keywords") or []:
        if word not in target.get("matched_keywords", []):
            target.setdefault("matched_keywords", []).append(word)

    if other.get("is_promo") and not target.get("is_promo"):
        target["is_promo"] = True
        target["promo_keywords"] = other.get("promo_keywords") or []

    # 厂商：谁都没有就尽力补一个
    if not target.get("vendor") and other.get("vendor"):
        target["vendor"] = other["vendor"]

    # 时间取更早的那份（通常是最早报道的那个）
    if other.get("time_known") and target.get("time_known"):
        if (other.get("published_at") or "") < (target.get("published_at") or ""):
            target["published_at"] = other["published_at"]
    elif other.get("time_known") and not target.get("time_known"):
        target["published_at"] = other["published_at"]
        target["time_known"] = True
