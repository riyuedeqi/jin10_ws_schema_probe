from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from optimized_news_filter import evaluate_optimized_news  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay Jin10 raw logs through the optimized filter.")
    parser.add_argument("--logs-dir", type=Path, default=config.LOG_DIR)
    parser.add_argument("--out", type=Path, default=config.LOG_DIR / "replay_report.md")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def load_raw_messages(logs_dir: Path) -> list[dict[str, Any]]:
    raw_rows: list[dict[str, Any]] = []
    for name in ("raw.jsonl", "raw_messages.jsonl", "raw_messages.log"):
        raw_rows = read_jsonl(logs_dir / name)
        if raw_rows:
            break

    messages: list[dict[str, Any]] = []
    for row in raw_rows:
        raw_text = row.get("raw_text")
        if isinstance(raw_text, str):
            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
        else:
            msg = row
        if isinstance(msg, dict):
            messages.append(msg)
    return messages


def sample_line(index: int, evaluation: dict[str, Any]) -> str:
    text = " ".join(str(evaluation.get("text") or "").split())
    reasons = "; ".join(evaluation.get("reasons") or [])
    return (
        f"{index}. score={evaluation.get('score')} "
        f"decision={evaluation.get('decision')} "
        f"skip={evaluation.get('skip_reason') or '-'} "
        f"reasons={reasons or '-'} "
        f"text={text[:220]}"
    )


def main() -> int:
    args = parse_args()
    raw_messages = load_raw_messages(args.logs_dir)
    old_pushed = read_jsonl(args.logs_dir / "pushed_news.log")
    old_qq_sent = read_jsonl(args.logs_dir / "qq_sent.log")
    current_push = read_jsonl(args.logs_dir / "push.jsonl")

    seen_keys: set[str] = set()
    push_samples: list[dict[str, Any]] = []
    quality_samples: list[dict[str, Any]] = []
    low_score_samples: list[dict[str, Any]] = []
    quality_skip_count = 0
    dedup_count = 0
    push_count = 0

    for msg in raw_messages:
        evaluation = evaluate_optimized_news(msg)
        skip_reason = str(evaluation.get("skip_reason") or "")
        dedupe_key = str(evaluation.get("dedupe_key") or "")

        if skip_reason.startswith("quality_"):
            quality_skip_count += 1
            if len(quality_samples) < 30:
                quality_samples.append(evaluation)
            continue

        if evaluation.get("decision") == "push":
            if dedupe_key in seen_keys:
                dedup_count += 1
                continue
            seen_keys.add(dedupe_key)
            push_count += 1
            if len(push_samples) < 30:
                push_samples.append(evaluation)
            continue

        if len(low_score_samples) < 30:
            low_score_samples.append(evaluation)

    sent_count = sum(1 for row in current_push if row.get("status") == "sent")
    lines = [
        "# Filter Replay Report",
        "",
        f"- logs_dir: `{args.logs_dir}`",
        f"- raw 总数: {len(raw_messages)}",
        f"- VIP/广告过滤数量: {quality_skip_count}",
        f"- 新规则推送数量: {push_count}",
        f"- 去重数量: {dedup_count}",
        f"- 当前 push.jsonl sent 数量: {sent_count}",
        f"- 旧 pushed_news 数量: {len(old_pushed)}",
        f"- 旧 qq_sent 数量: {len(old_qq_sent)}",
        "",
        "## 前 30 条推送样例及 reasons",
        "",
    ]
    lines.extend(sample_line(i, item) for i, item in enumerate(push_samples, 1))
    lines.extend(["", "## 前 30 条被过滤的 VIP/广告样例", ""])
    lines.extend(sample_line(i, item) for i, item in enumerate(quality_samples, 1))
    lines.extend(["", "## 前 30 条低分跳过样例", ""])
    lines.extend(sample_line(i, item) for i, item in enumerate(low_score_samples, 1))
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"report_written={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
