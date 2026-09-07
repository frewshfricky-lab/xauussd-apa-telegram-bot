import os
import json
import base64
import requests
import pandas as pd

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from apa_engine import analyze


# ============================================================
# CLOUD XAUUSD APA BOT
# ============================================================
#
# FEATURES:
#
# 1. APA signal generation
# 2. TP/SL monitoring
# 3. Duplicate signal protection
# 4. Persistent GitHub state
# 5. XAUUSD pip calculation
# 6. Completed trade history
# 7. Monday-Friday weekly statistics
# 8. Automatic Saturday weekly report
#
# XAUUSD:
# 0.01 price movement = 1 pip
# ============================================================


TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY"
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


SYMBOL = "XAU/USD"

STATE_FILE = "signal_state.json"

TWELVE_DATA_URL = (
    "https://api.twelvedata.com/time_series"
)

GITHUB_API_BASE = (
    "https://api.github.com"
)


# ============================================================
# XAUUSD PIP SETTINGS
# ============================================================

XAUUSD_PIP_SIZE = 0.01


# ============================================================
# WEEKLY REPORT SETTINGS
# ============================================================

# Nigeria/Lagos timezone.
# Saturday morning report is targeted for 8:00 AM local time.

REPORT_TIMEZONE = ZoneInfo(
    "Africa/Lagos"
)

REPORT_HOUR = 8
REPORT_MINUTE = 0


# ============================================================
# ENVIRONMENT
# ============================================================

