# BSC 链上事件监控脚本集合

本仓库包含三个用于监控 BSC (Binance Smart Chain) 链上事件的 Python 脚本，通过 WebSocket 实时订阅智能合约事件，并将关键信息推送至 Telegram。

## 📋 脚本概览

### 1. flap.py - 慈善代币监控
**功能：** 监控特定合约的 `TokenCreated` 事件，专注于识别慈善代币（受益人与创建者不同的代币）。

**主要特性：**
- 实时监控代币创建事件
- 自动解析代币名称、符号、创建者等信息
- 解码交易 input 数据，获取税率、受益人等详细信息
- 过滤掉地址以 `8888` 结尾的代币
- 仅推送受益人与创建者不同的慈善代币
- 提供 Avebot、Bloom、GMGN 等交易平台快捷链接

**配置方法：**
```bash
# 设置环境变量
export TELEGRAM_BOT_TOKEN="你的Telegram Bot Token"
export TELEGRAM_CHAT_ID="你的Telegram频道ID"

# 运行脚本
python flap.py

# 或使用 Docker
docker build -f Dockerfile.flap -t flap-monitor .
docker run -e TELEGRAM_BOT_TOKEN="xxx" -e TELEGRAM_CHAT_ID="xxx" flap-monitor
```

---

### 2. four.py - 代币创建与流动性监控
**功能：** 同时监控 `TokenCreate` 和 `LiquidityAdded` 两个事件，追踪代币从创建到添加流动性的完整生命周期。

**主要特性：**
- 双事件监控：代币创建 + 流动性添加
- 获取代币市值、持有者数量、Top10 持仓占比等市场数据
- 支持分别推送到不同的 Telegram 频道
- 提供多平台交易链接（Avebot、Axiom、Binance Web3、GMGN、OKX）
- 自动格式化市值显示（M/K/万）

**配置方法：**
```python
# 在脚本中直接修改以下配置
TELEGRAM_BOT_TOKEN = "你的Telegram Bot Token"
TELEGRAM_CHAT_ID_TOKEN_CREATE = "代币创建事件的频道ID"
TELEGRAM_CHAT_ID_TOKEN_BONDED = "流动性添加事件的频道ID"

# 运行脚本
python four.py

# 或使用 Docker
docker build -f Dockerfile.four -t four-monitor .
docker run four-monitor
```

---

### 3. pancake.py - PancakeSwap 交易对监控
**功能：** 监控 PancakeSwap Factory 合约的 `PairCreated` 事件，发现新创建的交易对。

**主要特性：**
- 实时监控 PancakeSwap 新交易对创建
- 智能过滤：
  - 黑名单过滤（WBNB、USDT 等常见代币）
  - 市值过滤（两个代币市值均小于 1M 则跳过）
  - 关键词过滤（仅推送名称或符号以 "dog" 结尾的代币）
- 自动选择市值较小的代币作为主推代币
- 获取代币元数据和市场信息
- 条件性添加 Axiom 链接（地址以 `0x4444` 开头或 `4444` 结尾）

**配置方法：**
```bash
# 设置环境变量
export TELEGRAM_BOT_TOKEN="你的Telegram Bot Token"
export TELEGRAM_CHAT_ID="你的Telegram频道ID"

# 可选：修改黑名单（在脚本第20-29行）
blacklist = [
    "0xBB4CDB9CBD36B01BD1CBAEBF2DE08D9173BC095C",  # wbnb
    "0x55d398326f99059ff775485246999027b3197955",  # usdt
    # 添加更多地址...
]

# 运行脚本
python pancake.py

# 或使用 Docker
docker build -f Dockerfile.pancake -t pancake-monitor .
docker run -e TELEGRAM_BOT_TOKEN="xxx" -e TELEGRAM_CHAT_ID="xxx" pancake-monitor
```

---

## 🚀 快速开始

### 环境要求
- Python 3.11+
- 依赖包：见 `requirements.txt`

### 安装依赖
```bash
pip install -r requirements.txt
```

### 依赖说明
```
websockets==12.0  # WebSocket 客户端
eth-abi==5.0.0    # 以太坊 ABI 编解码
aiohttp           # 异步 HTTP 客户端
```

---

## 🔧 通用配置

### Telegram Bot 设置
1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建新 Bot
3. 获取 Bot Token
4. 将 Bot 添加到目标频道并设为管理员
5. 获取频道 ID（可使用 [@userinfobot](https://t.me/userinfobot)）

### WebSocket RPC 节点
所有脚本需要配置 BSC WebSocket RPC 节点 URL（在脚本中搜索 `ws_url` 变量）：
```python
ws_url = "wss://你的BSC节点地址"
```

推荐节点提供商：
- [QuickNode](https://www.quicknode.com/)
- [Ankr](https://www.ankr.com/)
- [Infura](https://infura.io/)

---

## 📊 功能对比

| 功能 | flap.py | four.py | pancake.py |
|------|---------|---------|------------|
| 监控事件 | TokenCreated | TokenCreate + LiquidityAdded | PairCreated |
| 市值查询 | ❌ | ✅ | ✅ |
| 黑名单过滤 | ❌ | ❌ | ✅ |
| 关键词过滤 | ✅ (慈善代币) | ❌ | ✅ (dog结尾) |
| 多频道推送 | ❌ | ✅ | ❌ |
| 交易 input 解码 | ✅ | ❌ | ❌ |

---

## 🐳 Docker 部署

每个脚本都提供了独立的 Dockerfile，支持容器化部署：

```bash
# 构建镜像
docker build -f Dockerfile.flap -t flap-monitor .
docker build -f Dockerfile.four -t four-monitor .
docker build -f Dockerfile.pancake -t pancake-monitor .

# 运行容器
docker run -d --name flap \
  -e TELEGRAM_BOT_TOKEN="xxx" \
  -e TELEGRAM_CHAT_ID="xxx" \
  --restart unless-stopped \
  flap-monitor
```

---

## 📝 日志说明

所有脚本使用统一的日志格式：
```
[日志级别] 年月日时分秒 [模块名]：日志消息
```

日志级别：
- `INFO`：正常运行信息
- `WARNING`：警告信息（如 API 调用失败）
- `ERROR`：错误信息（如解析失败）

---

## 🔄 自动重连

所有脚本内置自动重连机制：
- WebSocket 连接断开后自动重连
- 默认重连延迟：5 秒
- 无限重试，确保服务持续运行

---

## ⚠️ 注意事项

1. **API 限制**：币安 Web3 API 可能有速率限制，建议添加适当的延迟
2. **WebSocket 稳定性**：建议使用付费 RPC 节点以获得更好的稳定性
3. **Telegram 限制**：避免短时间内发送大量消息，可能触发限流
4. **安全性**：不要将 Bot Token 和敏感信息提交到公开仓库

---

## 📄 许可证

本项目仅供学习和研究使用。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
