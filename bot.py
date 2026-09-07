import os
import json
import base64
import requests
import pandas as pd

from datetime import datetime, timezone, timedelta

from apa_engine import analyze


# ============================================================
# CLOUD XAUUSD APA BOT
#
# FEATURES
# ============================================================
#
# 1. APA signal generation
# 2. Active trade protection
# 3. Duplicate signal protection
# 4. TP / SL monitoring
# 5. Pip calculation
# 6. Weekly Monday-Friday performance tracking
# 7. Saturday weekly report
# 8. GitHub persistent state
#
# XAUUSD PIP DEFINITION:
# 0.01 price movement = 1 pip
#
# Example:
# Entry 4476.67
# TP    4405.97
#
# Difference = 70.70
# Pips = 7070
#
# ============================================================


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

# Support BOTH possible names so the existing GitHub Secret
# can continue working.
TWELVE_DATA_API_KEY = (
    os.getenv("TWELVEDATA_API_KEY")
    or os.getenv("TWELVE_DATA_API_KEY")
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN"
)

GITHUB_REPOSITORY = os.getenv(
    "GITHUB_REPOSITORY"
)


# ============================================================
# SETTINGS
# ============================================================

SYMBOL = "XAU/USD"

STATE_FILE = "signal_state.json"

PERFORMANCE_FILE = "apa_performance.json"

WEEKLY_REPORT_FILE = "weekly_report_state.json"

TWELVE_DATA_URL = (
    "https://api.twelvedata.com/time_series"
)

GITHUB_API_BASE = (
    "https://api.github.com"
)

# XAUUSD:
# 0.01 price movement = 1 pip
PIP_SIZE = 0.01


# ============================================================
# ENVIRONMENT CHECK
# ============================================================

def check_environment():

    missing = []

    if not TWELVE_DATA_API_KEY:
        missing.append(
            "TWELVEDATA_API_KEY"
        )

    if not TELEGRAM_BOT_TOKEN:
        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TELEGRAM_CHAT_ID:
        missing.append(
            "TELEGRAM_CHAT_ID"
        )

    if not GITHUB_TOKEN:
        missing.append(
            "GITHUB_TOKEN"
        )

    if not GITHUB_REPOSITORY:
        missing.append(
            "GITHUB_REPOSITORY"
        )

    if missing:

        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# TWELVE DATA
# ============================================================

def get_data(
    interval,
    outputsize=200
):

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }

    response = requests.get(
        TWELVE_DATA_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:

        raise RuntimeError(
            f"Twelve Data error: {data}"
        )

    df = pd.DataFrame(
        data["values"]
    )

    if df.empty:

        raise RuntimeError(
            f"No data returned for "
            f"{SYMBOL} {interval}"
        )

    for column in [
        "open",
        "high",
        "low",
        "close",
    ]:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        errors="coerce",
        utc=True
    )

    df = df.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    )

    df = df.sort_values(
        "datetime"
    ).reset_index(
        drop=True
    )

    return df


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(
            f"Telegram error: {result}"
        )

    print(
        "Telegram message sent."
    )


# ============================================================
# GITHUB HEADERS
# ============================================================

def github_headers():

    return {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",

        "Accept":
            "application/vnd.github+json",

        "X-GitHub-Api-Version":
            "2022-11-28",
    }


# ============================================================
# GET GITHUB FILE
# ============================================================

def get_github_file(
    filename,
    default_value
):

    url = (
        f"{GITHUB_API_BASE}/repos/"
        f"{GITHUB_REPOSITORY}/contents/"
        f"{filename}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        timeout=30,
    )

    if response.status_code == 404:

        return (
            default_value.copy()
            if isinstance(
                default_value,
                dict
            )
            else default_value
        )

    response.raise_for_status()

    data = response.json()

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

    result = json.loads(content)

    if isinstance(result, dict):

        result["_sha"] = data["sha"]

    return result


# ============================================================
# GET SIGNAL STATE
# ============================================================

def get_github_state():

    return get_github_file(
        STATE_FILE,
        {
            "status": "NONE",
            "_sha": None,
        }
    )


# ============================================================
# SAVE GITHUB FILE
# ============================================================

