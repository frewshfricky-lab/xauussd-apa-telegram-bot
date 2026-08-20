import pandas as pd


# ============================================================
# APA ENGINE — H4 NEUTRAL / H1 DIRECTION VERSION
#
# ANALYSIS
#   H4 primary bias
#   H1 directional confirmation
#
# POI / LIQUIDITY
#   M15 liquidity sweep
#
# ACTION
#   M15 CHoCH / BOS confirmation
#
# RISK
#   Minimum RR = 1:3
# ============================================================


SWING_LOOKBACK = 3
LIQUIDITY_LOOKBACK = 20
MIN_RR = 3.0


def _prepare(df):
    """Clean and standardize OHLC data."""

    data = df.copy()

    required = ["open", "high", "low", "close"]

    for column in required:
        if column not in data.columns:
            raise ValueError(
                f"Missing required column: {column}"
            )

        data[column] = pd.to_numeric(
            data[column],
            errors="coerce"
        )

    data = data.dropna(
        subset=required
    ).reset_index(drop=True)

    return data


def _atr(df, period=14):
    """Calculate ATR."""

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

    return true_range.rolling(
        period
    ).mean()


def _swing_highs(df):
    """Find confirmed swing highs."""

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

        if (
            value > left.max()
            and value >= right.max()
        ):
            result.append(
                (i, float(value))
            )

    return result


def _swing_lows(df):
    """Find confirmed swing lows."""

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

        if (
            value < left.min()
            and value <= right.min()
        ):
            result.append(
                (i, float(value))
            )

    return result


def _structure_bias(df):
    """
    Determine structure.

    bullish:
        Higher High + Higher Low

    bearish:
        Lower High + Lower Low

    neutral:
        Mixed / unclear structure
    """

    highs = _swing_highs(df)
    lows = _swing_lows(df)

    if len(highs) < 2 or len(lows) < 2:
        return "neutral"

    previous_high = highs[-2][1]
    latest_high = highs[-1][1]

    previous_low = lows[-2][1]
    latest_low = lows[-1][1]

    if (
        latest_high > previous_high
        and latest_low > previous_low
    ):
        return "bullish"

    if (
        latest_high < previous_high
        and latest_low < previous_low
    ):
        return "bearish"

    return "neutral"


def _select_direction(h4_bias, h1_bias):
    """
    Determine trading direction.

    RULES:

    H4 bullish + H1 bullish
        -> BUY

    H4 bearish + H1 bearish
        -> SELL

    H4 neutral + H1 bullish
        -> BUY

    H4 neutral + H1 bearish
        -> SELL

    H4 bullish + H1 neutral
        -> BUY

    H4 bearish + H1 neutral
        -> SELL

    H4 bullish + H1 bearish
        -> NO TRADE

    H4 bearish + H1 bullish
        -> NO TRADE

    Both neutral
        -> NO TRADE
    """

    if (
        h4_bias == "bullish"
        and h1_bias == "bearish"
    ):
        return None

    if (
        h4_bias == "bearish"
        and h1_bias == "bullish"
    ):
        return None

    if h4_bias == "bullish":
        return "buy"

    if h4_bias == "bearish":
        return "sell"

    if (
        h4_bias == "neutral"
        and h1_bias == "bullish"
    ):
        return "buy"

    if (
        h4_bias == "neutral"
        and h1_bias == "bearish"
    ):
        return "sell"

    if (
        h4_bias == "bullish"
        and h1_bias == "neutral"
    ):
        return "buy"

    if (
        h4_bias == "bearish"
        and h1_bias == "neutral"
    ):
        return "sell"

    return None


