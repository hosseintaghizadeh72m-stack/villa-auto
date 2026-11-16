"""پیشنهاد کلیپ‌های وایرال یوتیوب به مدیر: ۸۰٪ فارسی، ۲۰٪ خارجی.
رتبه‌بندی: نیمی بیشترین بازدید، نیمی بیشترین سرعت لایک (لایک در ساعت).
خود ویدیو دانلود و با دکمه «انتشار در کانال» برای مدیر فرستاده می‌شود.
آمار زیر خط ➖➖➖ فقط برای مدیر است و poller.py هنگام انتشار حذفش می‌کند."""
import asyncio
import glob
import json
import os
import re
from datetime import datetime, timedelta, timezone
from itertools import zip_longest

import httpx
import yt_dlp

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
MARK = "➖➖➖"
KB = {"inline_keyboard": [[{"text": "📢 انتشار در کانال", "callback_data": "ok"},
                           {"text": "❌ حذف", "callback_data": "no"}]]}

FA = re.compile(r"[\u0600-\u06FF]")
EN = re.compile(r"[A-Za-z]")
DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
TAG_RE = re.compile(r"#[\w\u200c\u0600-\u06FF]+")


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
    return f"{int(n // 1000)} هزار" if n >= 1000 else str(int(n))


def to_tag(s):
    s = re.sub(r"[^\w\u200c\u0600-\u06FF]+", "_", s.strip()).strip("_")
    return f"#{s}" if s else ""


def with_tags(text, extra=()):
    """متن اصلی + هشتگ‌های خود پست + هشتگ‌های hashtags.txt، بدون تکرار."""
    try:
        mine = open("hashtags.txt", encoding="utf-8").read().split()
    except OSError:
        mine = []
    have = {t.lower() for t in TAG_RE.findall(text)}
    add = []
    for t in list(extra) + mine:
        if t and t.lower() not in have:
            have.add(t.lower())
            add.append(t)
    return (text.strip() + ("\n\n" + " ".join(add) if add else "")).strip()


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
                        "desc": sn.get("description", ""), "tags": sn.get("tags", []),
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


def download(vid):
    os.makedirs("dl", exist_ok=True)
    opts = {"format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/b",
            "merge_output_format": "mp4", "outtmpl": f"dl/{vid}.%(ext)s", "quiet": True,
            "no_warnings": True, "noplaylist": True, "max_filesize": 48 * 1024 * 1024}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"https://www.youtube.com/shorts/{vid}", download=True)
        files = glob.glob(f"dl/{vid}.*")
        if files:
            return files[0], info.get("width"), info.get("height")
    except Exception as e:  # noqa: BLE001
        print("download failed:", vid, str(e)[:300])
    return None, None, None


async def send(c, v):
    tags = TAG_RE.findall(v["title"] + " " + v["desc"]) + [to_tag(t) for t in v["tags"][:6]]
    tags = [t for t in tags if t][:8]
    path, w, h = await asyncio.to_thread(download, v["id"])
    link = "" if path else f"\n🎬 https://youtu.be/{v['id']}"
    clean = with_tags(f"{v['title']}\n\n🎥 منبع: {v['channel']}{link}", tags)
    stats = (f"\n\n{MARK}\n📊 فقط برای تو (در کانال نمی‌آید)\n"
             f"{v['why']} | {'🇮🇷 فارسی' if v['fa'] else '🌍 خارجی'}"
             f"{'' if path else ' | ⚠️ دانلود نشد'}\n"
             f"👁 {num(v['views'])} | ❤️ {num(v['likes'])} | ⚡ {num(v['vel'])} لایک در ساعت | ⏱ {v['sec']} ثانیه\n"
             f"▶️ https://youtu.be/{v['id']}")
    cap = clean[:1024 - len(stats) - 1] + stats
    if path:
        data = {"chat_id": ADMIN, "caption": cap, "reply_markup": json.dumps(KB),
                "supports_streaming": "true", "duration": str(v["sec"])}
        if w and h:
            data.update(width=str(w), height=str(h))
        try:
            with open(path, "rb") as f:
                r = await c.post(f"{TG}/sendVideo", data=data, timeout=300,
                                 files={"video": (f"{v['id']}.mp4", f, "video/mp4")})
            print(v["id"], "video", r.status_code, r.text[:150])
            if r.status_code == 200:
                return True
        finally:
            os.remove(path)
        return await send_photo(c, v, with_tags(f"{v['title']}\n\n🎥 منبع: {v['channel']}\n🎬 https://youtu.be/{v['id']}", tags), stats)
    return await send_photo(c, v, clean, stats)


async def send_photo(c, v, clean, stats):
    cap = clean[:1024 - len(stats) - 1] + stats
    r = await c.post(f"{TG}/sendPhoto", json={
        "chat_id": ADMIN, "photo": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
        "caption": cap, "reply_markup": KB})
    print(v["id"], "photo", r.status_code)
    return r.status_code == 200


async def main():
    seen = json.load(open(SEEN_FILE)) if os.path.exists(SEEN_FILE) else []
    async with httpx.AsyncClient(timeout=60) as c:
        fresh = [v for v in await candidates(c) if v["id"] not in seen]
        fa = [v for v in fresh if v["fa"]]
        gl = [v for v in fresh if not v["fa"]]
        taken = set()
        chosen = pick(fa, round(COUNT * FA_SHARE), taken)
        chosen += pick(gl, COUNT - len(chosen), taken)
        chosen += pick(fa, COUNT - len(chosen), taken)  # اگر خارجی کم بود، با فارسی پر شود
        print("fresh:", len(fresh), "fa:", len(fa), "global:", len(gl), "chosen:", len(chosen))
        n_fa = sum(v["fa"] for v in chosen)
        text = (f"🎬 {len(chosen)} پیشنهاد تازه ({n_fa} فارسی، {len(chosen) - n_fa} خارجی). "
                "ویدیوها یکی‌یکی می‌رسند…") if chosen else "کلیپ تازه‌ای برای پیشنهاد پیدا نشد."
        await c.post(f"{TG}/sendMessage", json={"chat_id": ADMIN, "text": text})
        for v in chosen:
            try:
                if await send(c, v):
                    seen.append(v["id"])
            except Exception as e:  # noqa: BLE001
                print("send failed:", v["id"], type(e).__name__, e)
    json.dump(seen[-500:], open(SEEN_FILE, "w"))


asyncio.run(main())
