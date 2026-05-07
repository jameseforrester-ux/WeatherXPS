#!/usr/bin/env python3
"""
WeatherEdge v3 — Polymarket Weather Trading Bot
Complete rebuild with verified resolution stations, dynamic market fetching,
bracket-aware analysis, and clean UI.
"""

import os, io, re, json, math, asyncio, html, requests, requests.utils
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OW_KEY         = os.getenv("OPENWEATHER_KEY", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_KEY", "")

# ─────────────────────────────────────────────────────────────────────────────
# CITY DATABASE
# Keys = city slug as it appears in Polymarket event slugs
# e.g. "highest-temperature-in-nyc-on-..." → key = "nyc"
# confirmed = True  → resolution station verified directly from Polymarket rules
# confirmed = False → high-confidence inference from standard airport codes
# ─────────────────────────────────────────────────────────────────────────────
CITY_DB: Dict[str, Dict] = {
    # United States  (°F, 2°F brackets) ──────────────────────────────────────
    "nyc":           {"display":"New York City",  "flag":"🇺🇸", "metar":"KLGA","station":"LaGuardia Airport",              "lat":40.7769,"lon":-73.8740,"tz":"America/New_York",    "unit":"F","ok":True },
    "dallas":        {"display":"Dallas",          "flag":"🇺🇸", "metar":"KDAL","station":"Dallas Love Field",               "lat":32.8471,"lon":-96.8518,"tz":"America/Chicago",     "unit":"F","ok":True },
    "chicago":       {"display":"Chicago",         "flag":"🇺🇸", "metar":"KORD","station":"O'Hare International",            "lat":41.9742,"lon":-87.9073,"tz":"America/Chicago",     "unit":"F","ok":True },
    "miami":         {"display":"Miami",           "flag":"🇺🇸", "metar":"KMIA","station":"Miami International",             "lat":25.7959,"lon":-80.2870,"tz":"America/New_York",    "unit":"F","ok":True },
    "los-angeles":   {"display":"Los Angeles",     "flag":"🇺🇸", "metar":"KLAX","station":"LAX International",               "lat":33.9425,"lon":-118.408,"tz":"America/Los_Angeles", "unit":"F","ok":True },
    "seattle":       {"display":"Seattle",         "flag":"🇺🇸", "metar":"KSEA","station":"Seattle-Tacoma Intl",             "lat":47.4502,"lon":-122.309,"tz":"America/Los_Angeles", "unit":"F","ok":True },
    "san-francisco": {"display":"San Francisco",   "flag":"🇺🇸", "metar":"KSFO","station":"SFO International",               "lat":37.6213,"lon":-122.379,"tz":"America/Los_Angeles", "unit":"F","ok":True },
    "atlanta":       {"display":"Atlanta",         "flag":"🇺🇸", "metar":"KATL","station":"Hartsfield-Jackson",              "lat":33.6407,"lon":-84.4277,"tz":"America/New_York",    "unit":"F","ok":True },
    "houston":       {"display":"Houston",         "flag":"🇺🇸", "metar":"KHOU","station":"Hobby Airport",                   "lat":29.6454,"lon":-95.2789,"tz":"America/Chicago",     "unit":"F","ok":True },
    "denver":        {"display":"Denver",          "flag":"🇺🇸", "metar":"KBKF","station":"Buckley Space Force Base",        "lat":39.7168,"lon":-104.752,"tz":"America/Denver",      "unit":"F","ok":True },
    "austin":        {"display":"Austin",          "flag":"🇺🇸", "metar":"KAUS","station":"Austin-Bergstrom Intl",           "lat":30.1975,"lon":-97.6664,"tz":"America/Chicago",     "unit":"F","ok":False},
    # Europe  (°C, 1°C brackets) ──────────────────────────────────────────────
    "london":        {"display":"London",          "flag":"🇬🇧", "metar":"EGLC","station":"London City Airport",             "lat":51.5048,"lon":  0.0495,"tz":"Europe/London",       "unit":"C","ok":True },
    "paris":         {"display":"Paris",           "flag":"🇫🇷", "metar":"LFPB","station":"Paris-Le Bourget",                "lat":48.9694,"lon":  2.4411,"tz":"Europe/Paris",        "unit":"C","ok":True },
    "amsterdam":     {"display":"Amsterdam",       "flag":"🇳🇱", "metar":"EHAM","station":"Amsterdam Schiphol",              "lat":52.3105,"lon":  4.7683,"tz":"Europe/Amsterdam",    "unit":"C","ok":True },
    "madrid":        {"display":"Madrid",          "flag":"🇪🇸", "metar":"LEMD","station":"Adolfo Suárez Barajas",           "lat":40.4719,"lon": -3.5620,"tz":"Europe/Madrid",       "unit":"C","ok":True },
    "munich":        {"display":"Munich",          "flag":"🇩🇪", "metar":"EDDM","station":"Munich Airport",                  "lat":48.3537,"lon": 11.7750,"tz":"Europe/Berlin",       "unit":"C","ok":True },
    "istanbul":      {"display":"Istanbul",        "flag":"🇹🇷", "metar":"LTFM","station":"Istanbul Airport",                "lat":41.2753,"lon": 28.7519,"tz":"Europe/Istanbul",     "unit":"C","ok":True },
    "warsaw":        {"display":"Warsaw",          "flag":"🇵🇱", "metar":"EPWA","station":"Warsaw Chopin Airport",           "lat":52.1657,"lon": 20.9671,"tz":"Europe/Warsaw",       "unit":"C","ok":True },
    "milan":         {"display":"Milan",           "flag":"🇮🇹", "metar":"LIML","station":"Milan Linate Airport",            "lat":45.4654,"lon":  9.2768,"tz":"Europe/Rome",         "unit":"C","ok":False},
    "helsinki":      {"display":"Helsinki",        "flag":"🇫🇮", "metar":"EFHK","station":"Helsinki-Vantaa Airport",         "lat":60.3172,"lon": 24.9633,"tz":"Europe/Helsinki",     "unit":"C","ok":False},
    "moscow":        {"display":"Moscow",          "flag":"🇷🇺", "metar":"UUEE","station":"Sheremetyevo Airport",            "lat":55.9726,"lon": 37.4146,"tz":"Europe/Moscow",       "unit":"C","ok":False},
    "ankara":        {"display":"Ankara",          "flag":"🇹🇷", "metar":"LTAE","station":"Esenboğa Airport",                "lat":40.1281,"lon": 32.9951,"tz":"Europe/Istanbul",     "unit":"C","ok":False},
    # Asia-Pacific  (°C, 1°C brackets) ────────────────────────────────────────
    "tokyo":         {"display":"Tokyo",           "flag":"🇯🇵", "metar":"RJTT","station":"Tokyo Haneda Airport",            "lat":35.5494,"lon":139.7798,"tz":"Asia/Tokyo",          "unit":"C","ok":True },
    "seoul":         {"display":"Seoul",           "flag":"🇰🇷", "metar":"RKSI","station":"Incheon International",           "lat":37.4631,"lon":126.4400,"tz":"Asia/Seoul",          "unit":"C","ok":True },
    "hong-kong":     {"display":"Hong Kong",       "flag":"🇭🇰", "metar":"VHHH","station":"HK International Airport",        "lat":22.3080,"lon":113.9185,"tz":"Asia/Hong_Kong",      "unit":"C","ok":True },
    "taipei":        {"display":"Taipei",          "flag":"🇹🇼", "metar":"RCSS","station":"Taipei Songshan Airport",         "lat":25.0694,"lon":121.5522,"tz":"Asia/Taipei",         "unit":"C","ok":True },
    "shanghai":      {"display":"Shanghai",        "flag":"🇨🇳", "metar":"ZSPD","station":"Shanghai Pudong Intl",            "lat":31.1443,"lon":121.8083,"tz":"Asia/Shanghai",       "unit":"C","ok":True },
    "beijing":       {"display":"Beijing",         "flag":"🇨🇳", "metar":"ZBAA","station":"Beijing Capital Intl",            "lat":40.0801,"lon":116.5847,"tz":"Asia/Shanghai",       "unit":"C","ok":True },
    "singapore":     {"display":"Singapore",       "flag":"🇸🇬", "metar":"WSSS","station":"Changi Airport",                  "lat": 1.3502,"lon":103.9940,"tz":"Asia/Singapore",      "unit":"C","ok":True },
    "shenzhen":      {"display":"Shenzhen",        "flag":"🇨🇳", "metar":"ZGSZ","station":"Shenzhen Bao'an Intl",            "lat":22.6393,"lon":113.8107,"tz":"Asia/Shanghai",       "unit":"C","ok":True },
    "busan":         {"display":"Busan",           "flag":"🇰🇷", "metar":"RKPK","station":"Gimhae International",            "lat":35.1795,"lon":128.9383,"tz":"Asia/Seoul",          "unit":"C","ok":False},
    "chongqing":     {"display":"Chongqing",       "flag":"🇨🇳", "metar":"ZUCK","station":"Chongqing Jiangbei Intl",         "lat":29.7192,"lon":106.6414,"tz":"Asia/Shanghai",       "unit":"C","ok":False},
    "wuhan":         {"display":"Wuhan",           "flag":"🇨🇳", "metar":"ZHHH","station":"Wuhan Tianhe Intl",               "lat":30.7839,"lon":114.2080,"tz":"Asia/Shanghai",       "unit":"C","ok":False},
    "chengdu":       {"display":"Chengdu",         "flag":"🇨🇳", "metar":"ZUUU","station":"Chengdu Shuangliu Intl",          "lat":30.5784,"lon":103.9473,"tz":"Asia/Shanghai",       "unit":"C","ok":False},
    "guangzhou":     {"display":"Guangzhou",       "flag":"🇨🇳", "metar":"ZGGG","station":"Guangzhou Baiyun Intl",           "lat":23.3924,"lon":113.2990,"tz":"Asia/Shanghai",       "unit":"C","ok":False},
    "qingdao":       {"display":"Qingdao",         "flag":"🇨🇳", "metar":"ZSQD","station":"Qingdao Jiaodong Intl",           "lat":36.2661,"lon":120.3742,"tz":"Asia/Shanghai",       "unit":"C","ok":False},
    "jakarta":       {"display":"Jakarta",         "flag":"🇮🇩", "metar":"WIII","station":"Soekarno-Hatta Intl",             "lat":-6.1257,"lon":106.6556,"tz":"Asia/Jakarta",        "unit":"C","ok":False},
    "kuala-lumpur":  {"display":"Kuala Lumpur",    "flag":"🇲🇾", "metar":"WMKK","station":"KLIA",                             "lat": 2.7456,"lon":101.7099,"tz":"Asia/Kuala_Lumpur",   "unit":"C","ok":False},
    "manila":        {"display":"Manila",          "flag":"🇵🇭", "metar":"RPLL","station":"Ninoy Aquino Intl",                "lat":14.5086,"lon":121.0197,"tz":"Asia/Manila",         "unit":"C","ok":False},
    "lucknow":       {"display":"Lucknow",         "flag":"🇮🇳", "metar":"VILK","station":"Chaudhary Charan Singh Intl",     "lat":26.7606,"lon": 80.8893,"tz":"Asia/Kolkata",        "unit":"C","ok":False},
    "jeddah":        {"display":"Jeddah",          "flag":"🇸🇦", "metar":"OEJN","station":"King Abdulaziz Intl",             "lat":21.6796,"lon": 39.1564,"tz":"Asia/Riyadh",         "unit":"C","ok":False},
    "karachi":       {"display":"Karachi",         "flag":"🇵🇰", "metar":"OPKC","station":"Jinnah International",            "lat":24.9008,"lon": 67.1681,"tz":"Asia/Karachi",        "unit":"C","ok":False},
    "tel-aviv":      {"display":"Tel Aviv",        "flag":"🇮🇱", "metar":"LLBG","station":"Ben Gurion Airport",              "lat":32.0114,"lon": 34.8867,"tz":"Asia/Jerusalem",      "unit":"C","ok":False},
    # Americas & Oceania ──────────────────────────────────────────────────────
    "toronto":       {"display":"Toronto",         "flag":"🇨🇦", "metar":"CYYZ","station":"Pearson International",           "lat":43.6772,"lon": -79.631,"tz":"America/Toronto",     "unit":"C","ok":True },
    "wellington":    {"display":"Wellington",      "flag":"🇳🇿", "metar":"NZWN","station":"Wellington International",        "lat":-41.327,"lon":174.8052,"tz":"Pacific/Auckland",    "unit":"C","ok":True },
    "buenos-aires":  {"display":"Buenos Aires",    "flag":"🇦🇷", "metar":"SAEZ","station":"Ministro Pistarini Intl",         "lat":-34.822,"lon": -58.536,"tz":"America/Argentina/Buenos_Aires","unit":"C","ok":True },
    "mexico-city":   {"display":"Mexico City",     "flag":"🇲🇽", "metar":"MMMX","station":"Benito Juárez Intl",              "lat":19.4363,"lon": -99.072,"tz":"America/Mexico_City", "unit":"C","ok":False},
    "sao-paulo":     {"display":"Sao Paulo",       "flag":"🇧🇷", "metar":"SBSP","station":"Congonhas Airport",               "lat":-23.627,"lon": -46.657,"tz":"America/Sao_Paulo",   "unit":"C","ok":False},
    "panama-city":   {"display":"Panama City",     "flag":"🇵🇦", "metar":"MPTO","station":"Tocumen International",           "lat": 9.0714,"lon": -79.384,"tz":"America/Panama",      "unit":"C","ok":False},
    # Africa ──────────────────────────────────────────────────────────────────
    "lagos":         {"display":"Lagos",           "flag":"🇳🇬", "metar":"DNMM","station":"Murtala Muhammed Intl",           "lat": 6.5774,"lon":  3.3212,"tz":"Africa/Lagos",         "unit":"C","ok":False},
    "cape-town":     {"display":"Cape Town",       "flag":"🇿🇦", "metar":"FACT","station":"Cape Town International",         "lat":-33.965,"lon": 18.6017,"tz":"Africa/Johannesburg",  "unit":"C","ok":False},
}

# ─────────────────────────────────────────────────────────────────────────────
# USER STATE
# ─────────────────────────────────────────────────────────────────────────────
user_states: Dict[int, Dict] = {}

def get_state(cid: int) -> Dict:
    if cid not in user_states:
        user_states[cid] = {
            "active":       None,   # dict: city_key, market_type, target_date, poly_brackets
            "budget":       30.0,
            "stop_loss":    50,
            "center_override": None,
            "mkt_prices":   {},     # {bracket_label: yes_price}
            "data":         {"hrrr":None,"ecmwf":None,"ow":None,"metar":None},
            "markets_page": 0,
            "cached_events":None,
        }
    return user_states[cid]

# ─────────────────────────────────────────────────────────────────────────────
# FORMATTING HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def b(s):    return "<b>" + str(s) + "</b>"
def it(s):   return "<i>" + str(s) + "</i>"
def c(s):    return "<code>" + html.escape(str(s)) + "</code>"
def esc(s):  return html.escape(str(s))

DIV  = "━" * 28
SDIV = "─" * 28

def bar(v, mx=100, w=12):
    f = max(0, min(w, round(v / mx * w)))
    return "█" * f + "░" * (w - f)

def conf_icon(score):
    return "🟢" if score >= 70 else "🟡" if score >= 45 else "🔴"

def day_label(dt: datetime) -> str:
    today = datetime.now().date()
    d = dt.date()
    if d == today:              return "Today"
    if d == today + timedelta(1): return "Tomorrow"
    return dt.strftime("%b %-d")

def hours_left_to(target_date: datetime) -> float:
    eod = target_date.replace(hour=23, minute=59, second=0, microsecond=0)
    return max(0.0, (eod - datetime.now()).total_seconds() / 3600)

def hours_label(h: float) -> str:
    if h < 1:   return "<1h"
    if h < 24:  return f"{h:.0f}h"
    return f"{h/24:.1f}d"

def get_weights(h: float) -> Dict[str, float]:
    if h >= 60: return {"ecmwf":0.50,"hrrr":0.20,"ow":0.25,"metar":0.05}
    if h >= 36: return {"ecmwf":0.40,"hrrr":0.30,"ow":0.20,"metar":0.10}
    if h >= 24: return {"ecmwf":0.25,"hrrr":0.45,"ow":0.15,"metar":0.15}
    if h >= 12: return {"ecmwf":0.10,"hrrr":0.40,"ow":0.15,"metar":0.35}
    return             {"ecmwf":0.05,"hrrr":0.30,"ow":0.10,"metar":0.55}

def window_label(h: float) -> str:
    if h > 60: return "🌐 Early  — ECMWF dominant"
    if h > 36: return "📡 Mid    — HRRR rising"
    if h > 12: return "🎯 Late   — HRRR + METAR"
    return             "🔴 Final  — hold / manage"

def std_dev(arr: list) -> float:
    if len(arr) < 2: return 0.0
    m = sum(arr)/len(arr)
    return math.sqrt(sum((v-m)**2 for v in arr)/len(arr))

def c_to_f(c_: float) -> float: return round(c_ * 9/5 + 32, 2)

# ─────────────────────────────────────────────────────────────────────────────
# BRACKET PARSING
# ─────────────────────────────────────────────────────────────────────────────
INF = float("inf")

def parse_bracket(label: str) -> Optional[Tuple[float, float]]:
    """Parse a bracket label into (lo, hi) inclusive whole-degree range."""
    s = label.strip()
    # "68-69°F" or "68-69°C"
    m = re.match(r'^(-?\d+)-(-?\d+)°[FC]$', s)
    if m: return (float(m.group(1)), float(m.group(2)))
    # "22°C" or "68°F"
    m = re.match(r'^(-?\d+)°[FC]$', s)
    if m: v = float(m.group(1)); return (v, v)
    # "42°F or higher" / "42°C or higher"
    m = re.match(r'^(-?\d+)°[FC]\s+or\s+higher$', s, re.I)
    if m: return (float(m.group(1)), INF)
    # "23°F or below"
    m = re.match(r'^(-?\d+)°[FC]\s+or\s+below$', s, re.I)
    if m: return (-INF, float(m.group(1)))
    return None

def bracket_center(lo: float, hi: float) -> float:
    """Midpoint of a bracket (handles ±inf tails)."""
    if lo == -INF: return hi - 2
    if hi == INF:  return lo + 2
    return (lo + hi) / 2

def bracket_prob(members: list, lo: float, hi: float) -> float:
    """Fraction of ECMWF members that round to a whole degree in [lo, hi]."""
    if not members: return 0.0
    count = sum(1 for m in members if lo <= round(m) <= hi)
    return count / len(members)

# ─────────────────────────────────────────────────────────────────────────────
# POLYMARKET API
# ─────────────────────────────────────────────────────────────────────────────
MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}

