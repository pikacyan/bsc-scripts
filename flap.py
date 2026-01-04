import asyncio
import websockets
import json
from eth_abi import decode
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


def parse_event_data(data):
    """
    解析 TokenCreated 事件数据
    参数: (uint256 ts, address creator, uint256 nonce, address token, string name, string symbol, string meta)
    """
    try:
        data = data.replace("0x", "")

        # 每个参数占 64 个字符（32 字节）
        ts = int(data[0:64], 16)
        creator = "0x" + data[64:128][-40:]
        nonce = int(data[128:192], 16)
        token = "0x" + data[192:256][-40:]

        # 动态类型偏移量
        name_offset = int(data[256:320], 16)
        symbol_offset = int(data[320:384], 16)
        meta_offset = int(data[384:448], 16)

        # 解析字符串
        name_len = int(data[name_offset * 2 : name_offset * 2 + 64], 16)
        name = bytes.fromhex(
            data[name_offset * 2 + 64 : name_offset * 2 + 64 + name_len * 2]
        ).decode("utf-8")

        symbol_len = int(data[symbol_offset * 2 : symbol_offset * 2 + 64], 16)
        symbol = bytes.fromhex(
            data[symbol_offset * 2 + 64 : symbol_offset * 2 + 64 + symbol_len * 2]
        ).decode("utf-8")

        meta_len = int(data[meta_offset * 2 : meta_offset * 2 + 64], 16)
        meta = bytes.fromhex(
            data[meta_offset * 2 + 64 : meta_offset * 2 + 64 + meta_len * 2]
        ).decode("utf-8")

        return {
            "timestamp": ts,
            "creator": creator,
            "nonce": nonce,
            "token": token,
            "name": name,
            "symbol": symbol,
            "meta": meta,
        }

    except Exception as e:
        logger.error(f"事件解析失败: {e}")
        return None


def decode_input_data(input_data):
    """
    解码交易input数据
    参数结构: (string name, string symbol, string meta, uint8 dexThresh, bytes32 salt,
               uint16 taxRate, uint8 migratorType, address quoteToken, uint256 quoteAmt,
               address beneficiary, bytes permitData)
    """
    try:
        # 去掉函数选择器(前4字节，即0x开头的10个字符)
        data = input_data[10:] if input_data.startswith("0x") else input_data[8:]

        # 使用tuple类型包装所有参数
        types = [
            "(string,string,string,uint8,bytes32,uint16,uint8,address,uint256,address,bytes)"
        ]

        # 解码
        decoded = decode(types, bytes.fromhex(data))[0]

        return {
            "name": decoded[0],
            "symbol": decoded[1],
            "meta": decoded[2],
            "dexThresh": decoded[3],
            "salt": "0x" + decoded[4].hex(),
            "taxRate": decoded[5],
            "migratorType": decoded[6],
            "quoteToken": decoded[7],
            "quoteAmt": decoded[8],
            "beneficiary": decoded[9],
            "permitData": "0x" + decoded[10].hex(),
        }

    except Exception as e:
        logger.error(f"解码失败: {e}")
        return None


