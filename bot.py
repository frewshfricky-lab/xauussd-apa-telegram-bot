import os
import json
import base64
import requests
import pandas as pd

from apa_engine import analyze


# ============================================================
# CLOUD XAUUSD APA BOT
# SIGNAL STATE + DUPLICATE PROTECTION
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

def get_data(interval):

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": 200,
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

    required = [
        "open",
        "high",
        "low",
        "close",
    ]

    for column in required:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna(
        subset=required
    )

    df = df.iloc[::-1]

    df = df.reset_index(
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
# READ STATE FROM GITHUB
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

    # File does not exist yet.
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
# SAVE STATE TO GITHUB
# ============================================================

def save_github_state(state, max_attempts=3):

    """
    Save signal_state.json to GitHub.

    Handles GitHub 409/422 conflicts by retrieving
    the latest file SHA and trying again.
    """

    clean_state = dict(state)

    # Never store GitHub's internal SHA inside the JSON.
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
            f"(attempt {attempt}/{max_attempts})..."
        )

        response = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=30,
        )

        # Success
        if response.status_code in (
            200,
            201,
        ):

            result = response.json()

            new_sha = (
                result
                .get("content", {})
                .get("sha")
            )

            state["_sha"] = new_sha

            print(
                "Signal state saved to GitHub."
            )

            return True

        # GitHub says the file changed.
        if response.status_code in (
            409,
            422,
        ):

            print(
                "GitHub state conflict detected."
            )

            # Get the newest SHA.
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
# CURRENT PRICE
# ============================================================

def get_current_price():

    params = {
        "symbol": SYMBOL,
        "interval": "1min",
        "outputsize": 1,
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
            f"Price error: {data}"
        )

    candle = data["values"][0]

    return float(
        candle["close"]
    )


# ============================================================
# CLOSE ACTIVE SIGNAL
# ============================================================

def check_active_signal(state):

    if state.get(
        "status"
    ) != "ACTIVE":

        return state

    side = state.get("side")

    entry = float(
        state["entry"]
    )

    sl = float(
        state["sl"]
    )

    tp = float(
        state["tp"]
    )

    price = get_current_price()

    print(
        "ACTIVE SIGNAL CHECK"
    )

    print(
        "Direction:",
        side
    )

    print(
        "Entry:",
        entry
    )

    print(
        "SL:",
        sl
    )

    print(
        "TP:",
        tp
    )

    print(
        "Current price:",
        price
    )

    # ========================================================
    # SELL
    # ========================================================

    if side == "SELL":

        if price >= sl:

            state["status"] = "SL_HIT"

            state["closed_price"] = price

            print(
                "RESULT: SELL SL HIT"
            )

            send_telegram(
                "🛑 XAUUSD APA TRADE UPDATE\n\n"
                "📊 Direction: SELL\n"
                "❌ Status: STOP LOSS HIT\n\n"
                f"🛑 SL: {sl:.2f}\n"
                f"📍 Price: {price:.2f}\n\n"
                "⏳ Waiting for a NEW APA setup."
            )

            save_github_state(
                state
            )

            return state

        if price <= tp:

            state["status"] = "TP_HIT"

            state["closed_price"] = price

            print(
                "RESULT: SELL TP HIT"
            )

            send_telegram(
                "🎯 XAUUSD APA TRADE UPDATE\n\n"
                "📊 Direction: SELL\n"
                "✅ Status: TAKE PROFIT HIT\n\n"
                f"💰 TP: {tp:.2f}\n"
                f"📍 Price: {price:.2f}\n\n"
                "⏳ Waiting for a NEW APA setup."
            )

            save_github_state(
                state
            )

            return state

    # ========================================================
    # BUY
    # ========================================================

    if side == "BUY":

        if price <= sl:

            state["status"] = "SL_HIT"

            state["closed_price"] = price

            print(
                "RESULT: BUY SL HIT"
            )

            send_telegram(
                "🛑 XAUUSD APA TRADE UPDATE\n\n"
                "📊 Direction: BUY\n"
                "❌ Status: STOP LOSS HIT\n\n"
                f"🛑 SL: {sl:.2f}\n"
                f"📍 Price: {price:.2f}\n\n"
                "⏳ Waiting for a NEW APA setup."
            )

            save_github_state(
                state
            )

            return state

        if price >= tp:

            state["status"] = "TP_HIT"

            state["closed_price"] = price

            print(
                "RESULT: BUY TP HIT"
            )

            send_telegram(
                "🎯 XAUUSD APA TRADE UPDATE\n\n"
                "📊 Direction: BUY\n"
                "✅ Status: TAKE PROFIT HIT\n\n"
                f"💰 TP: {tp:.2f}\n"
                f"📍 Price: {price:.2f}\n\n"
                "⏳ Waiting for a NEW APA setup."
            )

            save_github_state(
                state
            )

            return state

    print(
        "ACTIVE SIGNAL: STILL OPEN"
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
        "Cloud XAUUSD APA check started"
    )

    check_environment()

    # ========================================================
    # MARKET DATA
    # ========================================================

    h4 = get_data("4h")
    h1 = get_data("1h")
    m15 = get_data("15min")

    print(
        "DATA CHECK:",
        len(h4),
        len(h1),
        len(m15)
    )

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

    # ========================================================
    # ACTIVE SIGNAL CHECK
    # ========================================================

    if state.get(
        "status"
    ) == "ACTIVE":

        updated_state = (
            check_active_signal(
                state
            )
        )

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

        state = updated_state

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
    # SEND TELEGRAM
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
    # SAVE NEW ACTIVE STATE
    # ========================================================

    new_state = {
        "status": "ACTIVE",

        "fingerprint":
            fingerprint,

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
    }

    # Carry the latest SHA from the state
    # we read at the beginning.
    if state.get("_sha"):
        new_state["_sha"] = state["_sha"]

    save_github_state(
        new_state
    )

    print(
        "APA SIGNAL STATUS: ACTIVE"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