def parse_event_slug(slug: str) -> Optional[Dict]:
    """Extract type / city_key / date from a Polymarket event slug."""
    m = re.match(
        r'^(highest|lowest)-temperature-in-(.+)-on-(\w+)-(\d+)-(\d+)$', slug
    )
    if not m: return None
    month_name = m.group(3).lower()
    month_num  = MONTH_MAP.get(month_name)
    if not month_num: return None
    try:
        target = datetime(int(m.group(5)), month_num, int(m.group(4)))
    except ValueError:
        return None
    return {
        "market_type": m.group(1),   # "highest" / "lowest"
        "city_key":    m.group(2),   # "nyc", "los-angeles", etc.
        "target_date": target,
    }

def parse_brackets_from_markets(markets: list) -> List[Dict]:
    """
    Extract bracket info from a list of Polymarket market objects.
    Returns list of {label, lo, hi, yes_price, no_price, volume}
    """
    out = []
    for mk in markets:
        label = (mk.get("question") or mk.get("title") or "").strip()
        parsed = parse_bracket(label)
        if not parsed: continue
        lo, hi = parsed
        prices_raw = mk.get("outcomePrices","[]")
        try: prices = json.loads(prices_raw) if isinstance(prices_raw,str) else (prices_raw or [])
        except: prices = []
        yes_p = float(prices[0]) if prices else None
        vol   = float(mk.get("volume") or mk.get("volumeNum") or 0)
        out.append({"label":label,"lo":lo,"hi":hi,"yes_price":yes_p,"volume":vol})
    # Sort by lo (ascending), putting tail brackets at ends
    out.sort(key=lambda x: (-INF if x["lo"]==-INF else x["lo"]))
    return out

