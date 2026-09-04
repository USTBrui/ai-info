# -*- coding: utf-8 -*-
r"""
AI 资讯每日看板 · 主程序

Author: wr

一条命令干完所有事：读配置 → 抓所有源 → 去重合并 → AI 摘要打分 → 生成网页数据。

常用法（在项目根目录执行）：
  python src\main.py                # 正常跑一次
  python src\main.py --no-ai        # 不花钱、不用 AI，纯规则排序
  python src\main.py --only=locdd_latest,linuxdo_latest   # 只抓指定的源
  python src\main.py --all          # 连配置里禁用的源也一起试
  python src\main.py --dry-run      # 只抓不写文件，用来试配置
  python src\main.py -v             # 把每一条标题都打印出来

正常情况下你不需要手动敲这些命令，
双击项目根目录的「一键刷新.bat」就够了。
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:  # 支持两种方式运行：python src/main.py 和 python -m src.main
    from . import ai_enrich, build
    from .config_loader import ConfigError, load_config
    from .dedupe import dedupe_and_cluster
    from .fetchers import create_fetcher
    from .fetchers.base import FetchResult, install_ipv4_preference
    from .normalize import normalize_all
    from .utils import now_cn, setup_console_encoding, strip_html, today_cn
except ImportError:  # pragma: no cover
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import ai_enrich, build
    from src.config_loader import ConfigError, load_config
    from src.dedupe import dedupe_and_cluster
    from src.fetchers import create_fetcher
    from src.fetchers.base import FetchResult, install_ipv4_preference
    from src.normalize import normalize_all
    from src.utils import now_cn, setup_console_encoding, strip_html, today_cn


def force_utf8_console() -> None:
    """按命令行窗口的实际编码输出中文（具体逻辑见 utils.setup_console_encoding）"""
    setup_console_encoding()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI 资讯每日看板：抓取你关心的 AI 资讯并生成看板",
    )
    parser.add_argument("--no-ai", action="store_true", help="不使用 AI 摘要，纯规则排序（不花钱也更快）")
    parser.add_argument("--only", default="", help="只抓指定 id 的源，多个用逗号隔开")
    parser.add_argument("--all", action="store_true", help="连配置里已禁用的源也一起抓")
    parser.add_argument("--dry-run", action="store_true", help="只抓不写文件，用来试配置对不对")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细信息，包括每条标题")
    return parser.parse_args()


def pick_sources(config, args) -> list:
    """根据命令行参数，决定这次要抓哪些源"""
    sources = list(config.sources) if args.all else [s for s in config.sources if s.enabled]

    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        sources = [s for s in sources if s.id in wanted]
        missing = wanted - {s.id for s in sources}
        if missing:
            print(f"注意：配置里找不到这些 id，已忽略：{', '.join(sorted(missing))}")

    return sources


def fetch_all(sources, settings: dict) -> list[FetchResult]:
    """并发抓取所有源。任何一个源出错都不会影响别的源。"""
    workers = max(1, int(settings.get("并发线程", 8)))
    results: list[FetchResult] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for source in sources:
            try:
                fetcher = create_fetcher(source, settings)
            except Exception as exc:  # noqa: BLE001
                results.append(FetchResult(
                    source_id=source.id,
                    source_name=source.name,
                    ok=False,
                    error=f"抓取器创建失败：{exc}",
                ))
                continue
            futures[pool.submit(fetcher.run)] = source

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                source = futures[future]
                results.append(FetchResult(
                    source_id=source.id,
                    source_name=source.name,
                    ok=False,
                    error=f"运行异常：{exc}",
                ))

    # 按配置里的顺序排好，输出时方便对照
    order = {s.id: i for i, s in enumerate(sources)}
    results.sort(key=lambda r: order.get(r.source_id, 999))
    return results


def sort_items(items: list[dict]) -> list[dict]:
    """排序：重要度 → 热度 → 命中的关注词数量 → 时间"""
    def sort_key(item: dict):
        heat = int((item.get("heat") or {}).get("replies", 0) or 0)
        return (
            -(item.get("score") or 3),
            -heat,
            -len(item.get("matched_keywords") or []),
            item.get("published_at") or "",
        )

    return sorted(items, key=sort_key)


def make_briefing(items: list[dict], date_str: str) -> str:
    """写一句话的今日简报（规则模式下的版本）"""
    if not items:
        return "这次没有抓到任何内容，可以打开「日志/抓取日志.md」看看是哪个源出了问题。"

    total = len(items)
    parts = [f"今天共汇总 {total} 条 AI 相关资讯"]

    promo_count = sum(1 for item in items if item.get("is_promo"))
    if promo_count:
        parts.append(f"其中 {promo_count} 条是优惠活动")

    top = [item for item in items if (item.get("score") or 0) >= 4][:3]
    if top:
        titles = "、".join(f"《{strip_html(item['title'], 24)}》" for item in top)
        parts.append(f"最值得关注的是 {titles}")

    hottest = max(
        items,
        key=lambda i: int((i.get("heat") or {}).get("replies", 0) or 0),
        default=None,
    )
    replies = int((hottest.get("heat") or {}).get("replies", 0) or 0) if hottest else 0
    if hottest and replies >= 10:
        parts.append(f"论坛里讨论最热烈的是《{strip_html(hottest['title'], 24)}》，已有 {replies} 条回复")

    return "；".join(parts) + "。"


def print_report(results: list[FetchResult], raw_count: int, final_count: int,
                 mode: str, note: str, items: list[dict], verbose: bool) -> None:
    """在屏幕上打印本次运行的成果"""
    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok

    print()
    print("=" * 60)
    print(f"数据源：成功 {ok} 个，失败 {fail} 个")
    print(f"抓到条目：{raw_count} 条 → 去重合并后 {final_count} 条")
    print(f"处理模式：{'AI 智能摘要' if mode == 'ai' else '规则模式'}")
    if note:
        print(f"说明：{note}")
    print("=" * 60)

    if fail:
        print("\n失败的源（不影响其他内容）：")
        for r in results:
            if not r.ok:
                print(f"  × {r.source_name}：{r.error}")
        print("  小提示：本机连不上的网站，不代表云端也连不上。GitHub Actions 在国外，通常能抓到更多。")

    if items:
        print(f"\n最重要的 10 条：")
        for index, item in enumerate(items[:10], start=1):
            stars = "★" * (item.get("score") or 3)
            heat = (item.get("heat") or {}).get("replies", 0)
            heat_text = f" {heat}回复" if heat else ""
            flag = " [优惠]" if item.get("is_promo") else ""
            cluster = f" ({item['cluster_size']}源)" if item.get("cluster_size", 1) > 1 else ""
            print(f"  {index:>2}. {stars} {strip_html(item['title'], 44)}{heat_text}{flag}{cluster}")

    if verbose:
        print("\n全部条目：")
        for index, item in enumerate(items, start=1):
            print(f"  {index:>3}. [{item.get('source_name','')}] {strip_html(item['title'], 60)}")


def main() -> int:
    force_utf8_console()
    args = parse_args()
    started = time.time()

    try:
        config = load_config()
    except ConfigError as exc:
        print("配置有问题，程序没法继续：\n")
        print(exc)
        return 1

    # 让后续所有网络请求优先走 IPv4，
    # 免得在 IPv6 不通的机器上每个请求都白等几十秒。
    if config.settings.get("强制IPv4优先", True):
        install_ipv4_preference()

    sources = pick_sources(config, args)
    if not sources:
        print("没有可抓取的源。请打开「配置/数据源清单.json」，把至少一个源的「启用」改成 true。")
        return 1

    print(f"开始抓取 {len(sources)} 个源，请稍等……")
    if config.settings.get("时区"):
        print(f"（时间按 {config.settings['时区']} 计算）")

    results = fetch_all(sources, config.settings)

    # 汇总所有抓到的条目
    source_by_id = {s.id: s for s in config.sources}
    pairs = []
    for result in results:
        if not result.ok:
            continue
        source = source_by_id.get(result.source_id)
        if source is None:
            continue
        for raw_item in result.items:
            pairs.append((source, raw_item))

    raw_count = len(pairs)
    items = normalize_all(pairs, config.keywords, config.settings)
    items = dedupe_and_cluster(items)

    # AI 摘要与打分（失败会自动降级）
    if args.no_ai:
        ai_enrich.apply_rule_mode(items, config.keywords)
        mode, note = "rule", "已按参数 --no-ai 跳过 AI"
    else:
        try:
            items, used_ai, note = ai_enrich.enrich(
                items, config.settings, config.keywords, verbose=args.verbose
            )
            mode = "ai" if used_ai else "rule"
        except Exception as exc:  # noqa: BLE001
            ai_enrich.apply_rule_mode(items, config.keywords)
            mode, note = "rule", f"AI 模块异常，已降级：{exc}"

    items = sort_items(items)

    date_str = today_cn()
    health = build.build_health(results)
    briefing = make_briefing(items, date_str)
    generated_at = now_cn()
    payload = build.build_payload(items, date_str, mode, briefing, health, generated_at)

    elapsed = time.time() - started

    if args.dry_run:
        print("\n试运行模式：数据已生成，但不会写入文件。")
        print_report(results, raw_count, len(items), mode, note, items, args.verbose)
        return 0

    written = build.write_data_files(
        payload, date_str, int(config.settings.get("归档保留天数", 30))
    )
    build.write_run_log(
        date_str=date_str,
        elapsed_seconds=elapsed,
        raw_count=raw_count,
        final_count=len(items),
        health=health,
        mode=mode,
        removed=written.get("removed") or [],
    )

    print_report(results, raw_count, len(items), mode, note, items, args.verbose)
    print(f"\n数据已写入：网页/data/数据-{date_str}.js")
    print(f"本次用时 {elapsed:.1f} 秒。现在双击「网页/index.html」就能看到看板了。")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
