"""پیشنهاد ۱۰ کلیپ یوتیوب: ۵ فارسی + ۵ جهانی. رتبه‌بندی فقط بر اساس بازدید.
اولویت موضوع: کمدی، بعد رقص، بعد سرگرمی. سن ویدیو شرط نیست (تکراری‌ها با seen.json حذف می‌شوند).
دانلود روی گوشی با تأیید ✅ انجام می‌شود؛ این فایل فقط queue.json را می‌نویسد."""
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
TG = f"https://api.telegram.org/bot{TOKEN}"


def env_list(name, default):
    return [q.strip() for q in os.environ.get(name, default).split(",") if q.strip()]


# (برچسب، پرس‌وجوهای فارسی، پرس‌وجوهای جهانی) به ترتیب اولویت
CATS = [
    ("😂 کمدی", env_list("TREND_FA_COMEDY", "کلیپ خنده دار,کمدی,طنز"),
     env_list("TREND_GL_COMEDY", "funny,comedy,prank")),
    ("💃 رقص", env_list("TREND_FA_DANCE", "رقص,رقص ایرانی"),
     env_list("TREND_GL_DANCE", "dance,dance challenge")),
    ("🎉 سرگرمی", env_list("TREND_FA_FUN", "سرگرمی,چالش"),
     env_list("TREND_GL_FUN", "entertainment,challenge,amazing")),
]
QUOTA = [int(x) for x in env_list("TREND_QUOTA", "3,1,1")]
COUNT = int(os.environ.get("TREND_COUNT", "10"))
FA_COUNT = int(os.environ.get("TREND_FA_COUNT", "5"))
DAYS = int(os.environ.get("TREND_DAYS", "0"))
PAGES = int(os.environ.get("TREND_PAGES", "2"))
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


def info(v):
    """توضیح مخصوص مدیر (زیر خط ➖➖➖ می‌آید و هنگام انتشار حذف می‌شود)."""
    kind = "🇮🇷 فارسی" if v["fa"] else "🌍 جهانی"
    stats = "👁 " + num(v["views"]) + " بازدید | ⏱ " + str(v["sec"]) + " ثانیه"
    return "\n".join([v["title"][:150], "🎥 " + v["channel"],
                      CATS[v["cat"]][0] + " | " + kind, stats])


async def get(c, path, **p):
    for n in range(4):
        try:
            r = await c.get(f"{API}/{path}", params=dict(p, key=KEY))
            if r.status_code != 200:
                raise RuntimeError(f"YouTube {r.status_code}: {r.text[:200]}")
            return r.json()
        except (httpx.HTTPError, RuntimeError):
            if n == 3:
                raise
            await asyncio.sleep(10)


async def search(c, q, extra, cat, ids):
    params = dict(part="snippet", type="video", q=q, order="viewCount",
                  videoDuration="short", safeSearch="strict", maxResults=50, **extra)
    if DAYS > 0:
        since = datetime.now(timezone.utc) - timedelta(days=DAYS)
        params["publishedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(PAGES):
        try:
            data = await get(c, "search", **params)
        except Exception as e:  # noqa: BLE001
            print("search failed:", q, type(e).__name__, e)
            return
        for it in data.get("items", []):
            vid = it["id"]["videoId"]
            ids[vid] = min(cat, ids.get(vid, cat))
        if not data.get("nextPageToken"):
            return
        params["pageToken"] = data["nextPageToken"]


async def candidates(c):
    ids = {}
    for cat, (_, fa_q, gl_q) in enumerate(CATS):
        for q in fa_q:
            await search(c, q, {"regionCode": "IR", "relevanceLanguage": "fa"}, cat, ids)
        for q in gl_q:
            await search(c, q, {}, cat, ids)
    out, lst = [], list(ids)
    for i in range(0, len(lst), 50):
        data = await get(c, "videos", part="snippet,contentDetails,statistics",
                         id=",".join(lst[i:i + 50]))
        for v in data.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            dur = seconds(v["contentDetails"].get("duration", ""))
            views = int(st.get("viewCount", 0) or 0)
            if not 0 < dur <= MAX_SEC or views < MIN_VIEWS:
                continue
            lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
            out.append({"id": v["id"], "title": sn.get("title", ""),
                        "channel": sn.get("channelTitle", ""), "views": views, "sec": dur,
                        "cat": ids[v["id"]],
                        "fa": persian(sn.get("title", "")) or lang.startswith("fa")})
    return out


def pick(items, n, taken):
    """سهمیه هر موضوع (کمدی/رقص/سرگرمی) بر اساس بازدید؛ کمبود با اولویت کمدی پر می‌شود."""
    pool = sorted((v for v in items if v["id"] not in taken),
                  key=lambda x: x["views"], reverse=True)
    out = []
    for cat, q in enumerate(QUOTA):
        for v in [x for x in pool if x["cat"] == cat][:q]:
            if len(out) < n:
                out.append(v)
    rest = sorted((v for v in pool if v not in out), key=lambda x: (x["cat"], -x["views"]))
    out += rest[:max(0, n - len(out))]
    for v in out:
        taken.add(v["id"])
    return out


async def main():
    seen = json.load(open(SEEN_FILE)) if os.path.exists(SEEN_FILE) else []
    async with httpx.AsyncClient(timeout=60) as c:
        fresh = [v for v in await candidates(c) if v["id"] not in seen]
        fa = [v for v in fresh if v["fa"]]
        gl = [v for v in fresh if not v["fa"]]
        taken = set()
        chosen = pick(fa, FA_COUNT, taken)
        chosen += pick(gl, COUNT - FA_COUNT, taken)
        chosen += pick(fa + gl, COUNT - len(chosen), taken)
        print("fresh:", len(fresh), "fa:", len(fa), "global:", len(gl), "chosen:", len(chosen))
        json.dump([{"id": v["id"], "info": info(v)} for v in chosen],
                  open(QUEUE_FILE, "w"), ensure_ascii=False)
        seen += [v["id"] for v in chosen]
        n_fa = sum(v["fa"] for v in chosen)
        if chosen:
            text = ("🎬 " + str(len(chosen)) + " ویدیوی پیشنهادی آماده است (" + str(n_fa)
                    + " فارسی، " + str(len(chosen) - n_fa) + " جهانی).\n"
                    "حلقه‌ی Termux آن‌ها را خودکار برایت می‌فرستد.")
        else:
            text = "ویدیوی تازه‌ای برای پیشنهاد پیدا نشد."
        await c.post(f"{TG}/sendMessage", json={"chat_id": ADMIN, "text": text})
    json.dump(seen[-3000:], open(SEEN_FILE, "w"))


asyncio.run(main())
# --- پایان فایل ---
