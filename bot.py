#!/usr/bin/env python3
"""WeatherEdge v2 — Polymarket Weather Trading Bot"""

import os, io, json, math, asyncio, html, requests, requests.utils
from datetime import datetime, timedelta
from typing import Optional, Dict, List
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

AIRPORTS = {
    "KJFK": {"lat": 40.6413, "lon": -73.7781, "city": "New York",       "name": "JFK", "tz": "America/New_York"},
    "KLAX": {"lat": 33.9425, "lon": -118.408,  "city": "Los Angeles",   "name": "LAX", "tz": "America/Los_Angeles"},
    "KORD": {"lat": 41.9742, "lon": -87.9073,  "city": "Chicago",       "name": "ORD", "tz": "America/Chicago"},
    "KATL": {"lat": 33.6407, "lon": -84.4277,  "city": "Atlanta",       "name": "ATL", "tz": "America/New_York"},
    "KDFW": {"lat": 32.8998, "lon": -97.0403,  "city": "Dallas",        "name": "DFW", "tz": "America/Chicago"},
    "KMIA": {"lat": 25.7959, "lon": -80.2870,  "city": "Miami",         "name": "MIA", "tz": "America/New_York"},
    "KSEA": {"lat": 47.4502, "lon": -122.309,  "city": "Seattle",       "name": "SEA", "tz": "America/Los_Angeles"},
    "KDEN": {"lat": 39.8561, "lon": -104.674,  "city": "Denver",        "name": "DEN", "tz": "America/Denver"},
    "KBOS": {"lat": 42.3656, "lon": -71.0096,  "city": "Boston",        "name": "BOS", "tz": "America/New_York"},
    "KSFO": {"lat": 37.6213, "lon": -122.379,  "city": "San Francisco", "name": "SFO", "tz": "America/Los_Angeles"},
}

user_states: Dict[int, Dict] = {}

def get_state(cid: int) -> Dict:
    if cid not in user_states:
        user_states[cid] = {
            "airport": "KJFK", "day_offset": 1,
            "market_type": "high", "unit": "F",
            "budget": 30.0, "stop_loss": 50,
            "center_override": None, "mkt_prices": {},
            "data": {"hrrr": None, "ecmwf": None, "ow": None, "metar": None},
            "poly": None,
        }
    return user_states[cid]

# ── Formatting ───────────────────────────────────────────────────────────────
def b(s):   return "<b>" + str(s) + "</b>"
def it(s):  return "<i>" + str(s) + "</i>"
def c(s):   return "<code>" + html.escape(str(s)) + "</code>"
def pre(s): return "<pre>" + html.escape(str(s)) + "</pre>"
def esc(s): return html.escape(str(s))

DIV  = "━" * 26
SDIV = "─" * 26

def bar(val, mx=100, w=12):
    f = max(0, min(w, round(val / mx * w)))
    return "█" * f + "░" * (w - f)

def conf_icon(score):
    return "🟢" if score >= 70 else "🟡" if score >= 45 else "🔴"

def window_label(h):
    if h > 60: return "🌐 EARLY  — ECMWF dominant"
    if h > 36: return "📡 MID    — HRRR rising"
    if h > 12: return "🎯 LATE   — HRRR + METAR"
    return              "🔴 FINAL  — manage only"

def day_label(d):
    return "Today" if d == 0 else "Tomorrow" if d == 1 else "+{} Days".format(d)

# ── Math ─────────────────────────────────────────────────────────────────────
def c_to_f(cv): return round(cv * 9/5 + 32, 2)

def std_dev(arr):
    if len(arr) < 2: return 0.0
    m = sum(arr) / len(arr)
    return math.sqrt(sum((v - m) ** 2 for v in arr) / len(arr))

def hours_left(day_offset):
    now = datetime.now()
    target = (now + timedelta(days=day_offset)).replace(hour=23, minute=59, second=0, microsecond=0)
    return max(0.0, (target - now).total_seconds() / 3600)

def get_weights(h):
    if h >= 60: return {"ecmwf": 0.50, "hrrr": 0.20, "ow": 0.25, "metar": 0.05}
    if h >= 36: return {"ecmwf": 0.40, "hrrr": 0.30, "ow": 0.20, "metar": 0.10}
    if h >= 24: return {"ecmwf": 0.25, "hrrr": 0.45, "ow": 0.15, "metar": 0.15}
    if h >= 12: return {"ecmwf": 0.10, "hrrr": 0.40, "ow": 0.15, "metar": 0.35}
    return             {"ecmwf": 0.05, "hrrr": 0.30, "ow": 0.10, "metar": 0.55}

# ── Fetchers ─────────────────────────────────────────────────────────────────
def fetch_hrrr(state):
    apt = AIRPORTS[state["airport"]]
    t_unit = "fahrenheit" if state["unit"] == "F" else "celsius"
    for model in ["hrrr_conus", "gfs_seamless"]:
        try:
            url = ("https://api.open-meteo.com/v1/forecast"
                   "?latitude={}&longitude={}"
                   "&daily=temperature_2m_max,temperature_2m_min"
                   "&temperature_unit={}&models={}&forecast_days=4&timezone={}").format(
                   apt["lat"], apt["lon"], t_unit, model, apt["tz"])
            d = requests.get(url, timeout=15).json()
            if "error" not in d:
                d["daily"]["_model"] = model
                return d["daily"]
        except Exception:
            pass
    return None

