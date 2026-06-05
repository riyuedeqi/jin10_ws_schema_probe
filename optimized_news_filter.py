from __future__ import annotations

import hashlib
import html
import json
import re
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import FILTER_AUDIT_LOG_PATH, SENT_DEDUPE_KEYS_PATH


PUSH_THRESHOLD = 6

QUALITY_SKIP_TYPES = {"vip", "ad", "promotion", "notice"}
QUALITY_SKIP_TERMS = [
    "金十VIP",
    "开通VIP",
    "会员专享",
    "会员内容",
    "付费内容",
    "订阅后查看",
    "点击查看",
    "查看详情",
    "下载金十",
    "打开APP",
    "立即开通",
    "限时优惠",
    "广告",
    "推广",
    "金十期货",
    "研报",
    "Live分析",
    "正在直播",
    "点击阅读",
    "点击进入直播间",
]

LOW_VALUE_SKIP_TERMS = [
    "金十数据整理：每日",
    "金十数据整理：昨日今晨重要新闻汇总",
    "金十数据整理：欧盘美盘重要新闻汇总",
    "金十数据整理：中东局势跟踪",
    "金十数据整理：周日重要消息汇总",
    "金十数据整理：周末重要消息汇总",
    "金十数据整理：每日债券市场要闻速递",
    "金十数据整理：俄乌冲突最新24小时局势跟踪",
    "每日美股市场要闻速递",
    "每日债券市场要闻速递",
    "今日重点关注的财经数据与事件",
    "本周重要事件与数据预告",
    "下周重要事件与数据预告",
    "周日重要消息汇总",
    "周末重要消息汇总",
    "一周热榜精选",
    "市场要闻速递",
    "重要新闻汇总",
    "过去24小时都忙了什么",
    "欧洲央行管委",
]

SCORE_GROUPS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "crypto_direct",
        10,
        (
            "比特币",
            "BTC",
            "以太坊",
            "ETH",
            "加密货币",
            "稳定币",
            "币安",
            "Binance",
            "Coinbase",
            "OKX",
            "加密 ETF",
            "加密ETF",
            "比特币ETF",
            "以太坊ETF",
        ),
    ),
    ("trump", 6, ("特朗普", "Trump", "美国总统")),
    (
        "middle_east_risk",
        7,
        (
            "伊朗",
            "美伊",
            "以色列",
            "霍尔木兹",
            "中东",
            "黎巴嫩",
            "真主党",
            "加沙",
            "哈马斯",
            "冲突",
            "空袭",
            "导弹",
            "袭击",
            "打击",
            "火箭弹",
            "无人机",
            "军事行动",
            "撤离",
            "疏散令",
            "战火",
            "停火",
            "核协议",
            "制裁",
        ),
    ),
    (
        "us_macro",
        8,
        ("美联储", "鲍威尔", "降息", "加息", "利率", "FOMC", "CPI", "PCE", "非农", "失业率", "通胀"),
    ),
    (
        "market_proxy",
        5,
        ("美债", "国债收益率", "美元指数", "纳指", "标普", "美股期货", "黄金", "原油", "WTI", "布伦特"),
    ),
)

