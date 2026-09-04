# -*- coding: utf-8 -*-
"""
构建产物：把整理好的条目写成网页能直接读取的数据文件

Author: wr

产出三个文件（都在「网页/data」目录下）：
  数据-最新.js   —— 最新一天的完整数据，网页首屏直接加载它
  数据-2026-09-04.js —— 当天归档，切换历史日期时按需加载
  数据-索引.js   —— 可用日期清单

为什么用 .js 而不是 .json？
因为你是双击本地网页文件打开的（file:// 协议），
浏览器在这种模式下不允许用 fetch 读本地 JSON，但允许用 <script> 加载 JS。
写成 JS 就是为了让你不用装任何服务器也能看。

为什么不写成一个变量名？
因为切换历史日期时会往页面里插入多个数据文件，
如果都叫同一个变量名，后加载的会把先加载的覆盖掉。
所以改成按日期当键挂上去：window.__AI_INFO_DATA__['2026-09-04']
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from .utils import build_js_data, now_cn

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "网页")
DATA_DIR = os.path.join(WEB_DIR, "data")
LOG_DIR = os.path.join(PROJECT_ROOT, "日志")
LOG_FILE = os.path.join(LOG_DIR, "抓取日志.md")

DATA_VAR = "__AI_INFO_DATA__"
INDEX_VAR = "__AI_INFO_INDEX__"

_LATEST_FILE = "数据-最新.js"
_INDEX_FILE = "数据-索引.js"
_DAILY_RE = re.compile(r"^数据-(\d{4}-\d{2}-\d{2})\.js$")

# 抓取日志最多保留最近这么多次运行记录，防止文件越来越大
LOG_KEEP_RUNS = 40


def ensure_dirs() -> None:
    """确保产物目录都存在"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def count_categories(items: list[dict]) -> dict:
    """统计每个分组各有多少条"""
    counts: dict[str, int] = {}
    for item in items:
        key = item.get("category") or "其他"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def build_payload(
    items: list[dict],
    date_str: str,
    mode: str,
    briefing: str,
    health: list[dict],
    generated_at: datetime,
) -> dict:
    """组装成网页要用的完整数据"""
    vendors = sorted({item["vendor"] for item in items if item.get("vendor")})
    sources = sorted({item.get("source_name", "") for item in items if item.get("source_name")})

    return {
        "date": date_str,
        "generated_at": generated_at.isoformat(),
        "mode": mode,                     # ai（AI 模式）或 rule（规则模式）
        "briefing": briefing,
        "stats": {
            "total": len(items),
            "promo": sum(1 for i in items if i.get("is_promo")),
            "today_new": sum(1 for i in items if (i.get("published_at") or "").startswith(date_str)),
            "sources_ok": sum(1 for h in health if h.get("status") == "ok"),
            "sources_fail": sum(1 for h in health if h.get("status") != "ok"),
            "categories": count_categories(items),
        },
        "vendors": vendors,
        "source_names": sources,
        "items": items,
        "sources_health": health,
    }


def write_data_files(payload: dict, date_str: str, keep_days: int) -> dict:
    """
    写出数据文件，返回本次写出的文件路径信息。

    同时清理过老的归档，只保留最近 keep_days 天的。
    """
    ensure_dirs()
    body = build_js_data(DATA_VAR, date_str, payload)

    latest_path = os.path.join(DATA_DIR, _LATEST_FILE)
    daily_path = os.path.join(DATA_DIR, f"数据-{date_str}.js")

    _write_text(latest_path, body)
    _write_text(daily_path, body)

    # 重新扫描目录，生成日期索引
    dates = list_archive_dates()
    if date_str not in dates:
        dates.insert(0, date_str)
    dates.sort(reverse=True)

    index_body = (
        f"window.{INDEX_VAR} = window.{INDEX_VAR} || [];\n"
        f"window.{INDEX_VAR} = {_js_array(dates)};\n"
    )
    _write_text(os.path.join(DATA_DIR, _INDEX_FILE), index_body)

    removed = cleanup_old_archives(keep_days)

    return {
        "latest": latest_path,
        "daily": daily_path,
        "dates": dates,
        "removed": removed,
    }


