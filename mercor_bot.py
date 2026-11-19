#!/usr/bin/env python3
"""
Mercor -> Telegram job alert bot (no extra installs needed, Python 3 only).

Usage (in Terminal):
  python3 mercor_bot.py --test    # sends a test message to your Telegram
  python3 mercor_bot.py --debug   # prints what Mercor returns (use if a field shows blank)
  python3 mercor_bot.py           # starts watching; leave the window open
"""
import json, os, sys, time, html, urllib.request, urllib.parse

# ====================== EDIT THESE ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")      # from @BotFather (on GitHub it is read from a secret)
CHAT_ID = os.environ.get("CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")          # from @userinfobot
CHECK_EVERY_MINUTES = 5
ONLY_KEYWORDS = []      # e.g. ["writer", "writing", "editor", "generalist"]; empty = alert on everything
# ========================================================

API_URL = "https://aws.api.mercor.com/work/listings-explore-page"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mercor_seen.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) personal-job-alert-bot", "Accept": "application/json"}


def http_get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
        return r.read()


def extract_listings(data):
    """Mercor may return a plain list or a dict that contains the list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in data.values():
            if isinstance(v, dict):
                found = extract_listings(v)
                if found:
                    return found
    return []


def pick(item, *keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def money(v):
    try:
        return f"${float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def listing_id(item):
    return str(pick(item, "listingId", "id", "listing_id") or "")


def listing_url(item):
    return pick(item, "listingUrl", "url") or f"https://work.mercor.com/jobs/{listing_id(item)}"


def build_message(item, kind):
    esc = lambda v: html.escape(str(v))
    title = pick(item, "title", "name", "jobTitle") or "Untitled"
    head = "🆕 <b>New Mercor Job!</b>" if kind == "new" else "🔄 <b>Mercor Offer Reopened!</b>"
    lines = [head, "", f"💼 <b>{esc(title)}</b>", ""]

    lo = pick(item, "rateMin", "salaryMin", "minRate")
    hi = pick(item, "rateMax", "salaryMax", "maxRate")
    freq = pick(item, "payRateFrequency", "rateFrequency", "salaryFrequency", "payType")
    if lo or hi:
        rate = money(lo) if (lo and (not hi or lo == hi)) else f"{money(lo)} - {money(hi)}" if lo else money(hi)
        lines.append(f"💰 <b>Pay:</b> {esc(rate)}" + (f" / {esc(freq)}" if freq else ""))

    commit = pick(item, "commitment", "commitmentType", "employmentType")
    hours = pick(item, "hoursPerWeek", "weeklyHours", "commitmentHours")
    if commit or hours:
        lines.append("⏱ <b>Commitment:</b> " + esc(commit or "") + (f" ({esc(hours)} hrs/wk)" if hours else ""))

    domain = pick(item, "listingDomain", "domain", "category")
    if domain:
        lines.append(f"🏷 <b>Domain:</b> {esc(domain)}")
    loc = pick(item, "location", "listingLocation")
    if loc:
        lines.append(f"📍 <b>Location:</b> {esc(loc)}")

    left = pick(item, "slotsLeft", "slotsRemaining", "remainingSlots", "slots_left")
    total = pick(item, "totalQuota", "quota", "totalSlots")
    if left is not None:
        lines.append(f"👥 <b>Slots Left:</b> {esc(left)}" + (f" (Total Quota: {esc(total)})" if total else ""))

    posted = pick(item, "postedAt", "createdAt")
    if posted:
        lines.append(f"🕒 <b>Posted:</b> {esc(posted)}")
    lines += ["", f'🔗 <a href="{html.escape(listing_url(item))}">Open on Mercor</a>']
    return "\n".join(lines)


def matches_keywords(item):
    if not ONLY_KEYWORDS:
        return True
    blob = json.dumps(item, default=str).lower()
    return any(k.lower() in blob for k in ONLY_KEYWORDS)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def save_state(known, active):
    with open(STATE_FILE, "w") as f:
        json.dump({"known": sorted(known), "active": sorted(active)}, f)


def check_once():
    listings = extract_listings(http_get_json(API_URL))
    current = {listing_id(i): i for i in listings if listing_id(i)}
    if not current:
        print("Got no listings back; skipping this round.")
        return
    state = load_state()
    if state is None:  # first run: remember everything, don't spam
        save_state(set(current), set(current))
        send_telegram(f"✅ Mercor alert bot is running. Watching {len(current)} current listings; "
                      f"I'll ping you when something new appears or reopens.")
        print(f"First run: saved {len(current)} listings.")
        return
    known, active = set(state["known"]), set(state["active"])
    sent = 0
    for lid, item in current.items():
        if lid not in known:
            kind = "new"
        elif lid not in active:
            kind = "reopened"
        else:
            continue
        if matches_keywords(item):
            send_telegram(build_message(item, kind))
            sent += 1
            time.sleep(1)
    save_state(known | set(current), set(current))
    print(f"{time.strftime('%H:%M:%S')} checked {len(current)} listings, sent {sent} alerts.")


def main():
    if "--test" in sys.argv:
        send_telegram("✅ Test message from your Mercor bot. Telegram is connected.")
        print("Test message sent.")
        return
    if "--debug" in sys.argv:
        listings = extract_listings(http_get_json(API_URL))
        print(f"{len(listings)} listings returned. First one:\n")
        print(json.dumps(listings[0], indent=2, default=str) if listings else "(none)")
        return
    if "--once" in sys.argv:  # used by GitHub Actions: check one time, then exit
        check_once()
        return
    print("Mercor bot started. Press Ctrl+C to stop.")
    while True:
        try:
            check_once()
        except Exception as e:
            print("Error (will retry):", e)
        time.sleep(CHECK_EVERY_MINUTES * 60)


if __name__ == "__main__":
    main()