def check_environment():

    missing = []

    if not TWELVE_DATA_API_KEY:
        missing.append(
            "TWELVE_DATA_API_KEY"
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
        "close"
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
            "close"
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
# DEFAULT STATE
# ============================================================

def default_state():

    return {
        "status": "NONE",
        "weekly_trades": [],
        "last_weekly_report": None,
        "_sha": None,
    }


# ============================================================
# GET GITHUB STATE
# ============================================================

def get_github_state():

    url = (
        f"{GITHUB_API_BASE}/repos/"
        f"{GITHUB_REPOSITORY}/contents/"
        f"{STATE_FILE}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        timeout=30,
    )

    if response.status_code == 404:

        return default_state()

    response.raise_for_status()

    data = response.json()

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

    state = json.loads(
        content
    )

    # --------------------------------------------------------
    # Upgrade old state files safely.
    # --------------------------------------------------------

    if not isinstance(
        state.get("weekly_trades"),
        list
    ):

        state["weekly_trades"] = []

    if (
        "last_weekly_report"
        not in state
    ):

        state["last_weekly_report"] = None

    state["_sha"] = data["sha"]

    return state


# ============================================================
# SAVE GITHUB STATE
# ============================================================

def save_github_state(
    state,
    max_attempts=3
):

    clean_state = dict(
        state
    )

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
        f"{STATE_FILE}"
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
                "Update APA signal state",

            "content":
                encoded,
        }

        if sha:

            payload["sha"] = sha

        print(
            f"Saving signal state "
            f"(attempt {attempt}/"
            f"{max_attempts})..."
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
                "Signal state saved to GitHub."
            )

            return True

        if response.status_code in (
            409,
            422
        ):

            print(
                "GitHub state conflict detected."
            )

            refresh = requests.get(
                url,
                headers=github_headers(),
                timeout=30,
            )

            if refresh.status_code == 200:

                latest = refresh.json()

                sha = latest.get(
                    "sha"
                )

                print(
                    "Retrieved latest GitHub "
                    "state SHA."
                )

                continue

        print(
            "GitHub state save failed:",
            response.status_code,
            response.text,
        )

    raise RuntimeError(
        "Could not save signal_state.json "
        "to GitHub after multiple attempts."
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
# CURRENT UTC TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def utc_now_string():

    return utc_now().isoformat()


# ============================================================
# PARSE STATE TIME
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
# XAUUSD PIPS
# ============================================================

def price_to_pips(
    price_distance
):

    return (
        abs(
            float(price_distance)
        )
        /
        XAUUSD_PIP_SIZE
    )


def calculate_trade_pips(
    side,
    entry,
    exit_price
):

    side = str(
        side
    ).upper()

    entry = float(entry)
    exit_price = float(exit_price)

    if side == "BUY":

        return (
            exit_price - entry
        ) / XAUUSD_PIP_SIZE

    if side == "SELL":

        return (
            entry - exit_price
        ) / XAUUSD_PIP_SIZE

    return 0.0


# ============================================================
# GET 1-MINUTE HISTORY
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
# FIND TP / SL TOUCH
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

        candles_to_check = candles[
            candles["datetime"]
            >= signal_time
        ].copy()

        print(
            "Candles checked since signal:",
            len(candles_to_check)
        )

    else:

        candles_to_check = (
            candles.copy()
        )

        print(
            "WARNING: Existing ACTIVE signal "
            "has no signal_time."
        )

        print(
            "Checking available 1-minute history "
            "to recover TP/SL status."
        )

    if candles_to_check.empty:

        print(
            "No monitoring candles available "
            "after signal time."
        )

        return None

    for _, candle in (
        candles_to_check.iterrows()
    ):

        candle_time = candle[
            "datetime"
        ]

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
                    "WARNING: SELL candle touched "
                    "both TP and SL:",
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
                    "WARNING: BUY candle touched "
                    "both TP and SL:",
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
# RECORD COMPLETED TRADE
# ============================================================

def record_completed_trade(
    state,
    exit_event
):

    if not isinstance(
        state.get("weekly_trades"),
        list
    ):

        state["weekly_trades"] = []

    side = str(
        state["side"]
    ).upper()

    entry = float(
        state["entry"]
    )

    exit_price = float(
        exit_event["price"]
    )

    result_type = exit_event[
        "type"
    ]

    trade_pips = calculate_trade_pips(
        side,
        entry,
        exit_price
    )

    if result_type == "TP_HIT":

        result = "WIN"

        r_result = float(
            state.get(
                "rr",
                3.0
            )
        )

    else:

        result = "LOSS"

        r_result = -1.0

    trade_record = {

        "side":
            side,

        "entry":
            entry,

        "sl":
            float(
                state["sl"]
            ),

        "tp":
            float(
                state["tp"]
            ),

        "exit":
            exit_price,

        "result":
            result,

        "status":
            result_type,

        "pips":
            round(
                trade_pips,
                1
            ),

        "r":
            round(
                r_result,
                2
            ),

        "signal_time":
            state.get(
                "signal_time"
            ),

        "closed_time":
            str(
                exit_event["time"]
            ),

        "fingerprint":
            state.get(
                "fingerprint"
            ),
    }

    state["weekly_trades"].append(
        trade_record
    )

    print(
        "COMPLETED TRADE RECORDED"
    )

    print(
        "Result:",
        result
    )

    print(
        "Pips:",
        round(
            trade_pips,
            1
        )
    )

    print(
        "R:",
        round(
            r_result,
            2
        )
    )

    return trade_record


# ============================================================
# CLOSE ACTIVE SIGNAL
# ============================================================

def close_signal(
    state,
    exit_event
):

    exit_type = exit_event[
        "type"
    ]

    exit_price = float(
        exit_event["price"]
    )

    exit_time = exit_event[
        "time"
    ]

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

    # --------------------------------------------------------
    # Calculate actual completed-trade pips.
    # --------------------------------------------------------

    completed_pips = calculate_trade_pips(
        side,
        entry,
        exit_price
    )

    # ========================================================
    # TAKE PROFIT
    # ========================================================

    if exit_type == "TP_HIT":

        state["status"] = (
            "TP_HIT"
        )

        state["closed_price"] = (
            exit_price
        )

        state["closed_time"] = str(
            exit_time
        )

        message = (
            "🎯 XAUUSD APA TRADE UPDATE\n\n"

            f"📊 Direction: {side}\n"
            "✅ Status: TAKE PROFIT HIT\n\n"

            f"🎯 Entry: {entry:.2f}\n"
            f"💰 TP: {tp:.2f}\n"
            f"📍 TP Price: "
            f"{exit_price:.2f}\n\n"

            f"📈 Pips Gained: "
            f"+{completed_pips:.1f}\n\n"

            f"🕐 Detected Candle: "
            f"{exit_time}\n\n"

            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} TP HIT"
        )

    # ========================================================
    # STOP LOSS
    # ========================================================

    else:

        state["status"] = (
            "SL_HIT"
        )

        state["closed_price"] = (
            exit_price
        )

        state["closed_time"] = str(
            exit_time
        )

        message = (
            "🛑 XAUUSD APA TRADE UPDATE\n\n"

            f"📊 Direction: {side}\n"
            "❌ Status: STOP LOSS HIT\n\n"

            f"🎯 Entry: {entry:.2f}\n"
            f"🛑 SL: {sl:.2f}\n"
            f"📍 SL Price: "
            f"{exit_price:.2f}\n\n"

            f"📉 Pips Lost: "
            f"{abs(completed_pips):.1f}\n\n"

            f"🕐 Detected Candle: "
            f"{exit_time}\n\n"

            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} SL HIT"
        )

    # --------------------------------------------------------
    # Record trade BEFORE saving state.
    # --------------------------------------------------------

    record_completed_trade(
        state,
        exit_event
    )

    # --------------------------------------------------------
    # Send result to Telegram.
    # --------------------------------------------------------

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # Save updated state.
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

    if state.get(
        "status"
    ) != "ACTIVE":

        return state

    print(
        "================================================"
    )

    print(
        "ACTIVE SIGNAL CHECK"
    )

    print(
        "Direction:",
        state.get("side")
    )

    print(
        "Entry:",
        state.get("entry")
    )

    print(
        "SL:",
        state.get("sl")
    )

    print(
        "TP:",
        state.get("tp")
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
        "No TP or SL detected "
        "in monitoring history."
    )

    return state