US_MACRO_CONTEXT_TERMS = (
    "美国",
    "美联储",
    "FOMC",
    "鲍威尔",
    "美元",
    "美债",
    "纳指",
    "标普",
    "美股",
    "CME",
)
US_SPECIFIC_MACRO_TERMS = ("美联储", "鲍威尔", "FOMC", "非农")
MIDDLE_EAST_CONTEXT_TERMS = ("战争", "冲突", "空袭", "导弹", "停火", "核协议", "制裁", "袭击", "封锁", "霍尔木兹")
MIDDLE_EAST_CORE_TERMS = ("伊朗", "美伊", "以色列", "霍尔木兹")
MIDDLE_EAST_EVENT_TERMS = ("战争", "冲突", "空袭", "导弹", "停火", "核协议", "袭击", "封锁")
MIDDLE_EAST_REGION_TERMS = ("中东", "黎巴嫩", "真主党", "哈马斯", "加沙", "胡塞", "红海")
SANCTION_CONTEXT_TERMS = (
    "伊朗",
    "美伊",
    "以色列",
    "中东",
    "霍尔木兹",
    "特朗普",
    "美国总统",
    "加密货币",
    "稳定币",
    "币安",
    "Binance",
    "Coinbase",
    "OKX",
)
FOREIGN_MACRO_EXCLUSION_TERMS = (
    "欧洲央行",
    "日本央行",
    "英国央行",
    "加拿大央行",
    "澳洲联储",
    "新西兰联储",
    "瑞士央行",
    "匈牙利央行",
    "法国",
    "德国",
    "英国",
    "日本",
    "匈牙利",
)
FOREIGN_MACRO_STRICT_EXCLUSION_TERMS = (
    "欧洲央行",
    "日本央行",
    "英国央行",
    "加拿大央行",
    "澳洲联储",
    "新西兰联储",
    "瑞士央行",
    "瑞典央行",
    "匈牙利央行",
    "澳大利亚",
    "欧元区",
    "瑞典",
)
MARKET_TRANSMISSION_TERMS = (
    "美联储",
    "鲍威尔",
    "FOMC",
    "美国CPI",
    "非农",
    "美元",
    "美债",
    "国债收益率",
    "美股",
    "纳指",
    "标普",
    "黄金",
    "原油",
    "油价",
    "WTI",
    "布伦特",
    "霍尔木兹",
)
LOCAL_MIDDLE_EAST_REPORT_TERMS = ("黎巴嫩", "黎以", "真主党", "加沙", "哈马斯", "以色列", "以军", "贝鲁特")
LOCAL_MIDDLE_EAST_EVENT_TERMS = (
    "袭击",
    "打击",
    "火箭弹",
    "无人机",
    "军事行动",
    "撤离",
    "疏散令",
    "战火",
    "冲突",
    "停火",
)
TRUMP_MARKET_OR_POLICY_TERMS = MARKET_TRANSMISSION_TERMS + (
    "关税",
    "贸易",
    "制裁",
    "预算",
    "债务",
    "赤字",
    "税改",
    "加密",
    "比特币",
    "稳定币",
    "伊朗",
    "美伊",
    "以色列",
    "霍尔木兹",
)
TRUMP_LOW_VALUE_TERMS = (
    "肯尼迪中心",
    "北约",
    "移民",
    "庇护申请",
    "证券欺诈",
    "点赞视频",
    "更名",
    "表演艺术中心",
    "纸币",
)
TRUMP_LOW_VALUE_RUSSIA_TERMS = ("俄罗斯", "俄新社", "俄方", "克里姆林宫")
TRUMP_LOW_VALUE_CONTACT_TERMS = (
    "特使",
    "女婿",
    "库什纳",
    "威特科夫",
    "接触",
    "会见",
    "会晤",
    "通话",
    "将与",
)
COMMODITY_COMMENTARY_SOURCE_TERMS = (
    "世界黄金协会",
    "黄金协会",
    "分析师",
    "机构",
    "报告",
)
COMMODITY_COMMENTARY_TERMS = (
    "实物市场",
    "黄金ETF",
    "资金流入",
    "资金流出",
    "贴水",
    "抛售迹象",
    "疲弱表现",
    "延续疲弱",
    "或延续",
    "可能来自",
    "市场焦点",
    "通胀预期",
    "债券收益率走势",
)

HOUSING_CREDIT_TERMS = (
    "抵押贷款",
    "房贷",
    "住房贷款",
    "购房贷款",
    "房价",
    "房地产市场",
    "新屋销售",
    "成屋销售",
    "房利美",
    "房地美",
    "Freddie Mac",
    "Fannie Mae",
    "MBA30年期固定抵押贷款利率",
    "MBA 30年期固定抵押贷款利率",
)
HOUSING_CREDIT_SOURCE_TERMS = (
    "房利美",
    "房地美",
    "Redfin",
    "全美地产经纪商协会",
    "美国全国房地产经纪人协会",
)
HOUSING_CREDIT_DIRECT_MARKET_TERMS = (
    "美联储",
    "鲍威尔",
    "FOMC",
    "CPI",
    "PCE",
    "非农",
    "失业率",
    "美元",
    "美债",
    "国债收益率",
    "纳指",
    "标普",
    "美股期货",
    "黄金",
    "原油",
    "WTI",
    "布伦特",
    "霍尔木兹",
)

