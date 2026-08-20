import pandas as pd


# ============================================================
# APA ENGINE — ADVANCED LIQUIDITY DETECTION
#
# H4 = PRIMARY BIAS
# H1 = DIRECTION / FILTER
# M15 = LIQUIDITY + STRUCTURE + ENTRY
#
# APA FLOW:
# ANALYSIS → POI → LIQUIDITY SWEEP → CHoCH/BOS → ENTRY
#
# MINIMUM RISK / REWARD = 1:3
# ============================================================


SWING_LOOKBACK = 3
LIQUIDITY_LOOKBACK = 40
MIN_RR = 3.0

# How close two highs/lows must be to be considered
# approximately equal liquidity.
EQUAL_LEVEL_TOLERANCE = 0.0015


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
    Determine market structure.

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
    Select trading direction.

    H4/H1 aligned:
        Follow direction.

    H4 neutral:
        Allow H1 direction.

    H1 neutral:
        Allow H4 direction.

    H4 and H1 opposite:
        Reject trade.
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

    return None


def _equal_high_groups(
    swing_highs
):
    """
    Find groups of approximately equal highs.

    Equal highs can represent buy-side liquidity.
    """

    groups = []

    for i in range(
        len(swing_highs)
    ):

        index_a, level_a = swing_highs[i]

        group = [
            (index_a, level_a)
        ]

        for j in range(
            i + 1,
            len(swing_highs)
        ):

            index_b, level_b = (
                swing_highs[j]
            )

            difference = abs(
                level_b - level_a
            ) / max(
                abs(level_a),
                0.00001
            )

            if difference <= EQUAL_LEVEL_TOLERANCE:
                group.append(
                    (index_b, level_b)
                )

        if len(group) >= 2:
            groups.append(group)

    return groups


def _equal_low_groups(
    swing_lows
):
    """
    Find groups of approximately equal lows.

    Equal lows can represent sell-side liquidity.
    """

    groups = []

    for i in range(
        len(swing_lows)
    ):

        index_a, level_a = swing_lows[i]

        group = [
            (index_a, level_a)
        ]

        for j in range(
            i + 1,
            len(swing_lows)
        ):

            index_b, level_b = (
                swing_lows[j]
            )

            difference = abs(
                level_b - level_a
            ) / max(
                abs(level_a),
                0.00001
            )

            if difference <= EQUAL_LEVEL_TOLERANCE:
                group.append(
                    (index_b, level_b)
                )

        if len(group) >= 2:
            groups.append(group)

    return groups


def _find_liquidity_sweep(
    df,
    direction
):
    """
    Advanced liquidity sweep detector.

    BUY:
        Looks for sell-side liquidity:
        - previous swing lows
        - equal lows
        - price trades below liquidity
        - candle closes back above liquidity

    SELL:
        Looks for buy-side liquidity:
        - previous swing highs
        - equal highs
        - price trades above liquidity
        - candle closes back below liquidity
    """

    swing_highs = _swing_highs(df)
    swing_lows = _swing_lows(df)

    start = max(
        0,
        len(df) - LIQUIDITY_LOOKBACK
    )

    candidates = []

    # --------------------------------------------------------
    # BUY-SIDE SETUP
    # --------------------------------------------------------

    if direction == "buy":

        # Normal swing-low liquidity
        for index, level in swing_lows:

            if index >= start:
                candidates.append(
                    (
                        index,
                        float(level),
                        "SWING LOW"
                    )
                )

        # Equal-low liquidity
        groups = _equal_low_groups(
            swing_lows
        )

        for group in groups:

            latest_index, latest_level = (
                group[-1]
            )

            if latest_index >= start:

                average_level = sum(
                    item[1]
                    for item in group
                ) / len(group)

                candidates.append(
                    (
                        latest_index,
                        float(average_level),
                        "EQUAL LOWS"
                    )
                )

        # Check newest liquidity first
        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        for (
            liquidity_index,
            liquidity_level,
            liquidity_type
        ) in candidates:

            if (
                liquidity_index
                >= len(df) - 1
            ):
                continue

            for candle in range(
                liquidity_index + 1,
                len(df)
            ):

                candle_low = float(
                    df["low"].iloc[candle]
                )

                candle_close = float(
                    df["close"].iloc[candle]
                )

                # Liquidity taken and price
                # closes back above it.
                if (
                    candle_low
                    < liquidity_level
                    and candle_close
                    > liquidity_level
                ):

                    return {
                        "index": candle,
                        "level": liquidity_level,
                        "extreme": candle_low,
                        "type": liquidity_type,
                    }

    # --------------------------------------------------------
    # SELL-SIDE SETUP
    # --------------------------------------------------------

    if direction == "sell":

        # Normal swing-high liquidity
        for index, level in swing_highs:

            if index >= start:
                candidates.append(
                    (
                        index,
                        float(level),
                        "SWING HIGH"
                    )
                )

        # Equal-high liquidity
        groups = _equal_high_groups(
            swing_highs
        )

        for group in groups:

            latest_index, latest_level = (
                group[-1]
            )

            if latest_index >= start:

                average_level = sum(
                    item[1]
                    for item in group
                ) / len(group)

                candidates.append(
                    (
                        latest_index,
                        float(average_level),
                        "EQUAL HIGHS"
                    )
                )

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        for (
            liquidity_index,
            liquidity_level,
            liquidity_type
        ) in candidates:

            if (
                liquidity_index
                >= len(df) - 1
            ):
                continue

            for candle in range(
                liquidity_index + 1,
                len(df)
            ):

                candle_high = float(
                    df["high"].iloc[candle]
                )

                candle_close = float(
                    df["close"].iloc[candle]
                )

                # Liquidity taken and price
                # closes back below it.
                if (
                    candle_high
                    > liquidity_level
                    and candle_close
                    < liquidity_level
                ):

                    return {
                        "index": candle,
                        "level": liquidity_level,
                        "extreme": candle_high,
                        "type": liquidity_type,
                    }

    return None