def fetch_ecmwf(state):
    apt = AIRPORTS[state["airport"]]
    t_unit = "fahrenheit" if state["unit"] == "F" else "celsius"
    try:
        url = ("https://ensemble-api.open-meteo.com/v1/ensemble"
               "?latitude={}&longitude={}"
               "&daily=temperature_2m_max,temperature_2m_min"
               "&temperature_unit={}&models=ecmwf_ifs04&forecast_days=4&timezone={}").format(
               apt["lat"], apt["lon"], t_unit, apt["tz"])
        d = requests.get(url, timeout=25).json()
        return d["daily"] if "error" not in d else None
    except Exception:
        return None

def fetch_ow(state):
    if not OW_KEY: return None
    apt = AIRPORTS[state["airport"]]
    units = "imperial" if state["unit"] == "F" else "metric"
    try:
        url = ("https://api.openweathermap.org/data/2.5/forecast"
               "?lat={}&lon={}&appid={}&units={}&cnt=40").format(
               apt["lat"], apt["lon"], OW_KEY, units)
        d = requests.get(url, timeout=10).json()
        return d if d.get("cod") in (200, "200") else None
    except Exception:
        return None

def fetch_metar(state):
    try:
        url = "https://aviationweather.gov/api/data/metar?ids={}&format=json&taf=false&hours=3".format(
              state["airport"])
        d = requests.get(url, timeout=10).json()
        return d if isinstance(d, list) else None
    except Exception:
        return None

def fetch_poly(state):
    apt = AIRPORTS[state["airport"]]
    try:
        kw = "{} temperature".format(apt["city"])
        url = ("https://gamma-api.polymarket.com/markets"
               "?active=true&closed=false&limit=50&keyword={}").format(
               requests.utils.quote(kw))
        d = requests.get(url, timeout=10).json()
        return d if isinstance(d, list) else d.get("data", [])
    except Exception:
        return None

def fetch_all(state):
    state["data"]["hrrr"]  = fetch_hrrr(state)
    state["data"]["ecmwf"] = fetch_ecmwf(state)
    state["data"]["metar"] = fetch_metar(state)
    state["data"]["ow"]    = fetch_ow(state)
    state["poly"]          = fetch_poly(state)
    return {
        "HRRR":        "✅" if state["data"]["hrrr"]  else "❌",
        "ECMWF":       "✅" if state["data"]["ecmwf"] else "❌",
        "METAR":       "✅" if state["data"]["metar"] else "❌",
        "OpenWeather": "✅" if state["data"]["ow"]    else ("⚠️" if not OW_KEY else "❌"),
        "Polymarket":  "✅" if state["poly"]           else "❌",
    }

# ── Processing ────────────────────────────────────────────────────────────────
def hrrr_temp(state):
    d = state["data"]["hrrr"]
    if not d: return None
    key  = "temperature_2m_max" if state["market_type"] == "high" else "temperature_2m_min"
    vals = d.get(key, [])
    idx  = state["day_offset"]
    return float(vals[idx]) if idx < len(vals) and vals[idx] is not None else None

def ecmwf_ens(state):
    d = state["data"]["ecmwf"]
    if not d: return None
    key  = "temperature_2m_max" if state["market_type"] == "high" else "temperature_2m_min"
    idx  = state["day_offset"]
    members = [float(d[k][idx]) for k in d
               if k.startswith(key + "_member") and idx < len(d[k]) and d[k][idx] is not None]
    if not members: return None
    mean = sum(members) / len(members)
    return {"mean": mean, "std": std_dev(members), "members": members, "count": len(members)}

def ow_temp(state):
    d = state["data"]["ow"]
    if not d or "list" not in d: return None
    ds    = (datetime.now() + timedelta(days=state["day_offset"])).strftime("%Y-%m-%d")
    items = [i for i in d["list"] if i.get("dt_txt", "").startswith(ds)]
    if not items: return None
    temps = [i["main"]["temp"] for i in items]
    return max(temps) if state["market_type"] == "high" else min(temps)

def metar_temp(state):
    d = state["data"]["metar"]
    if not isinstance(d, list) or not d: return None
    t = d[0].get("temp")
    if t is None: return None
    return c_to_f(t) if state["unit"] == "F" else float(t)

def build_consensus(state):
    h  = hours_left(state["day_offset"])
    w  = get_weights(h)
    ht = hrrr_temp(state)
    ed = ecmwf_ens(state)
    ot = ow_temp(state)
    mt = metar_temp(state) if state["day_offset"] == 0 else None

    pts = []
    if ht is not None: pts.append({"name": "HRRR",        "temp": ht,        "weight": w["hrrr"]})
    if ed is not None: pts.append({"name": "ECMWF",       "temp": ed["mean"],"weight": w["ecmwf"], "std": ed["std"]})
    if ot is not None: pts.append({"name": "OpenWeather", "temp": ot,        "weight": w["ow"]})
    if mt is not None: pts.append({"name": "METAR",       "temp": mt,        "weight": w["metar"]})
    if not pts: return None

    w_sum = sum(p["weight"] for p in pts)
    temp  = sum(p["temp"] * p["weight"] for p in pts) / w_sum
    ms    = std_dev([p["temp"] for p in pts])
    es    = ed["std"] if ed else 0.0
    conf  = max(10.0, min(95.0, 100 - ms * 12 - es * 8 - h * 0.25))
    return {"temp": temp, "rounded": round(temp), "sources": pts,
            "confidence": conf, "model_spread": ms, "ecmwf_spread": es,
            "hours": h, "weights": w}

