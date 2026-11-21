"""گزارش روزانهٔ قیمت‌ها برای کانال تلگرام.

مقدارهای ریالی به تومان تبدیل می‌شوند (÷10). تغییر نسبت به روز قبل از فایل
price_history.json محاسبه می‌شود (workflow آن را commit می‌کند).
متغیرهای محیطی: TELEGRAM_BOT_TOKEN, CHANNEL_ID
اجرای آزمایشی بدون ارسال و بدون ذخیره:  python price_post.py --dry
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
KEEP_DAYS = 10                           # تعداد روزهای نگه‌داشته‌شده در تاریخچه
TAGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hashtags.txt")
POST_TAGS = ["#طلا", "#دلار", "#بیتکوین", "#یورو", "#درهم", "#پوند",
             "#اتریوم", "#سکه", "#اونس_جهانی"]
HISTORY = os.environ.get("HISTORY_FILE", "price_history.json")
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


def change(now, old):
    """متن تغییر نسبت به روز قبل؛ اگر قیمت قبلی نیست رشتهٔ خالی."""
    if not old:
        return ""
    pct = (now - old) / old * 100
    if abs(pct) < 0.005:
        return "  ⚪ ➖ بدون تغییر"
    icon, arrow = ("🟢", "▲") if pct > 0 else ("🔴", "▼")
    return f"  {icon} {arrow} {abs(pct):.2f} درصد"


def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def baseline(hist, today):
    """آخرین قیمت‌های ثبت‌شده در روزی قبل از امروز."""
    days = sorted(d for d in hist if d < today)
    return hist[days[-1]] if days else {}


def save_history(hist, today, values):
    hist[today] = values
    for d in sorted(hist)[:-KEEP_DAYS]:
        del hist[d]
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)


def read_values(cur):
    v = {
        "g18": num(cur, "geram18"),
        "ons": num(cur, "ons"),
        "usd": num(cur, "price_dollar_rl"),
        "eur": num(cur, "price_eur"),
        "aed": num(cur, "price_aed"),
        "coin": num(cur, "sekee"),
        "gbp": num(cur, "price_gbp"),
        "btc": num(cur, "crypto-bitcoin-irr"),
        "eth": num(cur, "crypto-ethereum-irr"),
    }
    # بررسی منطقی: طلای ۱۸ از روی انس و دلار حدوداً باید همان قیمت باشد
    calc = v["ons"] / 31.1035 * 0.75 * v["usd"]
    if abs(calc - v["g18"]) / v["g18"] > 0.15:
        raise ValueError(f"ناسازگاری قیمت طلا: {calc:,.0f} در برابر {v['g18']:,.0f}")
    # سکه امامی حدود ۸.۱۳ گرم طلای ۲۲ عیار (۹۱.۶٪) است؛ مقدار آن باید نزدیک طلای ۱۸ باشد
    coin_calc = v["g18"] * 8.133 * 0.916 / 0.75
    if abs(v["coin"] / coin_calc - 1) > 0.25:
        raise ValueError(f"ناسازگاری قیمت سکه: {v['coin']:,.0f} در برابر {coin_calc:,.0f}")
    return v


def hashtags():
    """هشتگ‌های خود کاربر (hashtags.txt) + هشتگ‌های این پست، بدون تکرار."""
    try:
        with open(TAGS_FILE, encoding="utf-8") as f:
            own = f.read().split()
    except OSError:
        print("hashtags.txt پیدا نشد؛ فقط هشتگ‌های پست")
        own = []
    out = []
    for t in own + POST_TAGS:
        if t.startswith("#") and len(t) > 1 and t not in out:
            out.append(t)
    return " ".join(out)


def build(v, prev):
    ch = lambda k: change(v[k], prev.get(k))
    d = datetime.now(TEHRAN)
    lines = [
        "📊 <b>گزارش قیمت روزانه</b>",
        f"🗓 {d:%Y-%m-%d} | ⏰ {d:%H:%M}",
        "",
        "🥇 <b>طلا</b>",
        f"   • طلای ۱۸ عیار (هر گرم): <b>{toman(v['g18'])}</b> تومان{ch('g18')}",
        f"   • اونس جهانی: <b>{usd(v['ons'])}</b> دلار{ch('ons')}",
        f"   • سکه امامی: <b>{toman(v['coin'])}</b> تومان{ch('coin')}",
        "",
        "💵 <b>ارز</b>",
        f"   • دلار آمریکا: <b>{toman(v['usd'])}</b> تومان{ch('usd')}",
        f"   • یورو: <b>{toman(v['eur'])}</b> تومان{ch('eur')}",
        f"   • درهم امارات: <b>{toman(v['aed'])}</b> تومان{ch('aed')}",
        f"   • پوند انگلیس: <b>{toman(v['gbp'])}</b> تومان{ch('gbp')}",
        "",
        "🪙 <b>رمزارز</b>",
        f"   • بیت‌کوین: <b>{toman(v['btc'])}</b> تومان{ch('btc')}",
        f"   • اتریوم: <b>{toman(v['eth'])}</b> تومان{ch('eth')}",
    ]
    if prev:
        lines += ["", "<i>تغییرات نسبت به روز قبل</i>"]
    tags = hashtags()
    if tags:
        lines += ["", tags]
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
    v = read_values(cur)
    hist = load_history()
    today = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    text = build(v, baseline(hist, today))
    print(text)
    if "--dry" in sys.argv:
        return
    await send(text)
    save_history(hist, today, v)
    print("ارسال شد ✅")


if __name__ == "__main__":
    asyncio.run(main())