def fetch_poly_events() -> List[Dict]:
    """Fetch all active temperature events from Polymarket Gamma API."""
    all_events = []
    seen = set()
    endpoints = [
        "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=300&tag_slug=weather",
        "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=300&tag_slug=temperature",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=15)
            items = r.json() if isinstance(r.json(), list) else r.json().get("data",[])
            for ev in items:
                eid = ev.get("id") or ev.get("slug","")
                if eid in seen: continue
                slug = ev.get("slug","")
                parsed = parse_event_slug(slug)
                if not parsed: continue
                parsed["id"]       = eid
                parsed["slug"]     = slug
                parsed["title"]    = ev.get("title","")
                parsed["volume"]   = float(ev.get("volume") or ev.get("volumeNum") or 0)
                parsed["liquidity"]= float(ev.get("liquidity") or 0)
                parsed["end_date"] = ev.get("endDate") or ev.get("endDateIso")
                parsed["brackets"] = parse_brackets_from_markets(ev.get("markets") or [])
                seen.add(eid)
                all_events.append(parsed)
        except Exception:
            pass
    # Sort: soonest first, then by volume descending
    all_events.sort(key=lambda e: (e["target_date"], -e["volume"]))
    return all_events

def group_events_by_date(events: List[Dict]) -> Dict[str, List[Dict]]:
    """Group events by date label."""
    groups: Dict[str, List[Dict]] = {}
    for ev in events:
        label = day_label(ev["target_date"])
        groups.setdefault(label, []).append(ev)
    return groups

# ─────────────────────────────────────────────────────────────────────────────
# WEATHER FETCHERS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_hrrr(city: Dict, target_date: datetime, unit: str) -> Optional[Dict]:
    t_unit = "fahrenheit" if unit=="F" else "celsius"
    for model in ["hrrr_conus","gfs_seamless"]:
        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={city['lat']}&longitude={city['lon']}"
                f"&daily=temperature_2m_max,temperature_2m_min"
                f"&temperature_unit={t_unit}&models={model}&forecast_days=7"
                f"&timezone={city['tz']}"
            )
            d = requests.get(url,timeout=15).json()
            if "error" not in d:
                d["daily"]["_model"] = model
                d["daily"]["_dates"] = d["daily"].get("time",[])
                return d["daily"]
        except Exception: pass
    return None

def fetch_ecmwf(city: Dict, target_date: datetime, unit: str) -> Optional[Dict]:
    t_unit = "fahrenheit" if unit=="F" else "celsius"
    try:
        url = (
            f"https://ensemble-api.open-meteo.com/v1/ensemble"
            f"?latitude={city['lat']}&longitude={city['lon']}"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&temperature_unit={t_unit}&models=ecmwf_ifs04&forecast_days=7"
            f"&timezone={city['tz']}"
        )
        d = requests.get(url,timeout=25).json()
        if "error" not in d:
            d["daily"]["_dates"] = d["daily"].get("time",[])
            return d["daily"]
    except Exception: pass
    return None

def fetch_ow(city: Dict, target_date: datetime, unit: str) -> Optional[Dict]:
    if not OW_KEY: return None
    units = "imperial" if unit=="F" else "metric"
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={city['lat']}&lon={city['lon']}&appid={OW_KEY}"
            f"&units={units}&cnt=40"
        )
        d = requests.get(url,timeout=10).json()
        return d if d.get("cod") in (200,"200") else None
    except Exception: return None

def fetch_metar(metar_id: str) -> Optional[list]:
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={metar_id}&format=json&taf=false&hours=3"
        d = requests.get(url,timeout=10).json()
        return d if isinstance(d,list) else None
    except Exception: return None

def fetch_all_weather(city: Dict, target_date: datetime, unit: str, data_store: Dict) -> Dict[str,str]:
    data_store["hrrr"]  = fetch_hrrr(city, target_date, unit)
    data_store["ecmwf"] = fetch_ecmwf(city, target_date, unit)
    data_store["ow"]    = fetch_ow(city, target_date, unit)
    data_store["metar"] = fetch_metar(city["metar"])
    return {
        "HRRR":  "✅" if data_store["hrrr"]  else "❌",
        "ECMWF": "✅" if data_store["ecmwf"] else "❌",
        "OW":    "✅" if data_store["ow"]    else ("⚠️" if not OW_KEY else "❌"),
        "METAR": "✅" if data_store["metar"] else "❌",
    }

