import os
import json
import base64
import requests
import pandas as pd

from datetime import datetime, timezone

from apa_engine import analyze


# ============================================================
# CLOUD XAUUSD APA BOT
# ============================================================

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

SYMBOL = "XAU/USD"

STATE_FILE = "signal_state.json"

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
GITHUB_API_BASE = "https://api.github.com"


# ============================================================
# ENVIRONMENT
# ============================================================

def check_environment():

    missing = []

    if not TWELVE_DATA_API_KEY:
        missing.append("TWELVE_DATA_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")

    if not GITHUB_REPOSITORY:
        missing.append("GITHUB_REPOSITORY")

    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# TWELVE DATA
# ============================================================

def get_data(interval, outputsize=200):

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

    df = pd.DataFrame(data["values"])

    if df.empty:
        raise RuntimeError(
            f"No data returned for {SYMBOL} {interval}"
        )

    for column in ["open", "high", "low", "close"]:
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
    ).reset_index(drop=True)

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

    print("Telegram message sent.")


# ============================================================
# GITHUB HEADERS
# ============================================================

def github_headers():

    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
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

        return {
            "status": "NONE",
            "_sha": None,
        }

    response.raise_for_status()

    data = response.json()

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

    state = json.loads(content)

    state["_sha"] = data["sha"]

    return state


# ============================================================
# SAVE GITHUB STATE
# ============================================================

def save_github_state(state, max_attempts=3):

    clean_state = dict(state)

    clean_state.pop("_sha", None)

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

    sha = state.get("_sha")

    for attempt in range(1, max_attempts + 1):

        payload = {
            "message": "Update APA signal state",
            "content": encoded,
        }

        if sha:
            payload["sha"] = sha

        print(
            f"Saving signal state "
            f"(attempt {attempt}/{max_attempts})..."
        )

        response = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=30,
        )

        if response.status_code in (200, 201):

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

        if response.status_code in (409, 422):

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

                sha = latest.get("sha")

                print(
                    "Retrieved latest GitHub state SHA."
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
        signal.get("side", "")
    ).upper()

    entry = round(
        float(signal["entry"]),
        2
    )

    sl = round(
        float(signal["sl"]),
        2
    )

    tp = round(
        float(signal["tp"]),
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

def find_exit_event(state, candles):

    if candles.empty:
        return None

    side = str(
        state.get("side", "")
    ).upper()

    sl = float(
        state["sl"]
    )

    tp = float(
        state["tp"]
    )

    signal_time = parse_state_time(
        state.get("signal_time")
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # New signals have signal_time.
    # Old ACTIVE signals created by the previous bot may not.
    #
    # If signal_time is missing, we monitor the available
    # history so the old active signal can still be detected.
    # --------------------------------------------------------

    if signal_time is not None:

        candles_to_check = candles[
            candles["datetime"] >= signal_time
        ].copy()

        print(
            "Candles checked since signal:",
            len(candles_to_check)
        )

    else:

        candles_to_check = candles.copy()

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

    # --------------------------------------------------------
    # Check candles in chronological order.
    # --------------------------------------------------------

    for _, candle in candles_to_check.iterrows():

        candle_time = candle["datetime"]

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

            sl_touched = high >= sl
            tp_touched = low <= tp

            # ------------------------------------------------
            # If both were touched in the SAME 1-minute
            # candle, exact order cannot be known from OHLC.
            #
            # Use candle open/close to make a conservative
            # determination where possible.
            # ------------------------------------------------

            if sl_touched and tp_touched:

                open_price = float(
                    candle["open"]
                )

                close_price = float(
                    candle["close"]
                )

                print(
                    "WARNING: SELL candle touched "
                    "both TP and SL:",
                    candle_time
                )

                # If candle closed below TP, TP is the
                # more likely completed target.
                if close_price <= tp:

                    return {
                        "type": "TP_HIT",
                        "price": tp,
                        "time": candle_time,
                    }

                # If candle closed above SL, SL is the
                # more likely completed stop.
                if close_price >= sl:

                    return {
                        "type": "SL_HIT",
                        "price": sl,
                        "time": candle_time,
                    }

                # Otherwise do not guess.
                print(
                    "Ambiguous candle. "
                    "Waiting for clearer evidence."
                )

                continue

            if sl_touched:

                return {
                    "type": "SL_HIT",
                    "price": sl,
                    "time": candle_time,
                }

            if tp_touched:

                return {
                    "type": "TP_HIT",
                    "price": tp,
                    "time": candle_time,
                }

        # ====================================================
        # BUY
        # ====================================================

        elif side == "BUY":

            sl_touched = low <= sl
            tp_touched = high >= tp

            if sl_touched and tp_touched:

                open_price = float(
                    candle["open"]
                )

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
                        "type": "TP_HIT",
                        "price": tp,
                        "time": candle_time,
                    }

                if close_price <= sl:

                    return {
                        "type": "SL_HIT",
                        "price": sl,
                        "time": candle_time,
                    }

                print(
                    "Ambiguous candle. "
                    "Waiting for clearer evidence."
                )

                continue

            if sl_touched:

                return {
                    "type": "SL_HIT",
                    "price": sl,
                    "time": candle_time,
                }

            if tp_touched:

                return {
                    "type": "TP_HIT",
                    "price": tp,
                    "time": candle_time,
                }

    return None


# ============================================================
# CLOSE ACTIVE SIGNAL
# ============================================================

def close_signal(state, exit_event):

    exit_type = exit_event["type"]

    exit_price = float(
        exit_event["price"]
    )

    exit_time = exit_event["time"]

    side = str(
        state["side"]
    ).upper()

    tp = float(
        state["tp"]
    )

    sl = float(
        state["sl"]
    )

    if exit_type == "TP_HIT":

        state["status"] = "TP_HIT"

        state["closed_price"] = exit_price

        state["closed_time"] = str(
            exit_time
        )

        message = (
            "🎯 XAUUSD APA TRADE UPDATE\n\n"
            f"📊 Direction: {side}\n"
            "✅ Status: TAKE PROFIT HIT\n\n"
            f"💰 TP: {tp:.2f}\n"
            f"📍 TP Price: {exit_price:.2f}\n"
            f"🕐 Detected Candle: {exit_time}\n\n"
            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} TP HIT"
        )

    else:

        state["status"] = "SL_HIT"

        state["closed_price"] = exit_price

        state["closed_time"] = str(
            exit_time
        )

        message = (
            "🛑 XAUUSD APA TRADE UPDATE\n\n"
            f"📊 Direction: {side}\n"
            "❌ Status: STOP LOSS HIT\n\n"
            f"🛑 SL: {sl:.2f}\n"
            f"📍 SL Price: {exit_price:.2f}\n"
            f"🕐 Detected Candle: {exit_time}\n\n"
            "🔒 Signal CLOSED.\n"
            "⏳ Waiting for a NEW APA setup."
        )

        print(
            f"RESULT: {side} SL HIT"
        )

    send_telegram(
        message
    )

    save_github_state(
        state
    )

    return state


