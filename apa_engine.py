import pandas as pd


# ============================================================
# APA ENGINE
# Analysis → POI → Liquidity Sweep → CHoCH/BOS → Entry
# Minimum Risk/Reward = 1:3
# ============================================================


SWING_LOOKBACK = 3
LIQUIDITY_LOOKBACK = 20
MIN_RR = 3.0


def _prepare(df):
    """
    Clean and standardize OHLC data.
    """
    data = df.copy()

    required = ["open", "high", "low", "close"]

    for column in required:
        if column not in data.columns:
            raise ValueError(f"Missing required column: {column}")

        data[column] = pd.to_numeric(
            data[column],
            errors="coerce"
        )

    data = data.dropna(subset=required).reset_index(drop=True)

    return data


def _atr(df, period=14):
    """
    Calculate ATR for dynamic stop-loss placement.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.rolling(period).mean()

    return atr


def _swing_highs(df):
    """
    Identify confirmed swing highs.
    """
    highs = df["high"]

    result = []

    for i in range(
        SWING_LOOKBACK,
        len(df) - SWING_LOOKBACK
    ):
        left = highs.iloc[
            i - SWING_LOOKBACK:i
        ]

        right = highs.iloc[
            i + 1:i + SWING_LOOKBACK + 1
        ]

        value = highs.iloc[i]

        if value > left.max() and value >= right.max():
            result.append((i, float(value)))

    return result


def _swing_lows(df):
    """
    Identify confirmed swing lows.
    """
    lows = df["low"]

    result = []

    for i in range(
        SWING_LOOKBACK,
        len(df) - SWING_LOOKBACK
    ):
        left = lows.iloc[
            i - SWING_LOOKBACK:i
        ]

        right = lows.iloc[
            i + 1:i + SWING_LOOKBACK + 1
        ]

        value = lows.iloc[i]

        if value < left.min() and value <= right.min():
            result.append((i, float(value)))

    return result


def _structure_bias(df):
    """
    Determine market bias from swing structure.

    Bullish:
        Higher High + Higher Low

    Bearish:
        Lower High + Lower Low
    """
    highs = _swing_highs(df)
    lows = _swing_lows(df)

    if len(highs) < 2 or len(lows) < 2:
        return "neutral"

    previous_high = highs[-2][1]
    latest_high = highs[-1][1]

    previous_low = lows[-2][1]
    latest_low = lows[-1][1]

    if latest_high > previous_high and latest_low > previous_low:
        return "bullish"

    if latest_high < previous_high and latest_low < previous_low:
        return "bearish"

    return "neutral"


def _find_liquidity_sweep(df, direction):
    """
    Find the most recent liquidity sweep.

    BUY:
        Price takes a previous swing low
        and closes back above that level.

    SELL:
        Price takes a previous swing high
        and closes back below that level.
    """
    swings_high = _swing_highs(df)
    swings_low = _swing_lows(df)

    start = max(
        0,
        len(df) - LIQUIDITY_LOOKBACK
    )

    if direction == "buy":

        candidates = [
            x for x in swings_low
            if x[0] < len(df) - 1
        ]

        if not candidates:
            return None

        for index, level in reversed(candidates):

            if index < start:
                continue

            for candle in range(
                index + 1,
                len(df)
            ):

                low = float(df["low"].iloc[candle])
                close = float(df["close"].iloc[candle])

                if low < level and close > level:
                    return {
                        "index": candle,
                        "level": level,
                        "extreme": low,
                    }

    if direction == "sell":

        candidates = [
            x for x in swings_high
            if x[0] < len(df) - 1
        ]

        if not candidates:
            return None

        for index, level in reversed(candidates):

            if index < start:
                continue

            for candle in range(
                index + 1,
                len(df)
            ):

                high = float(df["high"].iloc[candle])
                close = float(df["close"].iloc[candle])

                if high > level and close < level:
                    return {
                        "index": candle,
                        "level": level,
                        "extreme": high,
                    }

    return None


def _find_choch_bos(df, sweep, direction):
    """
    Look for structural confirmation after liquidity sweep.

    BUY:
        Close above the most recent internal swing high.

    SELL:
        Close below the most recent internal swing low.
    """
    sweep_index = sweep["index"]

    if sweep_index >= len(df) - 1:
        return None

    highs = _swing_highs(df)
    lows = _swing_lows(df)

    if direction == "buy":

        previous_highs = [
            x for x in highs
            if x[0] < sweep_index
        ]

        if not previous_highs:
            return None

        structure_level = previous_highs[-1][1]

        for i in range(
            sweep_index + 1,
            len(df)
        ):

            close = float(df["close"].iloc[i])

            if close > structure_level:
                return {
                    "index": i,
                    "level": structure_level,
                    "type": "BOS/CHoCH",
                }

    if direction == "sell":

        previous_lows = [
            x for x in lows
            if x[0] < sweep_index
        ]

        if not previous_lows:
            return None

        structure_level = previous_lows[-1][1]

        for i in range(
            sweep_index + 1,
            len(df)
        ):

            close = float(df["close"].iloc[i])

            if close < structure_level:
                return {
                    "index": i,
                    "level": structure_level,
                    "type": "BOS/CHoCH",
                }

    return None


def _build_trade(df, direction, sweep, confirmation):
    """
    Build entry, SL and TP.

    Stop is placed beyond the liquidity sweep.
    Target is minimum 3R.
    """
    entry = float(
        df["close"].iloc[confirmation["index"]]
    )

    atr_series = _atr(df)

    atr_value = atr_series.iloc[
        confirmation["index"]
    ]

    if pd.isna(atr_value):
        atr_value = entry * 0.001

    atr_value = float(atr_value)

    buffer = atr_value * 0.15

    if direction == "buy":

        sl = float(sweep["extreme"]) - buffer

        risk = entry - sl

        if risk <= 0:
            return None

        tp = entry + (risk * MIN_RR)

    else:

        sl = float(sweep["extreme"]) + buffer

        risk = sl - entry

        if risk <= 0:
            return None

        tp = entry - (risk * MIN_RR)

    rr = abs(tp - entry) / abs(entry - sl)

    if rr < MIN_RR:
        return None

    return {
        "side": direction.upper(),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr": round(rr, 2),
    }


def analyze(h4, h1, m15):
    """
    Main APA analysis.

    Rules:

    1. H4 establishes the primary bias.
    2. H1 must agree with H4.
    3. M15 must sweep liquidity.
    4. M15 must then produce a structural break.
    5. Entry occurs at the confirmation candle close.
    6. SL goes beyond the sweep.
    7. TP is minimum 1:3 RR.
    """

    h4 = _prepare(h4)
    h1 = _prepare(h1)
    m15 = _prepare(m15)

    if (
        len(h4) < 50
        or len(h1) < 50
        or len(m15) < 50
    ):
        return None

    h4_bias = _structure_bias(h4)
    h1_bias = _structure_bias(h1)

    # Higher-timeframe agreement required.
    if h4_bias == "bullish" and h1_bias == "bullish":
        direction = "buy"

    elif h4_bias == "bearish" and h1_bias == "bearish":
        direction = "sell"

    else:
        return None

    sweep = _find_liquidity_sweep(
        m15,
        direction
    )

    if not sweep:
        return None

    confirmation = _find_choch_bos(
        m15,
        sweep,
        direction
    )

    if not confirmation:
        return None

    trade = _build_trade(
        m15,
        direction,
        sweep,
        confirmation
    )

    if not trade:
        return None

    trade["bias"] = (
        f"H4 {h4_bias.upper()} / "
        f"H1 {h1_bias.upper()}"
    )

    trade["reason"] = (
        f"M15 liquidity sweep + "
        f"{confirmation['type']} confirmation"
    )

    return trade
