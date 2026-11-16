import asyncio
import os
from datetime import datetime
import httpx

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


LAT, LON = "36.74", "53.10"
PLACE = "فرح‌آباد ساری"
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
fa = lambda x: str(x).translate(FA)

WMO = {0: ("آفتابی", "☀️"), 1: ("نیمه‌صاف", "🌤"), 2: ("کمی ابری", "⛅"), 3: ("ابری", "☁️"),
       45: ("مه‌آلود", "🌫"), 48: ("مه‌آلود", "🌫"), 51: ("نم‌نم باران", "🌦"), 53: ("نم‌نم باران", "🌦"),
       55: ("نم‌نم باران", "🌦"), 61: ("بارانی", "🌧"), 63: ("بارانی", "🌧"), 65: ("باران شدید", "🌧"),
       71: ("برفی", "🌨"), 73: ("برفی", "🌨"), 75: ("برف سنگین", "❄️"), 80: ("رگبار", "🌦"),
       81: ("رگبار", "🌦"), 82: ("رگبار شدید", "⛈"), 95: ("رعدوبرق", "⛈"), 96: ("رعدوبرق و تگرگ", "⛈"),
       99: ("رعدوبرق و تگرگ", "⛈")}


async def _meteo(c):
    r = await c.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": LAT, "longitude": LON, "timezone": "Asia/Tehran", "forecast_days": 5,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"})
    r.raise_for_status()
    d = r.json()["daily"]
    out = []
    for i, dt in enumerate(d["time"]):
        t, e = WMO.get(d["weather_code"][i], ("متغیر", "🌤"))
        out.append(dict(date=dt, tmax=d["temperature_2m_max"][i], tmin=d["temperature_2m_min"][i], text=t, icon=e,
                        rain=d["precipitation_probability_max"][i] or 0, wind=d["wind_speed_10m_max"][i]))
    return out


def _day(s):
    dt = datetime.strptime(s, "%Y-%m-%d")
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{WEEKDAYS[dt.weekday()]} {fa(jd)} {MONTHS[jm - 1]}"


def advice(t):
    if t["rain"] >= 50: return "☔ چتر یادت نره!"
    if t["tmax"] >= 32: return "🥵 هوا گرمه؛ آب زیاد بخور و کرم ضدآفتاب یادت نره."
    if t["tmax"] <= 10: return "🧥 هوا سرده؛ لباس گرم بپوش."
    if t["wind"] >= 35: return "💨 باد تنده؛ حواست به وسایل بیرون باشه."
    return "😎 هوای امروز عالیه؛ از روزت لذت ببر!"


async def build():
    async with httpx.AsyncClient(timeout=40) as c:
        days = await _meteo(c)
    t = days[0]
    lines = [f"🌤 <b>آب‌وهوای امروز {PLACE}</b>", f"📅 {_day(t['date'])}", "",
             f"{t['icon']} <b>{t['text']}</b>",
             f"🌡 {fa(round(t['tmin']))}° تا {fa(round(t['tmax']))}° درجه",
             f"🌧 احتمال بارش: {fa(round(t['rain']))}٪",
             f"💨 باد: تا {fa(round(t['wind']))} کیلومتر بر ساعت", "", advice(t), "", "📆 <b>روزهای بعد</b>"]
    for d in days[1:]:
        lines.append(f"{d['icon']} {_day(d['date']).rsplit(' ', 2)[0]}: {fa(round(d['tmin']))}° / {fa(round(d['tmax']))}°  {d['text']}")
    lines += ["", "<i>منبع: Open-Meteo</i>", "#آب_و_هوا #فرح_آباد"]
    return "\n".join(lines)


async def main():
    text = await build()
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={"chat_id": os.environ["CHANNEL_ID"], "text": text, "parse_mode": "HTML"})
        print(r.status_code, r.text[:200])
        r.raise_for_status()


asyncio.run(main())