def build_dist(state, con):
    ed = ecmwf_ens(state)
    if not ed or not con: return None
    ctr = state["center_override"] or round(con["temp"])
    buckets = {t: 0 for t in range(ctr - 8, ctr + 9)}
    for m in ed["members"]:
        r = round(m)
        if r in buckets: buckets[r] += 1
    total = len(ed["members"])
    return [{"temp": t, "prob": cnt / total, "pct": round(cnt / total * 100, 1), "count": cnt}
            for t, cnt in buckets.items()]

def get_pos(state, con):
    ctr = state["center_override"] or con["rounded"]
    return [ctr - 1, ctr, ctr + 1]

# ── Chart ─────────────────────────────────────────────────────────────────────
def make_chart(dist, positions, unit, apt_name, city, confidence, market_type):
    BG, CARD  = "#0d1117", "#161b22"
    MUTED     = "#8b949e"
    HIGHLIGHT = "#1f6feb"
    TEXT      = "#e6edf3"
    GRID      = "#21262d"
    SPINE     = "#30363d"
    ACCENT    = "#58a6ff"

    temps = [d["temp"] for d in dist]
    probs = [d["pct"]  for d in dist]
    cols  = [HIGHLIGHT if t in positions else CARD for t in temps]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    bars = ax.bar(temps, probs, color=cols, edgecolor=BG, linewidth=0.8, width=0.85, zorder=3)
    for bar_, t, p in zip(bars, temps, probs):
        if t in positions and p >= 1.0:
            ax.text(bar_.get_x() + bar_.get_width() / 2, bar_.get_height() + 0.25,
                    "{:.1f}%".format(p), ha="center", va="bottom", fontsize=9,
                    color=ACCENT, fontweight="bold", fontfamily="monospace")

    for p in positions:
        ax.axvline(p, color=ACCENT, linewidth=1.2, linestyle="--", alpha=0.5, zorder=2)

    conf_bar_str = bar(confidence)
    title_type = "High" if market_type == "high" else "Low"
    ax.set_xlabel("Temperature (°{})".format(unit), color=MUTED, fontsize=11, labelpad=8)
    ax.set_ylabel("Ensemble probability (%)", color=MUTED, fontsize=11, labelpad=8)
    ax.set_title(
        "ECMWF Ensemble  ·  {} {}  ·  Daily {}\nConfidence  {}  {}/100".format(
            apt_name, city, title_type, conf_bar_str, round(confidence)),
        color=TEXT, fontsize=11, pad=14, linespacing=1.6
    )
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(SPINE)
    ax.spines["left"].set_color(SPINE)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: "{:.0f}%".format(x)))

    pos_label = "{}\u2013{}°{}".format(positions[0], positions[2], unit)
    legend = [
        mpatches.Patch(color=HIGHLIGHT, label="Recommended positions ({})".format(pos_label)),
        mpatches.Patch(color=CARD,      label="Other buckets"),
    ]
    ax.legend(handles=legend, framealpha=0, labelcolor=MUTED, fontsize=9,
              loc="upper right", borderpad=0)

    plt.tight_layout(pad=1.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf

# ── Messages ──────────────────────────────────────────────────────────────────
def msg_no_data():
    return "\n".join([
        b("⛅ WeatherEdge"), DIV, "",
        "No data loaded yet.", "",
        "Tap {} to pull from all sources.".format(b("🔄 Fetch All")),
    ])

def msg_forecast(state):
    con = build_consensus(state)
    if not con:
        return msg_no_data()

    apt  = AIRPORTS[state["airport"]]
    unit = state["unit"]
    h    = con["hours"]
    dist = build_dist(state, con)
    pos  = get_pos(state, con)
    typ  = "High 🌡" if state["market_type"] == "high" else "Low ❄️"
    w    = con["weights"]

    # Header
    header = "{apt} {city}".format(apt=apt["name"], city=apt["city"])
    lines = [
        b("⛅ WeatherEdge") + "  ·  " + b(esc(header)),
        DIV,
        "📅  " + b(day_label(state["day_offset"])) + "  ·  Daily " + typ + "  ·  " + b("{:.0f}h".format(h)) + " to resolve",
        "🔲  " + window_label(h),
        "",
    ]

    # Model table
    lines.append(b("📊  Model Consensus"))
    lines.append(SDIV)

    w_sum = sum(p["weight"] for p in con["sources"])
    rows  = []
    for s in con["sources"]:
        wt_pct  = round(s["weight"] / w_sum * 100)
        spread  = "±{:.1f}°".format(s["std"]) if s.get("std") else "     "
        bar_str = bar(wt_pct, 100, 8)
        rows.append("{:<12} {:>5.1f}° {:<6}  {}  {:>3}%".format(
            s["name"], s["temp"], spread, bar_str, wt_pct))
    rows.append("─" * 42)
    rows.append("{:<12} {:>5.1f}°".format("Consensus", con["temp"]))
    lines.append(pre("\n".join(rows)))
    lines.append("")

    # Confidence
    score    = con["confidence"]
    bar_str  = bar(score)
    conf_row = "{} {:.0f}/100   spread ±{:.1f}°  ECMWF ±{:.1f}°".format(
               bar_str, score, con["model_spread"], con["ecmwf_spread"])
    lines += [
        b("{} Confidence  {:.0f}/100".format(conf_icon(score), score)),
        c(conf_row),
        "",
    ]

    # Positions
    lines.append(b("📦  3-Position Entry  ({})".format(unit)))
    lines.append(SDIV)

    pos_rows = []
    for idx, p in enumerate(pos):
        model_pct = next((d["pct"] for d in (dist or []) if d["temp"] == p), 0.0)
        is_ctr    = idx == 1
        prefix    = "⭐" if is_ctr else "  "
        alloc     = state["budget"] / 3
        mkt       = state["mkt_prices"].get(p)

        edge_part = ""
        if mkt:
            edge = model_pct / 100 - mkt
            sign = "+" if edge >= 0 else ""
            edge_part = "   edge {}{:.1f}%".format(sign, edge * 100)

        mkt_part  = "   mkt ${:.2f}".format(mkt) if mkt else ""
        ctr_label = "  ← center" if is_ctr else ""

        pos_rows.append("{} {:>3}°{}   {:>5.1f}%   ${:>6.2f}{}{}{}".format(
            prefix, p, unit, model_pct, alloc, mkt_part, edge_part, ctr_label))

    lines.append(pre("\n".join(pos_rows)))
    lines.append("")

    budget_str = "${:.2f}".format(state["budget"])
    sl_str     = "{}%".format(state["stop_loss"])
    lines.append("💰  Budget  " + b(budget_str) + "  ·  Stop loss  " + b(sl_str))

    return "\n".join(lines)


def msg_markets(state):
    apt  = AIRPORTS[state["airport"]]
    poly = state.get("poly")

    if poly is None:
        return "\n".join([b("🏪 Polymarket Markets"), DIV, "", "No data — use Fetch All first."])
    if not poly:
        return "\n".join([b("🏪 Polymarket Markets"), DIV, "",
                          "No markets found for {} temperature.".format(b(esc(apt["city"])))])

    header = "🏪 Polymarket Markets  ·  {} {}".format(b(esc(apt["name"])), esc(apt["city"]))
    lines  = [b("🏪 Polymarket Markets"), DIV,
              it("{} markets found".format(len(poly))), ""]

    for m in poly[:10]:
        q = (m.get("question") or m.get("title") or m.get("slug") or "Unknown")
        q = esc(q[:70] + ("…" if len(q) > 70 else ""))

        prices_raw = m.get("outcomePrices", "[]")
        try:   prices = json.loads(prices_raw) if isinstance(prices_raw, str) else (prices_raw or [])
        except: prices = []

        out_raw = m.get("outcomes", '["Yes","No"]')
        try:   outcomes = json.loads(out_raw) if isinstance(out_raw, str) else (out_raw or ["Yes", "No"])
        except: outcomes = ["Yes", "No"]

        price_parts = []
        for oi, o in enumerate(outcomes[:2]):
            if oi < len(prices) and prices[oi] is not None:
                try:
                    pv = float(prices[oi])
                    price_parts.append("{}: {}".format(esc(str(o)), b("${:.2f}".format(pv))))
                except Exception:
                    pass

        vol = m.get("volume") or m.get("volumeNum")
        end = m.get("endDate") or m.get("endDateIso", "")

        meta = []
        if price_parts: meta.append("  ".join(price_parts))
        if vol:
            try: meta.append("Vol ${:,}".format(int(float(vol))))
            except: pass
        if end:
            try: meta.append("Closes {}".format(end[:10]))
            except: pass

        lines.append("• " + q)
        if meta: lines.append("  " + it("  ·  ".join(meta)))
        lines.append("")

    return "\n".join(lines)


def msg_strategy(state):
    con = build_consensus(state)
    if not con:
        return "\n".join([b("💡 Strategy"), DIV, "", "No data — use Fetch All first."])

    apt   = AIRPORTS[state["airport"]]
    unit  = state["unit"]
    h     = con["hours"]
    dist  = build_dist(state, con)
    pos   = get_pos(state, con)
    alloc = state["budget"] / 3
    typ   = "High" if state["market_type"] == "high" else "Low"

    header = "{} Daily {}  ·  {}".format(apt["name"], typ, day_label(state["day_offset"]))
    lines  = [b("💡 Strategy  ·  " + esc(header)), DIV, "", b("📦  3-Position Entry Plan"), SDIV]

    pos_rows = []
    for idx, p in enumerate(pos):
        model_pct  = next((d["pct"] for d in (dist or []) if d["temp"] == p), 0.0)
        label      = "LOW   " if idx == 0 else "CENTER" if idx == 1 else "HIGH  "
        mkt        = state["mkt_prices"].get(p)
        edge_str   = ""
        profit_str = ""
        if mkt:
            edge       = model_pct / 100 - mkt
            profit     = alloc * (1 - mkt) / mkt if mkt > 0 else 0
            sign       = "+" if edge >= 0 else ""
            edge_str   = "  edge {}{:.1f}%".format(sign, edge * 100)
            profit_str = "  win +${:.2f}".format(profit)
        mkt_str = "  mkt ${:.2f}".format(mkt) if mkt else ""
        pos_rows.append("  {}  {:>3}°{}  {:>5.1f}%  ${:.2f}{}{}{}".format(
            label, p, unit, model_pct, alloc, mkt_str, edge_str, profit_str))

    lines.append(pre("\n".join(pos_rows)))

    budget_str  = "${:.2f}".format(state["budget"])
    maxloss_str = "${:.2f}".format(state["budget"] * state["stop_loss"] / 100)
    alloc_str   = "${:.2f}".format(alloc)
    sl_str      = "{}%".format(state["stop_loss"])

    lines += [
        "",
        "💰  Budget {}  ·  {}/leg  ·  Max loss {}".format(
            b(budget_str), alloc_str, b(maxloss_str)),
        "",
        b("🛡️  Stop Loss Rules"),
        SDIV,
    ]

    rules = (
        "  Rule 1 — PRICE STOP\n"
        "  Exit any leg if it drops {} from entry. No exceptions.\n"
        "\n"
        "  Rule 2 — CONSENSUS SHIFT\n"
        "  If model moves >2°{} from center ({}°), exit outer legs first.\n"
        "\n"
        "  Rule 3 — HOLD WINNER\n"
        "  Center >$0.75 with <6h left → hold to resolution.\n"
        "\n"
        "  Rule 4 — CORRELATED DROP\n"
        "  All 3 legs fall together → regime change. Exit all."
    ).format(sl_str, unit, pos[1])

    lines.append(pre(rules))
    lines += ["", b("⏱️  Entry Window  ({:.0f}h left)".format(h)), SDIV]

    if h > 60:
        tip = ("  🌐 EARLY WINDOW (60h+)\n"
               "  ECMWF ensemble dominant. Markets usually mispriced at open.\n"
               "  Best entry price — enter if confidence >60.")
    elif h > 36:
        tip = ("  📡 MID WINDOW (36–60h)\n"
               "  HRRR begins outperforming ECMWF. Confirm consensus hasn't\n"
               "  shifted since open. Good scale-in window.")
    elif h > 12:
        tip = ("  🎯 LATE WINDOW (12–36h)\n"
               "  HRRR dominant. METAR anchoring short-term. Highest model\n"
               "  accuracy. Best conviction window for entry.")
    else:
        tip = ("  🔴 FINAL WINDOW (0–12h)\n"
               "  METAR is now ground truth. Do NOT open new positions.\n"
               "  Manage existing: hold winners, cut positions below stop.")
    lines.append(pre(tip))

    return "\n".join(lines)


def msg_ai(state):
    if not ANTHROPIC_KEY:
        return "\n".join([
            b("🤖 AI Analysis"), DIV, "",
            "No Anthropic API key configured.", "",
            "Add " + c("ANTHROPIC_KEY=your_key") + " to your " + c(".env") + " file.",
        ])

    con = build_consensus(state)
    if not con:
        return "No data — fetch first."

    apt  = AIRPORTS[state["airport"]]
    unit = state["unit"]
    dist = build_dist(state, con)
    pos  = get_pos(state, con)

    top_b = ", ".join(
        "{}°{}:{:.1f}%".format(d["temp"], unit, d["pct"])
        for d in sorted(dist or [], key=lambda x: -x["prob"])[:8]
        if d["prob"] > 0.02
    )
    mkt_str = ", ".join(
        "{}°:{}".format(p, state["mkt_prices"].get(p, "?")) for p in pos
    )
    src_str = " | ".join(
        "{}={:.1f}°".format(s["name"], s["temp"]) for s in con["sources"]
    )

    prompt_lines = [
        "Expert prediction market weather trader. Return JSON only, no markdown.",
        "",
        "MARKET: {} {} Daily {} °{}".format(
            state["airport"], apt["city"],
            "HIGH" if state["market_type"] == "high" else "LOW", unit),
        "DAY: +{}d  HOURS: {:.1f}h".format(state["day_offset"], con["hours"]),
        "CONSENSUS: {:.1f}°{}".format(con["temp"], unit),
        "SOURCES: {}".format(src_str),
        "SPREADS: model=±{:.1f}° ecmwf=±{:.1f}°".format(
            con["model_spread"], con["ecmwf_spread"]),
        "CONFIDENCE: {:.0f}/100".format(con["confidence"]),
        "ECMWF TOP: {}".format(top_b),
        "POSITIONS: {}°, {}° (center), {}°{}".format(pos[0], pos[1], pos[2], unit),
        "MARKET PRICES: {}".format(mkt_str),
        "",
        ('Return: {"signal":"GO|CAUTIOUS|NO-GO","confidence":0-100,'
         '"summary":"1-2 sentences","flags":["..."],'
         '"stop_loss":"specific advice","timing":"entry timing","edge":"N/A or calc"}'),
    ]

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json",
                     "x-api-key": ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 600,
                  "messages": [{"role": "user", "content": "\n".join(prompt_lines)}]},
            timeout=30,
        )
        raw  = r.json()["content"][0]["text"]
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())

        sig      = data.get("signal", "?")
        sig_icon = {"GO": "🟢", "CAUTIOUS": "🟡", "NO-GO": "🔴"}.get(sig, "⚪")
        conf_val = data.get("confidence", "?")

        parts = [
            b("{} AI Signal: {}".format(sig_icon, sig)) + "  " + it("({}/100)".format(conf_val)),
            DIV,
            esc(data.get("summary", "")),
        ]
        flags = data.get("flags", [])
        if flags:
            parts += ["", b("⚠️  Risk Flags")] + ["  • " + esc(f) for f in flags]
        if data.get("stop_loss"):
            parts += ["", b("📉 Stop Loss:") + "  " + esc(data["stop_loss"])]
        if data.get("timing"):
            parts += [b("⏰ Timing:") + "  " + esc(data["timing"])]
        if data.get("edge") and data["edge"] != "N/A":
            parts += [b("📊 Edge:") + "  " + esc(data["edge"])]
        return "\n".join(parts)

    except Exception as e:
        return b("⚠️ AI Error") + "\n\n" + esc(str(e))


