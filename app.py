import os
import time
import threading
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 從環境變數讀取機密資訊（請在 Render 或本地設置環境變數）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
LINE_USER_ID = os.getenv("LINE_USER_ID")

# LINE SDK 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 監控參數
PRICE_CHECK_INTERVAL = 60           # 秒，每分鐘查一次價格
WHALER_CHECK_INTERVAL = 300         # 秒，每五分鐘查一次巨鯨交易
MIN_WHALE_AMOUNT_ETH = 500          # 巨鯨交易門檻：500 ETH
PRICE_ALERT_THRESHOLD = 0.05        # 5% 價格變動通知

last_price = None
notified_tx_ids = set()

def get_eth_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        res = requests.get(url, timeout=10).json()
        return res['ethereum']['usd']
    except Exception as e:
        print("取得 ETH 價格失敗:", e)
        return None

def get_latest_eth_transactions():
    try:
        url = (
            f"https://api.etherscan.io/api"
            f"?module=account&action=txlist"
            f"&address=0x0000000000000000000000000000000000000000"
            f"&startblock=0&endblock=99999999&page=1&offset=20&sort=desc"
            f"&apikey={ETHERSCAN_API_KEY}"
        )
        res = requests.get(url, timeout=10).json()
        if res['status'] != '1':
            return []
        return res['result']
    except Exception as e:
        print("取得巨鯨交易失敗:", e)
        return []

def analyze_whale_tx(tx):
    value_eth = int(tx['value']) / 1e18
    if value_eth < MIN_WHALE_AMOUNT_ETH:
        return None
    exchanges = ['binance', 'coinbase', 'kraken', 'ftx']
    from_addr = tx['from'].lower() if tx['from'] else ''
    to_addr = tx['to'].lower() if tx['to'] else ''
    direction = "無明顯趨勢"
    if any(ex in to_addr for ex in exchanges):
        direction = "空頭 - 巨鯨將 ETH 轉入交易所可能賣出"
    elif any(ex in from_addr for ex in exchanges):
        direction = "多頭 - 巨鯨從交易所轉出可能買入"
    return (value_eth, direction)

def notify_line(message):
    try:
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=message))
        print("已通知 LINE:", message)
    except Exception as e:
        print("通知 LINE 失敗:", e)

def monitor_price():
    global last_price
    while True:
        price = get_eth_price()
        if price:
            if last_price is None:
                last_price = price
                print(f"初始價格設為: ${price:.2f}")
            else:
                change = (price - last_price) / last_price
                if abs(change) >= PRICE_ALERT_THRESHOLD:
                    trend = "暴漲 📈" if change > 0 else "暴跌 📉"
                    msg = f"⚠️ ETH 價格 {trend}！目前價格：${price:.2f}，變動幅度：{change*100:.2f}%"
                    notify_line(msg)
                    last_price = price
                else:
                    print(f"價格變動不足通知門檻，目前價格：${price:.2f}")
        else:
            print("無法取得 ETH 價格")
        time.sleep(PRICE_CHECK_INTERVAL)

def monitor_whales():
    while True:
        txs = get_latest_eth_transactions()
        for tx in txs:
            tx_hash = tx['hash']
            if tx_hash in notified_tx_ids:
                continue
            analysis = analyze_whale_tx(tx)
            if analysis:
                value_eth, direction = analysis
                msg = (
                    f"🐋 巨鯨轉帳通知\n"
                    f"交易量: {value_eth:.2f} ETH\n"
                    f"方向: {direction}\n"
                    f"TxHash: https://etherscan.io/tx/{tx_hash}"
                )
                notify_line(msg)
                notified_tx_ids.add(tx_hash)
        time.sleep(WHALER_CHECK_INTERVAL)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    # 回覆用戶 ID，方便你取得自己的 LINE User ID
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"你的 LINE User ID 是：{user_id}"))

if __name__ == "__main__":
    # 監控執行緒
    threading.Thread(target=monitor_price, daemon=True).start()
    threading.Thread(target=monitor_whales, daemon=True).start()
    # 啟動 Flask Webhook
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
