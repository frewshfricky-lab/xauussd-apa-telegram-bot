import asyncio,os
from dotenv import load_dotenv
from market_data import get_bars
from apa_engine import analyze
from telegram_bot import Notifier
load_dotenv()
SYMBOL=os.getenv("TWELVEDATA_SYMBOL","XAU/USD"); WAIT=int(os.getenv("CHECK_SECONDS","60"))
async def main():
    n=Notifier(os.environ["TELEGRAM_BOT_TOKEN"],os.environ["TELEGRAM_CHAT_ID"])
    last=None; sent=None
    print("Cloud XAUUSD APA watcher started")
    while True:
        try:
            h4=get_bars(SYMBOL,"4h"); h1=get_bars(SYMBOL,"1h"); m15=get_bars(SYMBOL,"15min")
            t=m15.datetime.iloc[-2]
            if t!=last:
                last=t; s=analyze(h4,h1,m15)
                if s:
                    key=(str(t),s["side"],round(s["entry"],2))
                    if key!=sent: await n.send(s); sent=key; print("SIGNAL SENT",s)
                else: print(t,"No valid APA setup.")
        except Exception as e: print("ERROR:",repr(e))
        await asyncio.sleep(WAIT)
if __name__=="__main__": asyncio.run(main())
