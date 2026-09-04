# -*- coding: utf-8 -*-
r"""
探测数据源：把配置里的源挨个试一遍，看看哪些能抓、能抓多少条

Author: wr

什么时候用它：
  1. 刚加了一个新源，想确认网址对不对；
  2. 页面上某个源一直显示红色，想知道到底为什么失败；
  3. 想看看「配置里禁用」的那些源现在能不能用了。

用法（在项目根目录执行）：
  python src\tools\probe_sources.py            # 只测已启用的源
  python src\tools\probe_sources.py --all      # 连禁用的源一起测
  python src\tools\probe_sources.py --only=linuxdo_latest,locdd_latest
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# 允许直接运行本文件时也能 import 到 src 包
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config_loader import ConfigError, load_config  # noqa: E402
from src.fetchers import create_fetcher  # noqa: E402
from src.fetchers.base import install_ipv4_preference  # noqa: E402
from src.utils import setup_console_encoding, strip_html  # noqa: E402


def _fmt_status(row: dict) -> str:
    """把一行探测结果变成人看得懂的状态文字"""
    if not row["ok"]:
        return "失败"
    if row["count"] == 0:
        return "空"
    return "成功"


def probe(sources, settings, workers: int) -> list:
    """并发跑一遍所有源"""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for source in sources:
            try:
                fetcher = create_fetcher(source, settings)
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "source": source,
                    "ok": False,
                    "count": 0,
                    "ms": 0,
                    "error": f"抓取器创建失败：{exc}",
                    "sample": None,
                })
                continue
            futures[pool.submit(fetcher.run)] = source

        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "source": source,
                    "ok": False,
                    "count": 0,
                    "ms": 0,
                    "error": f"运行异常：{exc}",
                    "sample": None,
                })
                continue

            sample = None
            if result.items:
                first = result.items[0]
                sample = {
                    "title": strip_html(first.title, 60),
                    "url": first.url,
                    "heat": first.heat,
                    "time": first.published_at,
                }
            results.append({
                "source": source,
                "ok": result.ok,
                "count": len(result.items),
                "ms": result.elapsed_ms,
                "error": result.error,
                "sample": sample,
            })

    # 按配置的原始顺序输出，方便对照
    order = {s.id: i for i, s in enumerate(sources)}
    results.sort(key=lambda r: order.get(r["source"].id, 999))
    return results


def main() -> int:
    setup_console_encoding()
    parser = argparse.ArgumentParser(description="探测数据源是否可用")
    parser.add_argument("--all", action="store_true", help="连配置里已禁用的源也一起测")
    parser.add_argument("--only", default="", help="只测指定 id 的源，多个用逗号隔开，例如：linuxdo_latest,locdd_latest")
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print("配置有问题，先修好再来：\n")
        print(exc)
        return 1

    sources = list(config.sources) if args.all else [s for s in config.sources if s.enabled]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        sources = [s for s in sources if s.id in wanted]
        if not sources:
            print(f"没有找到 id 为 {args.only} 的源，请检查拼写。")
            return 1

    if config.settings.get("强制IPv4优先", True):
        install_ipv4_preference()

    workers = max(1, int(config.settings.get("并发线程", 8)))
    print(f"开始探测 {len(sources)} 个源，请稍等……\n")

    results = probe(sources, config.settings, workers)

    ok_count = sum(1 for r in results if r["ok"])
    print("=" * 78)
    print(f"{'状态':<6}{'条数':<6}{'耗时':<8}{'编号':<18}{'名称'}")
    print("=" * 78)
    for r in results:
        source = r["source"]
        status = _fmt_status(r)
        print(f"{status:<6}{r['count']:<6}{str(r['ms']) + 'ms':<8}{source.id:<18}{source.name}")
        if r["error"]:
            print(f"       └─ 原因：{r['error']}")
        if r["sample"]:
            sample = r["sample"]
            heat = f" [热度 {sample['heat']}]" if sample["heat"] else ""
            print(f"       └─ 样例：{sample['title']}{heat}")

    print("=" * 78)
    print(f"探测完成：成功 {ok_count} 个，失败 {len(results) - ok_count} 个。")

    failed = [r for r in results if not r["ok"]]
    if failed:
        print("\n失败的源可以先放着不管，程序会自动跳过它们，不影响其他内容。")
        print("如果你想修，通常是这两个原因：网址失效了，或者那个网站暂时拒绝访问。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
