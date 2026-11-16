"""جستجوی روزانه کلیپ‌های پربازدید فارسی در یوتیوب و ارسال به مدیر در تلگرام.
هر کلیپ با دکمه «ساخت پیش‌نویس» می‌آید؛ poller.py با زدن دکمه، کپشن فارسی می‌سازد."""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

API = "https://www.googleapis.com/youtube/v3"
KEY = os.environ["YOUTUBE_API_KEY"]
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN = os.environ["ADMIN_ID"]
QUERIES = [q.strip() for q in os.environ.get(
    "TREND_QUERIES", "کلیپ خنده دار,طنز,شمال ایران,سفر,ویژه,غذا").split(",") if q.strip()]
COUNT = int(os.environ.get("TREND_COUNT", "5"))
DAYS = int(os.environ.get("TREND_DAYS", "7"))
MAX_SEC = int(os.environ.get("TREND_MAX_SECONDS", "90"))
MIN_VIEWS = int(os.environ.get("TREND_MIN_VIEWS", "50000"))
SEEN_FILE = "seen.json"

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


def views_fa(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} میلیون".replace(".0", "")
    return f"{n // 1000} هزار" if n >= 1000 else str(n)


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
    for q in QUERIES:
        try:
            data = await get(c, "search", part="snippet", type="video", q=q, order="viewCount",
                             videoDuration="short", publishedAfter=since, regionCode="IR",
                             relevanceLanguage="fa", safeSearch="strict", maxResults=25)
        except Exception as e:  # noqa: BLE001
            print("search failed:", q, type(e).__name__, e)
            continue
        for it in data.get("items", []):
            ids[it["id"]["videoId"]] = None
    out, lst = [], list(ids)
    for i in range(0, len(lst), 50):
        data = await get(c, "videos", part="snippet,contentDetails,statistics", id=",".join(lst[i:i + 50]))
        for v in data.get("items", []):
            sn = v["snippet"]
            dur = seconds(v["contentDetails"].get("duration", ""))
            views = int(v.get("statistics", {}).get("viewCount", 0) or 0)
            lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
            if not 0 < dur <= MAX_SEC or views < MIN_VIEWS:
                continue
            if not (persian(sn.get("title", "")) or lang.startswith("fa")):
                continue
            out.append({"id": v["id"], "title": sn["title"], "channel": sn.get("channelTitle", ""),
                        "views": views, "sec": dur})
    out.sort(key=lambda x: x["views"], reverse=True)
    return out


async def send(c, v):
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    caption = (f"🔥 <b>{esc(v['title'])[:200]}</b>\n🎥 {esc(v['channel'])}\n"
               f"👁 {views_fa(v['views'])} بازدید | ⏱ {v['sec']} ثانیه")
    kb = {"inline_keyboard": [[
        {"text": "✍️ ساخت پیش‌نویس", "callback_data": f"yd:{v['id']}"},
        {"text": "▶️ تماشا", "url": f"https://www.youtube.com/watch?v={v['id']}"}]]}
    r = await c.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", json={
        "chat_id": ADMIN, "photo": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
        "caption": caption, "parse_mode": "HTML", "reply_markup": kb})
    print(v["id"], r.status_code)
    return r.status_code == 200


async def main():
    seen = json.load(open(SEEN_FILE)) if os.path.exists(SEEN_FILE) else []
    async with httpx.AsyncClient(timeout=30) as c:
        fresh = [v for v in await candidates(c) if v["id"] not in seen][:COUNT]
        print("fresh:", len(fresh))
        if not fresh:
            await c.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                         json={"chat_id": ADMIN, "text": "امروز کلیپ تازه‌ای برای پیشنهاد پیدا نشد."})
        for v in fresh:
            if await send(c, v):
                seen.append(v["id"])
    json.dump(seen[-500:], open(SEEN_FILE, "w"))


asyncio.run(main())