# ─────────────────────────────────────────────────────────────────────────────
# DATA EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
def date_index(data: Optional[Dict], target_date: datetime) -> int:
    """Find index of target_date in Open-Meteo daily data."""
    if not data: return -1
    dates = data.get("_dates",[])
    target_str = target_date.strftime("%Y-%m-%d")
    try: return dates.index(target_str)
    except ValueError: return -1

def extract_hrrr_temp(data_store: Dict, target_date: datetime, mtype: str) -> Optional[float]:
    d = data_store.get("hrrr")
    if not d: return None
    idx = date_index(d, target_date)
    if idx < 0: return None
    key = "temperature_2m_max" if mtype=="highest" else "temperature_2m_min"
    v = d.get(key,[])
    return float(v[idx]) if idx < len(v) and v[idx] is not None else None

def extract_ecmwf_ensemble(data_store: Dict, target_date: datetime, mtype: str) -> Optional[Dict]:
    d = data_store.get("ecmwf")
    if not d: return None
    idx = date_index(d, target_date)
    if idx < 0: return None
    key = "temperature_2m_max" if mtype=="highest" else "temperature_2m_min"
    members = [
        float(d[k][idx]) for k in d
        if k.startswith(key+"_member") and idx < len(d[k]) and d[k][idx] is not None
    ]
    if not members: return None
    mean = sum(members)/len(members)
    return {"mean":mean,"std":std_dev(members),"members":members,"count":len(members)}

def extract_ow_temp(data_store: Dict, target_date: datetime, mtype: str) -> Optional[float]:
    d = data_store.get("ow")
    if not d or "list" not in d: return None
    ds = target_date.strftime("%Y-%m-%d")
    items = [i for i in d["list"] if i.get("dt_txt","").startswith(ds)]
    if not items: return None
    temps = [i["main"]["temp"] for i in items]
    return max(temps) if mtype=="highest" else min(temps)

def extract_metar_temp(data_store: Dict, unit: str) -> Optional[float]:
    d = data_store.get("metar")
    if not isinstance(d,list) or not d: return None
    t = d[0].get("temp")
    if t is None: return None
    return c_to_f(t) if unit=="F" else float(t)

# ─────────────────────────────────────────────────────────────────────────────
# CONSENSUS ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def build_consensus(data_store: Dict, target_date: datetime, mtype: str,
                    unit: str, city_key: str) -> Optional[Dict]:
    h = hours_left_to(target_date)
    w = get_weights(h)

    ht = extract_hrrr_temp(data_store, target_date, mtype)
    ed = extract_ecmwf_ensemble(data_store, target_date, mtype)
    ot = extract_ow_temp(data_store, target_date, mtype)
    # Only use METAR as anchor if we're analyzing today & it's within 12h
    mt = extract_metar_temp(data_store, unit) if (
        target_date.date() == datetime.now().date() and h <= 24
    ) else None

    pts = []
    if ht is not None: pts.append({"name":"HRRR",        "temp":ht,        "weight":w["hrrr"]})
    if ed is not None: pts.append({"name":"ECMWF",       "temp":ed["mean"],"weight":w["ecmwf"],"std":ed["std"]})
    if ot is not None: pts.append({"name":"OpenWeather", "temp":ot,        "weight":w["ow"]})
    if mt is not None: pts.append({"name":"METAR",       "temp":mt,        "weight":w["metar"]})
    if not pts: return None

    w_sum  = sum(p["weight"] for p in pts)
    temp   = sum(p["temp"]*p["weight"] for p in pts) / w_sum
    ms     = std_dev([p["temp"] for p in pts])
    es     = ed["std"] if ed else 0.0
    conf   = max(10.0, min(95.0, 100 - ms*12 - es*8 - h*0.25))
    return {
        "temp":temp, "sources":pts,
        "confidence":conf, "model_spread":ms, "ecmwf_spread":es,
        "hours":h, "weights":w, "ensemble":ed,
    }

def find_center_bracket(consensus: Dict, brackets: List[Dict]) -> int:
    """Return index of bracket best matching the consensus temperature."""
    t = consensus["temp"]
    if not brackets: return 0
    best_idx, best_dist = 0, float("inf")
    for i, bk in enumerate(brackets):
        lo, hi = bk["lo"], bk["hi"]
        ctr = bracket_center(lo, hi)
        # Check if temp falls inside bracket first (exact match preferred)
        lo_eff = lo if lo != -INF else -9999
        hi_eff = hi if hi != INF  else  9999
        if lo_eff <= round(t) <= hi_eff:
            return i
        dist = abs(ctr - t)
        if dist < best_dist:
            best_dist, best_idx = dist, i
    return best_idx

def enrich_brackets(brackets: List[Dict], consensus: Dict, mkt_prices: Dict) -> List[Dict]:
    """Add ECMWF probability and edge to each bracket."""
    ed = consensus.get("ensemble")
    members = ed["members"] if ed else []
    for bk in brackets:
        bk["model_prob"] = bracket_prob(members, bk["lo"], bk["hi"]) if members else None
        manual = mkt_prices.get(bk["label"])
        bk["manual_price"] = float(manual) if manual else bk.get("yes_price")
        mp = bk["model_prob"]
        pp = bk["manual_price"]
        bk["edge"] = (mp - pp) if (mp is not None and pp is not None) else None
    return brackets

