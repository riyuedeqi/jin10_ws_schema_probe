from __future__ import annotations

import json
import re
import signal
import sys
import time
import traceback
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websocket import WebSocketApp

import config
from news_impact_classifier import (
    classify_news_impact,
    extract_news_impact_input,
    format_impact_for_push,
)
from optimized_news_filter import (
    append_filter_audit,
    build_optimized_push_text,
    evaluate_optimized_news,
    load_sent_dedupe_keys,
    mark_sent_dedupe_key,
)
from qq_pusher import post_onebot, summarize_body


SUBSCRIBE_MESSAGE = {"type": "subscribe", "channels": ["flash"]}

stop_requested = False
active_ws: WebSocketApp | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def mask_ws_url(url: str) -> str:
    return re.sub(r"([?&]token=)[^&]*", r"\1***", url, flags=re.IGNORECASE)


def ensure_dirs() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        file.flush()


def log_error(event: str, exc: Any | None = None, **extra: Any) -> None:
    payload: dict[str, Any] = {"time": now_iso(), "event": event, **extra}
    if exc is not None:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
    try:
        append_jsonl(config.ERROR_LOG_PATH, payload)
    except Exception as write_exc:
        print(f"[ERROR] write error log failed: {write_exc}", flush=True)


def message_id(msg: dict[str, Any]) -> str:
    value = msg.get("id")
    if value is None and isinstance(msg.get("data"), dict):
        value = msg["data"].get("id")
    return str(value or "")


def load_sent_news_ids() -> set[str]:
    path = config.SENT_NEWS_IDS_PATH
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def mark_sent_news_id(news_id: str) -> None:
    if not news_id:
        return
    config.SENT_NEWS_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.SENT_NEWS_IDS_PATH.open("a", encoding="utf-8") as file:
        file.write(news_id + "\n")
        file.flush()


def write_raw(receive_time: str, raw_text: str) -> None:
    if config.RAW_LOG_ENABLED:
        append_jsonl(config.RAW_LOG_PATH, {"receive_time": receive_time, "raw_text": raw_text})


def write_push(record: dict[str, Any]) -> None:
    append_jsonl(config.PUSH_LOG_PATH, record)


def write_impact_log(record: dict[str, Any]) -> None:
    try:
        append_jsonl(config.NEWS_IMPACT_LOG_PATH, record)
    except Exception as exc:
        print(f"[IMPACT] log_write_failed error={exc}", flush=True)