# ============================================================
# CHECK ACTIVE SIGNAL
# ============================================================

def check_active_signal(state):

    if state.get("status") != "ACTIVE":

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

    candles = get_monitoring_candles()

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

def format_signal(signal):

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

    return (
        "🚨 XAUUSD APA SIGNAL 🚨\n\n"

        f"📊 Direction: {side}\n"
        f"🎯 Entry: {entry:.2f}\n"
        f"🛑 Stop Loss: {sl:.2f}\n"
        f"💰 Take Profit: {tp:.2f}\n"
        f"📐 Risk/Reward: {rr:.1f}\n\n"

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

    # ========================================================
    # LOAD STATE FIRST
    # ========================================================

    state = get_github_state()

    print(
        "PREVIOUS SIGNAL STATUS:",
        state.get(
            "status",
            "NONE"
        )
    )

    # ========================================================
    # ACTIVE SIGNAL
    #
    # IMPORTANT:
    # We check the existing trade BEFORE looking for a new
    # APA setup.
    # ========================================================

    if state.get("status") == "ACTIVE":

        updated_state = check_active_signal(
            state
        )

        # ----------------------------------------------------
        # If still ACTIVE, absolutely NO new signal.
        # ----------------------------------------------------

        if updated_state.get(
            "status"
        ) == "ACTIVE":

            print(
                "Existing APA setup is still active."
            )

            print(
                "No new Telegram signal will be sent."
            )

            return

        # ----------------------------------------------------
        # TP_HIT or SL_HIT:
        #
        # The old trade is now CLOSED.
        # Continue below and search for a genuinely new setup.
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

    fingerprint = signal_fingerprint(
        signal
    )

    print(
        "NEW SETUP ID:",
        fingerprint
    )

    # ========================================================
    # DUPLICATE CHECK
    # ========================================================

    if (
        state.get("fingerprint")
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
    #
    # We use the latest closed M15 candle as the signal's
    # starting point.
    # ========================================================

    signal_time = None

    if not m15.empty:

        signal_time = str(
            m15.iloc[-1]["datetime"]
        )

    if not signal_time:

        signal_time = utc_now_string()

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

    # Preserve GitHub file SHA.
    if state.get("_sha"):

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
