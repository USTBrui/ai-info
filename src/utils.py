# -*- coding: utf-8 -*-
"""
通用小工具：时间、文本清洗、网址归一化、相似度、JS 数据文件生成

Author: wr

这里放的是各个模块都要用到的公共函数。
特别注意 now_cn()：全项目要取「现在时间」时必须用它，
不允许在别处直接写 datetime.now()，否则本机时间和服务器时间会打架。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 控制台输出


def setup_console_encoding() -> None:
    """
    让程序在 Windows 命令行里说中文不乱码、也不报错。

    这里不能简单粗暴地一律改成 UTF-8：
      - 如果窗口已经切成 UTF-8（代码页 65001），用 UTF-8 输出才对；
      - 如果是默认的简体中文窗口（代码页 936，也就是 GBK），
        强行输出 UTF-8 反而会变成一堆乱码。
    所以先看窗口当前用的是什么代码页，再决定用哪种编码说话。
    """
    import locale
    import os
    import sys

    if os.name != "nt":
        return

    code_page = 0
    try:
        import ctypes

        code_page = ctypes.windll.kernel32.GetConsoleOutputCP()
    except Exception:  # noqa: BLE001 - 取不到就按非 UTF-8 处理
        code_page = 0

    target = "utf-8" if code_page == 65001 else (locale.getpreferredencoding(False) or "gbk")

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding=target, errors="replace")
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 时间处理

# 中国不使用夏令时，全年固定 +08:00。
# 用固定偏移而不是 zoneinfo / pytz，是因为 Windows 上可能没有 tzdata 数据库，
# 用固定偏移能保证在任何机器上都跑得起来，且结果一致。
CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cn() -> datetime:
    """当前的北京时间（全项目唯一的取时间入口）"""
    return datetime.now(CN_TZ)


def today_cn() -> str:
    """今天的北京日期，格式 2026-09-04"""
    return now_cn().strftime("%Y-%m-%d")


def to_cn(dt: datetime | None) -> datetime | None:
    """把任意时间（通常带时区）换算成北京时间；没时区就按北京时间看待"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CN_TZ)
    return dt.astimezone(CN_TZ)


def parse_datetime(value) -> datetime | None:
    """
    把各种稀奇古怪的时间写法都尽量解析成北京时间。

    RSS / Atom 世界里时间格式特别乱：RFC822、ISO8601、带 Z 的、不带的……
    这里挨个试，实在认不出来就返回 None（调用方会当成「时间未知」处理，不会报错）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_cn(value)

    text = str(value).strip()
    if not text:
        return None

    # ISO8601：2026-09-04T08:45:10+08:00 或 2026-09-04T08:45:10Z
    try:
        return to_cn(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass

    # RFC822：Fri, 04 Sep 2026 08:45:10 +0000（RSS 里最常见的一种）
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return to_cn(parsed)
    except Exception:  # noqa: BLE001 - 解析库可能抛各种异常，一律忽略并继续尝试
        pass

    # 最后兜底：几种中国人爱写的格式
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return to_cn(datetime.strptime(text, fmt))
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------- 文本处理

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(raw: str | None, limit: int | None = None) -> str:
    """去掉 HTML 标签，得到一段干净的纯文本（可选截断字数）"""
    if not raw:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


# ---------------------------------------------------------------- 网址处理

# 这些参数通常是推广统计用的，去掉它们才能让同一个链接在不同来源下被认成同一条
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "ref", "referrer", "share_source", "share_medium",
    "share_token", "invite_code", "gclid", "fbclid",
}


def normalize_url(url: str | None) -> str:
    """
    把网址整理成统一形态，用于去重和生成 ID。
    做法：协议与域名转小写、去掉开头的 www.、去掉末尾斜杠、丢掉推广参数、去掉 # 锚点。
    """
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return (url or "").strip()

    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")

    query_pairs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urllib.parse.urlencode(query_pairs)

    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


# ---------------------------------------------------------------- 相似度

_CJK_SEG_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str | None) -> list[str]:
    """
    把标题切成一组「特征碎片」，用来比较两条标题像不像。

    中文用「二元字组」（两两相邻的字），英文和数字按单词切。
    例如「智谱发布新模型」→ ['智谱','谱发','发布','布新','新模','模型']
    这样做不需要引入 jieba 之类的分词库，零依赖，对短标题效果很好。
    """
    if not text:
        return []
    low = text.lower()
    tokens: list[str] = list(_WORD_RE.findall(low))
    for seg in _CJK_SEG_RE.findall(low):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


def jaccard(a: list[str], b: list[str]) -> float:
    """两组特征碎片的相似度，0~1。越大越像。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------- 指纹

def short_hash(*parts: str, length: int = 12) -> str:
    """给一组内容生成一个短指纹，用于条目 ID 和快照比对"""
    joined = "||".join(p if p is not None else "" for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


def make_item_id(title: str, url: str) -> str:
    """
    条目的唯一 ID。

    重要：只吃「标题 + 归一化网址」，不吃正文。
    正文里常有相对时间、阅读量这类每次都在变的东西，
    一旦算进指纹，同一条新闻每天都会被认为是新内容。
    """
    return short_hash(title.strip(), normalize_url(url))


# ---------------------------------------------------------------- 生成 JS 数据文件

def _js_safe(text: str) -> str:
    """
    让 JSON 文本能安全地塞进 <script> 标签里。
    正文里万一出现 </script> 会把网页截断，必须转义。
    """
    return (text
            .replace("</", "<\\/")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def build_js_data(var_name: str, key: str, payload: dict) -> str:
    """
    生成一行可直接在浏览器里加载的数据文件。

    为什么要写成 window.__AI_INFO_DATA__['2026-09-04'] = {...} 而不是
    window.__AI_INFO__ = {...} ？
    因为看板在切换历史日期时，会往页面里插入多个数据文件，
    如果都用同一个变量名，后加载的会把先加载的覆盖掉，当前内容就丢了。
    按日期当键挂上去，多个文件就能和平共处。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    key_literal = json.dumps(key, ensure_ascii=False)
    return (
        f"window.{var_name} = window.{var_name} || {{}};\n"
        f"window.{var_name}[{key_literal}] = {_js_safe(body)};\n"
    )
