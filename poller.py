"""پردازش پیام‌ها و دکمه‌های مدیر (هر ۱۰ دقیقه توسط GitHub Actions).
پست یوتیوب در کانال: پخش‌کننده‌ی ویدیو بالا و فقط هشتگ‌های خودمان (hashtags.txt) زیرش.
لینک، منبع و هشتگ‌های خود یوتیوب در متن کانال نمی‌آید."""
import asyncio
import os
import re

import httpx

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN = int(os.environ["ADMIN_ID"])
CHANNEL = os.environ["CHANNEL_ID"]
TG = f"https://api.telegram.org/bot{TOKEN}"

URL_RE = re.compile(r"https?://\S+")
YT_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})")
IG_RE = re.compile(r"instagram\.com/")
TAG_RE = re.compile(r"#[\w\u200c\u0600-\u06FF]+")
ANCHOR_RE = re.compile(r"🎬 https://youtu\.be/[\w-]{11}")
MARK = "➖➖➖"
DONE = set()  # جلوگیری از انتشار تکراری وقتی یک دکمه چند بار زده شود

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


def yt_url(s):
    """اولین لینک یوتیوب داخل متن را به شکل youtu.be برمی‌گرداند (یا رشته‌ی خالی)."""
    m = YT_RE.search(s or "")
    return f"https://youtu.be/{m.group(1)}" if m else ""


def preview(link):
    """پخش‌کننده‌ی ویدیو بالای متن نمایش داده شود."""
    return {"url": link, "show_above_text": True}


def with_tags(text, extra=()):
    """متن اصلی + هشتگ‌های ما؛ بدون تکرار."""
    text = (text or "").strip()
    have = {t.lower() for t in TAG_RE.findall(text)}
    add = []
    for t in list(extra) + my_tags():
        if t.lower() not in have:
            have.add(t.lower())
            add.append(t)
    return (text + ("\n\n" + " ".join(add) if add else "")).strip()


def channel_text(txt):
    """متن نهایی کانال برای پست یوتیوب: فقط هشتگ‌های ما (و متن دلخواه مدیر اگر ریپلای کرده)."""
    txt = txt.split(MARK)[0].strip()
    first, _, rest = txt.partition("\n")
    body = rest.strip() if ANCHOR_RE.fullmatch(first.strip()) else ""
    return body or " ".join(my_tags()) or "🎬"


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
        extra = {}
        link = yt_url(caption)
        if link:
            extra["link_preview_options"] = preview(link)
        return await tg(c, "sendMessage", chat_id=ADMIN, text=caption[:4000], reply_markup=KB, **extra)
    if len(caption) > 1024:
        await say(c, "⚠️ کپشن از ۱۰۲۴ حرف بیشتر است و کوتاه شد؛ با ریپلای می‌توانی اصلاحش کنی.")
        caption = caption[:1021] + "…"
    field = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation"}[kind]
    return await tg(c, field, chat_id=ADMIN, **{kind: file}, caption=caption, reply_markup=KB)


async def youtube_draft(c, vid, extra=""):
    """خط اول (🎬 لینک) فقط برای مدیر است و هنگام انتشار حذف می‌شود."""
    text = f"🎬 https://youtu.be/{vid}" + (f"\n\n{extra}" if extra else "")
    await send_draft(c, with_tags(text))


async def on_message(c, m):
    text = m.get("text") or m.get("caption") or ""
    reply = m.get("reply_to_message")
    if text.startswith("/"):
        return await say(c, HELP)
    # ریپلای روی پیش‌نویس = تعویض متن (لینک یوتیوب پیش‌نویس حفظ می‌شود)
    if reply and reply.get("from", {}).get("is_bot") and reply.get("reply_markup") and m.get("text"):
        if reply.get("text"):
            link = yt_url(reply["text"])
            body = f"🎬 {link}\n\n{text.replace(link, '').strip()}" if link else text
            extra = {"link_preview_options": preview(link)} if link else {}
            await tg(c, "editMessageText", chat_id=ADMIN, message_id=reply["message_id"],
                     text=with_tags(body)[:4000], reply_markup=KB, **extra)
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
    if d in ("ok", "no"):
        if mid in DONE:
            return
        DONE.add(mid)
    if d == "ok":
        # اول دکمه‌ها را برمی‌داریم تا دوبار منتشر نشود
        await tg(c, "editMessageReplyMarkup", chat_id=ADMIN, message_id=mid, reply_markup={"inline_keyboard": []})
        cap = m.get("caption")
        if m.get("text"):
            txt = m["text"]
            link = yt_url(txt)
            if link:
                # پست یوتیوب: پخش‌کننده بالا، فقط هشتگ‌های ما پایین
                r = await tg(c, "sendMessage", chat_id=CHANNEL, text=channel_text(txt)[:4000],
                             link_preview_options=preview(link))
            else:
                r = await tg(c, "sendMessage", chat_id=CHANNEL, text=txt.split(MARK)[0].strip()[:4000])
        elif cap and MARK in cap:  # آمار مخصوص مدیر حذف شود
            r = await tg(c, "copyMessage", chat_id=CHANNEL, from_chat_id=ADMIN, message_id=mid,
                         caption=cap.split(MARK)[0].strip())
        else:
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
        info = (await tg(c, "getWebhookInfo")).get("result", {})
        print("pending:", info.get("pending_update_count"), "webhook:", bool(info.get("url")))
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
