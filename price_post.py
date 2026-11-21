"""گزارش روزانهٔ قیمت‌ها برای کانال تلگرام.

منبع: TGJU (call5.tgju.org/ajax.json). همهٔ مقدارهای ریالی TGJU به تومان تبدیل می‌شوند (÷10).
متغیرهای محیطی: TELEGRAM_BOT_TOKEN, CHANNEL_ID
اجرای آزمایشی بدون ارسال:  python price_post.py --dry
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

URL = "https://call5.tgju.org/ajax.json"
RETRY_DELAYS = [5, 15, 30, 60]          # در مجموع ۵ تلاش
MAX_AGE_DAYS = 4                         # قدیمی‌تر از این یعنی دادهٔ کهنه
TEHRAN = timezone(timedelta(hours=3, minutes=30))
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) price-report/1.0"}


async def fetch():
    total = len(RETRY_DELAYS) + 1
    last = None
    for n in range(1, total + 1):
        try:
            async with httpx.AsyncClient(timeout=25, headers=HEADERS,
                                         follow_redirects=True) as c:
                r = await c.get(URL)
                r.raise_for_status()
                return r.json()["current"]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            last = e
            print(f"تلاش {n} از {total} ناموفق: {type(e).__name__}")
            if n < total:
                await asyncio.sleep(RETRY_DELAYS[n - 1])
    raise last


def num(cur, key, max_age_days=MAX_AGE_DAYS):
    """مقدار عددی یک کلید؛ اگر نبود یا کهنه بود خطا می‌دهد."""
    it = cur[key]
    v = float(str(it["p"]).replace(",", ""))
    ts = datetime.strptime(it["ts"], "%Y-%m-%d %H:%M:%S")
    now = datetime.now(TEHRAN).replace(tzinfo=None)
    if now - ts > timedelta(days=max_age_days):
        raise ValueError(f"داده کهنه است: {key} ({it['ts']})")
    if v <= 0:
        raise ValueError(f"مقدار نامعتبر: {key}")
    return v


def toman(rial):
    return f"{round(rial / 10):,}"


def usd(v):
    return f"{v:,.2f}"


def build(cur):
    g18 = num(cur, "geram18")
    ons = num(cur, "ons")
    dol = num(cur, "price_dollar_rl")
    eur = num(cur, "price_eur")
    aed = num(cur, "price_aed")
    btc = num(cur, "crypto-bitcoin-irr")
    eth = num(cur, "crypto-ethereum-irr")

    # بررسی منطقی: طلای ۱۸ از روی انس و دلار حدوداً باید همان قیمت باشد
    calc = ons / 31.1035 * 0.75 * dol
    if abs(calc - g18) / g18 > 0.15:
        raise ValueError(f"ناسازگاری قیمت طلا: {calc:,.0f} در برابر {g18:,.0f}")

    d = datetime.now(TEHRAN)
    lines = [
        "📊 <b>گزارش قیمت روزانه</b>",
        f"🗓 {d:%Y-%m-%d} | ⏰ {d:%H:%M}",
        "",
        "🥇 <b>طلا</b>",
        f"   • طلای ۱۸ عیار (هر گرم): <b>{toman(g18)}</b> تومان",
        f"   • اونس جهانی: <b>{usd(ons)}</b> دلار",
        "",
        "💵 <b>ارز</b>",
        f"   • دلار آمریکا: <b>{toman(dol)}</b> تومان",
        f"   • یورو: <b>{toman(eur)}</b> تومان",
        f"   • درهم امارات: <b>{toman(aed)}</b> تومان",
        "",
        "🪙 <b>رمزارز</b>",
        f"   • بیت‌کوین: <b>{toman(btc)}</b> تومان",
        f"   • اتریوم: <b>{toman(eth)}</b> تومان",
        "",
        "📡 منبع: TGJU",
    ]
    return "\n".join(lines)


async def send(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["CHANNEL_ID"]
    total = 3
    for n in range(1, total + 1):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True})
                if r.status_code == 200:
                    return
                print("پاسخ تلگرام:", r.status_code, r.text[:200])
                if r.status_code < 500 and r.status_code != 429:
                    break
        except httpx.HTTPError as e:
            print(f"ارسال {n} از {total} ناموفق: {type(e).__name__}")
        await asyncio.sleep(10)
    raise RuntimeError("ارسال به تلگرام ناموفق بود")


async def main():
    cur = await fetch()
    text = build(cur)
    print(text)
    if "--dry" in sys.argv:
        return
    await send(text)
    print("ارسال شد ✅")


if __name__ == "__main__":
    asyncio.run(main())
