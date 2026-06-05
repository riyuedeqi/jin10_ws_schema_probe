# Jin10 QQ Bot

金十 WebSocket 快讯筛选与 QQ 群推送机器人。项目会连接金十快讯 WebSocket，过滤低价值、广告、重复或噪声消息，只把更可能影响 BTC、黄金、美元、美债、美股、原油等市场的新闻推送到 QQ 群。

主链路：

```text
Jin10 WebSocket -> probe.py -> optimized_news_filter.py -> news_impact_classifier.py -> qq_pusher.py -> QQ Group
```

项目还包含一个可选的 QQ 群 AI 助手服务。群友 @ 机器人时，`ai_chat_bot.py` 可以调用 DeepSeek 回复；涉及 BTC/ETH 行情的问题会先尝试从 OKX 拉取实时行情上下文。

## Features

- 实时订阅金十 WebSocket 快讯。
- 按关键词、场景和质量规则过滤新闻。
- 对推送新闻生成去重 key，避免重复推送。
- 可选 DeepSeek 新闻影响分类，输出 BTC/黄金短线影响：利多、利空、中性。
- 支持 OneBot/NapCat HTTP API 推送 QQ 群。
- 支持 OneBot 事件 webhook，提供群内 @ 机器人 AI 回复。
- 保留 raw、audit、push、error 日志，方便回放和调试。
- 提供历史日志回放脚本和过滤规则回归测试。

## Project Structure

```text
.
├── probe.py                         # 主进程：连接金十、过滤、推送
├── optimized_news_filter.py          # 新闻过滤、评分、去重、推送文本格式化
├── news_impact_classifier.py         # DeepSeek 新闻影响分类
├── qq_pusher.py                      # OneBot HTTP 推送与测试工具
├── ai_chat_bot.py                    # 可选 QQ 群 AI @ 回复服务
├── config.py                         # 配置读取与路径定义
├── scripts/
│   ├── filter_regression_test.py      # 过滤规则回归测试
│   └── replay_optimized_filter.py     # 历史 raw 日志回放
├── deploy/
│   └── jin10-ai-chat-bot.service      # AI 助手 systemd 服务示例
├── jin10-qq-bot.service               # 主推送服务 systemd 示例
├── .env.example                       # 配置模板
└── SENSITIVE_CONFIG.md                # 敏感配置核对清单
```

## Requirements

- Python 3.10+
- 可用的金十 WebSocket 地址
- OneBot/NapCat HTTP API
- DeepSeek API key，可选但推荐，用于新闻影响分类和 AI 助手

安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuration

复制配置模板：

```bash
cp .env.example .env
```

填写 `.env` 或 `.env.local`。项目会先读取 `.env`，再读取 `.env.local` 覆盖同名配置。

推荐用法：

```text
.env.example  提交到 Git，用作模板
.env          本地/服务器运行配置，不提交
.env.local    本机私有覆盖配置，不提交
```

核心配置：

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
DEEPSEEK_TIMEOUT_SECONDS=0
DEEPSEEK_MAX_TOKENS=120

AI_CHAT_BOT_ENABLED=false
AI_CHAT_HOST=127.0.0.1
AI_CHAT_PORT=8765

MARKET_API_BASE_URL=https://www.okx.com
MARKET_PROXY_URL=http://127.0.0.1:7890
MARKET_TIMEOUT_SECONDS=6
```

`QQ_ACCESS_TOKEN_MODE` 可选值：

- `none`: 不携带 access token。
- `header`: 使用 `Authorization: Bearer <token>`。
- `query`: 将 `access_token` 拼到 URL 查询参数。

## Run

启动主推送机器人：

```bash
.venv/bin/python probe.py
```

启动后，程序会：

1. 创建 `logs/` 和 `data/` 目录。
2. 连接 `JIN10_WS_URL`。
3. 订阅 `flash` 频道。
4. 将原始消息写入 `logs/raw.jsonl`。
5. 使用 `optimized_news_filter.py` 判断是否推送。
6. 可选调用 DeepSeek 追加 BTC/黄金影响判断。
7. 通过 OneBot HTTP API 推送到 QQ 群。

## QQ Push Test

测试 OneBot API 状态：

```bash
.venv/bin/python qq_pusher.py --test-api
```

发送一条测试消息：

```bash
.venv/bin/python qq_pusher.py --send-test $'金十快讯\n\n【测试消息】推送通道正常。此消息为系统测试，并非真实新闻。'
```

## AI Chat Bot

AI 群聊助手是独立服务，不影响主推送链路。

开启配置：

```dotenv
AI_CHAT_BOT_ENABLED=true
AI_CHAT_HOST=127.0.0.1
AI_CHAT_PORT=8765
DEEPSEEK_API_KEY=replace_me
```

NapCat/OneBot 事件上报地址：

```text
http://127.0.0.1:8765/onebot
```

启动服务：

```bash
.venv/bin/python ai_chat_bot.py
```

机器人只响应 `QQ_GROUP_ID` 对应群里的 @ 消息。

## Logs And State

运行时会生成这些本地文件，均不应提交：

```text
logs/raw.jsonl                    # 原始 WebSocket 消息
logs/audit.jsonl                  # 过滤决策记录
logs/push.jsonl                   # 推送成功、失败或 dry-run 记录
logs/errors.jsonl                 # 错误记录
logs/news_impact_classifier.jsonl # 新闻影响分类日志
logs/ai_chat_bot.jsonl            # AI 助手日志
data/sent_dedupe_keys.txt         # 已推送去重 key
data/sent_news_ids.txt            # 已推送新闻 ID
```

## Replay And Test

回放历史 raw 日志，生成过滤报告：

```bash
.venv/bin/python scripts/replay_optimized_filter.py --logs-dir logs --out logs/replay_report.md
```

运行过滤规则回归测试：

```bash
.venv/bin/python scripts/filter_regression_test.py
```

编译检查：

```bash
.venv/bin/python -m py_compile \
  config.py \
  optimized_news_filter.py \
  news_impact_classifier.py \
  qq_pusher.py \
  probe.py \
  ai_chat_bot.py \
  scripts/replay_optimized_filter.py \
  scripts/filter_regression_test.py
```

## systemd

主推送服务示例：

```text
jin10-qq-bot.service
```

AI 助手服务示例：

```text
deploy/jin10-ai-chat-bot.service
```

服务文件默认使用路径：

```text
/home/ubuntu/jin10_ws_schema_probe
```

部署到服务器时，需要根据实际目录调整 `WorkingDirectory` 和 `ExecStart`。

## Security

不要提交真实配置：

- `.env`
- `.env.local`
- `logs/`
- `data/`
- `.venv/`

这些文件已经在 `.gitignore` 中排除。上传前可参考 `SENSITIVE_CONFIG.md` 检查敏感项。

常见敏感配置包括：

- `JIN10_WS_URL`
- `DEEPSEEK_API_KEY`
- `QQ_GROUP_ID`
- `QQ_ACCESS_TOKEN`
- `QQ_BOT_API_URL`
- `MARKET_PROXY_URL`

## GitHub

首次提交：

```bash
git init
git branch -M main
git add .
git commit -m "Initial commit"
```

推送到已有 GitHub 仓库：

```bash
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```
