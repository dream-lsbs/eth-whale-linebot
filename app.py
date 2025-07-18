import tkinter as tk
import requests
import threading
import time
import os

# 你可以修改的通知價格
UPPER_LIMIT = 3800
LOWER_LIMIT = 3300

def get_eth_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        response = requests.get(url)
        data = response.json()
        return data["ethereum"]["usd"]
    except:
        return None

def send_mac_notification(title, message):
    os.system(f'''osascript -e 'display notification "{message}" with title "{title}"' ''')

class ETHTracker:
    def __init__(self, root):
        self.root = root
        self.root.title("以太幣價格追蹤器")
        self.root.geometry("300x120")
        self.root.resizable(False, False)

        self.price_label = tk.Label(root, text="目前價格查詢中...", font=("Helvetica", 18))
        self.price_label.pack(pady=20)

        self.status_label = tk.Label(root, text="", font=("Helvetica", 12))
        self.status_label.pack()

        self.check_price_loop()

    def check_price_loop(self):
        def task():
            while True:
                price = get_eth_price()
                if price:
                    self.price_label.config(text=f"ETH: ${price:.2f}")
                    self.status_label.config(text=time.strftime("%H:%M:%S 更新"))

                    if price >= UPPER_LIMIT:
                        send_mac_notification("🚀 ETH 價格上升", f"目前價格：${price:.2f} 超過目標！")
                    elif price <= LOWER_LIMIT:
                        send_mac_notification("📉 ETH 價格下跌", f"目前價格：${price:.2f} 跌破警戒！")
                else:
                    self.price_label.config(text="無法取得價格")
                time.sleep(60)
        threading.Thread(target=task, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ETHTracker(root)
    root.mainloop()
import os
import time
import threading
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 讀環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("2007776585")
LINE_CHANNEL_SECRET = os.getenv("45fbd89f218e1dfebc5d862d3a19b324")
ETHERSCAN_API_KEY = os.getenv("4M8722YDXJQZ8RU1RJ9JFU19I38C2IGKMK")
LINE_USER_ID = os.getenv("wucibin")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 監控參數
PRICE_CHECK_INTERVAL = 60
WHALER_CHECK_INTERVAL = 300
MIN_WHALE_AMOUNT_ETH = 500
PRICE_ALERT_THRESHOLD = 0.05

last_price = None
notified_tx_ids = set()

def get_eth_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    res = requests.get(url).json()
    return res['ethereum']['usd']

def get_latest_eth_transactions():
    url = (
        f"https://api.etherscan.io/api"
        f"?module=account&action=txlist"
        f"&address=0x0000000000000000000000000000000000000000"
        f"&startblock=0&endblock=99999999&page=1&offset=20&sort=desc"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    res = requests.get(url).json()
    if res['status'] != '1':
        return []
    return res['result']

def analyze_whale_tx(tx):
    value_eth = int(tx['value']) / 1e18
    if value_eth < MIN_WHALE_AMOUNT_ETH:
        return None
    exchanges = ['binance', 'coinbase', 'kraken', 'ftx']
    from_addr = tx['from'].lower()
    to_addr = tx['to'].lower()
    direction = "無明顯趨勢"
    if any(ex in to_addr for ex in exchanges):
        direction = "空頭 - 巨鯨將 ETH 轉入交易所可能賣出"
    elif any(ex in from_addr for ex in exchanges):
        direction = "多頭 - 巨鯨從交易所轉出可能買入"
    return (value_eth, direction)

def notify_line(message):
    line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=message))

def monitor_price():
    global last_price
    while True:
        try:
            price = get_eth_price()
            if last_price is None:
                last_price = price
                print(f"初始價格設為: ${price:.2f}")
            else:
                change = (price - last_price) / last_price
                if abs(change) >= PRICE_ALERT_THRESHOLD:
                    trend = "暴漲 📈" if change > 0 else "暴跌 📉"
                    msg = f"⚠️ ETH 價格 {trend}！目前價格：${price:.2f}，變動幅度：{change*100:.2f}%"
                    print(msg)
                    notify_line(msg)
                    last_price = price
            time.sleep(PRICE_CHECK_INTERVAL)
        except Exception as e:
            print("價格監控錯誤:", e)
            time.sleep(PRICE_CHECK_INTERVAL)

def monitor_whales():
    while True:
        try:
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
                    print(msg)
                    notify_line(msg)
                    notified_tx_ids.add(tx_hash)
            time.sleep(WHALER_CHECK_INTERVAL)
        except Exception as e:
            print("巨鯨監控錯誤:", e)
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
    # 可回覆使用者傳入的文字，方便取得 user_id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="收到訊息"))

if __name__ == "__main__":
    threading.Thread(target=monitor_price, daemon=True).start()
    threading.Thread(target=monitor_whales, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
