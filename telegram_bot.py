import requests


class Notifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id

    def send(self, signal):
        message = (
            "🚨 XAUUSD APA SIGNAL 🚨\n\n"
            f"📊 Direction: {signal['side']}\n"
            f"🎯 Entry: {signal['entry']}\n"
            f"🛑 Stop Loss: {signal['sl']}\n"
            f"💰 Take Profit: {signal['tp']}\n"
            f"📐 Risk/Reward: {signal['rr']}\n"
            f"📈 Bias: {signal['bias']}\n\n"
            f"🔎 Setup: {signal['reason']}"
        )

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": self.chat_id,
                "text": message
            },
            timeout=20
        )

        response.raise_for_status()
