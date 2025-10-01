#!/usr/bin/env python3
# Daily Spanish Vocab Sender (B2->C1) with optional schedule guard
# - Picks 3 new words each run from vocab_es_b2c1.csv (es,pos,de,example)
# - Avoids repeats until exhausted
# - Sends via Telegram or WhatsApp (Twilio) depending on env vars
# - Optional guard: only send at TARGET_HOURS in TZ (default Europe/Berlin).
#   Set TARGET_HOURS="9,15,21" and run hourly from GitHub Actions.
#   Use FORCE_SEND=1 to bypass the guard (manual tests).

import csv, json, os, random, sys
from datetime import date, datetime
from pathlib import Path
import urllib.parse, urllib.request
from base64 import b64encode

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

ROOT = Path(__file__).resolve().parent
VOCAB_CSV = os.environ.get("VOCAB_CSV", str(ROOT / "vocab_es_b2c1.csv"))
STATE_JSON = os.environ.get("STATE_JSON", str(ROOT / "state.json"))
N_WORDS = int(os.environ.get("N_WORDS", "3"))

# Scheduling guard
TZ = os.environ.get("TZ", "Europe/Berlin")
TARGET_HOURS = os.environ.get("TARGET_HOURS", "")  # e.g., "9,15,21"
FORCE_SEND = os.environ.get("FORCE_SEND") == "1"

def schedule_allows_sending():
    # Return (allowed, date_str, hour) in given TZ. If TARGET_HOURS empty -> always True.
    if FORCE_SEND or not TARGET_HOURS.strip():
        now = datetime.utcnow()
        return True, date.today().isoformat(), now.hour
    tz = ZoneInfo(TZ) if ZoneInfo else None
    now = datetime.now(tz) if tz else datetime.now()
    date_str = now.date().isoformat()
    hour = now.hour
    try:
        targets = [int(h.strip()) for h in TARGET_HOURS.split(",") if h.strip()]
    except ValueError:
        targets = []
    return (hour in targets), date_str, hour

# --- Delivery backends ----------------------------------------------------
def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram not configured; skipping Telegram send.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        print("Telegram status:", resp.status)
        body = resp.read().decode("utf-8", errors="ignore")
        print("Telegram response body:", body)

def send_twilio_whatsapp(text: str) -> None:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    wa_from = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g., 'whatsapp:+14155238886'
    wa_to = os.environ.get("TWILIO_WHATSAPP_TO")      # e.g., 'whatsapp:+49...'
    if not (sid and token and wa_from and wa_to):
        print("Twilio WhatsApp not configured; skipping WhatsApp send.")
        return
    msg = urllib.parse.urlencode({"From": wa_from, "To": wa_to, "Body": text}).encode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    req = urllib.request.Request(url, data=msg)
    credentials = f"{sid}:{token}".encode()
    req.add_header("Authorization", "Basic " + b64encode(credentials).decode())
    with urllib.request.urlopen(req, timeout=20) as resp:
        print("Twilio status:", resp.status)

# --- Vocab selection logic ------------------------------------------------
def load_vocab(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if row.get("es")]

def load_state(path):
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"used": [], "last_sent": None, "sent_hours": {}}

def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def pick_words(vocab, state, n):
    total = len(vocab)
    used = set(state.get("used", []))
    available_idxs = [i for i in range(total) if i not in used]
    if len(available_idxs) < n:
        used = set()  # reset when exhausted
        available_idxs = list(range(total))
    chosen = random.sample(available_idxs, n)
    for i in chosen:
        used.add(i)
    state["used"] = sorted(list(used))
    state["last_sent"] = str(date.today())
    return [vocab[i] for i in chosen]

def format_message(words):
    today = date.today().isoformat()
    lines = [f"📚 Palabras del día ({today}):"]
    for i, w in enumerate(words, 1):
        es = w["es"]; pos = w.get("pos",""); de = w.get("de",""); ex = w.get("example","")
        lines.append(f"\n{i}. {es} [{pos}] — {de}\n   ↪ Ej.: {ex}")
    lines.append("\n¡Ánimo! 💪")
    return "\n".join(lines)

def main():
    allowed, date_str, hour = schedule_allows_sending()
    state = load_state(STATE_JSON)

    # avoid duplicate sends within the same hour (when running hourly)
    sent_hours = state.get("sent_hours", {})
    hours_today = set(sent_hours.get(date_str, []))

    if not allowed and not FORCE_SEND:
        print(f"Schedule guard: not a target hour ({hour}) in {TZ}. Skipping send.")
        return

    if hour in hours_today and not FORCE_SEND:
        print(f"Already sent for {date_str} at hour {hour}. Skipping duplicate.")
        return

    vocab = load_vocab(VOCAB_CSV)
    if len(vocab) < N_WORDS:
        print("Vocab list too small.")
        sys.exit(1)

    words = pick_words(vocab, state, N_WORDS)
    text = format_message(words)
    send_telegram(text)
    send_twilio_whatsapp(text)

    hours_today.add(hour)
    sent_hours[date_str] = sorted(list(hours_today))
    state["sent_hours"] = sent_hours
    save_state(STATE_JSON, state)
    print(text)

if __name__ == "__main__":
    main()