# ============================================================
# FORMAT SIGNAL
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
    # Pip values supplied by APA engine.
    #
    # Fallback calculation is included so older/alternate
    # engine output does not crash the bot.
    # --------------------------------------------------------

    risk_pips = float(
        signal.get(
            "risk_pips",
            price_to_pips(
                abs(entry - sl)
            )
        )
    )

    reward_pips = float(
        signal.get(
            "reward_pips",
            price_to_pips(
                abs(tp - entry)
            )
        )
    )

    return (
        "🚨 XAUUSD APA SIGNAL 🚨\n\n"

        f"📊 Direction: {side}\n"

        f"🎯 Entry: {entry:.2f}\n"

        f"🛑 Stop Loss: {sl:.2f}\n"

        f"💰 Take Profit: {tp:.2f}\n"

        f"📐 Risk/Reward: {rr:.1f}\n\n"

        f"📈 Potential Gain: "
        f"+{reward_pips:.1f} pips\n"

        f"📉 Potential Loss: "
        f"-{risk_pips:.1f} pips\n\n"

        f"📈 Bias: {bias}\n\n"

        f"🔎 Setup: {reason}"
    )


# ============================================================
# WEEKLY DATE HELPERS
# ============================================================

def local_now():

    return datetime.now(
        timezone.utc
    ).astimezone(
        REPORT_TIMEZONE
    )


def previous_week_range(
    current_local
):

    # Monday = 0
    # Sunday = 6

    current_monday = (
        current_local.date()
        -
        timedelta(
            days=current_local.weekday()
        )
    )

    previous_monday = (
        current_monday
        -
        timedelta(days=7)
    )

    previous_friday = (
        previous_monday
        +
        timedelta(days=4)
    )

    return (
        previous_monday,
        previous_friday
    )