def _find_liquidity_sweep(
    df,
    direction
):
    """
    Find a recent liquidity sweep.

    BUY:
        price takes a previous swing low
        and closes back above it.

    SELL:
        price takes a previous swing high
        and closes back below it.
    """

    swing_highs = _swing_highs(df)
    swing_lows = _swing_lows(df)

    start = max(
        0,
        len(df) - LIQUIDITY_LOOKBACK
    )

    if direction == "buy":

        candidates = [
            item
            for item in swing_lows
            if item[0] < len(df) - 1
        ]

        for index, level in reversed(
            candidates
        ):

            if index < start:
                continue

            for candle in range(
                index + 1,
                len(df)
            ):

                low = float(
                    df["low"].iloc[candle]
                )

                close = float(
                    df["close"].iloc[candle]
                )

                if (
                    low < level
                    and close > level
                ):
                    return {
                        "index": candle,
                        "level": level,
                        "extreme": low,
                    }

    if direction == "sell":

        candidates = [
            item
            for item in swing_highs
            if item[0] < len(df) - 1
        ]

        for index, level in reversed(
            candidates
        ):

            if index < start:
                continue

            for candle in range(
                index + 1,
                len(df)
            ):

                high = float(
                    df["high"].iloc[candle]
                )

                close = float(
                    df["close"].iloc[candle]
                )

                if (
                    high > level
                    and close < level
                ):
                    return {
                        "index": candle,
                        "level": level,
                        "extreme": high,
                    }

    return None


def _find_choch_bos(
    df,
    sweep,
    direction
):
    """
    Find structural confirmation
    after the liquidity sweep.
    """

    sweep_index = sweep["index"]

    if sweep_index >= len(df) - 1:
        return None

    swing_highs = _swing_highs(df)
    swing_lows = _swing_lows(df)

    if direction == "buy":

        previous_highs = [
            item
            for item in swing_highs
            if item[0] < sweep_index
        ]

        if not previous_highs:
            return None

        structure_level = (
            previous_highs[-1][1]
        )

        for i in range(
            sweep_index + 1,
            len(df)
        ):

            close = float(
                df["close"].iloc[i]
            )

            if close > structure_level:
                return {
                    "index": i,
                    "level": structure_level,
                    "type": "BOS/CHoCH",
                }

    if direction == "sell":

        previous_lows = [
            item
            for item in swing_lows
            if item[0] < sweep_index
        ]

        if not previous_lows:
            return None

        structure_level = (
            previous_lows[-1][1]
        )

        for i in range(
            sweep_index + 1,
            len(df)
        ):

            close = float(
                df["close"].iloc[i]
            )

            if close < structure_level:
                return {
                    "index": i,
                    "level": structure_level,
                    "type": "BOS/CHoCH",
                }

    return None