def classify_and_append_impact(push_text: str, receive_time: str, msg: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if not config.NEWS_IMPACT_CLASSIFIER_ENABLED:
        return push_text, None

    news_id = message_id(msg)
    impact_input = extract_news_impact_input(msg, receive_time)
    started = time.monotonic()
    log_record: dict[str, Any] = {
        "time": now_iso(),
        "news_id": news_id,
        "title": impact_input.title or impact_input.content[:80],
        "provider": config.NEWS_IMPACT_CLASSIFIER_PROVIDER,
    }

    try:
        impact = classify_news_impact(impact_input)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        write_impact_log(
            {
                **log_record,
                "success": False,
                "elapsed_ms": elapsed_ms,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        print(
            f"[IMPACT] success=false id={news_id or '-'} elapsed_ms={elapsed_ms} title={log_record['title'][:80]}",
            flush=True,
        )
        return push_text, None

    elapsed_ms = int((time.monotonic() - started) * 1000)
    write_impact_log({**log_record, "success": True, "elapsed_ms": elapsed_ms, "impact": impact})
    print(
        f"[IMPACT] success=true id={news_id or '-'} elapsed_ms={elapsed_ms} impact={impact}",
        flush=True,
    )
    return f"{push_text}\n\n{format_impact_for_push(impact)}", impact


def send_push(push_text: str, receive_time: str, msg: dict[str, Any], evaluation: dict[str, Any]) -> bool:
    dedupe_key = str(evaluation.get("dedupe_key") or "")
    base_record = {
        "time": now_iso(),
        "receive_time": receive_time,
        "news_id": message_id(msg),
        "dedupe_key": dedupe_key,
        "score": evaluation.get("score"),
        "reasons": evaluation.get("reasons") or [],
        "text": evaluation.get("text") or "",
        "push_text": push_text,
    }

    if not config.QQ_PUSH_ENABLED:
        write_push({**base_record, "status": "dry_run"})
        print(f"[QQ_DISABLED] key={dedupe_key}", flush=True)
        return True

    try:
        status, body = post_onebot(
            config.QQ_BOT_API_URL,
            {"group_id": config.QQ_GROUP_ID, "message": push_text},
        )
    except Exception as exc:
        http_status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        write_push({**base_record, "status": "failed", "http_status": http_status, "error": str(exc)})
        log_error("onebot_send_exception", exc, dedupe_key=dedupe_key, news_id=message_id(msg))
        return False

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    ok = 200 <= status < 300 and isinstance(payload, dict) and payload.get("retcode") == 0
    write_push(
        {
            **base_record,
            "status": "sent" if ok else "failed",
            "http_status": status,
            "response": summarize_body(body),
        }
    )
    return ok


def handle_message(receive_time: str, msg: dict[str, Any]) -> None:
    evaluation = evaluate_optimized_news(msg, receive_time)
    dedupe_key = str(evaluation.get("dedupe_key") or "")
    news_id = message_id(msg)

    if evaluation.get("decision") == "push" and dedupe_key in load_sent_dedupe_keys():
        evaluation = {**evaluation, "decision": "skip", "skip_reason": "duplicate_dedupe_key"}
    if evaluation.get("decision") == "push" and news_id and news_id in load_sent_news_ids():
        evaluation = {**evaluation, "decision": "skip", "skip_reason": "duplicate_news_id"}

    if config.AUDIT_LOG_ENABLED:
        append_filter_audit(evaluation, config.AUDIT_LOG_PATH)

    if evaluation.get("decision") != "push":
        return

    push_text = build_optimized_push_text(msg, receive_time, evaluation)
    push_text, impact = classify_and_append_impact(push_text, receive_time, msg)
    if impact is not None:
        evaluation = {**evaluation, "news_impact": impact}
    if send_push(push_text, receive_time, msg, evaluation):
        mark_sent_dedupe_key(dedupe_key)
        mark_sent_news_id(news_id)
        reasons = ";".join(evaluation.get("reasons") or [])
        print(f"[PUSH] key={dedupe_key} id={news_id or '-'} reasons={reasons}", flush=True)


def on_open(ws: WebSocketApp) -> None:
    ws.send(json.dumps(SUBSCRIBE_MESSAGE, ensure_ascii=False))
    print("[OPEN] connected, subscribed channels=flash", flush=True)


def on_message(ws: WebSocketApp, message: Any) -> None:
    receive_time = now_iso()
    raw_text = message if isinstance(message, str) else str(message)

    try:
        write_raw(receive_time, raw_text)
    except Exception as exc:
        log_error("write_raw_failed", exc)

    try:
        msg = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log_error("json_parse_failed", exc, raw_text=raw_text[:1000])
        return

    if not isinstance(msg, dict):
        return

    try:
        handle_message(receive_time, msg)
    except Exception as exc:
        log_error("handle_message_failed", exc, raw_text=raw_text[:1000])
        print(f"[ERROR] handle message failed: {exc}", flush=True)


def on_error(ws: WebSocketApp, error: Any) -> None:
    log_error("websocket_error", None, error=str(error))
    print(f"[ERROR] websocket: {error}", flush=True)


def on_close(ws: WebSocketApp, close_status_code: Any, close_msg: Any) -> None:
    log_error("websocket_closed", None, close_status_code=close_status_code, close_msg=close_msg)
    print(f"[CLOSE] code={close_status_code} msg={close_msg}", flush=True)


def request_stop(signum: int | None = None, frame: Any | None = None) -> None:
    global stop_requested
    stop_requested = True
    print("[STOP] graceful shutdown requested", flush=True)
    if active_ws is not None:
        active_ws.close()


def run() -> int:
    global active_ws
    ensure_dirs()
    if not config.JIN10_WS_URL:
        print("[ERROR] JIN10_WS_URL is missing in .env", flush=True)
        return 1
    if config.QQ_PUSH_ENABLED and not config.QQ_GROUP_ID:
        print("[ERROR] QQ_GROUP_ID is missing in .env", flush=True)
        return 1

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print(f"[START] url={mask_ws_url(config.JIN10_WS_URL)}", flush=True)
    reconnect_delay = 3
    while not stop_requested:
        active_ws = WebSocketApp(
            config.JIN10_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        try:
            active_ws.run_forever(ping_interval=20, ping_timeout=10)
        except KeyboardInterrupt:
            request_stop()
            break
        except Exception as exc:
            log_error("run_forever_failed", exc)
            print(f"[ERROR] run_forever failed: {exc}", flush=True)
        finally:
            active_ws = None

        if not stop_requested:
            print(f"[RECONNECT] sleeping={reconnect_delay}s", flush=True)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

    print("[EXIT] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
