# -*- coding: utf-8 -*-
"""
配置加载与校验：把「配置」目录里的中文 JSON 读成程序能用的对象。

Author: wr

设计原则：配置文件写错了，要给新手看得懂的中文提示，
明确指出是哪个文件、哪一行、错在哪、该怎么改。
绝不能甩一个英文报错让人干瞪眼。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "配置")

SOURCES_FILE = os.path.join(CONFIG_DIR, "数据源清单.json")
KEYWORDS_FILE = os.path.join(CONFIG_DIR, "关注关键词.json")

# 允许的源类型
VALID_TYPES = ("rss", "atom", "html_diff")
# 允许的分组
VALID_CATEGORIES = ("行业新闻", "论坛热议", "厂商动态", "更新日志", "优惠活动", "开源项目")

# 设置项写了就用你的，没写就用这里的默认值
DEFAULT_SETTINGS = {
    "时区": "Asia/Shanghai",
    "抓取超时秒": 20,
    "重试次数": 2,
    "并发线程": 8,
    "强制IPv4优先": True,
    "单条摘要保留字数": 200,
    "每个源最多条数": 50,
    "AI处理条数上限": 120,
    "AI每批条数": 10,
    "归档保留天数": 30,
    "同域名请求间隔秒": 1.5,
}

_JSON_HINT = (
    "小提示：JSON 文件里不能写注释；文字必须用双引号包起来；"
    "数组或对象的最后一项后面，不能多一个逗号。"
)


class ConfigError(Exception):
    """配置有问题时抛出，消息是完整的中文说明"""


@dataclass
class Source:
    """一个信息源"""
    id: str
    name: str
    type: str                 # rss / atom / html_diff
    url: str
    category: str
    vendor: str | None
    enabled: bool
    selectors: list[str] = field(default_factory=list)
    note: str = ""

    def label(self) -> str:
        return self.vendor or self.name


@dataclass
class Keywords:
    """关注词配置"""
    focus: list[dict] = field(default_factory=list)        # [{"词": "开源", "权重": 4}, ...]
    promo: list[str] = field(default_factory=list)         # 命中即认定为优惠活动
    vendors: dict[str, list[str]] = field(default_factory=dict)  # 厂商 -> 别名列表


@dataclass
class Config:
    settings: dict
    sources: list[Source]
    keywords: Keywords


def _load_json_file(path: str, what: str) -> dict:
    """读取一个 JSON 文件，出错时给出中文提示"""
    if not os.path.exists(path):
        raise ConfigError(
            f"找不到{what}：\n  {path}\n"
            f"请确认这个文件还在，或者文件名没有被改动。"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"{what}写得有问题，程序读不懂：\n"
            f"  文件：{path}\n"
            f"  位置：第 {e.lineno} 行，第 {e.colno} 列附近\n"
            f"  原因：{e.msg}\n"
            f"{_JSON_HINT}"
        ) from e
    except UnicodeDecodeError as e:
        raise ConfigError(
            f"{what}的编码不对，程序读不了：\n"
            f"  文件：{path}\n"
            f"  请用记事本打开它，选择「另存为」，编码选 UTF-8 再保存一次。\n"
            f"  原始错误：{e}"
        ) from e

    if not isinstance(data, dict):
        raise ConfigError(
            f"{what}的内容应该是一个对象（用花括号 {{}} 包起来的整体），"
            f"但现在不是：\n  {path}"
        )
    return data


def _validate_sources(raw: dict, path: str) -> list[Source]:
    """逐个检查源的配置，把发现的所有问题一次性列出来"""
    raw_list = raw.get("源列表")
    if not isinstance(raw_list, list):
        raise ConfigError(
            f"数据源清单里必须有一个「源列表」，而且它得是一个数组（用方括号 [] 包起来）：\n  {path}"
        )

    errors: list[str] = []
    sources: list[Source] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(raw_list, start=1):
        prefix = f"第 {index} 个源"

        if not isinstance(item, dict):
            errors.append(f"{prefix}：格式不对，应该是一个用花括号包起来的对象。")
            continue

        sid = str(item.get("id", "")).strip()
        name = str(item.get("名称", "")).strip()
        stype = str(item.get("类型", "")).strip()
        url = str(item.get("网址", "")).strip()

        if not sid:
            errors.append(f"{prefix}：缺少 id（英文代号），请补上，例如 \"id\": \"my_source\"。")
        elif sid in seen_ids:
            errors.append(f"{prefix}：id \"{sid}\" 和前面的源重名了，请改成不一样的。")
        else:
            seen_ids.add(sid)

        if not name:
            errors.append(f"{prefix}（id={sid or '未填写'}）：缺少「名称」。")

        if stype not in VALID_TYPES:
            errors.append(
                f"{prefix}（{name or sid}）：类型 \"{stype or '未填写'}\" 不认识，"
                f"只能填这几种之一：{' / '.join(VALID_TYPES)}。"
            )

        if not url:
            errors.append(f"{prefix}（{name or sid}）：缺少「网址」。")
        elif not url.lower().startswith(("http://", "https://")):
            errors.append(f"{prefix}（{name or sid}）：网址必须以 http:// 或 https:// 开头，现在是 \"{url}\"。")

        category = str(item.get("分类", "")).strip() or "行业新闻"
        if category not in VALID_CATEGORIES:
            errors.append(
                f"{prefix}（{name or sid}）：分类 \"{category}\" 不认识，"
                f"只能填这几种之一：{' / '.join(VALID_CATEGORIES)}。"
            )

        selectors = item.get("选择器", [])
        if selectors is None:
            selectors = []
        if not isinstance(selectors, list):
            errors.append(f"{prefix}（{name or sid}）：「选择器」必须是一个数组，"
                          f"例如 [\"div.item\", \"li\"]；不需要就写 []。")
            selectors = []
        else:
            selectors = [str(s) for s in selectors if str(s).strip()]
            # 只对「启用」的源强制要求选择器；禁用的源可以暂时空着，留档备用
            enabled = bool(item.get("启用", True))
            if stype == "html_diff" and enabled and not selectors:
                errors.append(
                    f"{prefix}（{name or sid}）：类型是 html_diff，必须至少填一个「选择器」，"
                    f"否则程序不知道去页面上取哪一块内容。"
                )

        vendor = item.get("厂商")
        vendor = str(vendor).strip() if vendor else None

        if not errors or sid:
            sources.append(Source(
                id=sid or f"__bad_{index}",
                name=name or sid or f"未命名源{index}",
                type=stype,
                url=url,
                category=category,
                vendor=vendor,
                enabled=bool(item.get("启用", True)),
                selectors=selectors,
                note=str(item.get("备注", "") or ""),
            ))

    if errors:
        raise ConfigError(
            f"数据源清单里有 {len(errors)} 处问题：\n"
            + "\n".join(f"  {i}. {msg}" for i, msg in enumerate(errors, start=1))
            + f"\n文件位置：{path}"
        )

    return sources


def _validate_keywords(raw: dict, path: str) -> Keywords:
    """读取关注词配置。这一块尽量宽松，缺了就当没有，不轻易报错。"""
    focus_raw = raw.get("关注词", []) or []
    focus: list[dict] = []
    if isinstance(focus_raw, list):
        for item in focus_raw:
            if isinstance(item, dict) and item.get("词"):
                try:
                    weight = int(item.get("权重", 3))
                except (TypeError, ValueError):
                    weight = 3
                focus.append({"词": str(item["词"]), "权重": max(1, min(5, weight))})

    promo_raw = raw.get("优惠词", []) or []
    promo = [str(w) for w in promo_raw if str(w).strip()] if isinstance(promo_raw, list) else []

    vendors_raw = raw.get("厂商别名", {}) or {}
    vendors: dict[str, list[str]] = {}
    if isinstance(vendors_raw, dict):
        for vendor, aliases in vendors_raw.items():
            if isinstance(aliases, list):
                vendors[str(vendor)] = [str(a).lower() for a in aliases if str(a).strip()]
            else:
                vendors[str(vendor)] = [str(aliases).lower()]

    return Keywords(focus=focus, promo=promo, vendors=vendors)


def load_config() -> Config:
    """读取全部配置。任何问题都会以中文 ConfigError 抛出来。"""
    sources_raw = _load_json_file(SOURCES_FILE, "数据源清单")
    keywords_raw = _load_json_file(KEYWORDS_FILE, "关注关键词")

    settings = dict(DEFAULT_SETTINGS)
    user_settings = sources_raw.get("设置", {}) or {}
    if isinstance(user_settings, dict):
        settings.update(user_settings)

    return Config(
        settings=settings,
        sources=_validate_sources(sources_raw, SOURCES_FILE),
        keywords=_validate_keywords(keywords_raw, KEYWORDS_FILE),
    )


def enabled_sources(config: Config) -> list[Source]:
    """只要启用的源"""
    return [s for s in config.sources if s.enabled]


if __name__ == "__main__":
    # 直接运行这个文件，就能检查配置写得对不对：
    #   python src\config_loader.py
    from .utils import setup_console_encoding

    setup_console_encoding()

    try:
        cfg = load_config()
    except ConfigError as err:
        print("配置有问题：\n")
        print(err)
        raise SystemExit(1)

    print("配置检查通过！")
    print(f"  启用的源：{len(enabled_sources(cfg))} 个（共 {len(cfg.sources)} 个）")
    print(f"  关注词：{len(cfg.keywords.focus)} 个")
    print(f"  优惠词：{len(cfg.keywords.promo)} 个")
    print(f"  厂商：{len(cfg.keywords.vendors)} 家")
    print("\n源清单：")
    for s in cfg.sources:
        flag = "√" if s.enabled else "×"
        print(f"  [{flag}] {s.id:<18} {s.type:<10} {s.name}")
