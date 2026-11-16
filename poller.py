"""پردازش پیام‌ها و دکمه‌های مدیر (هر ۱۰ دقیقه توسط GitHub Actions).
محتوا بدون هیچ تغییری (کپشن اصلی) منتشر می‌شود و فقط هشتگ‌های خودمان (hashtags.txt)
به انتهایش اضافه می‌شود. هشتگ‌های خود پست هم حفظ می‌شود."""
import asyncio
import os
import re

import httpx

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN = int(os.environ["ADMIN_ID"])
CHANNEL = os.environ["CHANNEL_ID"]
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
TG = f"https://api.telegram.org/bot{TOKEN}"

URL_RE = re.compile(r"https?://\S+")
YT_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})")
IG_RE = re.compile(r"instagram\.com/")
TAG_RE = re.compile(r"#[\w\u200c\u0600-\u06FF]+")

HELP = ("سلام 👋\nبرای ساخت پست:\n"
        "• ویدیو/عکس را (حتی فوروارد شده از اینستاگرام یا کانال دیگر) با کپشنش بفرست\n"
        "• لینک یوتیوب بفرست\n"
        "• لینک اینستاگرام را همراه متن کپشنش بفرست\n"
        "• یا یک متن بنویس\n"
        "کپشن بدون تغییر می‌ماند و هشتگ‌های ما به آخرش اضافه می‌شود.\n"
        "روی پیش‌نویس ریپلای کنی و متن بنویسی، کپشن با همان متن عوض می‌شود.")


def my_tags():
    try:
        return open("hashtags.txt", encoding="utf-8").read().split()
    except OSError:
        return []


def with_tags(text, extra=()):
    """متن اصلی + هشتگ‌های پست (extra) + هشتگ‌های ما؛ بدون تکرار."""
    text = (text or "").strip()
    have = {t.lower() for t in TAG_RE.findall(text)}
    add = []
    for t in list(extra) + my_tags():
        if t.lower() not in have:
            have.add(t.lower())
            add.append(t)
    return (text + ("\n\n" + " ".join(add) if add else "")).strip()


async def tg(c, method, **p):
    r = await c.post(f"{TG}/{method}", json=p)
    data = r.json()
    if not data.get("ok"):
        print("tg error", method, data.get("description"))
    return data


KB = {"inline_keyboard": [[{"text": "✅ انتشار در کانال", "callback_data": "ok"},
                           {"text": "❌ حذف", "callback_data": "no"}]]}


async def say(c, text):
    await tg(c, "sendMessage", chat_id=ADMIN, text=text, disable_web_page_preview=True)


async def send_draft(c, caption, kind="text", file=None):
    if kind == "text":
        return await tg(c, "sendMessage", chat_id=ADMIN, text=caption[:4000], reply_markup=KB)
    if len(caption) > 1024:
        await say(c, "⚠️ کپشن از ۱۰۲۴ حرف بیشتر است و کوتاه شد؛ با ریپلای می‌توانی اصلاحش کنی.")
        caption = caption[:1021] + "…"
    field = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation"}[kind]
    return await tg(c, field, chat_id=ADMIN, **{kind: file}, caption=caption, reply_markup=KB)


def to_tag(s):
    s = re.sub(r"[^\w\u200c\u0600-\u06FF]+", "_", s.strip()).strip("_")
    return f"#{s}" if s else ""


async def youtube_info(c, vid):
    """عنوان، کانال و هشتگ‌های خود ویدیو (از API یا oembed)."""
    if YT_KEY:
        r = await c.get("https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "snippet", "id": vid, "key": YT_KEY})
        if r.status_code == 200 and r.json().get("items"):
            sn = r.json()["items"][0]["snippet"]
            tags = TAG_RE.findall(sn.get("title", "") + " " + sn.get("description", ""))
            tags += [to_tag(t) for t in sn.get("tags", [])[:6]]
            return sn.get("title", ""), [t for t in tags if t][:8]
    r = await c.get("https://www.youtube.com/oembed",
                    params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
    return (r.json().get("title", "") if r.status_code == 200 else ""), []


async def youtube_draft(c, vid, extra=""):
    url = f"https://www.youtube.com/watch?v={vid}"
    title, tags = await youtube_info(c, vid)
    body = extra or title
    await send_draft(c, with_tags(f"{body}\n\n🎬 {url}", tags), "photo",
                     f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
