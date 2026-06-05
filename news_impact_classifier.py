from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import config
from optimized_news_filter import clean_news_text


SYSTEM_PROMPT = "你是宏观新闻影响分类器。只判断输入新闻对 BTC 和黄金的短线影响方向，不预测价格，不编造信息。输出必须是严格 JSON。"

IMPACT_LABELS = {
    "bullish": "利多",
    "bearish": "利空",
    "neutral": "中性",
    "利多": "利多",
    "利空": "利空",
    "中性": "中性",
}


@dataclass(frozen=True)
class NewsImpactInput:
    title: str
    content: str
    source: str
    time: str


def extract_news_impact_input(msg: dict[str, Any], receive_time: str) -> NewsImpactInput:
    data = msg.get("data")
    data = data if isinstance(data, dict) else {}

    title = _first_text(msg.get("title"), data.get("title"), data.get("vip_title"), msg.get("vip_title"))
    content = truncate_text(
        _first_text(msg.get("content"), data.get("content"), data.get("vip_desc"), msg.get("vip_desc")),
        config.NEWS_IMPACT_CLASSIFIER_MAX_CONTENT_CHARS,
    )
    source = _first_text(msg.get("source"), data.get("source"))
    news_time = _first_text(msg.get("time"), data.get("time"), receive_time)

    return NewsImpactInput(
        title=clean_news_text(title),
        content=clean_news_text(content),
        source=clean_news_text(source),
        time=clean_news_text(news_time),
    )


def classify_news_impact(news: NewsImpactInput) -> dict[str, Any]:
    if config.NEWS_IMPACT_CLASSIFIER_PROVIDER != "deepseek":
        raise ValueError(f"unsupported provider: {config.NEWS_IMPACT_CLASSIFIER_PROVIDER}")
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY is empty")

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(news)},
        ],
        "temperature": 0,
        "max_tokens": config.DEEPSEEK_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{config.DEEPSEEK_BASE_URL}/chat/completions"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=deepseek_timeout()) as response:
                raw_body = response.read(20000).decode("utf-8", errors="replace")
            response_payload = json.loads(raw_body)
            content = str(response_payload["choices"][0]["message"]["content"])
            try:
                return normalize_impact_payload(parse_json_tolerant(content))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{exc}; content={truncate_text(content, 300)}") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_exc = exc
            if attempt == 0:
                continue
            break

    raise RuntimeError(str(last_exc) if last_exc else "DeepSeek request failed")


def build_user_prompt(news: NewsImpactInput) -> str:
    return "\n".join(
        [
            "判断新闻对BTC和黄金的短线影响，只输出JSON。",
            f"标题：{news.title}",
            f"正文：{news.content}",
            f"来源：{news.source}",
            f"时间：{news.time}",
            '格式：{"btc":{"impact":"bullish|bearish|neutral","reason":"不超过20字"},'
            '"gold":{"impact":"bullish|bearish|neutral","reason":"不超过20字"}}',
        ]
    )


def deepseek_timeout() -> float | None:
    return None if config.DEEPSEEK_TIMEOUT_SECONDS <= 0 else config.DEEPSEEK_TIMEOUT_SECONDS


def format_impact_for_push(impact: dict[str, Any]) -> str:
    btc = impact["btc"]
    gold = impact["gold"]
    return "\n".join(
        [
            f"BTC：{btc['impact_label']}",
            f"黄金：{gold['impact_label']}",
            f"原因：BTC {btc['reason']}；黄金 {gold['reason']}",
        ]
    )


def normalize_impact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "btc": _normalize_asset(payload.get("btc")),
        "gold": _normalize_asset(payload.get("gold") or payload.get("黄金") or payload.get("xauusd")),
    }


def parse_json_tolerant(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))

    if not isinstance(payload, dict):
        raise ValueError("impact payload is not an object")
    return payload


def _normalize_asset(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("asset impact is not an object")

    impact_raw = str(value.get("impact") or value.get("direction") or "").strip().lower()
    reason = clean_news_text(str(value.get("reason") or "")).strip()
    label = IMPACT_LABELS.get(impact_raw)
    if not label:
        raise ValueError(f"invalid impact: {impact_raw}")
    if len(reason) > 20:
        reason = reason[:20]
    return {"impact": impact_raw, "impact_label": label, "reason": reason or "无明显影响"}


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def truncate_text(text: str, max_chars: int) -> str:
    cleaned = clean_news_text(text)
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3] + "..."
