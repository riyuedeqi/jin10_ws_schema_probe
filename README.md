# Jin10 QQ Bot

金十 WebSocket 快讯筛选后推送到 QQ 群。项目只保留一条主链路：

```text
Jin10 WebSocket -> optimized_news_filter.py -> OneBot QQ group
```

## Files

- `probe.py`: 主进程，连接 WebSocket、记录 raw、调用过滤器、推送 QQ。
- `optimized_news_filter.py`: 新闻质量过滤、BTC/ETH 交易影响评分、去重 key、审计日志。
- `qq_pusher.py`: OneBot HTTP 调用和手动测试消息。
- `ai_chat_bot.py`: OneBot 事件 webhook，群友 @ 机器人时调用 DeepSeek 回复。
- `config.py`: 从 `.env` 读取配置，代码里不放 token、群号等敏感信息。
- `scripts/replay_optimized_filter.py`: 用历史 raw 日志回放过滤规则。
- `scripts/filter_regression_test.py`: 快速回归测试。
- `SENSITIVE_CONFIG.md`: 敏感配置清单，方便上传 Git 前核对。

## Config

复制模板后填写真实值：

```bash
cp .env.example .env
```

`.env` 和 `.env.local` 不提交。真实 token、API key、群号等敏感信息都放这里；`.env.local` 会覆盖 `.env`，适合本机私有覆盖配置。

```dotenv
JIN10_WS_URL=wss://example/ws/user_xxx?token=replace_me
QQ_PUSH_ENABLED=true
QQ_BOT_API_URL=http://127.0.0.1:3000/send_group_msg
QQ_GROUP_ID=replace_me
QQ_ACCESS_TOKEN=
QQ_ACCESS_TOKEN_MODE=none
RAW_LOG_ENABLED=true
AUDIT_LOG_ENABLED=true
NEWS_IMPACT_CLASSIFIER_ENABLED=true
NEWS_IMPACT_CLASSIFIER_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
AI_CHAT_BOT_ENABLED=false
AI_CHAT_HOST=127.0.0.1
AI_CHAT_PORT=8765
MARKET_PROXY_URL=http://127.0.0.1:7890
```

上传 Git 前看一遍：

```text
SENSITIVE_CONFIG.md
```

## Logs

新日志只保留 4 类：

- `logs/raw.jsonl`: 原始 WebSocket 消息。
- `logs/audit.jsonl`: 每条消息的过滤决策。
- `logs/push.jsonl`: QQ 推送成功、失败或 dry-run 记录。
- `logs/errors.jsonl`: 异常和连接错误。

去重 key 持久化在：

- `data/sent_dedupe_keys.txt`

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python probe.py
```

systemd 服务仍使用：

```text
/home/ubuntu/jin10_ws_schema_probe/.venv/bin/python /home/ubuntu/jin10_ws_schema_probe/probe.py
```

## Test QQ

```bash
.venv/bin/python qq_pusher.py --test-api
.venv/bin/python qq_pusher.py --send-test $'金十快讯\n\n【测试消息】推送通道正常。此消息为系统测试，并非真实新闻。'
```

## AI Chat

开启后，NapCat 需把 OneBot HTTP 事件上报到：

```text
http://127.0.0.1:8765/onebot
```

机器人只响应 `QQ_GROUP_ID` 群内 @ 机器人的消息。systemd 服务文件：

```text
deploy/jin10-ai-chat-bot.service
```

## Replay

```bash
.venv/bin/python scripts/replay_optimized_filter.py --logs-dir logs --out logs/replay_report.md
```

脚本兼容旧日志名：`raw_messages.jsonl`、`raw_messages.log`、`pushed_news.log`、`qq_sent.log`。

## Verify

```bash
.venv/bin/python -m py_compile config.py optimized_news_filter.py qq_pusher.py probe.py ai_chat_bot.py scripts/replay_optimized_filter.py
.venv/bin/python scripts/filter_regression_test.py
```

## Git Hygiene

`.gitignore` 已排除 `.env`、`.env.local`、`logs/`、`data/`、`.venv/`、`backups/`、`.trash_*/` 等本地产物。正常上传只需要源代码、`requirements.txt`、`.env.example` 和文档。
