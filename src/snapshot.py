# -*- coding: utf-8 -*-
"""
快照读写与比对：给「没有 RSS 的厂商官网」用的变化检测

Author: wr

工作原理：
  很多厂商的更新日志、价格页、活动页根本没有 RSS。
  那就每天去看一眼那个页面，把看到的条目记下来；
  下次再去时，跟上次记的对比，多出来的就是「新动态」。

三条关键约束（都是踩过坑总结出来的）：

1. 快照必须提交到 Git 仓库。
   GitHub Actions 每次运行都是一台全新的机器，
   快照不落盘的话，下次运行时根本没有「上次」可以比，
   这个机制就整个失效了。

2. 快照永不过期，每次比对后直接用本次结果覆盖重建。
   不要搞「保留最近 N 天」那套：
   一是 CI 里 git checkout 会把文件修改时间全部重置，按时间清理必然误判；
   二是快照一旦过期就会退化为「首次运行」，
   一次网络抖动导致的连续失败，就会让整页历史条目被当成新增，直接刷屏。

3. 指纹只算「标题 + 网址」，绝不算正文。
   页面里常有相对时间、阅读量、访问数这类每次都在变的东西，
   算进去的话，同一条内容每天都会被误判为「有变化」。
"""

from __future__ import annotations

import json
import os

from .utils import normalize_url, now_cn, short_hash

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(PROJECT_ROOT, "快照")


def snapshot_path(source_id: str) -> str:
    return os.path.join(SNAPSHOT_DIR, f"{source_id}.json")


def make_key(title: str, url: str) -> str:
    """
    条目的指纹。

    只吃标题和归一化后的网址，不碰正文，
    这样页面上的时间戳、计数器变化就不会造成误报。
    """
    return short_hash((title or "").strip(), normalize_url(url))


def load(source_id: str) -> dict | None:
    """读取某个源的上次快照；没有就返回 None（代表这是第一次抓）"""
    path = snapshot_path(source_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        # 快照坏了不要紧，当作没有快照，重新建立基线即可
        return None


def save(source_id: str, entries: list[dict]) -> None:
    """覆盖写入快照。旧内容会被本次结果完全替换，所以体积恒定。"""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    payload = {
        "source_id": source_id,
        "updated_at": now_cn().isoformat(),
        "count": len(entries),
        "items": entries,
    }
    with open(snapshot_path(source_id), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def diff_and_update(source_id: str, entries: list[dict]) -> tuple[list[dict], bool]:
    """
    跟上次快照比对，返回 (新出现的条目, 这次是不是基线)。

    基线模式：第一次抓某个源时，只把当前内容记下来，一条都不产出。
    否则第一天会把页面上所有的历史更新都当成「今天新增」，
    整个看板被一个源刷满。
    """
    previous = load(source_id)

    # 先把本次结果存下来，保证哪怕下面出错也不会丢快照
    save(source_id, entries)

    if previous is None:
        return [], True

    old_keys = {item.get("key") for item in previous.get("items") or [] if item.get("key")}
    fresh = [item for item in entries if item.get("key") not in old_keys]
    return fresh, False