# ============================================================
# TRADE BELONGS TO WEEK?
# ============================================================

def trade_is_in_week(
    trade,
    week_start,
    week_end
):

    closed_time = parse_state_time(
        trade.get(
            "closed_time"
        )
    )

    if closed_time is None:

        return False

    local_date = (
        closed_time
        .to_pydatetime()
        .astimezone(
            REPORT_TIMEZONE
        )
        .date()
    )

    return (
        week_start
        <= local_date
        <= week_end
    )


# ============================================================
# BUILD WEEKLY REPORT
# ============================================================

def build_weekly_report(
    trades,
    week_start,
    week_end
):

    weekly = [
        trade
        for trade in trades
        if trade_is_in_week(
            trade,
            week_start,
            week_end
        )
    ]

    total = len(
        weekly
    )

    wins = sum(
        1
        for trade in weekly
        if trade.get(
            "result"
        ) == "WIN"
    )

    losses = sum(
        1
        for trade in weekly
        if trade.get(
            "result"
        ) == "LOSS"
    )

    pips_won = sum(
        float(
            trade.get(
                "pips",
                0
            )
        )
        for trade in weekly
        if float(
            trade.get(
                "pips",
                0
            )
        ) > 0
    )

    pips_lost = sum(
        abs(
            float(
                trade.get(
                    "pips",
                    0
                )
            )
        )
        for trade in weekly
        if float(
            trade.get(
                "pips",
                0
            )
        ) < 0
    )

    net_pips = (
        pips_won
        - pips_lost
    )

    net_r = sum(
        float(
            trade.get(
                "r",
                0
            )
        )
        for trade in weekly
    )

    if total > 0:

        win_rate = (
            wins
            /
            total
        ) * 100

    else:

        win_rate = 0.0

    if weekly:

        best_trade = max(
            weekly,
            key=lambda x:
                float(
                    x.get(
                        "pips",
                        0
                    )
                )
        )

        worst_trade = min(
            weekly,
            key=lambda x:
                float(
                    x.get(
                        "pips",
                        0
                    )
                )

    else:

        best_trade = None
        worst_trade = None

    message = (
        "📊 XAUUSD APA WEEKLY REPORT\n\n"

        f"📅 Week: "
        f"{week_start.strftime('%b %d')} "
        f"– "
        f"{week_end.strftime('%b %d, %Y')}\n\n"

        f"📌 Total Trades: {total}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"📈 Win Rate: {win_rate:.1f}%\n\n"

        f"🟢 Pips Won: +{pips_won:.1f}\n"
        f"🔴 Pips Lost: -{pips_lost:.1f}\n"
        f"📊 Net Pips: "
        f"{net_pips:+.1f}\n\n"

        f"💹 Net R: "
        f"{net_r:+.2f}R\n"
    )

    if best_trade:

        message += (
            "\n🏆 Best Trade: "
            f"{best_trade.get('side', '')} "
            f"+{float(best_trade.get('pips', 0)):.1f} pips"
        )

    if worst_trade:

        message += (
            "\n📉 Worst Trade: "
            f"{worst_trade.get('side', '')} "
            f"{float(worst_trade.get('pips', 0)):+.1f} pips"
        )

    if not weekly:

        message += (
            "\n\nℹ️ No completed APA trades "
            "were recorded Monday-Friday."
        )

    else:

        message += (
            "\n\n⏳ New trading week begins Monday."
        )

    return (
        message,
        weekly
    )


# ============================================================
# SATURDAY WEEKLY REPORT
# ============================================================

def maybe_send_weekly_report(
    state
):

    now_local = local_now()

    # --------------------------------------------------------
    # Only Saturday.
    #
    # Saturday = 5
    # --------------------------------------------------------

    if now_local.weekday() != 5:

        return state

    # --------------------------------------------------------
    # Only after configured Saturday morning time.
    # --------------------------------------------------------

    if (
        now_local.hour
        < REPORT_HOUR
    ):

        return state

    if (
        now_local.hour
        == REPORT_HOUR
        and now_local.minute
        < REPORT_MINUTE
    ):

        return state

    week_start, week_end = (
        previous_week_range(
            now_local
        )
    )

    report_key = (
        week_start.isoformat()
        +
        "|"
        +
        week_end.isoformat()
    )

    # --------------------------------------------------------
    # Prevent duplicate Saturday reports.
    # --------------------------------------------------------

    if (
        state.get(
            "last_weekly_report"
        )
        == report_key
    ):

        print(
            "Weekly report already sent for:",
            report_key
        )

        return state

    trades = state.get(
        "weekly_trades",
        []
    )

    message, weekly = (
        build_weekly_report(
            trades,
            week_start,
            week_end
        )
    )

    print(
        "================================================"
    )

    print(
        "SATURDAY WEEKLY REPORT"
    )

    print(
        "Week:",
        week_start,
        "to",
        week_end
    )

    print(
        "Trades:",
        len(weekly)
    )

    print(
        "================================================"
    )

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # Mark report as sent.
    # --------------------------------------------------------

    state[
        "last_weekly_report"
    ] = report_key

    save_github_state(
        state
    )

    print(
        "Weekly report sent successfully."
    )

    return state


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

    # ========================================================
    # LOAD STATE
    # ========================================================

    state = get_github_state()

    print(
        "PREVIOUS SIGNAL STATUS:",
        state.get(
            "status",
            "NONE"
        )
    )

    # --------------------------------------------------------
    # Weekly report check.
    #
    # This happens before market analysis.
    # On Saturday, the bot can report the previous
    # Monday-Friday week.
    # --------------------------------------------------------

    state = maybe_send_weekly_report(
        state
    )

    # ========================================================
    # ACTIVE SIGNAL
    # ========================================================

    if state.get(
        "status"
    ) == "ACTIVE":

        updated_state = (
            check_active_signal(
                state
            )
        )

        # ----------------------------------------------------
        # Still active = NO new signal.
        # ----------------------------------------------------

        if updated_state.get(
            "status"
        ) == "ACTIVE":

            print(
                "Existing APA setup is still active."
            )

            print(
                "No new Telegram signal "
                "will be sent."
            )

            return

        # ----------------------------------------------------
        # Closed trade.
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
    # SIGNAL ID
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
            m15.iloc[-1]["datetime"]
        )

    if not signal_time:

        signal_time = (
            utc_now_string()
        )

    # ========================================================
    # PIP VALUES
    # ========================================================

    entry = float(
        signal["entry"]
    )

    sl = float(
        signal["sl"]
    )

    tp = float(
        signal["tp"]
    )

    risk_pips = float(
        signal.get(
            "risk_pips",
            price_to_pips(
                abs(entry - sl)
            )
        )
    )

    reward_pips = float(
        signal.get(
            "reward_pips",
            price_to_pips(
                abs(tp - entry)
            )
        )
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
            entry,

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

        "risk_pips":
            risk_pips,

        "reward_pips":
            reward_pips,

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

        # ----------------------------------------------------
        # IMPORTANT:
        # Preserve all previously completed weekly trades.
        # ----------------------------------------------------

        "weekly_trades":
            state.get(
                "weekly_trades",
                []
            ),

        "last_weekly_report":
            state.get(
                "last_weekly_report"
            ),
    }

    # --------------------------------------------------------
    # Preserve GitHub file SHA.
    # --------------------------------------------------------

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
        "Potential gain:",
        reward_pips,
        "pips"
    )

    print(
        "Potential loss:",
        risk_pips,
        "pips"
    )

    print(
        "Waiting for TP or SL..."
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    main()