# ─────────────────────────────────────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────────────────────────────────────
def make_chart(brackets: List[Dict], center_idx: int,
               display: str, market_type: str, unit: str, confidence: float) -> io.BytesIO:
    BG, CARD = "#0d1117", "#161b22"
    MUTED, TEXT = "#8b949e", "#e6edf3"
    ACCENT, SPINE, GRID = "#58a6ff", "#30363d", "#21262d"
    HIGHLIGHT = "#1f6feb"

    labels = [bk["label"] for bk in brackets]
    model  = [bk.get("model_prob",0) or 0 for bk in brackets]
    market = [bk.get("manual_price") for bk in brackets]
    colors = [HIGHLIGHT if i==center_idx else (HIGHLIGHT+"88" if abs(i-center_idx)<=1 else CARD)
              for i in range(len(brackets))]

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(max(10, len(brackets)*0.85), 4.8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    bars = ax.bar(x, [m*100 for m in model], color=colors, edgecolor=BG, width=0.65, zorder=3, label="Model (ECMWF)")
    # Overlay market price dots
    mkt_x, mkt_y = [], []
    for i, mp in enumerate(market):
        if mp is not None:
            mkt_x.append(i)
            mkt_y.append(mp*100)
    if mkt_x:
        ax.scatter(mkt_x, mkt_y, color="#f0883e", zorder=5, s=60, label="Market price", marker="D")

    # Labels on highlighted bars
    for i, (bar_, m) in enumerate(zip(bars, model)):
        if abs(i-center_idx) <= 1 and m*100 >= 1:
            ax.text(bar_.get_x()+bar_.get_width()/2, bar_.get_height()+0.3,
                    f"{m*100:.1f}%", ha="center", va="bottom", fontsize=8,
                    color=ACCENT, fontweight="bold", fontfamily="monospace")

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v:.0f}%"))
    for sp in ["top","right"]: ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(SPINE)
    ax.spines["left"].set_color(SPINE)
    ax.grid(axis="y", color=GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel(f"Temperature bracket (°{unit})", color=MUTED, fontsize=10)
    ax.set_ylabel("Probability (%)", color=MUTED, fontsize=10)
    conf_bar = bar(confidence)
    type_str = "High" if market_type == "highest" else "Low"
    ax.set_title(
        f"ECMWF Ensemble  ·  {display} Daily {type_str}\nConfidence  {conf_bar}  {confidence:.0f}/100",
        color=TEXT, fontsize=11, pad=12, linespacing=1.6
    )
    if mkt_x:
        ax.legend(framealpha=0, labelcolor=MUTED, fontsize=9, loc="upper right")

    plt.tight_layout(pad=1.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────
def msg_market_list(events: List[Dict], page: int = 0) -> str:
    if not events:
        return "\n".join([
            b("🌡 Weather Markets"), DIV, "",
            "No active temperature markets found right now.",
            "Polymarket usually opens new markets at midnight ET.",
        ])

    ITEMS_PER_PAGE = 12
    grouped = group_events_by_date(events)
    date_keys = list(grouped.keys())

    # Flatten to pages
    all_items = []
    for dk in date_keys:
        all_items.append(("__header__", dk))
        for ev in grouped[dk]:
            all_items.append(("event", ev))

    total = len([x for x in all_items if x[0]=="event"])
    start = page * ITEMS_PER_PAGE
    end   = start + ITEMS_PER_PAGE

    # Slice events (keep headers)
    event_count = 0
    lines = [b("🌡 Polymarket Temperature Markets"), DIV]

    current_header = None
    shown = 0
    for kind, item in all_items:
        if kind == "__header__":
            current_header = item
            continue
        event_count += 1
        if event_count <= start: continue
        if event_count > end: break

        ev    = item
        ck    = ev["city_key"]
        city  = CITY_DB.get(ck)
        flag  = city["flag"] if city else "🌍"
        disp  = city["display"] if city else ck.replace("-"," ").title()
        stn   = city["station"] if city else "unknown station"
        ok    = city["ok"] if city else False
        conf  = "✅" if ok else "⚠️"
        h     = hours_left_to(ev["target_date"])
        typ   = "🌡" if ev["market_type"]=="highest" else "❄️"
        vol   = f"${ev['volume']/1000:.0f}K" if ev["volume"] >= 1000 else f"${ev['volume']:.0f}"

        if current_header and shown == 0 or (event_count == start+1):
            lines += ["", b(current_header), SDIV]
            current_header = None

        # Top bracket by yes_price
        top_bk = ""
        if ev["brackets"]:
            best = max(ev["brackets"], key=lambda x: x.get("yes_price") or 0, default=None)
            if best and best.get("yes_price"):
                top_bk = f"  {esc(best['label'])} {best['yes_price']*100:.0f}¢"

        lines.append(
            f"{flag} {b(esc(disp))}"
            f"  {it(esc(stn))} {conf}"
            f"  {typ}  {hours_label(h)}"
            f"  {vol}"
            f"{top_bk}"
        )
        shown += 1

    total_pages = math.ceil(len([x for x in all_items if x[0]=="event"]) / ITEMS_PER_PAGE)
    lines += ["", it(f"Page {page+1}/{total_pages}  ·  {total} markets  ·  Tap a city to analyze")]
    return "\n".join(lines)


def msg_analysis(state: Dict, city: Dict, consensus: Dict,
                 brackets: List[Dict], center_idx: int) -> str:
    active = state["active"]
    h      = consensus["hours"]
    unit   = city["unit"]
    conf   = consensus["confidence"]
    typ    = "Daily High 🌡" if active["market_type"]=="highest" else "Daily Low ❄️"
    ok_str = "✅ verified" if city["ok"] else "⚠️ unconfirmed"

    lines = [
        b("⛅ WeatherEdge Analysis"),
        DIV,
        f"{city['flag']}  {b(esc(city['display']))}  ·  {typ}",
        f"📍  {esc(city['station'])} ({city['metar']})  {ok_str}",
        f"📅  {day_label(active['target_date'])}  ·  ⏱ {hours_label(h)} left",
    ]

    if not city["ok"]:
        lines += [
            "",
            "⚠️ " + it("Resolution station not yet confirmed from Polymarket rules."),
            it("Verify at polymarket.com before trading."),
        ]

    # ── Consensus ──
    lines += ["", b("Consensus"), SDIV]
    w_sum = sum(p["weight"] for p in consensus["sources"])
    rows  = []
    for s in consensus["sources"]:
        wt  = round(s["weight"]/w_sum*100)
        sd  = f"±{s['std']:.1f}°" if s.get("std") else "      "
        rows.append(f"  {s['name']:<13} {s['temp']:>5.1f}°  {sd:<7}  {wt:>3}%")
    rows.append("  " + "─"*38)
    rows.append(f"  {'Consensus':<13} {consensus['temp']:>5.1f}°")
    lines.append(c("\n".join(rows)))

    # ── Confidence ──
    lines += [
        "",
        b(f"{conf_icon(conf)}  Confidence  {conf:.0f} / 100"),
        c(f"  {bar(conf)}  {conf:.0f}/100"
          f"  spread ±{consensus['model_spread']:.1f}°"
          f"  ECMWF ±{consensus['ecmwf_spread']:.1f}°"
          f"  {h:.0f}h lead"),
        c(f"  {window_label(h)}"),
    ]

    # ── Brackets ──
    if brackets:
        lines += ["", b("3-Position Entry"), SDIV]
        alloc = state["budget"] / 3
        pos_rows = []
        for i, bk in enumerate(brackets):
            dist = abs(i - center_idx)
            if dist > 1: continue
            tag    = "⭐" if i==center_idx else "  "
            ctr_lbl= "  ← center" if i==center_idx else ""
            mp_str = f"  mkt {bk['manual_price']*100:.0f}¢" if bk.get("manual_price") else ""
            ed_str = ""
            if bk.get("edge") is not None:
                sign = "+" if bk["edge"] >= 0 else ""
                ed_str = f"  edge {sign}{bk['edge']*100:.1f}%"
            model_str = f"{bk['model_prob']*100:.1f}%" if bk.get("model_prob") is not None else " — "
            pos_rows.append(
                f"  {tag} {bk['label']:<11}  {model_str:>6}{mp_str}{ed_str}{ctr_lbl}"
            )
        pos_rows.append("  " + "─"*38)
        pos_rows.append(f"  Budget ${state['budget']:.2f}  ·  ${alloc:.2f}/bracket  ·  stop {state['stop_loss']}%")
        lines.append(c("\n".join(pos_rows)))

        # Market volume
        vol  = active.get("event_volume", 0)
        liq  = active.get("event_liquidity", 0)
        if vol:
            vol_str = f"${vol/1000:.0f}K vol" if vol >= 1000 else f"${vol:.0f}"
            liq_str = f"  ·  ${liq/1000:.0f}K liq" if liq >= 1000 else ""
            lines += ["", it(f"Market  {vol_str}{liq_str}")]

    return "\n".join(lines)


def msg_strategy(state: Dict, city: Dict, brackets: List[Dict], center_idx: int,
                 consensus: Dict) -> str:
    active = state["active"]
    h      = consensus["hours"]
    unit   = city["unit"]
    typ    = "High" if active["market_type"]=="highest" else "Low"
    alloc  = state["budget"] / 3

    lines = [
        b(f"💡 Strategy  ·  {esc(city['display'])} Daily {typ}"),
        b(f"   {day_label(active['target_date'])}"),
        DIV,
    ]

    # Positions
    lines.append(b("📦  3-Position Entry Plan"))
    lines.append(SDIV)
    pos_rows = []
    for i, bk in enumerate(brackets):
        dist = abs(i - center_idx)
        if dist > 1: continue
        label  = "LOW   " if i < center_idx else ("CENTER" if i == center_idx else "HIGH  ")
        mp_str, edge_str, profit_str = "", "", ""
        if bk.get("manual_price"):
            mp  = bk["manual_price"]
            ed  = bk.get("edge")
            pft = alloc * (1 - mp) / mp if mp > 0 else 0
            mp_str  = f"  mkt {mp*100:.0f}¢"
            profit_str = f"  win +${pft:.2f}"
            if ed is not None:
                sign = "+" if ed >= 0 else ""
                edge_str = f"  edge {sign}{ed*100:.1f}%"
        model_str = f"{bk['model_prob']*100:.1f}%" if bk.get("model_prob") is not None else " — "
        pos_rows.append(
            f"  {label}  {bk['label']:<11}  {model_str:>6}{mp_str}{edge_str}{profit_str}"
        )
    pos_rows.append("  " + "─"*38)
    budget_str  = f"${state['budget']:.2f}"
    maxloss_str = f"${state['budget']*state['stop_loss']/100:.2f}"
    pos_rows.append(f"  Budget {budget_str}  ·  ${alloc:.2f}/bracket  ·  max loss {maxloss_str}")
    lines.append(c("\n".join(pos_rows)))

    # Stop loss rules
    lines += ["", b("🛡️  Stop Loss Rules"), SDIV]
    ctr_label = brackets[center_idx]["label"] if brackets else "?"
    unit_sym  = "°" + unit
    rules = (
        f"  1  PRICE STOP  ({state['stop_loss']}%)\n"
        f"     Exit any bracket if it drops {state['stop_loss']}% from entry.\n"
        f"\n"
        f"  2  CONSENSUS SHIFT\n"
        f"     Model moves >2{unit_sym} from center ({esc(ctr_label)})?\n"
        f"     Exit outer brackets first.\n"
        f"\n"
        f"  3  HOLD WINNER\n"
        f"     Center >75¢ with <6h left  →  hold to resolution.\n"
        f"\n"
        f"  4  CORRELATED DROP\n"
        f"     All 3 brackets drop together  →  exit full position."
    )
    lines.append(c(rules))

    # Entry timing
    lines += ["", b(f"⏱  Entry Window  ({hours_label(h)} left)"), SDIV]
    if h > 60:
        tip = (
            "  🌐 EARLY WINDOW (60h+)\n"
            "  ECMWF dominant. Markets usually mispriced at open.\n"
            "  Best price opportunity — enter if confidence >60."
        )
    elif h > 36:
        tip = (
            "  📡 MID WINDOW (36-60h)\n"
            "  HRRR begins outperforming. Confirm consensus hasn't\n"
            "  shifted. Good scale-in window."
        )
    elif h > 12:
        tip = (
            "  🎯 LATE WINDOW (12-36h)\n"
            "  HRRR dominant, METAR anchoring. Highest model accuracy.\n"
            "  Best conviction entry window."
        )
    else:
        tip = (
            "  🔴 FINAL (<12h)\n"
            "  METAR is ground truth. Do NOT open new positions.\n"
            "  Manage existing: hold winners, cut below stop."
        )
    lines.append(c(tip))
    return "\n".join(lines)


def msg_ai(state: Dict, city: Dict, consensus: Dict, brackets: List[Dict], center_idx: int) -> str:
    if not ANTHROPIC_KEY:
        return "\n".join([
            b("🤖 AI Analysis"), DIV, "",
            "No Anthropic API key configured.", "",
            "Add " + c("ANTHROPIC_KEY=your_key") + " to your " + c(".env") + " file.",
        ])
    active = state["active"]
    unit   = city["unit"]
    top_b  = "  ".join(
        f"{bk['label']} {bk['model_prob']*100:.1f}%"
        for bk in brackets if bk.get("model_prob",0) > 0.03
    )
    pos_bks = [brackets[i] for i in range(max(0,center_idx-1), min(len(brackets),center_idx+2))]
    mkt_str = "  ".join(
        f"{bk['label']} mkt={bk['manual_price']*100:.0f}¢" if bk.get("manual_price") else f"{bk['label']} mkt=?"
        for bk in pos_bks
    )
    src_str = "  |  ".join(
        f"{s['name']} {s['temp']:.1f}°" for s in consensus["sources"]
    )
    prompt = (
        f"Expert prediction market weather trader. Return JSON only.\n\n"
        f"MARKET: {city['display']} Daily {'HIGH' if active['market_type']=='highest' else 'LOW'} °{unit}\n"
        f"DAY: {day_label(active['target_date'])}  HOURS: {consensus['hours']:.1f}h\n"
        f"STATION: {city['station']} ({city['metar']}) confirmed={city['ok']}\n"
        f"CONSENSUS: {consensus['temp']:.1f}°{unit}\n"
        f"SOURCES: {src_str}\n"
        f"SPREADS: model ±{consensus['model_spread']:.1f}° ecmwf ±{consensus['ecmwf_spread']:.1f}°\n"
        f"CONFIDENCE: {consensus['confidence']:.0f}/100\n"
        f"TOP BRACKETS: {top_b}\n"
        f"POSITIONS: {mkt_str}\n\n"
        "Return: "
        '{"signal":"GO|CAUTIOUS|NO-GO","confidence":0-100,'
        '"summary":"1-2 sentences","flags":["..."],'
        '"stop_loss":"specific advice","timing":"entry timing","edge":"N/A or calc"}'
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":600,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=30,
        )
        data = json.loads(r.json()["content"][0]["text"].replace("```json","").replace("```","").strip())
        sig  = data.get("signal","?")
        icon = {"GO":"🟢","CAUTIOUS":"🟡","NO-GO":"🔴"}.get(sig,"⚪")
        conf = data.get("confidence","?")
        parts = [
            b(f"{icon}  AI Signal: {sig}") + "  " + it(f"({conf}/100)"),
            DIV,
            esc(data.get("summary","")),
        ]
        for f_ in data.get("flags",[]):
            parts.append("  ⚠️ " + esc(f_))
        if data.get("stop_loss"):
            parts += ["", b("📉 Stop Loss:") + "  " + esc(data["stop_loss"])]
        if data.get("timing"):
            parts += [b("⏰ Timing:") + "  " + esc(data["timing"])]
        if data.get("edge") and data["edge"] != "N/A":
            parts += [b("📊 Edge:") + "  " + esc(data["edge"])]
        return "\n".join(parts)
    except Exception as e:
        return b("⚠️ AI Error") + "\n\n" + esc(str(e))

# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌡  Browse Markets",      callback_data="browse_markets")],
        [InlineKeyboardButton("🔄  Refresh Analysis",   callback_data="refresh_analysis"),
         InlineKeyboardButton("📊  Distribution Chart", callback_data="send_chart")],
        [InlineKeyboardButton("💡  Strategy",           callback_data="show_strategy"),
         InlineKeyboardButton("🤖  AI Signal",          callback_data="run_ai")],
        [InlineKeyboardButton("⚙️  Settings",           callback_data="show_settings")],
    ])