def _find_choch_bos(
    df,
    sweep,
    direction
):
    """
    Confirm structural shift after liquidity sweep.

    BUY:
        Close above a relevant swing high.

    SELL:
        Close below a relevant swing low.
    """

    sweep_index = sweep["index"]

    if sweep_index >= len(df) - 1:
        return None

    swing_highs = _swing_highs(df)
    swing_lows = _swing_lows(df)

    # --------------------------------------------------------
    # BUY STRUCTURAL CONFIRMATION
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # SELL STRUCTURAL CONFIRMATION
    # --------------------------------------------------------

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
    Build entry, SL and TP.

    SL:
        Beyond liquidity sweep.

    TP:
        Minimum 3R.
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

    atr_value = float(
        atr_value
    )

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
        "entry": round(
            entry,
            2
        ),
        "sl": round(
            sl,
            2
        ),
        "tp": round(
            tp,
            2
        ),
        "rr": round(
            rr,
            2
        ),
    }


def analyze(h4, h1, m15):
    """
    Main APA analysis.

    Required:

    1. H4/H1 directional framework
    2. M15 liquidity sweep
    3. M15 CHoCH/BOS
    4. Minimum 1:3 RR

    No Telegram signal is returned unless
    every required condition passes.
    """

    h4 = _prepare(h4)
    h1 = _prepare(h1)
    m15 = _prepare(m15)

    print("================================")
    print("ADVANCED APA ENGINE CHECK")
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
    # 1. ANALYSIS
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
    # 2. SELECT DIRECTION
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
            "REASON: TIMEFRAME CONFLICT "
            "OR NO DIRECTION"
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
            "H4 NEUTRAL:"
        )

        print(
            "USING H1 DIRECTION"
        )

    elif (
        h4_bias != "neutral"
        and h1_bias == "neutral"
    ):

        print(
            "H1 NEUTRAL:"
        )

        print(
            "USING H4 DIRECTION"
        )

    else:

        print(
            "HTF DIRECTION ALIGNED"
        )

    # --------------------------------------------------------
    # 3. LIQUIDITY / POI
    # --------------------------------------------------------

    sweep = _find_liquidity_sweep(
        m15,
        direction
    )

    if not sweep:

        print(
            "M15 LIQUIDITY: NOT FOUND"
        )

        print(
            "LOOKBACK:",
            LIQUIDITY_LOOKBACK,
            "CANDLES"
        )

        print(
            "RESULT: NO SETUP"
        )

        return None

    print(
        "M15 LIQUIDITY: FOUND"
    )

    print(
        "LIQUIDITY TYPE:",
        sweep["type"]
    )

    print(
        "LIQUIDITY LEVEL:",
        round(
            sweep["level"],
            2
        )
    )

    print(
        "SWEEP EXTREME:",
        round(
            sweep["extreme"],
            2
        )
    )

    # --------------------------------------------------------
    # 4. CHoCH / BOS
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
        "STRUCTURE LEVEL:",
        round(
            confirmation["level"],
            2
        )
    )

    # --------------------------------------------------------
    # 5. RISK MANAGEMENT
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
            "MINIMUM REQUIRED RR:",
            MIN_RR
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
    # 6. FINAL APA SIGNAL
    # --------------------------------------------------------

    trade["bias"] = (
        f"H4 {h4_bias.upper()} / "
        f"H1 {h1_bias.upper()}"
    )

    trade["reason"] = (
        f"{sweep['type']} liquidity sweep + "
        "M15 CHoCH/BOS confirmation"
    )

    print("================================")
    print("RESULT: VALID APA SETUP")
    print("================================")

    return trade
