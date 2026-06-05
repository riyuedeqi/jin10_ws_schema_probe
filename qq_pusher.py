from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any

import config


def _build_onebot_request(api_url: str, payload: dict[str, Any]) -> urllib.request.Request:
    url = api_url
    headers = {"Content-Type": "application/json"}
    if config.QQ_ACCESS_TOKEN and config.QQ_ACCESS_TOKEN_MODE == "header":
        headers["Authorization"] = f"Bearer {config.QQ_ACCESS_TOKEN}"
    elif config.QQ_ACCESS_TOKEN and config.QQ_ACCESS_TOKEN_MODE == "query":
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode({'access_token': config.QQ_ACCESS_TOKEN})}"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(url, data=body, headers=headers, method="POST")


def post_onebot(api_url: str, payload: dict[str, Any]) -> tuple[int, str]:
    request = _build_onebot_request(api_url, payload)
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(2000).decode("utf-8", errors="replace")
        return response.status, body


def summarize_body(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        for key in ("user_id", "self_id", "uin", "qq"):
            if key in data:
                value = str(data[key])
                data[key] = value[:3] + "***" + value[-2:] if len(value) > 5 else "***"
    return json.dumps(payload, ensure_ascii=False)[:500]


def send_to_qq_group(text: str) -> bool:
    if not config.QQ_PUSH_ENABLED:
        print("send=blocked reason=QQ_PUSH_ENABLED_FALSE", flush=True)
        return False
    if not config.QQ_GROUP_ID:
        print("send=blocked reason=QQ_GROUP_ID_EMPTY", flush=True)
        return False
    status, body = post_onebot(config.QQ_BOT_API_URL, {"group_id": config.QQ_GROUP_ID, "message": text})
    print(f"send_http_status={status}", flush=True)
    print(f"send_response={summarize_body(body)}", flush=True)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return 200 <= status < 300
    return payload.get("retcode") == 0


def test_api() -> int:
    base_url = config.QQ_BOT_API_URL.rsplit("/", 1)[0]
    ok_count = 0
    for endpoint in ("get_status", "get_login_info", "get_version_info"):
        try:
            status, body = post_onebot(f"{base_url}/{endpoint}", {})
        except Exception as exc:
            print(f"{endpoint}: failed error={type(exc).__name__}: {exc}", flush=True)
            continue
        ok_count += 1
        print(f"{endpoint}: ok status={status} body={summarize_body(body)}", flush=True)
    return 0 if ok_count else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a QQ group test message through OneBot.")
    parser.add_argument("--test-api", action="store_true", help="Probe OneBot status APIs without sending messages.")
    parser.add_argument("--send-test", help="Send exactly one message.")
    args = parser.parse_args()

    if args.test_api:
        return test_api()
    if args.send_test is not None:
        return 0 if send_to_qq_group(args.send_test) else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