def _build_trade(
    df,
    direction,
    sweep,
    confirmation
):
    """
    Build trade with SL beyond sweep
    and minimum 1:3 RR.
    """

    entry = float(
        df["close"].iloc[
            confirmation["index"]
        ]
    )

    atr_values = _atr(df)

    atr_value = atr_values.iloc[
        confirmation["index"]
    ]

    if pd.isna(atr_value):
        atr_value = entry * 0.001

    atr_value = float(atr_value)

    buffer = atr_value * 0.15

    if direction == "buy":

        sl = (
            float(sweep["extreme"])
            - buffer
        )

        risk = entry - sl

        if risk <= 0:
            return None

        tp = (
            entry
            + risk * MIN_RR
        )

    else:

        sl = (
            float(sweep["extreme"])
            + buffer
        )

        risk = sl - entry

        if risk <= 0:
            return None

        tp = (
            entry
            - risk * MIN_RR
        )

    rr = abs(
        tp - entry
    ) / abs(
        entry - sl
    )

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
    Main APA engine.

    H4:
        Primary market structure.

    H1:
        Directional confirmation.

    M15:
        Liquidity sweep and CHoCH/BOS.

    Risk:
        Minimum 1:3 RR.
    """

    h4 = _prepare(h4)
    h1 = _prepare(h1)
    m15 = _prepare(m15)

    print("================================")
    print("APA ENGINE CHECK")
    print("================================")

    print(
        "H4 candles:",
        len(h4)
    )

    print(
        "H1 candles:",
        len(h1)
    )

    print(
        "M15 candles:",
        len(m15)
    )

    if (
        len(h4) < 50
        or len(h1) < 50
        or len(m15) < 50
    ):

        print(
            "RESULT: NOT ENOUGH DATA"
        )

        return None

    # --------------------------------------------------------
    # HIGHER-TIMEFRAME ANALYSIS
    # --------------------------------------------------------

    h4_bias = _structure_bias(h4)
    h1_bias = _structure_bias(h1)

    print(
        "H4 BIAS:",
        h4_bias.upper()
    )

    print(
        "H1 BIAS:",
        h1_bias.upper()
    )

    # --------------------------------------------------------
    # DIRECTION SELECTION
    # --------------------------------------------------------

    direction = _select_direction(
        h4_bias,
        h1_bias
    )

    if direction is None:

        print(
            "HTF DIRECTION: REJECTED"
        )

        print(
            "REASON: H4/H1 CONFLICT OR BOTH NEUTRAL"
        )

        print(
            "RESULT: NO SETUP"
        )

        return None

    print(
        "HTF DIRECTION:",
        direction.upper()
    )

    if (
        h4_bias == "neutral"
        and h1_bias != "neutral"
    ):

        print(
            "H4 STATUS: NEUTRAL"
        )

        print(
            "H1 STATUS: DIRECTION USED"
        )

    elif (
        h4_bias != "neutral"
        and h1_bias == "neutral"
    ):

        print(
            "H1 STATUS: NEUTRAL"
        )

        print(
            "H4 STATUS: PRIMARY DIRECTION USED"
        )

    else:

        print(
            "HTF STATUS: ALIGNED"
        )

    # --------------------------------------------------------
    # LIQUIDITY SWEEP
    # --------------------------------------------------------

    sweep = _find_liquidity_sweep(
        m15,
        direction
    )

    if not sweep:

        print(
            "M15 LIQUIDITY SWEEP: NOT FOUND"
        )

        print(
            "RESULT: NO SETUP"
        )

        return None

    print(
        "M15 LIQUIDITY SWEEP: FOUND"
    )

    print(
        "Sweep level:",
        round(
            sweep["level"],
            2
        )
    )

    print(
        "Sweep extreme:",
        round(
            sweep["extreme"],
            2
        )
    )

    # --------------------------------------------------------
    # CHoCH / BOS
    # --------------------------------------------------------

    confirmation = _find_choch_bos(
        m15,
        sweep,
        direction
    )

    if not confirmation:

        print(
            "M15 CHoCH/BOS: NOT FOUND"
        )

        print(
            "RESULT: NO SETUP"
        )

        return None

    print(
        "M15 CHoCH/BOS: CONFIRMED"
    )

    print(
        "Structure level:",
        round(
            confirmation["level"],
            2
        )
    )

    # --------------------------------------------------------
    # TRADE CONSTRUCTION
    # --------------------------------------------------------

    trade = _build_trade(
        m15,
        direction,
        sweep,
        confirmation
    )

    if not trade:

        print(
            "RISK/REWARD: FAILED"
        )

        print(
            "RESULT: NO SETUP"
        )

        return None

    print(
        "RISK/REWARD:",
        trade["rr"]
    )

    print(
        "ENTRY:",
        trade["entry"]
    )

    print(
        "STOP LOSS:",
        trade["sl"]
    )

    print(
        "TAKE PROFIT:",
        trade["tp"]
    )

    # --------------------------------------------------------
    # FINAL SIGNAL
    # --------------------------------------------------------

    trade["bias"] = (
        f"H4 {h4_bias.upper()} / "
        f"H1 {h1_bias.upper()}"
    )

    trade["reason"] = (
        "M15 liquidity sweep + "
        "CHoCH/BOS confirmation"
    )

    print("================================")
    print("RESULT: VALID APA SETUP")
    print("================================")

    return trade
