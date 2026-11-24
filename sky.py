import asyncio
import httpx
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3, minutes=30))
HRS = range(6, 21)
SKY = ["صاف", "کمی ابری", "قسمتی ابری", "ابری", "بارش پراکنده", "بارانی", "باران شدید", "رعدوبرق"]
ICON = ["☀️", "🌤", "⛅", "☁️", "🌦", "🌧", "🌧", "⛈"]


def lvl(rows):
    if not rows:
        return None
    cl = sum(r[0] for r in rows) / len(rows)
    mm = sum(r[1] for r in rows)
    if any(r[2] for r in rows):
        return 7
    for i, lim in ((6, 10), (5, 2), (4, 0.2)):
        if mm >= lim:
            return i
    return 0 if cl < 12.5 else 1 if cl < 37.5 else 2 if cl < 75 else 3


def merge(a, b):
    lo, hi = sorted((a, b))
    if lo == hi:
        i = lo
        return SKY[i], ICON[i], i
    if lo <= 2 and hi >= 4:
        return "قسمتی ابری با احتمال بارش", "🌦", 4
    if hi - lo == 1:
        return f"{SKY[lo]} تا {SKY[hi]}", ICON[hi], hi
    i = (lo + hi + 1) // 2
    return SKY[i], ICON[i], i


async def get(url, params, headers=None):
    for k in range(3):
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as c:
                r = await c.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, ValueError) as e:
            print("sky: تلاش", k + 1, "ناموفق", type(e).__name__, flush=True)
            if k < 2:
                await asyncio.sleep(5 * 3 ** k)


async def om(day, lat, lon):
    j = await get("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "Asia/Tehran", "forecast_days": 1,
        "hourly": "cloud_cover,precipitation,weather_code"})
    if not j:
        return None
    h = j["hourly"]
    rows = [(h["cloud_cover"][i] or 0, h["precipitation"][i] or 0, (h["weather_code"][i] or 0) >= 95)
            for i, s in enumerate(h["time"]) if s[:10] == day and int(s[11:13]) in HRS]
    return lvl(rows)


async def met(day, lat, lon):
    j = await get("https://api.met.no/weatherapi/locationforecast/2.0/compact",
                  {"lat": lat, "lon": lon}, {"User-Agent": "FarahabadWeatherBot/1.0"})
    if not j:
        return None
    rows = []
    for x in j["properties"]["timeseries"]:
        t = datetime.strptime(x["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
        n = x["data"].get("next_1_hours")
        if n and t.strftime("%Y-%m-%d") == day and t.hour in HRS:
            rows.append((x["data"]["instant"]["details"].get("cloud_area_fraction", 0),
                         n.get("details", {}).get("precipitation_amount", 0) or 0,
                         "thunder" in n["summary"]["symbol_code"]))
    return lvl(rows)


async def today(day, lat, lon):
    a, b = await asyncio.gather(om(day, lat, lon), met(day, lat, lon))
    print("sky: open-meteo =", a, "met.no =", b, flush=True)
    v = [x for x in (a, b) if x is not None]
    if not v:
        return {}
    text, icon, i = merge(v[0], v[-1])
    return {"text": text, "icon": icon, "lvl": i}