def list_archive_dates() -> list[str]:
    """扫描数据目录，看看现在存了哪些日期的归档"""
    if not os.path.isdir(DATA_DIR):
        return []
    dates = []
    for name in os.listdir(DATA_DIR):
        match = _DAILY_RE.match(name)
        if match:
            dates.append(match.group(1))
    dates.sort(reverse=True)
    return dates


def cleanup_old_archives(keep_days: int) -> list[str]:
    """删掉超过保留天数的旧归档文件，返回被删掉的文件名"""
    dates = list_archive_dates()
    if len(dates) <= keep_days:
        return []

    expired = dates[keep_days:]
    removed = []
    for date_str in expired:
        path = os.path.join(DATA_DIR, f"数据-{date_str}.js")
        try:
            os.remove(path)
            removed.append(f"数据-{date_str}.js")
        except OSError:
            pass
    return removed


def build_health(results) -> list[dict]:
    """把抓取结果整理成网页「数据源健康面板」要用的数据"""
    health = []
    for result in results:
        health.append({
            "id": result.source_id,
            "name": result.source_name,
            "status": "ok" if result.ok else "fail",
            "count": len(result.items),
            "ms": result.elapsed_ms,
            "error": result.error or "",
            "warning": result.warning or "",
        })
    health.sort(key=lambda h: (h["status"] != "ok", -h["count"]))
    return health


def write_run_log(
    date_str: str,
    elapsed_seconds: float,
    raw_count: int,
    final_count: int,
    health: list[dict],
    mode: str,
    removed: list[str],
) -> None:
    """把这次运行的情况写进「日志/抓取日志.md」，最新的一次排在最前面"""
    ensure_dirs()

    ok = sum(1 for h in health if h["status"] == "ok")
    fail = len(health) - ok
    now = now_cn()

    lines = [
        f"## {now.strftime('%Y-%m-%d %H:%M')}（北京时间）",
        "",
        f"- 处理模式：{'AI 智能摘要' if mode == 'ai' else '规则模式（未使用 AI）'}",
        f"- 本次用时：{elapsed_seconds:.1f} 秒",
        f"- 抓到条目：{raw_count} 条，去重合并后 {final_count} 条",
        f"- 数据源：成功 {ok} 个，失败 {fail} 个",
        "",
        "| 数据源 | 状态 | 条数 | 耗时 |",
        "| --- | --- | --- | --- |",
    ]

    for h in health:
        status = "成功" if h["status"] == "ok" else "失败"
        lines.append(f"| {h['name']} | {status} | {h['count']} | {h['ms']}ms |")
        if h.get("error"):
            lines.append(f"| ↳ 原因 | {h['error']} | | |")

    if removed:
        lines.append("")
        lines.append(f"- 已清理过期归档：{len(removed)} 个（{'、'.join(removed[:5])}）")

    lines.append("")
    new_block = "\n".join(lines)

    old_blocks: list[str] = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # 按 "## " 开头的段落切分，保留最近若干次
        parts = re.split(r"(?m)^## ", content)
        header = parts[0] if parts and not parts[0].startswith("20") else ""
        blocks = ["## " + p for p in parts[1:] if p.strip()]
        old_blocks = blocks[: LOG_KEEP_RUNS - 1]
        if header.strip() and not header.startswith("## "):
            old_blocks.insert(0, header.rstrip())

    header_line = "# 抓取日志\n\n每次运行的记录都会写在这里，最新的一次排在最前面。\n"
    final = header_line + "\n" + new_block + "\n"
    if old_blocks:
        final += "\n" + "\n".join(old_blocks)

    _write_text(LOG_FILE, final)


def _js_array(values: list[str]) -> str:
    """生成 JS 字符串数组字面量"""
    import json

    return json.dumps(values, ensure_ascii=False)


def _write_text(path: str, text: str) -> None:
    """统一用 UTF-8 写文件，避免 Windows 上出现中文乱码"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