def kb_analysis():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  Distribution Chart",  callback_data="send_chart"),
         InlineKeyboardButton("💡  Strategy",            callback_data="show_strategy")],
        [InlineKeyboardButton("🤖  AI Signal",           callback_data="run_ai"),
         InlineKeyboardButton("🌡  Browse Markets",      callback_data="browse_markets")],
        [InlineKeyboardButton("←  Menu",                 callback_data="back_main")],
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("←  Main Menu", callback_data="back_main")]])

def kb_market_list(events: List[Dict], page: int) -> InlineKeyboardMarkup:
    grouped  = group_events_by_date(events)
    buttons  = []
    ITEMS_PER_PAGE = 12
    all_ev   = [ev for group in grouped.values() for ev in group]
    total    = len(all_ev)
    page_ev  = all_ev[page*ITEMS_PER_PAGE:(page+1)*ITEMS_PER_PAGE]

    row = []
    for ev in page_ev:
        ck   = ev["city_key"]
        city = CITY_DB.get(ck)
        flag = city["flag"] if city else "🌍"
        disp = (city["display"] if city else ck.replace("-"," ").title())[:14]
        typ  = "🌡" if ev["market_type"]=="highest" else "❄️"
        label = f"{flag}{typ} {disp}"
        row.append(InlineKeyboardButton(label, callback_data=f"select_event_{ev['slug']}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"market_page_{page-1}"))
    total_pages = math.ceil(total / ITEMS_PER_PAGE)
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"market_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("←  Main Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def kb_settings(state: Dict):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Budget: ${state['budget']:.0f}", callback_data="set_budget"),
         InlineKeyboardButton(f"Stop: {state['stop_loss']}%",    callback_data="set_stoploss")],
        [InlineKeyboardButton("←  Back", callback_data="back_main")],
    ])

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_active_analysis(state: Dict) -> Optional[Tuple]:
    """
    Returns (city, consensus, brackets, center_idx) for the active market,
    or None if not ready.
    """
    active = state.get("active")
    if not active: return None
    city = CITY_DB.get(active["city_key"])
    if not city: return None

    consensus = build_consensus(
        state["data"], active["target_date"],
        active["market_type"], city["unit"], active["city_key"]
    )
    if not consensus: return None

    brackets   = enrich_brackets(active.get("brackets",[]), consensus, state["mkt_prices"])
    center_idx = (
        state["center_override"] if state.get("center_override") is not None
        else find_center_bracket(consensus, brackets)
    )
    return city, consensus, brackets, center_idx


async def run_fetch_and_reply(q_or_msg, state: Dict, city: Dict):
    """Background fetch + send analysis (used from callback and command)."""
    active = state["active"]
    status = await asyncio.to_thread(
        fetch_all_weather, city, active["target_date"], city["unit"], state["data"]
    )
    result = get_active_analysis(state)
    if not result:
        text = "\n".join([b("❌  No Data"), "", "Weather APIs returned no data for this station."])
        try:
            await q_or_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_back())
        except Exception:
            await q_or_msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_back())
        return
    city_, con, bks, ctr = result
    sl   = "  ".join(f"{k} {v}" for k, v in status.items())
    text = msg_analysis(state, city_, con, bks, ctr) + f"\n\n{SDIV}\n{it(sl)}"
    try:
        await q_or_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_analysis())
    except Exception:
        await q_or_msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_analysis())