COMPANY_SPECIFIC_TERMS = (
    "股份",
    "公司",
    "公告",
    "互动平台",
    "股价",
    "涨停",
    "A股",
    "港股",
    "IPO",
    "财报",
    "净利润",
    "董事会",
    "控股子公司",
    "生产经营",
    "采购合同",
    "客户订单",
    "业务营收",
)
COMPANY_SPECIFIC_STRONG_TERMS = (
    "股份",
    "互动平台",
    "股价",
    "涨停",
    "A股",
    "港股",
    "IPO",
    "财报",
    "净利润",
    "董事会",
    "控股子公司",
    "生产经营",
    "采购合同",
    "客户订单",
    "业务营收",
)
COMPANY_MARKET_RELEVANT_TERMS = (
    "加密货币",
    "稳定币",
    "比特币",
    "BTC",
    "以太坊",
    "ETH",
    "黄金",
    "美元",
    "美债",
    "国债收益率",
    "美联储",
    "CPI",
    "PCE",
    "非农",
    "霍尔木兹",
    "原油",
    "油价",
)
FED_LOW_INFORMATION_TERMS = (
    "尚未发现",
    "尚未看到",
    "不知道",
    "很难说",
    "不确定性非常高",
    "政策处于良好状态",
    "已做好双向应对准备",
    "当前提供前瞻指引可能会产生误导",
    "拭目以待",
    "没有评论",
    "拒绝置评",
)
FED_STRONG_TERMS = (
    "降息",
    "加息",
    "提高利率",
    "下调利率",
    "通胀",
    "就业",
    "劳动力市场",
    "PCE",
    "CPI",
    "非农",
    "点阵图",
    "利率路径",
    "国债收益率",
    "美元",
    "美债",
)

IGNORED_TEXT_KEYS = {
    "id",
    "time",
    "timestamp",
    "create_time",
    "update_time",
    "action",
    "type",
    "m_type",
    "event",
    "url",
    "link",
    "href",
    "image",
    "pic",
    "avatar",
    "source_link",
    "voices",
    "voice",
    "audio",
    "audios",
    "yunlong",
    "yunyang",
    "xiaochen",
    "xiaotong",
}


