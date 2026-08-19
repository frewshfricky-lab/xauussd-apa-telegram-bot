import pandas as pd


def _swing_high(df, i, left=2, right=2):
    if i < left or i + right >= len(df):
        return False

    h = df["high"].iloc[i]
    return h > df["high"].iloc[i-left:i].max() and h >= df["high"].iloc[i+1:i+right+1].max()


def _swing_low(df, i, left=2, right=2):
    if i < left or i + right >= len(df):
        return False

    l = df["low"].iloc[i]
    return l < df["low"].iloc[i-left:i].min() and l <= df["low"].iloc[i+1:i+right+1].min()


def _trend(df):
    highs = []
    lows = []

    for i in range(2, len(df) - 2):
        if _swing_high(df, i):
            highs.append(df["high"].iloc[i])

        if _swing_low(df, i):
            lows.append(df["low"].iloc[i])

    if len(highs) < 2 or len(lows) < 2:
        return "neutral"

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "bullish"

    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "bearish"

    return "neutral"


def _recent_levels(df):
    highs = []
    lows = []

    for i in range(2, len(df) - 2):
        if _swing_high(df, i):
            highs.append(df["high"].iloc[i])

        if _swing_low(df, i):
            lows.append(df["low"].iloc[i])

    return (
        highs[-1] if highs else None,
        lows[-1] if lows else None
    )


def analyze(h4, h1, m15):
    if len(h4) < 20 or len(h1) < 20 or len(m15) < 20:
        return None

    h4_trend = _trend(h4)
    h1_trend = _trend(h1)

    if h4_trend == "bullish" and h1_trend == "bullish":
        bias = "buy"

    elif h4_trend == "bearish" and h1_trend == "bearish":
        bias = "sell"

    else:
        return None

    recent_high, recent_low = _recent_levels(m15)

    if recent_high is None or recent_low is None:
        return None

    prev = m15.iloc[-2]
    candle = m15.iloc[-1]

    entry = float(candle["close"])

    if bias == "buy":
        # Liquidity sweep below the recent M15 low,
        # followed by a bullish close.
        swept = float(candle["low"]) < float(recent_low)
        bullish_close = float(candle["close"]) > float(candle["open"])

        if not (swept and bullish_close):
            return None

        sl = float(candle["low"]) - 0.5
        risk = entry - sl

        if risk <= 0:
            return None

        tp = entry + (risk * 3)

        return {
            "side": "BUY",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "rr": "1:3",
            "bias": "H4/H1 bullish",
            "reason": "M15 liquidity sweep + bullish confirmation"
        }

    if bias == "sell":
        # Liquidity sweep above the recent M15 high,
        # followed by a bearish close.
        swept = float(candle["high"]) > float(recent_high)
        bearish_close = float(candle["close"]) < float(candle["open"])

        if not (swept and bearish_close):
            return None

        sl = float(candle["high"]) + 0.5
        risk = sl - entry

        if risk <= 0:
            return None

        tp = entry - (risk * 3)

        return {
            "side": "SELL",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "rr": "1:3",
            "bias": "H4/H1 bearish",
            "reason": "M15 liquidity sweep + bearish confirmation"
        }

    return None
