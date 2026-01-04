import asyncio
import websockets
import json
import logging
from eth_abi import decode
import aiohttp

# 配置日志系统
chinese_time_format = "%Y年%m月%d日%H时%M分%S秒"
log_format = "[%(levelname)s] %(asctime)s [%(name)s]：%(message)s"
logging.basicConfig(
    format=log_format, level=logging.INFO, datefmt=chinese_time_format, force=True
)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Telegram 配置
TELEGRAM_BOT_TOKEN = ""  # 替换为你的 bot token
TELEGRAM_CHAT_ID_TOKEN_CREATE = ""  # TokenCreate 事件的频道 ID
TELEGRAM_CHAT_ID_TOKEN_BONDED = ""  # TokenBONDED 事件的频道 ID


async def send_telegram_message(message, chat_id, parse_mode=None, reply_markup=None):
    """使用 Telegram HTTP API 发送消息"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Telegram 消息发送成功到 {chat_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Telegram 消息发送失败: {response.status} - {error_text}"
                    )
                    return False
    except Exception as e:
        logger.error(f"发送 Telegram 消息异常: {e}")
        return False


def decode_token_create_event(data_hex):
    """解析 TokenCreate 事件数据"""
    try:
        decoded = decode(
            [
                "address",
                "address",
                "uint256",
                "string",
                "string",
                "uint256",
                "uint256",
                "uint256",
            ],
            bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex),
        )
        return {
            "creator": decoded[0],
            "token": decoded[1],
            "requestId": decoded[2],
            "name": decoded[3],
            "symbol": decoded[4],
            "totalSupply": decoded[5],
            "totalSupply_formatted": decoded[5] / 10**18,
            "launchTime": decoded[6],
            "launchFee": decoded[7],
            "launchFee_formatted": decoded[7] / 10**18,
        }
    except Exception as e:
        logger.error(f"解析 TokenCreate 事件失败: {e}")
        return None


def decode_liquidity_added_event(data_hex):
    """解析 LiquidityAdded 事件数据"""
    try:
        decoded = decode(
            [
                "address",
                "uint256",
                "address",
                "uint256",
            ],
            bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex),
        )
        return {
            "base": decoded[0],
            "offers": decoded[1],
            "quote": decoded[2],
            "funds": decoded[3],
        }
    except Exception as e:
        logger.error(f"解析 LiquidityAdded 事件失败: {e}")
        return None


async def get_token_info(ws, token_address):
    """通过WebSocket获取代币信息（名称和符号）"""
    try:
        name_selector = "0x06fdde03"
        symbol_selector = "0x95d89b41"

        # 获取name
        name_payload = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "eth_call",
            "params": [{"to": token_address, "data": name_selector}, "latest"],
        }
        await ws.send(json.dumps(name_payload))
        name_response = await ws.recv()
        name_data = json.loads(name_response)

        # 获取symbol
        symbol_payload = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "eth_call",
            "params": [{"to": token_address, "data": symbol_selector}, "latest"],
        }
        await ws.send(json.dumps(symbol_payload))
        symbol_response = await ws.recv()
        symbol_data = json.loads(symbol_response)

        # 解析结果
        name = ""
        symbol = ""

        if (
            "result" in name_data
            and name_data["result"]
            and name_data["result"] != "0x"
        ):
            result = name_data["result"].replace("0x", "")
            if len(result) >= 128:
                length = int(result[64:128], 16)
                name_hex = result[128 : 128 + length * 2]
                name = bytes.fromhex(name_hex).decode("utf-8", errors="ignore")

        if (
            "result" in symbol_data
            and symbol_data["result"]
            and symbol_data["result"] != "0x"
        ):
            result = symbol_data["result"].replace("0x", "")
            if len(result) >= 128:
                length = int(result[64:128], 16)
                symbol_hex = result[128 : 128 + length * 2]
                symbol = bytes.fromhex(symbol_hex).decode("utf-8", errors="ignore")

        return name, symbol

    except Exception as e:
        logger.warning(f"获取代币信息失败: {e}")
        return "", ""


async def get_token_market_info(token_address):
    """通过币安API获取代币市场信息"""
    try:
        url = "https://web3.binance.com/bapi/defi/v4/public/wallet-direct/buw/wallet/market/token/dynamic/info"
        params = {"chainId": "56", "contractAddress": token_address}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("success") and result.get("data"):
                        data = result["data"]
                        return {
                            "marketCap": float(data.get("marketCap", 0)),
                            "devHolders": data.get("devHolders", 0),
                            "devHoldingPercent": data.get("holdersDevPercent", "0"),
                            "holders": data.get("holders", "0"),
                            "top10HoldersPercentage": data.get(
                                "top10HoldersPercentage", "0"
                            ),
                        }
                return None
    except Exception as e:
        logger.warning(f"获取市场信息异常: {e}")
        return None


async def subscribe_bsc_events():
    """
    连接到 BSC 主网 WebSocket，订阅指定合约的两个事件
    """
    ws_url = ""
    contract = "0x5c952063c7fc8610FFDB798152D69F0B9550762b"
    token_create_topic = (
        "0x396d5e902b675b032348d3d2e9517ee8f0c4a926603fbc075d3d282ff00cad20"
    )
    liquidity_added_topic = (
        "0xc18aa71171b358b706fe3dd345299685ba21a5316c66ffa9e319268b033c44b0"
    )

    # 订阅 TokenCreate 事件
    subscribe_token_create = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": ["logs", {"address": contract, "topics": [token_create_topic]}],
    }

    # 订阅 LiquidityAdded 事件
    subscribe_liquidity_added = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "eth_subscribe",
        "params": ["logs", {"address": contract, "topics": [liquidity_added_topic]}],
    }

    retry_delay = 5  # 重连延迟秒数

    while True:
        try:
            async with websockets.connect(
                ws_url, ping_interval=20, ping_timeout=10, close_timeout=10
            ) as ws:
                logger.info(f"已连接到 BSC 主网")

                # 发送订阅请求
                await ws.send(json.dumps(subscribe_token_create))
                logger.info(f"已订阅合约 {contract} 的 TokenCreate 事件")

                await ws.send(json.dumps(subscribe_liquidity_added))
                logger.info(f"已订阅合约 {contract} 的 LiquidityAdded 事件")

                # 持续接收事件
                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if "params" in data and "result" in data["params"]:
                        event_result = data["params"]["result"]

                        # 打印事件信息
                        topics = event_result.get("topics", [])
                        event_data = event_result.get("data", "")

                        # 判断事件类型并解析
                        if topics and topics[0] == token_create_topic:
                            logger.info(f"收到 TokenCreate 事件")
                            parsed = decode_token_create_event(event_data)
                            if parsed:
                                logger.info(
                                    f"代币名称: {parsed['name']} | 代币符号: {parsed['symbol']} | 代币地址: {parsed['token']}"
                                )

                                # 发送 Telegram 通知到 TokenCreate 频道
                                if TELEGRAM_CHAT_ID_TOKEN_CREATE:
                                    token_addr = parsed["token"]
                                    token_name = parsed["name"]
                                    token_symbol = parsed["symbol"]
                                    creator_addr = parsed["creator"]

                                    msg = f"🆕 新代币创建\n\n"
                                    msg += f"💰 代币名称: {token_name}(💛BSC)\n"
                                    msg += f"🔣 代币符号: {token_symbol}\n\n"
                                    msg += f"[Avebot链接]({f'https://pro.ave.ai/token/{token_addr}-bsc?lang=zh-cn&code=pikacyan'}) | "
                                    msg += f"[Axiom链接]({f'https://axiom.trade/t/{token_addr}?chain=bnb'}) | "
                                    msg += f"[Binance Web3]({f'https://web3.binance.com/zh-CN/token/bsc/{token_addr}?ref=ER50PYNM'}) | "
                                    msg += f"[GMGN链接]({f'https://gmgn.ai/bsc/token/CHENGZI_{token_addr}'}) | "
                                    msg += f"[OKX Web3]({f'https://web3.okx.com/zh-hans/token/bsc/{token_addr}'})\n\n"
                                    msg += f"📋 合约地址: `{token_addr}`\n\n"
                                    msg += f"✨ Powered by [PikacyanWeb3](https://x.com/pikacyanweb3)"
                                    buttons = {
                                        "inline_keyboard": [
                                            [
                                                {
                                                    "text": "🐦 Search CA on X",
                                                    "url": f"https://x.com/search?q={token_addr}",
                                                },
                                                {
                                                    "text": "🐦 Search Creator on X",
                                                    "url": f"https://x.com/search?q={creator_addr}",
                                                },
                                            ],
                                            [
                                                {
                                                    "text": "Avebot 立即购买",
                                                    "url": f"https://t.me/AveSniperBot_01_bot?start={token_addr}-pikacyan",
                                                },
                                                {
                                                    "text": "Bloom 立即购买",
                                                    "url": f"https://t.me/BloomEVMbot?start=ref_pikacyan_ca_{token_addr}",
                                                },
                                            ],
                                        ]
                                    }
                                    await send_telegram_message(
                                        msg,
                                        TELEGRAM_CHAT_ID_TOKEN_CREATE,
                                        parse_mode="Markdown",
                                        reply_markup=buttons,
                                    )

                        elif topics and topics[0] == liquidity_added_topic:
                            logger.info(f"收到 LiquidityAdded 事件")
                            logger.info(f"{event_data}")
                            logger.info(f"{topics}")
                            parsed = decode_liquidity_added_event(event_data)
                            if parsed:
                                logger.info(f"{parsed}")

                                # 发送 Telegram 通知到 LiquidityAdded 频道
                                if TELEGRAM_CHAT_ID_TOKEN_BONDED:
                                    base_addr = parsed["base"]
                                    quote_addr = parsed["quote"]

                                    # 通过 RPC 获取代币名称和符号
                                    base_name, base_symbol = await get_token_info(
                                        ws, base_addr
                                    )
                                    logger.info(
                                        f"Base代币信息: {base_name} ({base_symbol})"
                                    )

                                    # 获取市场信息
                                    market_info = await get_token_market_info(base_addr)
                                    if market_info:
                                        logger.info(
                                            f"市值: ${market_info['marketCap']:,.2f} | "
                                            f"持有者: {market_info['holders']} | "
                                            f"Dev持仓: {market_info['devHoldingPercent']}% ({market_info['devHolders']}个)"
                                        )

                                    # 构造交易平台链接
                                    platform_links = (
                                        f"[Avebot]({f'https://pro.ave.ai/token/{base_addr}-bsc?lang=zh-cn&code=pikacyan'}) | "
                                        f"[Axiom]({f'https://axiom.trade/meme/{base_addr}?chain=bnb'}) | "
                                        f"[Binance]({f'https://web3.binance.com/zh-CN/token/bsc/{base_addr}?ref=ER50PYNM'}) | "
                                        f"[GMGN]({f'https://gmgn.ai/bsc/token/CHENGZI_{base_addr}'}) | "
                                        f"[OKX]({f'https://web3.okx.com/zh-hans/token/bnbchain/{base_addr}'})"
                                    )

                                    # 构建消息，包含市场信息
                                    market_cap_formatted = ""
                                    top10_percent = "0"
                                    if market_info:
                                        mc = market_info["marketCap"]
                                        if mc >= 1000000:
                                            market_cap_formatted = f"{mc/1000000:.1f}M USD ({mc/10000:.1f}万)"
                                        elif mc >= 1000:
                                            market_cap_formatted = (
                                                f"{mc/1000:.1f}K USD ({mc/10000:.1f}万)"
                                            )
                                        else:
                                            market_cap_formatted = f"{mc:.1f} USD"
                                        top10_raw = market_info.get(
                                            "top10HoldersPercentage", "0"
                                        )
                                        top10_percent = (
                                            f"{float(top10_raw):.2f}"
                                            if top10_raw
                                            else "0"
                                        )

                                    msg = f"🚀🚀🚀 代币已迁移\n\n"
                                    msg += (
                                        f"💰 代币名称: {base_name or '未知'}(💛BSC)\n"
                                    )
                                    msg += f"🔣 代币符号: {base_symbol or '?'}\n\n"

                                    if market_info:
                                        msg += (
                                            f"🚀 当前市值: **{market_cap_formatted}**\n"
                                        )
                                        msg += f"👥 持币人数: **{market_info['holders']}** | Top10持仓: **{top10_percent}%**\n\n"

                                    msg += f"[Avebot链接]({f'https://pro.ave.ai/token/{base_addr}-bsc?lang=zh-cn&code=pikacyan'}) | "
                                    msg += f"[Axiom链接]({f'https://axiom.trade/t/{base_addr}?chain=bnb'}) | "
                                    msg += f"[Binance Web3]({f'https://web3.binance.com/zh-CN/token/bsc/{base_addr}?ref=ER50PYNM'}) | "
                                    msg += f"[GMGN链接]({f'https://gmgn.ai/bsc/token/CHENGZI_{base_addr}'}) | "
                                    msg += f"[OKX Web3]({f'https://web3.okx.com/zh-hans/token/bsc/{base_addr}'})\n\n"
                                    msg += f"📋 合约地址: `{base_addr}`\n\n"
                                    msg += f"✨ Powered by [PikacyanWeb3](https://x.com/pikacyanweb3)"
                                    buttons = {
                                        "inline_keyboard": [
                                            [
                                                {
                                                    "text": "🐦 Search CA on X",
                                                    "url": f"https://x.com/search?q={base_addr}",
                                                },
                                            ],
                                            [
                                                {
                                                    "text": "Avebot 立即购买",
                                                    "url": f"https://t.me/AveSniperBot_01_bot?start={base_addr}-pikacyan",
                                                },
                                                {
                                                    "text": "Bloom 立即购买",
                                                    "url": f"https://t.me/BloomEVMbot?start=ref_pikacyan_ca_{base_addr}",
                                                },
                                            ],
                                        ]
                                    }
                                    await send_telegram_message(
                                        msg,
                                        TELEGRAM_CHAT_ID_TOKEN_BONDED,
                                        parse_mode="Markdown",
                                        reply_markup=buttons,
                                    )
                    else:
                        logger.debug(f"收到消息: {data}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"连接已关闭: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"连接错误: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)


if __name__ == "__main__":
    # 订阅事件
    asyncio.run(subscribe_bsc_events())