def save_github_file(
    filename,
    state,
    commit_message,
    max_attempts=5
):

    clean_state = dict(state)

    clean_state.pop(
        "_sha",
        None
    )

    content = json.dumps(
        clean_state,
        indent=2
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    url = (
        f"{GITHUB_API_BASE}/repos/"
        f"{GITHUB_REPOSITORY}/contents/"
        f"{filename}"
    )

    sha = state.get(
        "_sha"
    )

    for attempt in range(
        1,
        max_attempts + 1
    ):

        payload = {
            "message":
                commit_message,

            "content":
                encoded,
        }

        if sha:

            payload["sha"] = sha

        print(
            f"Saving {filename} "
            f"(attempt "
            f"{attempt}/{max_attempts})..."
        )

        response = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code in (
            200,
            201
        ):

            result = response.json()

            state["_sha"] = (
                result
                .get("content", {})
                .get("sha")
            )

            print(
                f"{filename} "
                "saved to GitHub."
            )

            return True

        if response.status_code in (
            409,
            422
        ):

            print(
                "GitHub file conflict. "
                "Refreshing SHA..."
            )

            refresh = requests.get(
                url,
                headers=github_headers(),
                timeout=30,
            )

            if refresh.status_code == 200:

                latest = (
                    refresh.json()
                )

                sha = latest.get(
                    "sha"
                )

                state["_sha"] = sha

                continue

        print(
            "GitHub save failed:",
            response.status_code,
            response.text
        )

    raise RuntimeError(
        f"Could not save {filename} "
        "to GitHub."
    )


# ============================================================
# SIGNAL STATE SAVE
# ============================================================

def save_github_state(state):

    return save_github_file(
        STATE_FILE,
        state,
        "Update APA signal state"
    )


# ============================================================
# PERFORMANCE STATE
# ============================================================

def get_performance_state():

    default = {
        "trades": [],
        "_sha": None,
    }

    return get_github_file(
        PERFORMANCE_FILE,
        default
    )


def save_performance_state(
    performance
):

    return save_github_file(
        PERFORMANCE_FILE,
        performance,
        "Update APA performance"
    )


# ============================================================
# WEEKLY REPORT STATE
# ============================================================

def get_weekly_report_state():

    default = {
        "last_report_week": "",
        "_sha": None,
    }

    return get_github_file(
        WEEKLY_REPORT_FILE,
        default
    )


def save_weekly_report_state(
    state
):

    return save_github_file(
        WEEKLY_REPORT_FILE,
        state,
        "Update APA weekly report state"
    )


# ============================================================
# SIGNAL FINGERPRINT
# ============================================================

def signal_fingerprint(signal):

    side = str(
        signal.get(
            "side",
            ""
        )
    ).upper()

    entry = round(
        float(
            signal["entry"]
        ),
        2
    )

    sl = round(
        float(
            signal["sl"]
        ),
        2
    )

    tp = round(
        float(
            signal["tp"]
        ),
        2
    )

    return (
        f"{side}|"
        f"{entry}|"
        f"{sl}|"
        f"{tp}"
    )


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def utc_now_string():

    return utc_now().isoformat()


# ============================================================
# PARSE TIME
# ============================================================

def parse_state_time(value):

    if not value:

        return None

    try:

        timestamp = pd.to_datetime(
            value,
            utc=True
        )

        if pd.isna(timestamp):

            return None

        return timestamp

    except Exception:

        return None


# ============================================================
# PIP CALCULATION
# ============================================================

def calculate_pips(
    entry,
    exit_price,
    side
):

    entry = float(entry)

    exit_price = float(
        exit_price
    )

    side = str(
        side
    ).upper()

    if side == "BUY":

        price_difference = (
            exit_price - entry
        )

    else:

        price_difference = (
            entry - exit_price
        )

    pips = (
        price_difference
        / PIP_SIZE
    )

    return round(
        pips,
        2
    )


# ============================================================
# FORMAT PIPS
# ============================================================

def format_pips(pips):

    pips = float(pips)

    if pips > 0:

        return f"+{pips:.2f} pips"

    return f"{pips:.2f} pips"


# ============================================================
# RECORD CLOSED TRADE
# ============================================================

def record_closed_trade(
    state,
    exit_event
):

    performance = (
        get_performance_state()
    )

    trades = performance.get(
        "trades",
        []
    )

    side = str(
        state.get(
            "side",
            ""
        )
    ).upper()

    entry = float(
        state["entry"]
    )

    exit_price = float(
        exit_event["price"]
    )

    result_type = (
        exit_event["type"]
    )

    pips = calculate_pips(
        entry,
        exit_price,
        side
    )

    trade = {

        "closed_at":
            str(
                exit_event["time"]
            ),

        "side":
            side,

        "entry":
            entry,

        "exit":
            exit_price,

        "sl":
            float(
                state["sl"]
            ),

        "tp":
            float(
                state["tp"]
            ),

        "result":
            result_type,

        "pips":
            pips,

        "fingerprint":
            state.get(
                "fingerprint",
                ""
            ),
    }

    # Prevent accidental duplicate recording.
    for old_trade in trades:

        if (
            old_trade.get(
                "fingerprint"
            )
            == trade["fingerprint"]
            and old_trade.get(
                "closed_at"
            )
            == trade["closed_at"]
        ):

            print(
                "Trade already recorded."
            )

            return performance

    trades.append(
        trade
    )

    performance["trades"] = trades

    save_performance_state(
        performance
    )

    print(
        "Closed trade recorded."
    )

    print(
        "RESULT:",
        result_type
    )

    print(
        "PIPS:",
        format_pips(pips)
    )

    return performance


# ============================================================
# WEEK IDENTIFICATION
# ============================================================

def get_week_start(
    timestamp
):

    timestamp = pd.Timestamp(
        timestamp
    )

    if timestamp.tzinfo is None:

        timestamp = timestamp.tz_localize(
            "UTC"
        )

    else:

        timestamp = timestamp.tz_convert(
            "UTC"
        )

    monday = (
        timestamp
        - pd.Timedelta(
            days=timestamp.weekday()
        )
    )

    monday = monday.normalize()

    return monday


# ============================================================
# WEEKLY STATISTICS
# ============================================================

def calculate_weekly_stats(
    trades,
    reference_time=None
):

    if reference_time is None:

        reference_time = pd.Timestamp(
            utc_now()
        )

    week_start = get_week_start(
        reference_time
    )

    week_end = (
        week_start
        + pd.Timedelta(
            days=5
        )
    )

    weekly_trades = []

    for trade in trades:

        closed_at = parse_state_time(
            trade.get(
                "closed_at"
            )
        )

        if closed_at is None:

            continue

        if (
            closed_at >= week_start
            and closed_at < week_end
        ):

            weekly_trades.append(
                trade
            )

    wins = sum(
        1
        for trade in weekly_trades
        if trade.get(
            "result"
        ) == "TP_HIT"
    )

    losses = sum(
        1
        for trade in weekly_trades
        if trade.get(
            "result"
        ) == "SL_HIT"
    )

    total = len(
        weekly_trades
    )

    net_pips = sum(
        float(
            trade.get(
                "pips",
                0
            )
        )
        for trade in weekly_trades
    )

    win_rate = (
        (wins / total) * 100
        if total > 0
        else 0
    )

    return {

        "week_start":
            str(
                week_start.date()
            ),

        "wins":
            wins,

        "losses":
            losses,

        "total":
            total,

        "net_pips":
            round(
                net_pips,
                2
            ),

        "win_rate":
            round(
                win_rate,
                2
            ),
    }


# ============================================================
# SEND WEEKLY REPORT
# ============================================================

def send_weekly_report_if_needed():

    now = utc_now()

    # Python weekday:
    # Monday = 0
    # Tuesday = 1
    # Wednesday = 2
    # Thursday = 3
    # Friday = 4
    # Saturday = 5
    # Sunday = 6

    if now.weekday() != 5:

        return

    report_state = (
        get_weekly_report_state()
    )

    current_week_start = (
        get_week_start(now)
    )

    week_key = str(
        current_week_start.date()
    )

    if (
        report_state.get(
            "last_report_week"
        )
        == week_key
    ):

        print(
            "Weekly report already sent "
            "for this week."
        )

        return

    performance = (
        get_performance_state()
    )

    trades = performance.get(
        "trades",
        []
    )

    stats = calculate_weekly_stats(
        trades,
        now
    )

    if stats["total"] == 0:

        message = (
            "📊 XAUUSD APA WEEKLY REPORT\n\n"
            f"📅 Week: "
            f"{stats['week_start']}\n\n"
            "No closed APA trades recorded "
            "for the previous Monday-Friday period."
        )

    else:

        net_pips = stats[
            "net_pips"
        ]

        if net_pips > 0:

            pip_text = (
                f"+{net_pips:.2f} pips"
            )

        else:

            pip_text = (
                f"{net_pips:.2f} pips"
            )

        message = (
            "📊 XAUUSD APA WEEKLY REPORT\n\n"

            f"📅 Week starting: "
            f"{stats['week_start']}\n\n"

            f"📈 Total trades: "
            f"{stats['total']}\n"

            f"✅ Wins: "
            f"{stats['wins']}\n"

            f"❌ Losses: "
            f"{stats['losses']}\n\n"

            f"🎯 Win rate: "
            f"{stats['win_rate']:.2f}%\n"

            f"📊 Net result: "
            f"{pip_text}\n\n"

            "Monday-Friday trading results."
        )

    send_telegram(
        message
    )

    report_state[
        "last_report_week"
    ] = week_key

    save_weekly_report_state(
        report_state
    )

    print(
        "Weekly APA report sent."
    )


# ============================================================
# GET MONITORING CANDLES
# ============================================================

def get_monitoring_candles():

    print(
        "Downloading recent 1-minute "
        "candles for TP/SL monitoring..."
    )

    data = get_data(
        "1min",
        outputsize=2000
    )

    print(
        "1-minute candles received:",
        len(data)
    )

    if not data.empty:

        print(
            "Monitoring period:",
            data.iloc[0]["datetime"],
            "to",
            data.iloc[-1]["datetime"]
        )

    return data


# ============================================================
# FIND TP / SL EVENT
# ============================================================

def find_exit_event(
    state,
    candles
):

    if candles.empty:

        return None

    side = str(
        state.get(
            "side",
            ""
        )
    ).upper()

    sl = float(
        state["sl"]
    )

    tp = float(
        state["tp"]
    )

    signal_time = parse_state_time(
        state.get(
            "signal_time"
        )
    )

    if signal_time is not None:

        candles_to_check = (
            candles[
                candles["datetime"]
                >= signal_time
            ]
            .copy()
        )

        print(
            "Candles checked since signal:",
            len(candles_to_check)
        )

    else:

        candles_to_check = (
            candles.copy()
        )

        print(
            "WARNING: ACTIVE signal "
            "has no signal_time."
        )

        print(
            "Checking available history."
        )

    if candles_to_check.empty:

        return None

    for _, candle in (
        candles_to_check.iterrows()
    ):

        candle_time = (
            candle["datetime"]
        )

        high = float(
            candle["high"]
        )

        low = float(
            candle["low"]
        )

        # ====================================================
        # SELL
        # ====================================================

        if side == "SELL":

            sl_touched = (
                high >= sl
            )

            tp_touched = (
                low <= tp
            )

            if (
                sl_touched
                and tp_touched
            ):

                close_price = float(
                    candle["close"]
                )

                print(
                    "WARNING: SELL candle "
                    "touched both TP and SL:",
                    candle_time
                )

                if close_price <= tp:

                    return {
                        "type":
                            "TP_HIT",

                        "price":
                            tp,

                        "time":
                            candle_time,
                    }

                if close_price >= sl:

                    return {
                        "type":
                            "SL_HIT",

                        "price":
                            sl,

                        "time":
                            candle_time,
                    }

                print(
                    "Ambiguous candle. "
                    "Waiting for clearer evidence."
                )

                continue

            if sl_touched:

                return {
                    "type":
                        "SL_HIT",

                    "price":
                        sl,

                    "time":
                        candle_time,
                }

            if tp_touched:

                return {
                    "type":
                        "TP_HIT",

                    "price":
                        tp,

                    "time":
                        candle_time,
                }

        # ====================================================
        # BUY
        # ====================================================

        elif side == "BUY":

            sl_touched = (
                low <= sl
            )

            tp_touched = (
                high >= tp
            )

            if (
                sl_touched
                and tp_touched
            ):

                close_price = float(
                    candle["close"]
                )

                print(
                    "WARNING: BUY candle "
                    "touched both TP and SL:",
                    candle_time
                )

                if close_price >= tp:

                    return {
                        "type":
                            "TP_HIT",

                        "price":
                            tp,

                        "time":
                            candle_time,
                    }

                if close_price <= sl:

                    return {
                        "type":
                            "SL_HIT",

                        "price":
                            sl,

                        "time":
                            candle_time,
                    }

                print(
                    "Ambiguous candle. "
                    "Waiting for clearer evidence."
                )

                continue

            if sl_touched:

                return {
                    "type":
                        "SL_HIT",

                    "price":
                        sl,

                    "time":
                        candle_time,
                }

            if tp_touched:

                return {
                    "type":
                        "TP_HIT",

                    "price":
                        tp,

                    "time":
                        candle_time,
                }

    return None


# ============================================================
# CLOSE ACTIVE SIGNAL
# ============================================================

def close_signal(
    state,
    exit_event
):

    exit_type = (
        exit_event["type"]
    )

    exit_price = float(
        exit_event["price"]
    )

    exit_time = (
        exit_event["time"]
    )

    side = str(
        state["side"]
    ).upper()

    entry = float(
        state["entry"]
    )

    tp = float(
        state["tp"]
    )

    sl = float(
        state["sl"]
    )

    pips = calculate_pips(
        entry,
        exit_price,
        side
    )

    state["closed_price"] = (
        exit_price
    )

    state["closed_time"] = str(
        exit_time
    )

    state["closed_pips"] = (
        pips
    )

    if exit_type == "TP_HIT":

        state["status"] = (
            "TP_HIT"
        )

        message = (
            "🎯 XAUUSD APA TRADE UPDATE\n\n"

            f"📊 Direction: {side}\n"
            "✅ Status: TAKE PROFIT HIT\n\n"

            f"🎯 Entry: {entry:.2f}\n"
            f"💰 TP: {tp:.2f}\n"
            f"📍 TP Price: {exit_price:.2f}\n\n"

            f"📈 Result: "
            f"{format_pips(pips)}\n"

            f"🕐 Detected Candle: "
            f"{exit_time}\n\n"

            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} TP HIT"
        )

    else:

        state["status"] = (
            "SL_HIT"
        )

        message = (
            "🛑 XAUUSD APA TRADE UPDATE\n\n"

            f"📊 Direction: {side}\n"
            "❌ Status: STOP LOSS HIT\n\n"

            f"🎯 Entry: {entry:.2f}\n"
            f"🛑 SL: {sl:.2f}\n"
            f"📍 SL Price: {exit_price:.2f}\n\n"

            f"📉 Result: "
            f"{format_pips(pips)}\n"

            f"🕐 Detected Candle: "
            f"{exit_time}\n\n"

            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} SL HIT"
        )

    # --------------------------------------------------------
    # Record performance FIRST.
    # --------------------------------------------------------

    record_closed_trade(
        state,
        exit_event
    )

    # --------------------------------------------------------
    # Telegram update.
    # --------------------------------------------------------

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # Save closed state.
    # --------------------------------------------------------

    save_github_state(
        state
    )

    return state


