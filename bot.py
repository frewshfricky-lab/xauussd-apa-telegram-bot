import os
from dotenv import load_dotenv
from market_data import get_bars
from apa_engine import analyze
from telegram_bot import Notifier

load_dotenv()

SYMBOL = os.getenv("TWELVEDATA_SYMBOL", "XAU/USD")


def main():
    notifier = Notifier(
        os.environ["TELEGRAM_BOT_TOKEN"],
        os.environ["TELEGRAM_CHAT_ID"]
    )

    print("Cloud XAUUSD APA check started")

    try:
        h4 = get_bars(SYMBOL, "4h")
        h1 = get_bars(SYMBOL, "1h")
        m15 = get_bars(SYMBOL, "15min")

        print("DATA CHECK:", len(h4), len(h1), len(m15))

        signal = analyze(h4, h1, m15)

        if signal:
            notifier.send(signal)
            print("SIGNAL SENT:", signal)
        else:
            print("No valid APA setup.")

    except Exception as e:
        print("ERROR:", repr(e))
        raise


if __name__ == "__main__":
    main()
