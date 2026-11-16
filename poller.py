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

async def on_message(c, m):
    text = m.get("text") or m.get("caption") or ""
    reply = m.get("reply_to_message")
    if text.startswith("/"):
        return await say(c, HELP)
    # ریپلای روی پیش‌نویس = تعویض کپشن
    if reply and reply.get("from", {}).get("is_bot") and reply.get("reply_markup") and m.get("text"):
        if reply.get("text"):
            await tg(c, "editMessageText", chat_id=ADMIN, message_id=reply["message_id"],
                     text=with_tags(text)[:4000], reply_markup=KB)
        else:
            await tg(c, "editMessageCaption", chat_id=ADMIN, message_id=reply["message_id"],
                     caption=with_tags(text)[:1024], reply_markup=KB)
        return
    urls = URL_RE.findall(text)
    rest = URL_RE.sub("", text).strip()
    for k in ("photo", "video", "animation"):
        if m.get(k):
            f = m[k][-1]["file_id"] if k == "photo" else m[k]["file_id"]
            return await send_draft(c, with_tags(text), k, f)
    for u in urls:
        mm = YT_RE.search(u)
        if mm:
            return await youtube_draft(c, mm.group(1), rest)
    for u in urls:
        if IG_RE.search(u):
            if len(rest) < 10:
                return await say(c, "از لینک اینستاگرام نمی‌توانم ویدیو بگیرم. خود ویدیو را فوروارد کن، "
                                    "یا لینک را با متن کپشنش بفرست.")
            return await send_draft(c, with_tags(rest))
    if text.strip():
        return await send_draft(c, with_tags(text))


async def on_callback(c, q):
    m, d = q["message"], q["data"]
    mid = m["message_id"]
    await tg(c, "answerCallbackQuery", callback_query_id=q["id"])
    if d == "ok":
        # اول دکمه‌ها را برمی‌داریم تا دوبار منتشر نشود
        await tg(c, "editMessageReplyMarkup", chat_id=ADMIN, message_id=mid, reply_markup={"inline_keyboard": []})
        r = await tg(c, "copyMessage", chat_id=CHANNEL, from_chat_id=ADMIN, message_id=mid)
        await say(c, "✅ در کانال منتشر شد." if r.get("ok") else f"❌ انتشار نشد: {r.get('description')}")
    elif d == "no":
        await tg(c, "deleteMessage", chat_id=ADMIN, message_id=mid)
    elif d.startswith("yd:"):
        await tg(c, "editMessageReplyMarkup", chat_id=ADMIN, message_id=mid, reply_markup={"inline_keyboard": []})
        await youtube_draft(c, d[3:])


async def main():
    async with httpx.AsyncClient(timeout=40) as c:
        data = await tg(c, "getUpdates", timeout=0, allowed_updates=["message", "callback_query"])
        ups = data.get("result", [])
        print("updates:", len(ups))
        for u in ups:
            try:
                if "callback_query" in u and u["callback_query"]["from"]["id"] == ADMIN:
                    await on_callback(c, u["callback_query"])
                elif "message" in u and u["message"]["from"]["id"] == ADMIN:
                    await on_message(c, u["message"])
            except Exception as e:  # noqa: BLE001
                print("error:", type(e).__name__, e)
                await say(c, f"❌ خطا: {str(e)[:300]}")
        if ups:
            await tg(c, "getUpdates", offset=ups[-1]["update_id"] + 1, timeout=0)


asyncio.run(main())