# ── Keyboards ──────────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄  Fetch All Data",     callback_data="fetch_all")],
        [InlineKeyboardButton("🏢  Airport",            callback_data="menu_airport"),
         InlineKeyboardButton("📅  Day",                callback_data="menu_day")],
        [InlineKeyboardButton("🌡️  High / Low",         callback_data="menu_type"),
         InlineKeyboardButton("°F  /  °C",              callback_data="menu_unit")],
        [InlineKeyboardButton("📊  Forecast",           callback_data="show_forecast"),
         InlineKeyboardButton("🏪  Markets",            callback_data="show_markets")],
        [InlineKeyboardButton("💡  Strategy",           callback_data="show_strategy"),
         InlineKeyboardButton("🤖  AI Signal",          callback_data="run_ai")],
    ])

def kb_forecast():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  Distribution Chart",  callback_data="send_chart"),
         InlineKeyboardButton("🔄  Refresh",             callback_data="fetch_all")],
        [InlineKeyboardButton("🏪  Markets",              callback_data="show_markets"),
         InlineKeyboardButton("💡  Strategy",             callback_data="show_strategy")],
        [InlineKeyboardButton("🤖  AI Signal",            callback_data="run_ai"),
         InlineKeyboardButton("←  Menu",                  callback_data="back_main")],
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("←  Main Menu", callback_data="back_main")]])

