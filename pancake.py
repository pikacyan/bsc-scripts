import asyncio
import websockets
import json
import logging
import aiohttp
import os

# 配置日志系统
chinese_time_format = "%Y年%m月%d日%H时%M分%S秒"
log_format = "[%(levelname)s] %(asctime)s [%(name)s]：%(message)s"
logging.basicConfig(
    format=log_format, level=logging.INFO, datefmt=chinese_time_format, force=True
)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Telegram配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
blacklist = [
    "0xBB4CDB9CBD36B01BD1CBAEBF2DE08D9173BC095C",  # wbnb
    "0x000ae314e2a2172a039b26378814c252734f556a",  # aster
    "0x55d398326f99059ff775485246999027b3197955",  # usdt
    "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d",  # usd1
    "0xce24439f2d9c6a2289f741120fe202248b666666",  # u
    "0x0782b6d8c4551b9760e74c0545a9bcd90bdc41e5",  # lisusd
]
# 自动将所有黑名单地址转换为大写，实现不区分大小写的匹配
blacklist = [addr.upper() for addr in blacklist]


def parse_pair_created_event(topics, data):
    """
    解析 PairCreated 事件
    Event: PairCreated(address indexed token0, address indexed token1, address pair, uint256)
    - topics[0]: event signature (topic0)
    - topics[1]: token0 address (indexed)
    - topics[2]: token1 address (indexed)
    - data: pair address + pair index (non-indexed)
    """
    try:
        # 解析indexed参数（在topics中）
        token0 = "0x" + topics[1][-40:]  # 取后40个字符（20字节地址）
        token1 = "0x" + topics[2][-40:]

        # 解析non-indexed参数（在data中）
        data = data.replace("0x", "")

        # pair地址（前32字节）
        pair = "0x" + data[24:64]  # 跳过前24个0，取20字节地址

        # pair索引（后32字节）
        pair_index = int(data[64:128], 16)

        return {
            "token0": token0,
            "token1": token1,
            "pair": pair,
            "pairIndex": pair_index,
        }

    except Exception as e:
        logger.error(f"事件解析失败: {e}")
        return None