async def send_telegram_message(text, token_address=None, chat_id=None):
    """发送Telegram消息"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        if token_address:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Avebot 立即购买",
                            "url": f"https://t.me/AveSniperBot_01_bot?start={token_address}-pikacyan",
                        },
                        {
                            "text": "Bloom 立即购买",
                            "url": f"https://t.me/BloomEVMbot?start=ref_AJ3IYD6EXI_ca_{token_address}",
                        },
                        {
                            "text": "GMGN 立即购买",
                            "url": f"https://t.me/gmgn_bsc_bot?start=i_lZKIXD4b_c_{token_address}",
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


async def get_transaction_input(ws, tx_hash):
    """通过WebSocket获取交易的input数据"""
    request_id = 2
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "eth_getTransactionByHash",
        "params": [tx_hash],
    }
    await ws.send(json.dumps(payload))

    # 等待响应
    response = await ws.recv()
    data = json.loads(response)

    if "result" in data and data["result"]:
        return data["result"].get("input")
    return None


async def subscribe_bsc_event():
    """
    连接到 BSC 主网 WebSocket，订阅指定合约的事件，并解码交易input
    """
    ws_url = ""
    contract = "0xe2cE6ab80874Fa9Fa2aAE65D277Dd6B8e65C9De0"
    topic = "0x504e7f360b2e5fe33cbaaae4c593bc55305328341bf79009e43e0e3b7f699603"

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
                logger.info(f"已订阅合约 {contract}")

                # 持续接收事件
                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if "params" in data and "result" in data["params"]:
                        event_result = data["params"]["result"]
                        logger.info(f"收到新事件")

                        # 解析事件日志数据
                        event_data = event_result.get("data")
                        event_info = None
                        if event_data:
                            event_info = parse_event_data(event_data)
                            if event_info:
                                logger.info(
                                    f"[事件数据] 代币名称: {event_info['name']} 代币符号: ({event_info['symbol']}) 代币地址: {event_info['token']} 创建者: {event_info['creator']}"
                                )

                                # 如果token地址以8888结尾，跳过获取交易详情
                                if event_info["token"].endswith("8888"):
                                    logger.info(f"代币地址以8888结尾，跳过获取交易详情")
                                    continue

                        # 获取交易哈希并解码input
                        tx_hash = event_result.get("transactionHash")
                        if tx_hash:
                            logger.info(f"正在获取交易 {tx_hash} 的input数据...")
                            input_data = await get_transaction_input(ws, tx_hash)
                            if input_data:
                                input_info = decode_input_data(input_data)
                                if input_info:
                                    logger.info(
                                        f"[交易数据] 代币名称: {input_info['name']} 代币符号: ({input_info['symbol']}) 税率: {input_info['taxRate']} 受益人: {input_info['beneficiary']}"
                                    )

                                    # 检查受益人和创建者是否相同
                                    if (
                                        input_info["beneficiary"].lower()
                                        == event_info["creator"].lower()
                                    ):
                                        logger.info(f"受益人与创建者相同，跳过发送消息")
                                    else:
                                        msg = (
                                            f"🔔 *新慈善代币创建*\n\n"
                                            f"📛 *代币名称:* {input_info['name']}\n"
                                            f"🔤 *代币符号:* {input_info['symbol']}\n"
                                            f"📍 *代币地址:* `{event_info['token']}`\n\n"
                                            f"👤 *创建者:* `{event_info['creator']}`\n"
                                            f"💰 *税率:* {input_info['taxRate'] / 100:.2f}% + 1%\n"
                                            f"💸 *受益人:* `{input_info['beneficiary']}` [Search on X🔎](https://x.com/search?q={input_info['beneficiary']}) | [Search on GitHub🔎](https://github.com/search?q={input_info['beneficiary']}&type=code)\n\n"
                                            f"🔗 *交易哈希:* [{tx_hash}](https://bscscan.com/tx/{tx_hash})\n\n"
                                            f"🔗 *交易平台:*\n"
                                            f"[Avebot链接](https://pro.ave.ai/token/{event_info['token']}-bsc) | "
                                            f"[GMGN链接](https://gmgn.ai/bsc/token/{event_info['token']}) | "
                                            f"[OKX Web3](https://web3.okx.com/zh-hans/token/bsc/{event_info['token']})"
                                        )
                                        await send_telegram_message(
                                            msg, event_info["token"]
                                        )
                            else:
                                logger.warning(f"无法获取交易input数据")
                    else:
                        logger.debug(f"收到消息: {data}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"连接已关闭: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"连接错误: {e}，{retry_delay}秒后重连...")
            await asyncio.sleep(retry_delay)


if __name__ == "__main__":
    # 订阅事件并自动解码
    asyncio.run(subscribe_bsc_event())