def kb_airports(current):
    items = list(AIRPORTS.items())
    rows  = []
    for i in range(0, len(items), 2):
        rows.append([
            InlineKeyboardButton(
                "{}{} {}".format("✓ " if k == current else "", v["name"], v["city"]),
                callback_data="set_airport_" + k,
            )
            for k, v in items[i:i+2]
        ])
    rows.append([InlineKeyboardButton("←  Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_day(cur):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("{}Today".format("✓ " if cur == 0 else ""),    callback_data="set_day_0"),
         InlineKeyboardButton("{}Tomorrow".format("✓ " if cur == 1 else ""), callback_data="set_day_1"),
         InlineKeyboardButton("{}+2 Days".format("✓ " if cur == 2 else ""),  callback_data="set_day_2")],
        [InlineKeyboardButton("←  Back", callback_data="back_main")],
    ])

def kb_type(cur):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("{}🌡️  Daily High".format("✓ " if cur == "high" else ""), callback_data="set_type_high"),
         InlineKeyboardButton("{}❄️  Daily Low".format("✓ " if cur == "low"  else ""), callback_data="set_type_low")],
        [InlineKeyboardButton("←  Back", callback_data="back_main")],
    ])

def kb_unit(cur):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("{}  Fahrenheit  °F".format("✓" if cur == "F" else ""), callback_data="set_unit_F"),
         InlineKeyboardButton("{}  Celsius  °C".format("✓" if cur == "C" else ""),    callback_data="set_unit_C")],
        [InlineKeyboardButton("←  Back", callback_data="back_main")],
    ])