async def send_telegram_message(text, contract_address=None, chat_id=None):
    """发送Telegram消息"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }

        if contract_address:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Avebot 立即购买",
                            "url": f"https://t.me/AveSniperBot_01_bot?start={contract_address}-pikacyan",
                        },
                        {
                            "text": "Bloom 立即购买",
                            "url": f"https://t.me/BloomEVMbot?start=ref_AJ3IYD6EXI_ca_{contract_address}",
                        },
                        {
                            "text": "GMGN 立即购买",
                            "url": f"https://t.me/gmgn_bsc_bot?start=i_lZKIXD4b_c_{contract_address}",
                        },
                    ]
                ]
            }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    pass
    except Exception as e:
        logger.warning(f"Telegram发送失败: {e}")


async def get_token_info(ws, token_address):
    """通过WebSocket获取代币信息（名称和符号）"""
    try:
        # ERC20的name()和symbol()函数选择器
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
            # 跳过前64字符（偏移量），然后读取长度
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


async def get_token_market_cap(token_address):
    """通过币安API获取代币市值"""
    try:
        url = f"https://web3.binance.com/bapi/defi/v4/public/wallet-direct/buw/wallet/market/token/dynamic/info"
        params = {"chainId": "56", "contractAddress": token_address}  # BSC链ID

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("success") and result.get("data"):
                        market_cap = result["data"].get("marketCap")
                        if market_cap:
                            # 将字符串转换为浮点数
                            return float(market_cap)
                logger.warning(
                    f"获取市值失败，token: {token_address}, 状态码: {resp.status}"
                )
                return 0
    except Exception as e:
        logger.warning(f"获取市值异常: {e}, token: {token_address}")
        return 0


async def get_token_metadata(token_address):
    """通过币安API获取代币元数据，返回(name, symbol)或("", "")"""
    try:
        url = f"https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/dex/market/token/meta/info"
        params = {"chainId": "56", "contractAddress": token_address}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("success") and result.get("data"):
                        data = result["data"]
                        return data.get("name", ""), data.get("symbol", "")
                return "", ""
    except Exception as e:
        return "", ""


async def subscribe_pancakeswap_pair_created():
    """
    连接到 BSC 主网 WebSocket，订阅 PancakeSwap Factory 的 PairCreated 事件
    """
    ws_url = ""
    contract = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"  # PancakeSwap Factory
    topic = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"  # PairCreated

    subscribe_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": ["logs", {"address": contract, "topics": [topic]}],
    }

    retry_delay = 5  # 重连延迟秒数

    while True:
        try:
            async with websockets.connect(
                ws_url, ping_interval=20, ping_timeout=10, close_timeout=10
            ) as ws:
                logger.info(f"已连接到 BSC 主网")

                # 发送订阅请求
                await ws.send(json.dumps(subscribe_payload))
                logger.info(
                    f"已订阅 PancakeSwap Factory 合约 {contract} 的 PairCreated 事件"
                )

                # 持续接收事件
                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if "params" in data and "result" in data["params"]:
                        event_result = data["params"]["result"]
                        logger.info(f"🎉 收到新的 PairCreated 事件")

                        # 解析事件数据
                        topics = event_result.get("topics", [])
                        event_data = event_result.get("data", "")

                        if len(topics) >= 3:
                            event_info = parse_pair_created_event(topics, event_data)
                            if event_info:
                                logger.info(
                                    f"[交易对创建] Token0: {event_info['token0']} | Token1: {event_info['token1']} | Pair: {event_info['pair']} | Index: {event_info['pairIndex']}"
                                )

                                # 检查黑名单（不区分大小写）
                                token0_upper = event_info["token0"].upper()
                                token1_upper = event_info["token1"].upper()

                                if (
                                    token0_upper in blacklist
                                    or token1_upper in blacklist
                                ):
                                    logger.info(
                                        f"Token0或Token1在黑名单中，跳过: {event_info['token0']} / {event_info['token1']}"
                                    )
                                    continue

                                # 检查市值
                                token0_market_cap = await get_token_market_cap(
                                    event_info["token0"]
                                )
                                token1_market_cap = await get_token_market_cap(
                                    event_info["token1"]
                                )

                                logger.info(f"Token0市值: ${token0_market_cap:,.2f}")
                                logger.info(f"Token1市值: ${token1_market_cap:,.2f}")

                                # 如果两个token的市值都小于1M，则跳过
                                MIN_MARKET_CAP = 1_000_000  # 1M
                                if (
                                    token0_market_cap < MIN_MARKET_CAP
                                    and token1_market_cap < MIN_MARKET_CAP
                                ):
                                    logger.info(
                                        f"两个token市值都小于1M，跳过: Token0=${token0_market_cap:,.2f}, Token1=${token1_market_cap:,.2f}"
                                    )
                                    continue

                                # 获取代币信息，优先用API，失败则用区块链
                                token0_name, token0_symbol = await get_token_metadata(
                                    event_info["token0"]
                                ) or await get_token_info(ws, event_info["token0"])
                                token1_name, token1_symbol = await get_token_metadata(
                                    event_info["token1"]
                                ) or await get_token_info(ws, event_info["token1"])

                                logger.info(
                                    f"Token0信息: {token0_name} ({token0_symbol})"
                                )
                                logger.info(
                                    f"Token1信息: {token1_name} ({token1_symbol})"
                                )

                                # 选择市值较小的token作为合约地址
                                if token0_market_cap <= token1_market_cap:
                                    contract_address = event_info["token0"]
                                    contract_name = token0_name or "Unknown"
                                    contract_symbol = token0_symbol or "?"
                                    paired_token_address = event_info["token1"]
                                    paired_token_name = token1_name or "Unknown"
                                    paired_token_symbol = token1_symbol or "?"
                                    contract_market_cap = token0_market_cap
                                    paired_market_cap = token1_market_cap
                                else:
                                    contract_address = event_info["token1"]
                                    contract_name = token1_name or "Unknown"
                                    contract_symbol = token1_symbol or "?"
                                    paired_token_address = event_info["token0"]
                                    paired_token_name = token0_name or "Unknown"
                                    paired_token_symbol = token0_symbol or "?"
                                    contract_market_cap = token1_market_cap
                                    paired_market_cap = token0_market_cap

                                logger.info(
                                    f"选择市值较小的Token作为合约地址: {contract_address} (市值: ${contract_market_cap:,.2f})"
                                )

                                # 检查token的name或symbol是否以dog结尾
                                if not (
                                    contract_name.lower().endswith("dog")
                                    or contract_symbol.lower().endswith("dog")
                                ):
                                    logger.info(
                                        f"Token的name或symbol不以dog结尾，跳过: {contract_address}"
                                    )
                                    continue

                                # 获取交易哈希
                                tx_hash = event_result.get("transactionHash", "")

                                # 构建交易平台链接 - 参考 simple.py 的格式
                                # 检查是否需要添加 Axiom 链接
                                axiom_link = ""
                                if contract_address.lower().startswith(
                                    "0x4444"
                                ) or contract_address.lower().endswith("4444"):
                                    axiom_link = f"[Axiom链接](https://axiom.trade/meme/{contract_address}?chain=bnb) | "

                                # 构建完整的链接字符串
                                platform_links = (
                                    f"[Avebot链接](https://pro.ave.ai/token/{contract_address}-bsc?lang=zh-cn&code=pikacyan) | "
                                    f"{axiom_link}"
                                    f"[Binance Web3](https://web3.binance.com/zh-CN/token/bsc/{contract_address}?ref=ER50PYNM) | "
                                    f"[GMGN链接](https://gmgn.ai/bsc/token/CHENGZI_{contract_address}) | "
                                    f"[OKX Web3](https://web3.okx.com/zh-hans/token/bsc/{contract_address})"
                                )

                                # 构建Telegram消息 - 格式类似app.py
                                msg = (
                                    f"🥞 *PancakeSwap新交易对创建*\n\n"
                                    f"📛 *代币名称:* {contract_name}\n"
                                    f"🔤 *代币符号:* {contract_symbol}\n"
                                    f"📍 *代币地址:* `{contract_address}`\n\n"
                                    f"💰 *市值:* ${contract_market_cap:,.2f}\n"
                                    f"🔗 *交易对:* {paired_token_name} ({paired_token_symbol})\n"
                                    f"📍 *配对地址:* `{paired_token_address}`\n"
                                    f"💰 *配对市值:* ${paired_market_cap:,.2f}\n\n"
                                    f"🔗 *交易对地址:* `{event_info['pair']}`\n"
                                    f"🔗 *交易哈希:* [{tx_hash}](https://bscscan.com/tx/{tx_hash})\n\n"
                                    f"🔗 *交易平台:*\n"
                                    f"{platform_links}"
                                )

                                await send_telegram_message(msg, contract_address)
                        else:
                            logger.warning(f"topics数量不足: {len(topics)}")
                    else:
                        logger.debug(f"收到消息: {data}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"连接已关闭: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"连接错误: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)


if __name__ == "__main__":
    # 订阅 PancakeSwap PairCreated 事件
    asyncio.run(subscribe_pancakeswap_pair_created())
