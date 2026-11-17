"""پیشنهاد کلیپ‌های وایرال یوتیوب: ۸۰٪ فارسی، ۲۰٪ خارجی.
رتبه‌بندی: نیمی بیشترین بازدید، نیمی بیشترین سرعت لایک (لایک در ساعت).
دانلود روی گوشی انجام می‌شود (yt_phone.py)؛ این فایل فقط لیست را در queue.json می‌نویسد
و به مدیر خبر می‌دهد که لیست آماده است."""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from itertools import zip_longest

import httpx

API = "https://www.googleapis.com/youtube/v3"
KEY = os.environ["YOUTUBE_API_KEY"]
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN = os.environ["ADMIN_ID"]
TG = f"https://api.telegram.org/bot{TOKEN}"


def env_list(name, default):
    return [q.strip() for q in os.environ.get(name, default).split(",") if q.strip()]


FA_QUERIES = env_list("TREND_QUERIES", "کلیپ خنده دار,طنز,شمال ایران,سفر,ویژه,غذا")
GLOBAL_QUERIES = env_list("TREND_GLOBAL_QUERIES", "funny,viral,satisfying,amazing")
COUNT = int(os.environ.get("TREND_COUNT", "10"))
FA_SHARE = float(os.environ.get("TREND_FA_SHARE", "0.8"))
DAYS = int(os.environ.get("TREND_DAYS", "7"))
MAX_SEC = int(os.environ.get("TREND_MAX_SECONDS", "90"))
MIN_VIEWS = int(os.environ.get("TREND_MIN_VIEWS", "20000"))
SEEN_FILE = "seen.json"
QUEUE_FILE = "queue.json"

FA = re.compile(r"[\u0600-\u06FF]")
EN = re.compile(r"[A-Za-z]")
DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def seconds(s):
    m = DUR.fullmatch(s or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def persian(t):
    return len(FA.findall(t)) >= 3 and len(FA.findall(t)) >= len(EN.findall(t))


def num(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} میلیون".replace(".0 ", " ")
    if n >= 1000:
        return f"{int(n // 1000)} هزار"
    return str(int(n))


async def get(c, path, **p):
    for n in range(4):
        try:
            r = await c.get(f"{API}/{path}", params=dict(p, key=KEY))
            if r.status_code != 200:
                raise RuntimeError(f"YouTube {r.status_code}: {r.text[:200]}")
            return r.json()
        except httpx.HTTPError:
            if n == 3:
                raise
            await asyncio.sleep(10)


async def candidates(c):
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = {}
    searches = [(q, {"regionCode": "IR", "relevanceLanguage": "fa"}) for q in FA_QUERIES]
    searches += [(q, {}) for q in GLOBAL_QUERIES]
    for q, extra in searches:
        try:
            data = await get(c, "search", part="snippet", type="video", q=q, order="viewCount",
                             videoDuration="short", publishedAfter=since, safeSearch="strict",
                             maxResults=25, **extra)
        except Exception as e:  # noqa: BLE001
            print("search failed:", q, type(e).__name__, e)
            continue
        for it in data.get("items", []):
            ids[it["id"]["videoId"]] = None
    out, lst = [], list(ids)
    now = datetime.now(timezone.utc)
    for i in range(0, len(lst), 50):
        data = await get(c, "videos", part="snippet,contentDetails,statistics", id=",".join(lst[i:i + 50]))
        for v in data.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            dur = seconds(v["contentDetails"].get("duration", ""))
            views = int(st.get("viewCount", 0) or 0)
            likes = int(st.get("likeCount", 0) or 0)
            if not 0 < dur <= MAX_SEC or views < MIN_VIEWS:
                continue
            pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            hours = max((now - pub).total_seconds() / 3600, 1)
            lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
            out.append({"id": v["id"], "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                        "views": views, "likes": likes, "sec": dur, "vel": likes / hours,
                        "fa": persian(sn.get("title", "")) or lang.startswith("fa")})
    return out


def pick(items, n, taken):
    """یکی در میان: پربازدیدترین و سریع‌ترین در لایک گرفتن."""
    by_views = sorted(items, key=lambda x: x["views"], reverse=True)
    by_vel = sorted(items, key=lambda x: x["vel"], reverse=True)
    out = []
    for a, b in zip_longest(by_views, by_vel):
        for v, why in ((a, "🔥 پربازدید"), (b, "⚡ لایک سریع")):
            if v and v["id"] not in taken and len(out) < n:
                taken.add(v["id"])
                v["why"] = why
                out.append(v)
    return out


# --- پایان بخش ۱ ---def info(v):
    """توضیح مخصوص مدیر (زیر خط ➖➖➖ در کپشن می‌آید و هنگام انتشار حذف می‌شود)."""
    title = v["title"][:150]
    kind = "🇮🇷 فارسی" if v["fa"] else "🌍 خارجی"
    stats = ("👁 " + num(v["views"]) + " | ❤️ " + num(v["likes"]) + " | ⚡ "
             + num(v["vel"]) + " لایک در ساعت | ⏱ " + str(v["sec"]) + " ثانیه")
    lines = [title, "🎥 " + v["channel"], v["why"] + " | " + kind, stats]
    return "\n".join(lines)


async def main():
    seen = json.load(open(SEEN_FILE)) if os.path.exists(SEEN_FILE) else []
    async with httpx.AsyncClient(timeout=60) as c:
        fresh = [v for v in await candidates(c) if v["id"] not in seen]
        fa = [v for v in fresh if v["fa"]]
        gl = [v for v in fresh if not v["fa"]]
        taken = set()
        chosen = pick(fa, round(COUNT * FA_SHARE), taken)
        chosen += pick(gl, COUNT - len(chosen), taken)
        chosen += pick(fa, COUNT - len(chosen), taken)
        print("fresh:", len(fresh), "fa:", len(fa), "global:", len(gl), "chosen:", len(chosen))
        queue = [{"id": v["id"], "info": info(v)} for v in chosen]
        json.dump(queue, open(QUEUE_FILE, "w"), ensure_ascii=False)
        seen += [v["id"] for v in chosen]
        n_fa = sum(v["fa"] for v in chosen)
        if chosen:
            text = ("🎬 " + str(len(chosen)) + " ویدیوی تازه آماده است (" + str(n_fa) + " فارسی، "
                    + str(len(chosen) - n_fa) + " خارجی).\n"
                    "در Termux (با فیلترشکن روشن) این را اجرا کن:\n"
                    "cd ~/villa_bot && python yt_phone.py")
        else:
            text = "ویدیوی تازه‌ای برای پیشنهاد پیدا نشد."
        await c.post(f"{TG}/sendMessage", json={"chat_id": ADMIN, "text": text})
    json.dump(seen[-500:], open(SEEN_FILE, "w"))


asyncio.run(main())
# --- پایان فایل ---