@dataclass(frozen=True)
class OptimizedEvaluation:
    timestamp: str
    kind: str
    text: str
    score: int
    reasons: list[str]
    decision: str
    skip_reason: str
    dedupe_key: str
    matched_keywords: list[str]
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "text": self.text,
            "score": self.score,
            "final_score": self.score,
            "reasons": self.reasons,
            "decision": self.decision,
            "skip_reason": self.skip_reason,
            "dedupe_key": self.dedupe_key,
            "matched_keywords": self.matched_keywords,
            "hit_type": "optimized_filter_hit" if self.decision == "push" else "pure_noise",
            "reason_type": "optimized_filter_hit" if self.decision == "push" else "pure_noise",
            "metadata": self.metadata,
            "fields": {"body": self.text, "title": "", "meta": self.kind},
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_raw_json(raw: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def extract_metadata(msg: dict[str, Any]) -> dict[str, Any]:
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    return {
        "type": msg.get("type"),
        "channel": msg.get("channel"),
        "category": msg.get("category") or data.get("category"),
        "source": msg.get("source") or data.get("source"),
        "event": msg.get("event"),
        "action": msg.get("action"),
        "important": msg.get("important"),
        "id": msg.get("id"),
        "time": msg.get("time"),
    }


def message_kind(msg: dict[str, Any]) -> str:
    metadata = extract_metadata(msg)
    parts = [
        str(metadata.get("event") or ""),
        str(metadata.get("type") or ""),
        str(metadata.get("category") or ""),
        str(metadata.get("source") or ""),
    ]
    return "|".join(part for part in parts if part) or "unknown"


def iter_string_fields(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            strings.append(text)
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key) in IGNORED_TEXT_KEYS:
                continue
            strings.extend(iter_string_fields(item))
    elif isinstance(value, list):
        for item in value:
            strings.extend(iter_string_fields(item))
    return strings


def dedupe_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for part in parts:
        compact = " ".join(part.split())
        if not compact or compact in seen:
            continue
        seen.add(compact)
        output.append(compact)
    return output


def clean_news_text(text: str) -> str:
    unescaped = html.unescape(text)
    without_tags = re.sub(r"<[^>]+>", " ", unescaped)
    return " ".join(without_tags.split())


def extract_news_text(msg: dict[str, Any]) -> str:
    data = msg.get("data")
    preferred: list[str] = []
    for key in ("title", "content", "vip_title", "vip_desc"):
        value = msg.get(key)
        if isinstance(value, str) and value.strip():
            preferred.append(value.strip())
    if isinstance(data, dict):
        for key in ("title", "content", "vip_title", "vip_desc"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                preferred.append(value.strip())
    if preferred:
        return clean_news_text(" ".join(dedupe_parts(preferred)))
    return clean_news_text(" ".join(dedupe_parts(iter_string_fields(msg))))


def _ascii_keyword_in_text(text: str, keyword: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])", text, re.IGNORECASE))


def keyword_in_text(text: str, keyword: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9 ]+", keyword):
        return _ascii_keyword_in_text(text, keyword)
    return keyword.lower() in text.lower()


def find_hits(text: str, keywords: tuple[str, ...] | list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword_in_text(text, keyword)]


def quality_skip_reason(msg: dict[str, Any], text: str) -> str:
    metadata = extract_metadata(msg)
    for key in ("type", "category", "source", "event"):
        value = str(metadata.get(key) or "").strip().lower()
        if value in QUALITY_SKIP_TYPES:
            return f"quality_{key}_{value}"
    if str(metadata.get("event") or "").strip().lower() == "flash-hot-changed":
        return "low_value_event_flash_hot_changed"
    data = msg.get("data")
    if str(metadata.get("type") or "").strip().lower() == "flash" and isinstance(data, list):
        return "low_value_flash_list"
    extras = msg.get("extras")
    if isinstance(extras, dict) and extras.get("ad") is True:
        return "quality_extras_ad"
    if isinstance(data, dict) and data.get("lock") is True:
        return "quality_member_wall"
    hit_terms = find_hits(text, QUALITY_SKIP_TERMS)
    if hit_terms:
        return "quality_text_" + hit_terms[0]
    low_value_terms = find_hits(text, LOW_VALUE_SKIP_TERMS)
    if low_value_terms:
        return "low_value_text_" + low_value_terms[0]
    if is_low_value_commodity_commentary(text):
        return "low_value_commodity_commentary"
    if is_low_value_housing_credit(text):
        return "low_value_housing_credit"
    return ""


def low_value_score_skip_reason(text: str, reasons: list[str]) -> str:
    labels = [reason.split(":", 1)[0] for reason in reasons]

    if is_low_value_trump_only(text, labels):
        return "low_value_trump_context"

    if is_company_keyword_false_positive(text, labels):
        return "low_value_company_keyword_context"

    if is_low_information_fed_quote(text, labels):
        return "low_value_fed_quote"

    if "middle_east_risk" in labels and "trump" not in labels:
        if (
            find_hits(text, FOREIGN_MACRO_STRICT_EXCLUSION_TERMS)
            and not find_hits(text, MARKET_TRANSMISSION_TERMS)
            and not is_local_middle_east_report(text)
        ):
            return "low_value_foreign_macro_context"
        if find_hits(text, ("中东",)) and not find_hits(text, MARKET_TRANSMISSION_TERMS + LOCAL_MIDDLE_EAST_REPORT_TERMS):
            return "low_value_middle_east_background"

    return ""


def is_local_middle_east_report(text: str) -> bool:
    return bool(find_hits(text, LOCAL_MIDDLE_EAST_REPORT_TERMS) and find_hits(text, LOCAL_MIDDLE_EAST_EVENT_TERMS))


def is_low_value_commodity_commentary(text: str) -> bool:
    if not find_hits(text, ("黄金", "原油", "油价", "能源")):
        return False
    return bool(find_hits(text, COMMODITY_COMMENTARY_SOURCE_TERMS) and find_hits(text, COMMODITY_COMMENTARY_TERMS))


def is_low_value_housing_credit(text: str) -> bool:
    if not find_hits(text, HOUSING_CREDIT_TERMS):
        return False
    if find_hits(text, HOUSING_CREDIT_SOURCE_TERMS):
        return True
    if find_hits(text, ("卖家", "买家", "库存", "房产经纪人", "销售旺季", "购房者", "住房贷款利率")):
        return True
    return not find_hits(text, HOUSING_CREDIT_DIRECT_MARKET_TERMS)


def is_low_value_trump_only(text: str, labels: list[str]) -> bool:
    if "trump" not in labels:
        return False
    if any(label in labels for label in ("crypto_direct", "middle_east_risk", "us_macro", "market_proxy")):
        return False
    return bool(find_hits(text, TRUMP_LOW_VALUE_TERMS) or not find_hits(text, TRUMP_MARKET_OR_POLICY_TERMS))


def is_company_keyword_false_positive(text: str, labels: list[str]) -> bool:
    if not find_hits(text, COMPANY_SPECIFIC_TERMS):
        return False
    if not find_hits(text, COMPANY_SPECIFIC_STRONG_TERMS):
        return False
    if "crypto_direct" in labels:
        return False
    if find_hits(text, ("重大经营影响", "重大不利影响")) and not find_hits(text, ("未带来重大", "未造成重大", "不产生重大")):
        return False
    if find_hits(text, COMPANY_MARKET_RELEVANT_TERMS) and not find_hits(
        text,
        ("未带来重大经营影响", "尚未对公司经营产生不利影响", "占整体比重较小", "不涉及"),
    ):
        return False
    return bool(set(labels) & {"trump", "middle_east_risk", "market_proxy", "us_macro"})


def is_low_information_fed_quote(text: str, labels: list[str]) -> bool:
    if "us_macro" not in labels or len(labels) != 1:
        return False
    if not find_hits(text, ("美联储",)):
        return False
    if len(text) > 120:
        return False
    if find_hits(text, FED_STRONG_TERMS) and not find_hits(text, FED_LOW_INFORMATION_TERMS):
        return False
    return bool(find_hits(text, FED_LOW_INFORMATION_TERMS))


def normalize_for_dedupe(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"<[^>]+>", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    punctuation = string.punctuation + "，。！？；：、“”‘’（）《》【】…—·￥"
    normalized = re.sub("[" + re.escape(punctuation) + "]", "", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", normalized)
    return normalized[:200]


def build_dedupe_key(text: str) -> str:
    normalized = normalize_for_dedupe(text)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def should_count_us_macro(text: str, hits: list[str]) -> bool:
    if any(hit in US_SPECIFIC_MACRO_TERMS for hit in hits):
        return True
    if not find_hits(text, US_MACRO_CONTEXT_TERMS):
        return False
    if find_hits(text, FOREIGN_MACRO_EXCLUSION_TERMS) and not find_hits(text, ("美国", "美联储", "FOMC", "鲍威尔")):
        return False
    return True


def should_count_trump(text: str) -> bool:
    if find_hits(text, TRUMP_LOW_VALUE_RUSSIA_TERMS) and find_hits(text, TRUMP_LOW_VALUE_CONTACT_TERMS):
        return bool(find_hits(text, TRUMP_MARKET_OR_POLICY_TERMS))
    return True


def should_count_middle_east(text: str, hits: list[str]) -> bool:
    if not hits:
        return False
    if hits == ["制裁"]:
        return bool(find_hits(text, SANCTION_CONTEXT_TERMS))
    if hits == ["中东"]:
        return bool(find_hits(text, MIDDLE_EAST_CONTEXT_TERMS))
    if any(hit in MIDDLE_EAST_CORE_TERMS for hit in hits):
        return True
    if is_local_middle_east_report(text):
        return True
    if any(hit in MIDDLE_EAST_EVENT_TERMS for hit in hits):
        return bool(find_hits(text, MIDDLE_EAST_REGION_TERMS))
    return False


def score_text(text: str) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    matched_keywords: list[str] = []
    for label, points, keywords in SCORE_GROUPS:
        hits = find_hits(text, keywords)
        if hits:
            if label == "trump" and not should_count_trump(text):
                continue
            if label == "us_macro" and not should_count_us_macro(text, hits):
                continue
            if label == "middle_east_risk" and not should_count_middle_east(text, hits):
                continue
            score += points
            reasons.append(f"{label}:+{points}({','.join(hits)})")
            matched_keywords.extend(hits)
    return score, reasons, dedupe_parts(matched_keywords)


def evaluate_optimized_news(msg: dict[str, Any], timestamp: str | None = None) -> dict[str, Any]:
    timestamp = timestamp or now_iso()
    text = extract_news_text(msg)
    kind = message_kind(msg)
    dedupe_key = build_dedupe_key(text)
    metadata = extract_metadata(msg)

    skip_reason = quality_skip_reason(msg, text)
    if skip_reason:
        return OptimizedEvaluation(
            timestamp=timestamp,
            kind=kind,
            text=text,
            score=0,
            reasons=[],
            decision="skip",
            skip_reason=skip_reason,
            dedupe_key=dedupe_key,
            matched_keywords=[],
            metadata=metadata,
        ).as_dict()

    score, reasons, matched_keywords = score_text(text)
    skip_reason = low_value_score_skip_reason(text, reasons)
    if skip_reason:
        return OptimizedEvaluation(
            timestamp=timestamp,
            kind=kind,
            text=text,
            score=score,
            reasons=reasons,
            decision="skip",
            skip_reason=skip_reason,
            dedupe_key=dedupe_key,
            matched_keywords=matched_keywords,
            metadata=metadata,
        ).as_dict()

    decision = "push" if score >= PUSH_THRESHOLD else "skip"
    skip_reason = "" if decision == "push" else "score_below_threshold"
    return OptimizedEvaluation(
        timestamp=timestamp,
        kind=kind,
        text=text,
        score=score,
        reasons=reasons,
        decision=decision,
        skip_reason=skip_reason,
        dedupe_key=dedupe_key,
        matched_keywords=matched_keywords,
        metadata=metadata,
    ).as_dict()


def build_optimized_push_text(msg: dict[str, Any], receive_time: str, evaluation: dict[str, Any]) -> str:
    news_time = msg.get("time") or receive_time
    text = str(evaluation.get("text") or extract_news_text(msg))
    compact = clean_news_text(text)
    if len(compact) > 800:
        compact = compact[:799] + "..."
    return "\n".join(["金十快讯", "", f"时间：{news_time}", f"内容：{compact}"])


def load_sent_dedupe_keys(path: Path = SENT_DEDUPE_KEYS_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def mark_sent_dedupe_key(dedupe_key: str, path: Path = SENT_DEDUPE_KEYS_PATH) -> None:
    if not dedupe_key:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(dedupe_key + "\n")
        file.flush()


def append_filter_audit(evaluation: dict[str, Any], path: Path = FILTER_AUDIT_LOG_PATH) -> None:
    payload = {
        "timestamp": evaluation.get("timestamp") or now_iso(),
        "kind": evaluation.get("kind") or "",
        "text": evaluation.get("text") or "",
        "score": evaluation.get("score") or 0,
        "reasons": evaluation.get("reasons") or [],
        "decision": evaluation.get("decision") or "",
        "skip_reason": evaluation.get("skip_reason") or "",
        "dedupe_key": evaluation.get("dedupe_key") or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        file.flush()
