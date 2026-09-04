# -*- coding: utf-8 -*-
"""
AI 摘要与重要度打分（DeepSeek），失败时自动降级为规则打分

Author: wr

设计原则：**程序永远不能因为 AI 出问题就跑不下去**。
没有 Key、Key 失效、网络不通、模型返回了奇怪的东西……
任何一种情况都只是让那几条内容改用规则打分，其他内容照常处理。
页面上会显示「规则模式」的小徽章，让你知道这次没用上 AI。

怎么用：
  本地：在项目根目录建一个 .env 文件，写一行  DEEPSEEK_API_KEY=sk-xxxxxx
  云端：在 GitHub 仓库的 Settings → Secrets 里添加 DEEPSEEK_API_KEY
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime

from .config_loader import Keywords
from .normalize import focus_weight
from .utils import now_cn, strip_html

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
REQUEST_TIMEOUT = 90  # 秒

# ------------------------------------------------------------------ 提示词

PROMPT_TEMPLATE = """你是 AI 资讯编辑。下面是一批今天抓到的资讯，请逐条处理。

输入每行格式为：编号 | 标题 | 原文摘要

请严格按以下要求输出：
1. 只输出一个 JSON 数组，不要任何解释文字，不要用 ``` 代码块包裹。
2. 数组长度必须等于输入条数，顺序与输入一致。
3. 每条格式：{{"i": <输入编号>, "summary": <字符串>, "score": <1到5的整数>, "promo": <true或false>, "vendor": <字符串或null>}}
4. summary 规则：用不超过 40 个字，补充标题里没有的新信息。如果原文确实没有更多信息，就返回空字符串 ""。绝对禁止把标题换个说法复述一遍。
5. score 规则：5=重大发布或行业震动，4=值得一看，3=一般，2=边角料，1=没有价值。
6. promo 规则：只有明确属于「免费、限免、折扣、赠送额度、降价」这类优惠活动才填 true。
7. vendor 规则：涉及的大模型厂商或工具名（如 DeepSeek、智谱、Kimi、Cursor），看不出来就填 null。
8. 严禁编造输入内容里不存在的信息。宁可返回空字符串，也不要编。
9. 如果这批内容整体都没有价值，可以全部给 score=1、summary=""，但数组长度仍然要保持一致。

输入内容：
{block}
"""


# ------------------------------------------------------------------ 密钥

def get_api_key() -> str:
    """
    取出 DeepSeek 的 Key。

    先找环境变量（GitHub Actions 用的是这种方式），
    找不到再读项目根目录的 .env 文件（本地用这种方式）。
    """
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key

    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("DEEPSEEK_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass

    return ""


# ------------------------------------------------------------------ 规则打分

def rule_score(item: dict, keywords: Keywords) -> int:
    """
    不花钱的打分办法：根据热度、关注词、是否优惠、时效来估算重要度。

    打分范围 1-5，和 AI 打分的口径尽量保持一致。
    """
    score = 3

    heat = item.get("heat") or {}
    replies = int(heat.get("replies", 0) or 0)
    participants = int(heat.get("participants", 0) or 0)

    # 热度加分：门槛定高一点，否则热帖全都顶到 5 星，反而分不出轻重
    heat_bonus = 0
    if replies >= 200 or participants >= 60:
        heat_bonus = 2
    elif replies >= 50 or participants >= 25:
        heat_bonus = 1
    score += heat_bonus

    # 命中你设置的关注词才加分
    weight = focus_weight(f"{item.get('title','')} {item.get('summary_raw','')}", keywords)
    if weight >= 15:
        score += 1

    # 优惠活动单独加一档，保证它们能冒头
    if item.get("is_promo"):
        score += 1

    return max(1, min(5, score))


def apply_rule_mode(items: list[dict], keywords: Keywords) -> None:
    """给所有尚未经过 AI 处理的条目打上规则分"""
    for item in items:
        if item.get("ai"):
            continue
        item["score"] = rule_score(item, keywords)
        item["summary_ai"] = strip_html(item.get("summary_raw") or "", 60)


# ------------------------------------------------------------------ 调用 AI

def _extract_json_array(text: str) -> list | None:
    """从模型的回复里抠出 JSON 数组。模型有时会多说几句话，这里要能容错。"""
    if not text:
        return None

    cleaned = text.strip()
    # 去掉可能的 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    if not cleaned:
        return None

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        pass

    # 退一步：截取第一个 [ 到最后一个 ] 之间的内容再试
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None
    return None


def _call_api(prompt: str, api_key: str) -> list | None:
    """真的去请求 DeepSeek，返回解析后的 JSON 数组；任何问题都返回 None"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一个严谨的 AI 资讯编辑，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "stream": False,
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"接口返回错误 {exc.code}：{detail or exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"请求失败：{exc}") from exc

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"返回内容格式异常：{exc}") from exc

    result = _extract_json_array(content)
    if result is None:
        raise RuntimeError("模型返回的不是有效的 JSON 数组")
    return result


def _build_block(batch: list[tuple[int, dict]]) -> str:
    """把一批条目拼成提示词里的输入块"""
    lines = []
    for index, item in batch:
        title = (item.get("title") or "").replace("\n", " ").strip()
        summary = (item.get("summary_raw") or "").replace("\n", " ").strip()
        if len(summary) > 160:
            summary = summary[:160] + "…"
        lines.append(f"{index} | {title} | {summary}")
    return "\n".join(lines)


def _apply_ai_result(item: dict, record: dict) -> None:
    """把模型给的一条结果写回条目"""
    summary = record.get("summary")
    if isinstance(summary, str):
        summary = summary.strip()
        # 模型不听话、把标题复述一遍时，宁可不用
        if summary and summary != (item.get("title") or "").strip():
            item["summary_ai"] = summary[:80]

    score = record.get("score")
    if isinstance(score, (int, float)):
        item["score"] = max(1, min(5, int(score)))

    promo = record.get("promo")
    if isinstance(promo, bool) and promo:
        item["is_promo"] = True

    vendor = record.get("vendor")
    if isinstance(vendor, str) and vendor.strip() and vendor.strip().lower() != "null":
        item["vendor"] = vendor.strip()

    item["ai"] = True


# ------------------------------------------------------------------ 对外入口

def enrich(
    items: list[dict],
    settings: dict,
    keywords: Keywords,
    verbose: bool = False,
) -> tuple[list[dict], bool, str]:
    """
    给条目做摘要和打分。

    返回 (条目列表, 是否用上了 AI, 说明文字)。
    无论出什么问题都不抛异常，最差也就是退回规则模式。
    """
    api_key = get_api_key()
    if not api_key:
        apply_rule_mode(items, keywords)
        return items, False, "没有配置 DEEPSEEK_API_KEY，已自动使用规则模式"

    limit = int(settings.get("AI处理条数上限", 120))
    batch_size = max(1, int(settings.get("AI每批条数", 10)))

    # 只对「预计最重要」的一批调用 AI，省时间也省钱
    candidates = items[:limit]
    batches = [
        candidates[i:i + batch_size]
        for i in range(0, len(candidates), batch_size)
    ]

    success_batches = 0
    failed_batches = 0
    notes: list[str] = []

    for batch_no, batch in enumerate(batches, start=1):
        indexed = [(i, it) for i, it in enumerate(batch)]
        prompt = PROMPT_TEMPLATE.format(block=_build_block(indexed))

        try:
            records = _call_api(prompt, api_key)
        except Exception as exc:  # noqa: BLE001 - 单批失败绝不能影响全局
            failed_batches += 1
            notes.append(f"第 {batch_no} 批失败：{exc}")
            if verbose:
                print(f"  [AI] 第 {batch_no} 批失败，改用规则：{exc}")
            continue

        if not records:
            failed_batches += 1
            notes.append(f"第 {batch_no} 批返回为空")
            continue

        # 用编号做映射，防止模型少返回或多返回造成错位
        by_index: dict[int, dict] = {}
        for record in records:
            if isinstance(record, dict):
                try:
                    by_index[int(record.get("i", -1))] = record
                except (TypeError, ValueError):
                    continue

        for index, item in indexed:
            record = by_index.get(index)
            if record is None:
                continue
            _apply_ai_result(item, record)

        success_batches += 1

    # AI 没顾上的（超出上限的、失败的批次）一律补规则分
    apply_rule_mode(items, keywords)

    used_ai = success_batches > 0
    if used_ai:
        note = f"AI 处理了 {success_batches} 批"
        if failed_batches:
            note += f"，{failed_batches} 批失败已降级"
    else:
        note = "AI 全部批次失败，已整体降级为规则模式"
        if notes:
            note += f"（{notes[0]}）"

    return items, used_ai, note