# ─────────────────────────────────────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    active = state.get("active")
    last  = ""
    if active:
        ck   = active["city_key"]
        city = CITY_DB.get(ck, {})
        last = (
            f"\n\n{b('Last market')}\n{SDIV}\n"
            f"{c(city.get('display',ck))} {c(city.get('station',''))}"
            f"\n{c(day_label(active['target_date']))}"
            f"  {'High' if active['market_type']=='highest' else 'Low'}"
        )

    text = "\n".join([
        b("⛅  WeatherEdge"),
        DIV,
        it("Polymarket Weather Trading Assistant"),
        "",
        (
            "Multi-model consensus combining ECMWF ensemble, HRRR, "
            "METAR/ASOS, and OpenWeather for Polymarket temperature markets. "
            "All resolution stations verified directly from Polymarket rules."
        ),
        "",
        b("Quick commands"),
        SDIV,
        c("/markets")        + "  browse live markets",
        c("/price 70-71°F 0.28") + "  log bracket price",
        c("/budget 30")     + "  set budget",
        c("/stoploss 50")   + "  set stop loss %",
        c("/help")          + "  all commands",
    ]) + last

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "\n".join([
        b("⛅  WeatherEdge  —  Help"),
        DIV, "",
        b("Navigation"),
        c("/start")      + "           main menu",
        c("/markets")    + "           browse live markets",
        c("/refresh")    + "           re-fetch weather + show analysis",
        c("/chart")      + "           distribution chart",
        c("/strategy")   + "           3-bracket entry plan",
        c("/analyze")    + "           AI trading signal",
        "",
        b("Configuration"),
        c('/price "70-71°F" 0.28') + "",
        "                    " + it("log a bracket's market price"),
        c("/budget 30")  + "           set total budget",
        c("/stoploss 50")+ "           set stop loss %",
        c("/override 2") + "           override center bracket index",
        c("/reset")      + "           clear prices + override",
        "",
        b("How it works"),
        SDIV,
        "1. Browse markets → tap a city",
        "2. Bot fetches ECMWF, HRRR, METAR for the",
        it("   exact Polymarket resolution station"),
        "3. Builds weighted consensus + confidence score",
        "4. Maps ECMWF ensemble to actual market brackets",
        "5. Recommends 3 adjacent brackets + edge calc",
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_markets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    msg   = await update.message.reply_text(
        f"{b('⏳  Fetching markets…')}\n{SDIV}\n{it('Loading all active temperature events from Polymarket…')}",
        parse_mode=ParseMode.HTML
    )
    events = await asyncio.to_thread(fetch_poly_events)
    state["cached_events"] = events
    state["markets_page"]  = 0
    text = msg_market_list(events, 0)
    await msg.edit_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_market_list(events, 0)
    )


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    if not state.get("active"):
        await update.message.reply_text(
            f"{b('⚠️  No market selected')}\n\nUse /markets to pick one first.",
            parse_mode=ParseMode.HTML, reply_markup=kb_back()
        )
        return
    ck   = state["active"]["city_key"]
    city = CITY_DB.get(ck)
    if not city:
        await update.message.reply_text(f"City {ck} not in database.", parse_mode=ParseMode.HTML)
        return
    msg = await update.message.reply_text(
        f"{b('⏳  Refreshing…')}\n{SDIV}\n{it('ECMWF  ·  HRRR  ·  METAR  ·  OpenWeather')}",
        parse_mode=ParseMode.HTML
    )
    await run_fetch_and_reply(msg, state, city)


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    result = get_active_analysis(state)
    if not result:
        await update.message.reply_text(
            f"{b('❌  No Data')}\n\nFetch a market first with /markets.",
            parse_mode=ParseMode.HTML
        )
        return
    city, con, bks, ctr = result
    active = state["active"]
    buf = await asyncio.to_thread(
        make_chart, bks, ctr,
        city["display"], active["market_type"], city["unit"], con["confidence"]
    )
    cap = (
        f"ECMWF Ensemble  ·  {city['display']} Daily "
        f"{'High' if active['market_type']=='highest' else 'Low'}"
        f"\n{day_label(active['target_date'])}  ·  "
        f"Consensus {con['temp']:.1f}°{city['unit']}  ·  "
        f"Confidence {con['confidence']:.0f}/100"
    )
    await update.message.reply_photo(photo=buf, caption=cap)


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    result = get_active_analysis(state)
    if not result:
        await update.message.reply_text(
            f"{b('❌  No Data')}\n\nFetch a market first with /markets.",
            parse_mode=ParseMode.HTML
        )
        return
    city, con, bks, ctr = result
    await update.message.reply_text(
        msg_strategy(state, city, bks, ctr, con),
        parse_mode=ParseMode.HTML, reply_markup=kb_back()
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    result = get_active_analysis(state)
    if not result:
        await update.message.reply_text(
            f"{b('❌  No Data')}\n\nFetch a market first with /markets.",
            parse_mode=ParseMode.HTML
        )
        return
    msg = await update.message.reply_text(
        f"{b('🤖  Running AI Analysis…')}\n{SDIV}\n{it('Synthesising forecast data…')}",
        parse_mode=ParseMode.HTML
    )
    city, con, bks, ctr = result
    result_text = await asyncio.to_thread(msg_ai, state, city, con, bks, ctr)
    await msg.edit_text(result_text, parse_mode=ParseMode.HTML, reply_markup=kb_back())


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    # Usage: /price 70-71°F 0.28  OR  /price "70-71°F" 0.28
    text_raw = " ".join(context.args or [])
    # Try to parse last token as price, everything before as bracket label
    parts = text_raw.rsplit(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            f"{b('📌  Log Bracket Price')}\n{SDIV}\n\n"
            f"Usage:  {c('/price [bracket] [price]')}\n"
            f"Example:  {c('/price 70-71°F 0.28')}\n"
            f"Price is between 0 and 1 (e.g. 0.28 = 28¢).",
            parse_mode=ParseMode.HTML
        )
        return
    label = parts[0].strip().strip('"').strip("'")
    try:
        price = float(parts[1])
        if not 0 < price < 1: raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text(
            f"{b('❌  Invalid price')}\n\nPrice must be between 0 and 1.\n"
            f"Example:  {c('/price 70-71°F 0.28')}",
            parse_mode=ParseMode.HTML
        )
        return

    state["mkt_prices"][label] = price

    # Show edge if we have data
    result = get_active_analysis(state)
    lines  = [b("✅  Price Logged"), SDIV, c(f"{label}  →  {price*100:.0f}¢")]
    if result:
        _, con, bks, _ = result
        bk = next((b_ for b_ in bks if b_["label"]==label), None)
        if bk and bk.get("model_prob") is not None:
            edge = bk["model_prob"] - price
            sign = "+" if edge >= 0 else ""
            icon = "🟢" if edge > 0.05 else "🟡" if edge > -0.05 else "🔴"
            model_pct_str = "{:.1f}%".format(bk["model_prob"]*100)
            edge_pct_str  = "{}{:.1f}%".format(sign, edge*100)
            lines += [
                "",
                "Model:  " + b(model_pct_str),
                "Edge:   " + b(edge_pct_str) + "  " + icon,
            ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    try:
        state["budget"] = float((context.args or [])[0])
        total_str  = "${:.2f}".format(state["budget"])
        per_leg_str = "${:.2f}".format(state["budget"]/3)
        await update.message.reply_text(
            b("✅  Budget Updated") + "\n" + SDIV + "\n"
            + c("Total:   " + total_str) + "\n"
            + c("Per leg: " + per_leg_str),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text(f"Usage:  {c('/budget 30')}", parse_mode=ParseMode.HTML)


async def cmd_stoploss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    try:
        state["stop_loss"] = int((context.args or [])[0])
        sl_msg = "Exit any bracket if it drops  {}%  from entry".format(state["stop_loss"])
        await update.message.reply_text(
            b("✅  Stop Loss Updated") + "\n" + SDIV + "\n" + c(sl_msg),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text(f"Usage:  {c('/stoploss 50')}", parse_mode=ParseMode.HTML)


async def cmd_override(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    try:
        idx = int((context.args or [])[0])
        state["center_override"] = idx
        result = get_active_analysis(state)
        bk_label = ""
        if result:
            _, _, bks, _ = result
            if 0 <= idx < len(bks):
                bk_label = f"  ({esc(bks[idx]['label'])})"
        await update.message.reply_text(
            f"{b('✅  Center Override Set')}\n{SDIV}\n"
            f"{c(f'Bracket index {idx}{bk_label}')}",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text(
            f"Usage:  {c('/override [index]')}\nExample:  {c('/override 3')}",
            parse_mode=ParseMode.HTML
        )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    state["mkt_prices"]      = {}
    state["center_override"] = None
    await update.message.reply_text(
        f"{b('✅  Reset Complete')}\n{SDIV}\n"
        f"{c('Market prices cleared')}\n"
        f"{c('Center override cleared')}",
        parse_mode=ParseMode.HTML
    )

# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────────────────────
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    await q.answer()
    cid   = q.message.chat_id
    state = get_state(cid)
    d     = q.data

    # ── Navigation ──────────────────────────────────────────────────────────
    if d == "back_main":
        await q.edit_message_text(
            f"{b('⛅  WeatherEdge')}\n{DIV}\n\n"
            f"{c('Use the buttons below or type /markets to browse live markets')}",
            parse_mode=ParseMode.HTML, reply_markup=kb_main()
        )

    elif d == "browse_markets":
        await q.edit_message_text(
            f"{b('⏳  Fetching markets…')}\n{SDIV}\n{it('Loading Polymarket temperature events…')}",
            parse_mode=ParseMode.HTML
        )
        events = await asyncio.to_thread(fetch_poly_events)
        state["cached_events"] = events
        state["markets_page"]  = 0
        await q.edit_message_text(
            msg_market_list(events, 0),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_market_list(events, 0)
        )

    elif d.startswith("market_page_"):
        page   = int(d[len("market_page_"):])
        events = state.get("cached_events") or []
        state["markets_page"] = page
        await q.edit_message_text(
            msg_market_list(events, page),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_market_list(events, page)
        )

    elif d.startswith("select_event_"):
        slug   = d[len("select_event_"):]
        events = state.get("cached_events") or []
        ev     = next((e for e in events if e["slug"]==slug), None)
        if not ev:
            await q.answer("Market not found. Refresh markets.", show_alert=True)
            return
        city = CITY_DB.get(ev["city_key"])
        if not city:
            await q.edit_message_text(
                f"{b('⚠️  City Not in Database')}\n{DIV}\n\n"
                f"City key {c(esc(ev['city_key']))} has no station mapping.\n"
                f"Cannot fetch weather data.",
                parse_mode=ParseMode.HTML, reply_markup=kb_back()
            )
            return

        # Set active market
        state["active"] = {
            "city_key":        ev["city_key"],
            "market_type":     ev["market_type"],
            "target_date":     ev["target_date"],
            "brackets":        ev["brackets"],
            "event_slug":      slug,
            "event_volume":    ev["volume"],
            "event_liquidity": ev["liquidity"],
        }
        state["data"] = {"hrrr":None,"ecmwf":None,"ow":None,"metar":None}
        state["mkt_prices"]      = {}
        state["center_override"] = None

        typ = "High 🌡" if ev["market_type"]=="highest" else "Low ❄️"
        await q.edit_message_text(
            f"{b('⏳  Fetching weather data…')}\n{DIV}\n"
            f"{city['flag']}  {b(esc(city['display']))}  ·  Daily {typ}\n"
            f"📍  {esc(city['station'])} ({city['metar']})\n"
            f"📅  {day_label(ev['target_date'])}\n\n"
            f"{it('ECMWF ensemble · HRRR/GFS · METAR · OpenWeather')}",
            parse_mode=ParseMode.HTML
        )
        await run_fetch_and_reply(q.message, state, city)

    elif d == "refresh_analysis":
        active = state.get("active")
        if not active:
            await q.answer("No market selected.", show_alert=True)
            return
        city = CITY_DB.get(active["city_key"])
        if not city:
            await q.answer("City not in database.", show_alert=True)
            return
        await q.edit_message_text(
            f"{b('⏳  Refreshing…')}\n{SDIV}\n{it('ECMWF  ·  HRRR  ·  METAR  ·  OpenWeather')}",
            parse_mode=ParseMode.HTML
        )
        await run_fetch_and_reply(q.message, state, city)

    elif d == "show_strategy":
        result = get_active_analysis(state)
        if not result:
            await q.edit_message_text(
                f"{b('❌  No Data')}\n\nFetch a market first.",
                parse_mode=ParseMode.HTML, reply_markup=kb_back()
            )
            return
        city, con, bks, ctr = result
        await q.edit_message_text(
            msg_strategy(state, city, bks, ctr, con),
            parse_mode=ParseMode.HTML, reply_markup=kb_back()
        )

    elif d == "run_ai":
        result = get_active_analysis(state)
        if not result:
            await q.edit_message_text(
                f"{b('❌  No Data')}\n\nFetch a market first.",
                parse_mode=ParseMode.HTML, reply_markup=kb_back()
            )
            return
        await q.edit_message_text(
            f"{b('🤖  Running AI Analysis…')}\n{SDIV}\n{it('Synthesising forecast data…')}",
            parse_mode=ParseMode.HTML
        )
        city, con, bks, ctr = result
        res = await asyncio.to_thread(msg_ai, state, city, con, bks, ctr)
        await q.edit_message_text(res, parse_mode=ParseMode.HTML, reply_markup=kb_back())

    elif d == "send_chart":
        result = get_active_analysis(state)
        if not result:
            await q.answer("No data yet — select and fetch a market first.", show_alert=True)
            return
        city, con, bks, ctr = result
        if not bks:
            await q.answer("No bracket data available.", show_alert=True)
            return
        active = state["active"]
        buf = await asyncio.to_thread(
            make_chart, bks, ctr,
            city["display"], active["market_type"], city["unit"], con["confidence"]
        )
        cap = (
            f"ECMWF Ensemble  ·  {city['display']} Daily "
            f"{'High' if active['market_type']=='highest' else 'Low'}"
            f"\n{day_label(active['target_date'])}  ·  "
            f"Consensus {con['temp']:.1f}°{city['unit']}  ·  {con['confidence']:.0f}/100 conf"
        )
        await q.message.reply_photo(photo=buf, caption=cap)

    elif d == "show_settings":
        b_str  = "${:.2f}".format(state["budget"])
        pl_str = "${:.2f}".format(state["budget"]/3)
        sl_str = "{}%".format(state["stop_loss"])
        text = "\n".join([
            b("⚙️  Settings"), DIV, "",
            "Budget:     " + b(b_str),
            "Per bracket:" + b(pl_str),
            "Stop loss:  " + b(sl_str),
            "",
            "Use " + c("/budget [amount]") + " and " + c("/stoploss [%]") + " to update.",
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_back())

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("ERROR: TELEGRAM_TOKEN not set in .env")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    for cmd, handler in [
        ("start",    cmd_start),
        ("help",     cmd_help),
        ("markets",  cmd_markets),
        ("refresh",  cmd_refresh),
        ("chart",    cmd_chart),
        ("strategy", cmd_strategy),
        ("analyze",  cmd_analyze),
        ("price",    cmd_price),
        ("budget",   cmd_budget),
        ("stoploss", cmd_stoploss),
        ("override", cmd_override),
        ("reset",    cmd_reset),
    ]:
        app.add_handler(CommandHandler(cmd, handler))
    app.add_handler(CallbackQueryHandler(on_callback))

    confirmed = sum(1 for v in CITY_DB.values() if v["ok"])
    total     = len(CITY_DB)
    print(f"⛅  WeatherEdge v3 started")
    print(f"   City database:  {confirmed} confirmed + {total-confirmed} inferred  ({total} total)")
    print(f"   Telegram:       {'set' if TELEGRAM_TOKEN else 'MISSING'}")
    print(f"   OpenWeather:    {'set' if OW_KEY else 'not set (optional)'}")
    print(f"   Anthropic AI:   {'set' if ANTHROPIC_KEY else 'not set (optional)'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