# ============================================================
# CHECK ACTIVE SIGNAL
# ============================================================

def check_active_signal(
    state
):

    if (
        state.get(
            "status"
        )
        != "ACTIVE"
    ):

        return state

    print(
        "================================================"
    )

    print(
        "ACTIVE SIGNAL CHECK"
    )

    print(
        "Direction:",
        state.get(
            "side"
        )
    )

    print(
        "Entry:",
        state.get(
            "entry"
        )
    )

    print(
        "SL:",
        state.get(
            "sl"
        )
    )

    print(
        "TP:",
        state.get(
            "tp"
        )
    )

    print(
        "Signal time:",
        state.get(
            "signal_time",
            "UNKNOWN"
        )
    )

    print(
        "================================================"
    )

    candles = (
        get_monitoring_candles()
    )

    exit_event = find_exit_event(
        state,
        candles
    )

    if exit_event:

        print(
            "EXIT EVENT FOUND:",
            exit_event
        )

        return close_signal(
            state,
            exit_event
        )

    print(
        "ACTIVE SIGNAL: STILL OPEN"
    )

    print(
        "No TP or SL detected."
    )

    return state


# ============================================================
# FORMAT NEW SIGNAL
# ============================================================

def format_signal(
    signal
):

    side = signal["side"]

    entry = float(
        signal["entry"]
    )

    sl = float(
        signal["sl"]
    )

    tp = float(
        signal["tp"]
    )

    rr = float(
        signal["rr"]
    )

    bias = signal.get(
        "bias",
        "N/A"
    )

    reason = signal.get(
        "reason",
        "APA setup"
    )

    # --------------------------------------------------------
    # Calculate theoretical TP and SL pips.
    # --------------------------------------------------------

    if side.upper() == "BUY":

        potential_profit_pips = (
            tp - entry
        ) / PIP_SIZE

        potential_loss_pips = (
            entry - sl
        ) / PIP_SIZE

    else:

        potential_profit_pips = (
            entry - tp
        ) / PIP_SIZE

        potential_loss_pips = (
            sl - entry
        ) / PIP_SIZE

    return (
        "🚨 XAUUSD APA SIGNAL 🚨\n\n"

        f"📊 Direction: {side}\n"
        f"🎯 Entry: {entry:.2f}\n"
        f"🛑 Stop Loss: {sl:.2f}\n"
        f"💰 Take Profit: {tp:.2f}\n"
        f"📐 Risk/Reward: {rr:.1f}\n\n"

        f"📈 Potential Gain: "
        f"+{potential_profit_pips:.2f} pips\n"

        f"📉 Potential Loss: "
        f"-{potential_loss_pips:.2f} pips\n\n"

        f"📈 Bias: {bias}\n\n"

        f"🔎 Setup: {reason}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "================================================"
    )

    print(
        "Cloud XAUUSD APA check started"
    )

    print(
        "================================================"
    )

    check_environment()

    # --------------------------------------------------------
    # Saturday weekly report check.
    # --------------------------------------------------------

    send_weekly_report_if_needed()

    # --------------------------------------------------------
    # Load previous signal state.
    # --------------------------------------------------------

    state = (
        get_github_state()
    )

    print(
        "PREVIOUS SIGNAL STATUS:",
        state.get(
            "status",
            "NONE"
        )
    )

    # ========================================================
    # ACTIVE SIGNAL
    # ========================================================

    if (
        state.get(
            "status"
        )
        == "ACTIVE"
    ):

        updated_state = (
            check_active_signal(
                state
            )
        )

        # ----------------------------------------------------
        # STILL ACTIVE:
        # ABSOLUTELY NO NEW SIGNAL.
        # ----------------------------------------------------

        if (
            updated_state.get(
                "status"
            )
            == "ACTIVE"
        ):

            print(
                "Existing APA setup is still active."
            )

            print(
                "No new Telegram signal will be sent."
            )

            return

        # ----------------------------------------------------
        # CLOSED:
        # Search for a genuinely new setup.
        # ----------------------------------------------------

        state = updated_state

        print(
            "Previous signal is CLOSED."
        )

        print(
            "Searching for a NEW APA setup..."
        )

    # ========================================================
    # MARKET DATA
    # ========================================================

    h4 = get_data(
        "4h",
        outputsize=200
    )

    h1 = get_data(
        "1h",
        outputsize=200
    )

    m15 = get_data(
        "15min",
        outputsize=200
    )

    print(
        "DATA CHECK:",
        len(h4),
        len(h1),
        len(m15)
    )

    # ========================================================
    # APA ENGINE
    # ========================================================

    signal = analyze(
        h4,
        h1,
        m15
    )

    if not signal:

        print(
            "No valid APA setup."
        )

        return

    # ========================================================
    # SIGNAL FINGERPRINT
    # ========================================================

    fingerprint = (
        signal_fingerprint(
            signal
        )
    )

    print(
        "NEW SETUP ID:",
        fingerprint
    )

    # ========================================================
    # DUPLICATE CHECK
    # ========================================================

    if (
        state.get(
            "fingerprint"
        )
        == fingerprint
    ):

        print(
            "DUPLICATE SETUP DETECTED."
        )

        print(
            "Telegram signal NOT sent."
        )

        return

    # ========================================================
    # SEND SIGNAL
    # ========================================================

    message = format_signal(
        signal
    )

    send_telegram(
        message
    )

    print(
        "NEW APA SIGNAL SENT TO TELEGRAM."
    )

    # ========================================================
    # SIGNAL TIME
    # ========================================================

    signal_time = None

    if not m15.empty:

        signal_time = str(
            m15.iloc[-1][
                "datetime"
            ]
        )

    if not signal_time:

        signal_time = (
            utc_now_string()
        )

    # ========================================================
    # SAVE ACTIVE STATE
    # ========================================================

    new_state = {

        "status":
            "ACTIVE",

        "fingerprint":
            fingerprint,

        "signal_time":
            signal_time,

        "side":
            signal["side"],

        "entry":
            float(
                signal["entry"]
            ),

        "sl":
            float(
                signal["sl"]
            ),

        "tp":
            float(
                signal["tp"]
            ),

        "rr":
            float(
                signal["rr"]
            ),

        "bias":
            signal.get(
                "bias",
                ""
            ),

        "reason":
            signal.get(
                "reason",
                ""
            ),

        "created_at":
            utc_now_string(),
    }

    # Preserve GitHub SHA.
    if state.get(
        "_sha"
    ):

        new_state["_sha"] = (
            state["_sha"]
        )

    save_github_state(
        new_state
    )

    print(
        "APA SIGNAL STATUS: ACTIVE"
    )

    print(
        "Signal time:",
        signal_time
    )

    print(
        "Waiting for TP or SL..."
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    main()
