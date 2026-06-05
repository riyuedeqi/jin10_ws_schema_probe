from __future__ import annotations

import json
import signal
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import config
from optimized_news_filter import clean_news_text
from qq_pusher import post_onebot, summarize_body


SYSTEM_PROMPT = (
    "你是QQ群里的中文AI助手。回答要简洁、准确、友好。"
    "如果问题涉及金融市场，只做信息分析，不给确定性投资建议。"
    "如果用户问题附带了实时行情数据，必须优先基于这些数据回答，并说明数据来源和时间；"
    "如果没有实时数据，不要假装看到了实时价格或K线。"
)

MARKET_SYMBOL_ALIASES = {
    "BTC": ("BTC", "比特币", "bitcoin"),
    "ETH": ("ETH", "以太坊", "ethereum"),
}
MARKET_KEYWORDS = (
    "价格",
    "现价",
    "行情",
    "k线",
    "K线",
    "走势",
    "涨跌",
    "支撑",
    "压力",
    "突破",
    "回调",
    "做多",
    "做空",
    "多空",
)
MARKET_SWAP_KEYWORDS = ("合约", "永续", "swap", "perp", "做多", "做空", "多空", "开多", "开空", "杠杆")

server: ThreadingHTTPServer | None = None


@dataclass(frozen=True)
class ChatRequest:
    group_id: str
    user_id: str
    message_id: str
    question: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        file.flush()


def write_chat_log(record: dict[str, Any]) -> None:
    try:
        append_jsonl(config.AI_CHAT_LOG_PATH, {"time": now_iso(), **record})
    except Exception as exc:
        print(f"[AI_CHAT] log_write_failed error={exc}", flush=True)


def onebot_base_url() -> str:
    return config.QQ_BOT_API_URL.rsplit("/", 1)[0]


def get_bot_user_id() -> str:
    status, body = post_onebot(f"{onebot_base_url()}/get_login_info", {})
    if not (200 <= status < 300):
        raise RuntimeError(f"get_login_info http_status={status}")
    payload = json.loads(body)
    user_id = payload.get("data", {}).get("user_id") if isinstance(payload, dict) else None
    if user_id is None:
        raise RuntimeError(f"get_login_info missing user_id: {summarize_body(body)}")
    return str(user_id)


def parse_chat_request(event: dict[str, Any], bot_user_id: str) -> ChatRequest | None:
    if not config.AI_CHAT_BOT_ENABLED:
        return None
    if str(event.get("post_type") or "") != "message":
        return None
    if str(event.get("message_type") or "") != "group":
        return None
    group_id = str(event.get("group_id") or "")
    if config.QQ_GROUP_ID and group_id != str(config.QQ_GROUP_ID):
        return None
    user_id = str(event.get("user_id") or "")
    if user_id == bot_user_id:
        return None

    message = event.get("message")
    question = extract_question(message, bot_user_id)
    if not question:
        return None
    if len(question) > config.AI_CHAT_MAX_QUESTION_CHARS:
        question = question[: config.AI_CHAT_MAX_QUESTION_CHARS]

    return ChatRequest(
        group_id=group_id,
        user_id=user_id,
        message_id=str(event.get("message_id") or ""),
        question=question,
    )


def extract_question(message: Any, bot_user_id: str) -> str:
    mentioned = False
    parts: list[str] = []
    if isinstance(message, list):
        for item in message:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if item_type == "at" and str(data.get("qq") or "") == bot_user_id:
                mentioned = True
                continue
            if item_type == "text":
                parts.append(str(data.get("text") or ""))
    elif isinstance(message, str):
        marker = f"[CQ:at,qq={bot_user_id}]"
        if marker in message:
            mentioned = True
            parts.append(message.replace(marker, " "))

    if not mentioned:
        return ""
    return clean_news_text(" ".join(parts)).strip()


def detect_market_symbols(question: str) -> list[str]:
    lowered = question.lower()
    symbols: list[str] = []
    for symbol, aliases in MARKET_SYMBOL_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases):
            symbols.append(symbol)
    return symbols


def should_fetch_market_context(question: str) -> bool:
    if not detect_market_symbols(question):
        return False
    return any(keyword in question for keyword in MARKET_KEYWORDS)


def http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "jin10-ai-chat-bot/1.0",
        },
        method="GET",
    )
    opener = (
        urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": config.MARKET_PROXY_URL, "https": config.MARKET_PROXY_URL})
        )
        if config.MARKET_PROXY_URL
        else urllib.request
    )
    with opener.open(request, timeout=config.MARKET_TIMEOUT_SECONDS) as response:
        body = response.read(120000).decode("utf-8", errors="replace")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("market api response is not an object")
    return payload


