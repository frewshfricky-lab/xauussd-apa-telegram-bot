import os
import json
import requests
import pandas as pd

from apa_engine import analyze


# ============================================================
# CLOUD XAUUSD APA BOT
# DUPLICATE SIGNAL PROTECTION
#
# The bot:
# 1. Downloads XAUUSD data
# 2. Runs APA analysis
# 3. Creates a unique fingerprint for every setup
# 4. Saves the active setup to GitHub
# 5. Prevents duplicate Telegram signals
# 6. Tracks SL / TP
# 7. Waits for a NEW setup after the old one closes
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

SYMBOL = "XAU/USD"

STATE_FILE = "signal_state.json"

TWELVE_DATA_URL = (
    "https://api.twelvedata.com/time_series"
)

GITHUB_API_BASE = (
    "https://api.github.com"
)


# ============================================================
# BASIC CHECKS
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

    if missing:

        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# GET MARKET DATA
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

    df = pd.DataFrame(
        data["values"]
    )

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
# GITHUB STATE STORAGE
# ============================================================


def github_headers():

    token = os.getenv(
        "GITHUB_TOKEN"
    )

    if not token:
        return None

    return {
        "Authorization":
            f"Bearer {token}",
        "Accept":
            "application/vnd.github+json",
        "X-GitHub-Api-Version":
            "2022-11-28",
    }


def get_github_state():

    """
    Read signal_state.json from GitHub.

    If it does not exist yet, return a blank state.
    """

    token = os.getenv(
        "GITHUB_TOKEN"
    )

    repository = os.getenv(
        "GITHUB_REPOSITORY"
    )

    if not token or not repository:

        print(
            "WARNING: GitHub state storage "
            "variables unavailable."
        )

        return {
            "status": "NONE"
        }

    url = (
        f"{GITHUB_API_BASE}/repos/"
        f"{repository}/contents/"
        f"{STATE_FILE}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        timeout=30,
    )

    if response.status_code == 404:

        return {
            "status": "NONE"
        }

    response.raise_for_status()

    data = response.json()

    import base64

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

    state = json.loads(
        content
    )

    state["_sha"] = data["sha"]

    return state


def save_github_state(state):

    """
    Save signal state back to GitHub.

    This allows the next GitHub Actions run
    to remember the previous setup.
    """

    token = os.getenv(
        "GITHUB_TOKEN"
    )

    repository = os.getenv(
        "GITHUB_REPOSITORY"
    )

    if not token or not repository:

        print(
            "WARNING: Could not save GitHub state."
        )

        return

    sha = state.pop(
        "_sha",
        None
    )

    content = json.dumps(
        state,
        indent=2
    )

    import base64

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    url = (
        f"{GITHUB_API_BASE}/repos/"
        f"{repository}/contents/"
        f"{STATE_FILE}"
    )

    payload = {
        "message":
            "Update APA signal state",
        "content": encoded,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    print(
        "Signal state saved to GitHub."
    )


# ============================================================
# SIGNAL FINGERPRINT
# ============================================================


def signal_fingerprint(signal):

    """
    Create a unique ID for a setup.

    Same direction + entry + SL + TP
    = same setup.
    """

    side = str(
        signal.get("side", "")
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
# CHECK ACTIVE TRADE
# ============================================================


def check_active_signal(state):

    if state.get("status") != "ACTIVE":
        return state

    side = state.get(
        "side"
    )

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

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

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
                state.copy()
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
                state.copy()
            )

            return state

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

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
                state.copy()
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
                state.copy()
            )

            return state

    print(
        "ACTIVE SIGNAL: STILL OPEN"
    )

    return state


# ============================================================
# FORMAT APA SIGNAL
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

    message = (
        "🚨 XAUUSD APA SIGNAL 🚨\n\n"

        f"📊 Direction: {side}\n"
        f"🎯 Entry: {entry:.2f}\n"
        f"🛑 Stop Loss: {sl:.2f}\n"
        f"💰 Take Profit: {tp:.2f}\n"
        f"📐 Risk/Reward: {rr:.1f}\n\n"

        f"📈 Bias: {bias}\n\n"

        f"🔎 Setup: {reason}\n\n"

        "🧪 Demo/Test Signal"
    )

    return message


# ============================================================
# MAIN
# ============================================================


def main():

    print(
        "Cloud XAUUSD APA check started"
    )

    check_environment()

    # --------------------------------------------------------
    # GET DATA
    # --------------------------------------------------------

    h4 = get_data("4h")
    h1 = get_data("1h")
    m15 = get_data("15min")

    print(
        "DATA CHECK:",
        len(h4),
        len(h1),
        len(m15)
    )

    # --------------------------------------------------------
    # LOAD PREVIOUS SIGNAL
    # --------------------------------------------------------

    state = get_github_state()

    print(
        "PREVIOUS SIGNAL STATUS:",
        state.get(
            "status",
            "NONE"
        )
    )

    # --------------------------------------------------------
    # CHECK ACTIVE SIGNAL FIRST
    # --------------------------------------------------------

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

        # If SL or TP was hit,
        # continue to look for a NEW setup.

        state = updated_state

    # --------------------------------------------------------
    # RUN APA ENGINE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CREATE SIGNAL ID
    # --------------------------------------------------------

    fingerprint = (
        signal_fingerprint(
            signal
        )
    )

    print(
        "NEW SETUP ID:",
        fingerprint
    )

    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    previous_fingerprint = (
        state.get(
            "fingerprint"
        )
    )

    if (
        previous_fingerprint
        == fingerprint
    ):

        print(
            "DUPLICATE SETUP DETECTED."
        )

        print(
            "Telegram signal NOT sent."
        )

        return

    # --------------------------------------------------------
    # SEND NEW SIGNAL
    # --------------------------------------------------------

    message = format_signal(
        signal
    )

    send_telegram(
        message
    )

    print(
        "NEW APA SIGNAL SENT TO TELEGRAM."
    )

    # --------------------------------------------------------
    # SAVE ACTIVE SIGNAL
    # --------------------------------------------------------

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