# ── Handlers ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    apt   = AIRPORTS[state["airport"]]

    apt_row  = "{:5}  {}".format(apt["name"], apt["city"])
    type_row = "{:5}  Daily {}".format(
        "High" if state["market_type"] == "high" else "Low",
        "High" if state["market_type"] == "high" else "Low")
    day_row  = "{:8}  Target day".format(day_label(state["day_offset"]))
    unit_row = "°{:4}  Unit".format(state["unit"])

    text = "\n".join([
        b("⛅  WeatherEdge"),
        DIV,
        it("Polymarket Weather Trading Bot"),
        "",
        ("Combines ECMWF ensemble (51 members), HRRR, METAR/ASOS, and "
         "OpenWeather into a time-weighted forecast for Polymarket daily "
         "temperature markets. Recommends 3 adjacent positions with confidence "
         "scoring and edge calculation."),
        "",
        b("Current Target"),
        SDIV,
        c(apt_row),
        c(type_row),
        c(day_row),
        c(unit_row),
        "",
        b("Quick Commands"),
        SDIV,
        c("/price 72 0.35") + "  log a market price",
        c("/budget 30")     + "  set total budget",
        c("/stoploss 50")   + "  set stop loss %",
        c("/override 73")   + "  override center position",
        c("/reset")         + "  clear prices + override",
        c("/help")          + "  all commands",
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "\n".join([
        b("⛅  WeatherEdge  —  Commands"),
        DIV, "",
        b("Navigation"),
        c("/start")     + "           main menu",
        c("/fetch")     + "           fetch all data + forecast",
        c("/forecast")  + "           current consensus",
        c("/chart")     + "           ECMWF distribution chart",
        c("/markets")   + "           live Polymarket listings",
        c("/strategy")  + "           3-position entry plan",
        c("/analyze")   + "           AI trading signal",
        "",
        b("Configuration"),
        c("/price [T] [P]")  + "   log market price",
        "                    " + it("e.g. /price 72 0.35"),
        c("/budget [amt]")   + "    set total budget",
        "                    " + it("e.g. /budget 30"),
        c("/stoploss [%]")   + "    set stop loss %",
        "                    " + it("e.g. /stoploss 50"),
        c("/override [T]")   + "    override center position",
        "                    " + it("e.g. /override 73"),
        c("/reset")          + "           clear prices + override",
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    msg   = await update.message.reply_text(
        "\n".join([b("⏳  Fetching data…"), SDIV,
                   it("Pulling HRRR · ECMWF · METAR · OpenWeather · Polymarket")]),
        parse_mode=ParseMode.HTML,
    )
    status = await asyncio.to_thread(fetch_all, state)
    sl_str = "  ".join("{} {}".format(k, v) for k, v in status.items())
    text   = "{}\n\n{}\n{}".format(msg_forecast(state), SDIV, it(sl_str))
    await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_forecast())


async def cmd_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid   = update.effective_chat.id
    state = get_state(cid)
    await update.message.reply_text(msg_forecast(state), parse_mode=ParseMode.HTML, reply_markup=kb_forecast())


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    con  = build_consensus(state)
    if not con:
        await update.message.reply_text(
            "\n".join([b("❌  No Data"), "", "Use /fetch first."]),
            parse_mode=ParseMode.HTML)
        return
    dist = build_dist(state, con)
    if not dist:
        await update.message.reply_text(
            "\n".join([b("❌  No ECMWF Data"), "", "ECMWF ensemble didn't load."]),
            parse_mode=ParseMode.HTML)
        return
    apt = AIRPORTS[state["airport"]]
    pos = get_pos(state, con)
    buf = await asyncio.to_thread(make_chart, dist, pos, state["unit"],
                                  apt["name"], apt["city"], con["confidence"], state["market_type"])
    caption = ("ECMWF Ensemble  ·  {} {}  ·  Daily {}\n"
               "{}  ·  {:.1f}°{}  ·  Confidence {:.0f}/100").format(
               apt["name"], apt["city"],
               "High" if state["market_type"] == "high" else "Low",
               day_label(state["day_offset"]), con["temp"], state["unit"], con["confidence"])
    await update.message.reply_photo(photo=buf, caption=caption)


async def cmd_markets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    await update.message.reply_text(msg_markets(state), parse_mode=ParseMode.HTML, reply_markup=kb_back())


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    await update.message.reply_text(msg_strategy(state), parse_mode=ParseMode.HTML, reply_markup=kb_back())


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    msg  = await update.message.reply_text(
        "\n".join([b("🤖  Running AI Analysis…"), SDIV, it("Synthesizing model data…")]),
        parse_mode=ParseMode.HTML,
    )
    result = await asyncio.to_thread(msg_ai, state)
    await msg.edit_text(result, parse_mode=ParseMode.HTML, reply_markup=kb_back())


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "\n".join([b("📌  Log Market Price"), SDIV, "",
                       "Usage:  " + c("/price [temp] [price]"),
                       "Example:  " + c("/price 72 0.35")]),
            parse_mode=ParseMode.HTML)
        return
    try:
        temp  = int(args[0])
        price = float(args[1])
        if not 0 < price < 1: raise ValueError
        state["mkt_prices"][temp] = price

        con  = build_consensus(state)
        dist = build_dist(state, con) if con else None
        mp   = next((d["pct"] for d in (dist or []) if d["temp"] == temp), None)

        logged_row = "{}°{}  →  ${:.2f}".format(temp, state["unit"], price)
        parts = [b("✅  Price Logged"), SDIV, c(logged_row)]
        if mp is not None:
            edge = mp / 100 - price
            sign = "+" if edge >= 0 else ""
            icon = "🟢" if edge > 0.05 else "🟡" if edge > -0.05 else "🔴"
            parts += ["",
                      "Model prob:  " + b("{:.1f}%".format(mp)),
                      "Edge:  " + b("{}{:.1f}%".format(sign, edge * 100)) + "  " + icon]
        await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)
    except (ValueError, IndexError):
        await update.message.reply_text(
            "\n".join([b("❌  Invalid Input"), "",
                       "Usage:  " + c("/price 72 0.35"),
                       "Price must be between 0 and 1."]),
            parse_mode=ParseMode.HTML)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    try:
        state["budget"] = float((context.args or [])[0])
        total_str = "${:.2f}".format(state["budget"])
        leg_str   = "${:.2f}".format(state["budget"] / 3)
        await update.message.reply_text(
            "\n".join([b("✅  Budget Updated"), SDIV,
                       c("Total:   " + total_str),
                       c("Per leg: " + leg_str)]),
            parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Usage:  " + c("/budget 30"), parse_mode=ParseMode.HTML)


async def cmd_stoploss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    try:
        state["stop_loss"] = int((context.args or [])[0])
        sl_str = "Exit any leg if it drops  {}%  from entry".format(state["stop_loss"])
        await update.message.reply_text(
            "\n".join([b("✅  Stop Loss Updated"), SDIV, c(sl_str)]),
            parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Usage:  " + c("/stoploss 50"), parse_mode=ParseMode.HTML)


async def cmd_override(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    try:
        state["center_override"] = int((context.args or [])[0])
        ov_str = "Positions will center on  {}°{}".format(
            state["center_override"], state["unit"])
        await update.message.reply_text(
            "\n".join([b("✅  Center Override Set"), SDIV, c(ov_str)]),
            parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Usage:  " + c("/override 73"), parse_mode=ParseMode.HTML)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    state = get_state(cid)
    state["mkt_prices"]      = {}
    state["center_override"] = None
    await update.message.reply_text(
        "\n".join([b("✅  Reset Complete"), SDIV,
                   c("Market prices cleared"),
                   c("Center override cleared")]),
        parse_mode=ParseMode.HTML)


# ── Callback handler ───────────────────────────────────────────────────────────
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    cid  = q.message.chat_id
    state = get_state(cid)
    d    = q.data

    if d == "back_main":
        apt      = AIRPORTS[state["airport"]]
        apt_row  = "{:5}  {}".format(apt["name"], apt["city"])
        type_str = "High" if state["market_type"] == "high" else "Low"
        type_row = "{:5}  Daily {}".format(type_str, type_str)
        day_row  = "{:8}  Target".format(day_label(state["day_offset"]))
        unit_row = "°{:4}  Unit".format(state["unit"])
        text = "\n".join([
            b("⛅  WeatherEdge"), DIV, "",
            c(apt_row), c(type_row), c(day_row), c(unit_row),
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif d == "menu_airport":
        await q.edit_message_text(b("🏢  Select Airport") + "\n" + DIV,
                                   parse_mode=ParseMode.HTML, reply_markup=kb_airports(state["airport"]))
    elif d == "menu_day":
        await q.edit_message_text(b("📅  Select Target Day") + "\n" + DIV,
                                   parse_mode=ParseMode.HTML, reply_markup=kb_day(state["day_offset"]))
    elif d == "menu_type":
        await q.edit_message_text(b("🌡️  Select Market Type") + "\n" + DIV,
                                   parse_mode=ParseMode.HTML, reply_markup=kb_type(state["market_type"]))
    elif d == "menu_unit":
        await q.edit_message_text(b("°  Select Temperature Unit") + "\n" + DIV,
                                   parse_mode=ParseMode.HTML, reply_markup=kb_unit(state["unit"]))

    elif d.startswith("set_airport_"):
        state["airport"] = d[len("set_airport_"):]
        apt = AIRPORTS[state["airport"]]
        row = "{}  —  {}".format(apt["name"], apt["city"])
        await q.edit_message_text(
            "\n".join([b("✅  Airport Updated"), SDIV, c(row)]),
            parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif d.startswith("set_day_"):
        state["day_offset"] = int(d[len("set_day_"):])
        await q.edit_message_text(
            "\n".join([b("✅  Target Day Updated"), SDIV, c(day_label(state["day_offset"]))]),
            parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif d.startswith("set_type_"):
        state["market_type"] = d[len("set_type_"):]
        type_str = "Daily High" if state["market_type"] == "high" else "Daily Low"
        await q.edit_message_text(
            "\n".join([b("✅  Market Type Updated"), SDIV, c(type_str)]),
            parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif d.startswith("set_unit_"):
        state["unit"] = d[len("set_unit_"):]
        await q.edit_message_text(
            "\n".join([b("✅  Unit Updated"), SDIV, c("°" + state["unit"])]),
            parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif d == "fetch_all":
        await q.edit_message_text(
            "\n".join([b("⏳  Fetching data…"), SDIV,
                       it("HRRR · ECMWF · METAR · OpenWeather · Polymarket")]),
            parse_mode=ParseMode.HTML)
        status = await asyncio.to_thread(fetch_all, state)
        sl = "  ".join("{} {}".format(k, v) for k, v in status.items())
        text = "{}\n\n{}\n{}".format(msg_forecast(state), SDIV, it(sl))
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_forecast())

    elif d == "show_forecast":
        await q.edit_message_text(msg_forecast(state), parse_mode=ParseMode.HTML, reply_markup=kb_forecast())

    elif d == "show_markets":
        await q.edit_message_text(msg_markets(state), parse_mode=ParseMode.HTML, reply_markup=kb_back())

    elif d == "show_strategy":
        await q.edit_message_text(msg_strategy(state), parse_mode=ParseMode.HTML, reply_markup=kb_back())

    elif d == "run_ai":
        await q.edit_message_text(
            "\n".join([b("🤖  Running AI Analysis…"), SDIV, it("Synthesizing forecast data…")]),
            parse_mode=ParseMode.HTML)
        result = await asyncio.to_thread(msg_ai, state)
        await q.edit_message_text(result, parse_mode=ParseMode.HTML, reply_markup=kb_back())

    elif d == "send_chart":
        con = build_consensus(state)
        if not con:
            await q.answer("No data yet — fetch first", show_alert=True); return
        dist = build_dist(state, con)
        if not dist:
            await q.answer("No ECMWF data for chart", show_alert=True); return
        apt = AIRPORTS[state["airport"]]
        pos = get_pos(state, con)
        buf = await asyncio.to_thread(make_chart, dist, pos, state["unit"],
                                      apt["name"], apt["city"], con["confidence"], state["market_type"])
        caption = ("ECMWF Ensemble  ·  {} {}  ·  Daily {}\n"
                   "{}  ·  {:.1f}°{}  ·  Confidence {:.0f}/100").format(
                   apt["name"], apt["city"],
                   "High" if state["market_type"] == "high" else "Low",
                   day_label(state["day_offset"]), con["temp"], state["unit"], con["confidence"])
        await q.message.reply_photo(photo=buf, caption=caption)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("ERROR: TELEGRAM_TOKEN is not set in your .env file")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    for cmd, handler in [
        ("start",    cmd_start),
        ("help",     cmd_help),
        ("fetch",    cmd_fetch),
        ("forecast", cmd_forecast),
        ("chart",    cmd_chart),
        ("markets",  cmd_markets),
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

    print("⛅  WeatherEdge bot started")
    print("   Telegram:     set" if TELEGRAM_TOKEN else "   Telegram:     MISSING")
    print("   OpenWeather:  set" if OW_KEY else "   OpenWeather:  not set (optional)")
    print("   Anthropic AI: set" if ANTHROPIC_KEY else "   Anthropic AI: not set (optional)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
