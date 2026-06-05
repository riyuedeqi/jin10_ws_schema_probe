from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


BASE_DIR = Path(__file__).resolve().parent
TRUE_VALUES = {"1", "true", "yes", "on"}

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def env_int(name: str, default: int) -> int:
    return int(env_str(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(env_str(name, str(default)))

LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

RAW_LOG_PATH = LOG_DIR / "raw.jsonl"
AUDIT_LOG_PATH = LOG_DIR / "audit.jsonl"
PUSH_LOG_PATH = LOG_DIR / "push.jsonl"
NEWS_IMPACT_LOG_PATH = LOG_DIR / "news_impact_classifier.jsonl"
ERROR_LOG_PATH = LOG_DIR / "errors.jsonl"
SENT_DEDUPE_KEYS_PATH = DATA_DIR / "sent_dedupe_keys.txt"
SENT_NEWS_IDS_PATH = DATA_DIR / "sent_news_ids.txt"

# Backward-compatible names used by the filter module and old reports.
FILTER_AUDIT_LOG_PATH = AUDIT_LOG_PATH
QQ_SENT_LOG_PATH = PUSH_LOG_PATH
QQ_FAILED_LOG_PATH = ERROR_LOG_PATH

JIN10_WS_URL = env_str("JIN10_WS_URL")
QQ_BOT_API_URL = env_str("QQ_BOT_API_URL", "http://127.0.0.1:3000/send_group_msg")
QQ_GROUP_ID = env_str("QQ_GROUP_ID")
QQ_ACCESS_TOKEN = env_str("QQ_ACCESS_TOKEN")
QQ_ACCESS_TOKEN_MODE = env_str("QQ_ACCESS_TOKEN_MODE", "none").lower()
QQ_PUSH_ENABLED = env_bool("QQ_PUSH_ENABLED", True)

RAW_LOG_ENABLED = env_bool("RAW_LOG_ENABLED", True)
AUDIT_LOG_ENABLED = env_bool("AUDIT_LOG_ENABLED", True)

NEWS_IMPACT_CLASSIFIER_ENABLED = env_bool("NEWS_IMPACT_CLASSIFIER_ENABLED", True)
NEWS_IMPACT_CLASSIFIER_PROVIDER = env_str("NEWS_IMPACT_CLASSIFIER_PROVIDER", "deepseek").lower()
DEEPSEEK_API_KEY = env_str("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = env_str("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_TIMEOUT_SECONDS = env_float("DEEPSEEK_TIMEOUT_SECONDS", 10)
DEEPSEEK_MAX_TOKENS = env_int("DEEPSEEK_MAX_TOKENS", 120)
NEWS_IMPACT_CLASSIFIER_MAX_CONTENT_CHARS = env_int("NEWS_IMPACT_CLASSIFIER_MAX_CONTENT_CHARS", 1200)

AI_CHAT_BOT_ENABLED = env_bool("AI_CHAT_BOT_ENABLED")
AI_CHAT_HOST = env_str("AI_CHAT_HOST", "127.0.0.1")
AI_CHAT_PORT = env_int("AI_CHAT_PORT", 8765)
AI_CHAT_LOG_PATH = LOG_DIR / "ai_chat_bot.jsonl"
AI_CHAT_MAX_QUESTION_CHARS = env_int("AI_CHAT_MAX_QUESTION_CHARS", 1000)
AI_CHAT_MAX_REPLY_CHARS = env_int("AI_CHAT_MAX_REPLY_CHARS", 1800)
AI_CHAT_REPLY_PREFIX = env_str("AI_CHAT_REPLY_PREFIX")

MARKET_API_BASE_URL = env_str("MARKET_API_BASE_URL", "https://www.okx.com").rstrip("/")
MARKET_PROXY_URL = env_str("MARKET_PROXY_URL", "http://127.0.0.1:7890")
MARKET_TIMEOUT_SECONDS = env_float("MARKET_TIMEOUT_SECONDS", 6)