def okx_get(path: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    return http_get_json(f"{config.MARKET_API_BASE_URL}{path}?{query}")


def fmt_float(value: Any, digits: int = 4) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    text = f"{number:.{digits}f}"
    return text.rstrip("0").rstrip(".")


def fmt_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def calc_change_percent(last: Any, open_price: Any) -> str:
    try:
        open_number = float(open_price)
        if open_number == 0:
            return "-"
        return fmt_percent(float(last) / open_number - 1)
    except (TypeError, ValueError):
        return "-"


def okx_ts_to_iso(ts_ms: Any) -> str:
    try:
        timestamp = int(str(ts_ms)) / 1000
    except (TypeError, ValueError):
        return "-"
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat(timespec="minutes")


def summarize_okx_candles(candles: list[Any], limit: int = 6) -> str:
    rows: list[str] = []
    for row in reversed(candles[:limit]):
        if not isinstance(row, list) or len(row) < 6:
            continue
        rows.append(
            " ".join(
                [
                    okx_ts_to_iso(row[0]),
                    f"O={fmt_float(row[1])}",
                    f"H={fmt_float(row[2])}",
                    f"L={fmt_float(row[3])}",
                    f"C={fmt_float(row[4])}",
                    f"Vol={fmt_float(row[5], 2)}",
                ]
            )
        )
    return "\n".join(rows) or "-"


def detect_market_inst_id(symbol: str, question: str) -> str:
    lowered = question.lower()
    if any(keyword.lower() in lowered for keyword in MARKET_SWAP_KEYWORDS):
        return f"{symbol}-USDT-SWAP"
    return f"{symbol}-USDT"


def fetch_symbol_market_context(symbol: str, question: str) -> str:
    inst_id = detect_market_inst_id(symbol, question)
    ticker_payload = okx_get("/api/v5/market/ticker", {"instId": inst_id})
    ticker_data = ticker_payload.get("data")
    if not isinstance(ticker_data, list) or not ticker_data:
        raise ValueError(f"OKX ticker missing data for {inst_id}")
    ticker = ticker_data[0]
    if not isinstance(ticker, dict):
        raise ValueError(f"OKX ticker row is invalid for {inst_id}")

    candle_1h_payload = okx_get("/api/v5/market/candles", {"instId": inst_id, "bar": "1H", "limit": "6"})
    candle_15m_payload = okx_get("/api/v5/market/candles", {"instId": inst_id, "bar": "15m", "limit": "6"})
    candles_1h = candle_1h_payload.get("data") if isinstance(candle_1h_payload.get("data"), list) else []
    candles_15m = candle_15m_payload.get("data") if isinstance(candle_15m_payload.get("data"), list) else []

    return "\n".join(
        [
            f"{inst_id} OKX ticker",
            f"time={okx_ts_to_iso(ticker.get('ts'))}",
            f"last={fmt_float(ticker.get('last'))} bid={fmt_float(ticker.get('bidPx'))} ask={fmt_float(ticker.get('askPx'))}",
            f"24h_high={fmt_float(ticker.get('high24h'))} 24h_low={fmt_float(ticker.get('low24h'))}",
            f"24h_open={fmt_float(ticker.get('open24h'))} 24h_change={calc_change_percent(ticker.get('last'), ticker.get('open24h'))}",
            f"24h_volume_base={fmt_float(ticker.get('vol24h'), 2)}",
            "recent_1h_candles:",
            summarize_okx_candles(candles_1h),
            "recent_15m_candles:",
            summarize_okx_candles(candles_15m),
        ]
    )


def build_market_context(question: str) -> str:
    if not should_fetch_market_context(question):
        return ""
    sections: list[str] = []
    errors: list[str] = []
    for symbol in detect_market_symbols(question):
        try:
            sections.append(fetch_symbol_market_context(symbol, question))
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    if not sections and errors:
        return "实时行情数据获取失败，回答时必须说明没有拿到实时价格/K线，不要编造。\n" + "\n".join(errors)
    if errors:
        sections.append("partial_fetch_errors:\n" + "\n".join(errors))
    return "实时行情数据来源：OKX public market API。\n" + "\n\n".join(sections)


def build_user_content(question: str, market_context: str) -> str:
    if not market_context:
        return question
    return "\n\n".join(
        [
            "下面是程序刚刚获取的实时行情数据，请优先基于这些数据回答。不要编造未提供的数据。",
            market_context,
            f"用户问题：{question}",
        ]
    )


def classify_question(question: str) -> str:
    if not config.DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY is empty")
    market_context = build_market_context(question)
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(question, market_context)},
        ],
        "temperature": 0.3,
        "max_tokens": max(256, config.DEEPSEEK_MAX_TOKENS * 4),
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{config.DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = None if config.DEEPSEEK_TIMEOUT_SECONDS <= 0 else config.DEEPSEEK_TIMEOUT_SECONDS
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw_body = response.read(40000).decode("utf-8", errors="replace")
    response_payload = json.loads(raw_body)
    answer = str(response_payload["choices"][0]["message"]["content"]).strip()
    answer = clean_news_text(answer)
    if len(answer) > config.AI_CHAT_MAX_REPLY_CHARS:
        answer = answer[: config.AI_CHAT_MAX_REPLY_CHARS - 3] + "..."
    return answer or "我没想好怎么回答这个问题。"


def send_group_reply(chat: ChatRequest, answer: str) -> bool:
    text = f"{config.AI_CHAT_REPLY_PREFIX}{answer}" if config.AI_CHAT_REPLY_PREFIX else answer
    message: list[dict[str, Any]] = []
    if chat.message_id:
        message.append({"type": "reply", "data": {"id": chat.message_id}})
    message.append({"type": "text", "data": {"text": text}})
    status, body = post_onebot(
        config.QQ_BOT_API_URL,
        {"group_id": chat.group_id, "message": message},
    )
    payload = json.loads(body)
    ok = 200 <= status < 300 and isinstance(payload, dict) and payload.get("retcode") == 0
    write_chat_log(
        {
            "event": "reply_sent" if ok else "reply_failed",
            "group_id": chat.group_id,
            "user_id": chat.user_id,
            "message_id": chat.message_id,
            "http_status": status,
            "response": summarize_body(body),
        }
    )
    return ok


def handle_chat_event(event: dict[str, Any], bot_user_id: str) -> None:
    chat = parse_chat_request(event, bot_user_id)
    if chat is None:
        return
    started = time.monotonic()
    write_chat_log(
        {
            "event": "question_received",
            "group_id": chat.group_id,
            "user_id": chat.user_id,
            "message_id": chat.message_id,
            "question": chat.question,
        }
    )
    try:
        answer = classify_question(chat.question)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        write_chat_log(
            {
                "event": "ai_success",
                "group_id": chat.group_id,
                "user_id": chat.user_id,
                "message_id": chat.message_id,
                "elapsed_ms": elapsed_ms,
                "answer": answer,
            }
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        write_chat_log(
            {
                "event": "ai_failed",
                "group_id": chat.group_id,
                "user_id": chat.user_id,
                "message_id": chat.message_id,
                "elapsed_ms": elapsed_ms,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        answer = "我刚刚连接 AI 失败了，稍后再试一下。"

    try:
        send_group_reply(chat, answer)
    except Exception as exc:
        write_chat_log(
            {
                "event": "send_failed",
                "group_id": chat.group_id,
                "user_id": chat.user_id,
                "message_id": chat.message_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        print(f"[AI_CHAT] send_failed error={exc}", flush=True)


class OneBotWebhookHandler(BaseHTTPRequestHandler):
    bot_user_id = ""

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            event = json.loads(raw_body)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
        except Exception as exc:
            write_chat_log({"event": "bad_request", "error_type": type(exc).__name__, "error": str(exc)})
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(204)
        self.end_headers()
        threading.Thread(target=handle_chat_event, args=(event, self.bot_user_id), daemon=True).start()

    def log_message(self, format: str, *args: Any) -> None:
        return


def request_stop(signum: int | None = None, frame: Any | None = None) -> None:
    if server is not None:
        print("[AI_CHAT] stopping", flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()


def run() -> int:
    global server
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not config.AI_CHAT_BOT_ENABLED:
        print("[AI_CHAT] disabled by AI_CHAT_BOT_ENABLED", flush=True)
        return 1
    bot_user_id = get_bot_user_id()
    OneBotWebhookHandler.bot_user_id = bot_user_id
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    server = ThreadingHTTPServer((config.AI_CHAT_HOST, config.AI_CHAT_PORT), OneBotWebhookHandler)
    print(
        f"[AI_CHAT] listening={config.AI_CHAT_HOST}:{config.AI_CHAT_PORT} group={config.QQ_GROUP_ID} bot={bot_user_id}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    print("[AI_CHAT] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
