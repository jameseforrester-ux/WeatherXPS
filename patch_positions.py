#!/usr/bin/env python3
"""
WeatherEdge — Positions + METAR Alerts + Persistent Menu
Run with: python3 patch_positions.py
"""
import ast

MARKER = "# POSITIONS_PATCH_v1"

with open("bot.py") as f:
    src = f.read()

if MARKER in src:
    print("Already patched.")
    exit(0)

errors = []

def replace(old, new, label):
    global src
    if old in src:
        src = src.replace(old, new, 1)
        print("  OK  " + label)
    else:
        errors.append(label)
        print("  !!  " + label + " -- not found")

# ── 1. Imports ────────────────────────────────────────────────────────────────
replace(
    "import os, io, re, json, math, asyncio, html, requests, requests.utils",
    "import os, io, re, json, math, uuid, asyncio, html, requests, requests.utils",
    "add uuid"
)
replace(
    "from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup",
    "from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton",
    "add ReplyKeyboardMarkup"
)
replace(
    "from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes",
    "from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters",
    "add MessageHandler"
)

# ── 2. Core additions after user_states ───────────────────────────────────────
CORE = r"""
# POSITIONS_PATCH_v1
# -- Persistent bottom keyboard -----------------------------------------------
BOTTOM_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("\U0001f321\ufe0f  Markets"),  KeyboardButton("\U0001f4cb  Positions")],
        [KeyboardButton("\U0001f504  Refresh"),        KeyboardButton("\u2699\ufe0f  Settings")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# -- Position storage (JSON, survives restarts) --------------------------------
_PF = "positions.json"

def _pload() -> dict:
    try:
        with open(_PF) as f:
            return json.load(f)
    except Exception:
        return {}

def _psave(d: dict):
    try:
        with open(_PF, "w") as f:
            json.dump(d, f, default=str, indent=2)
    except Exception:
        pass

_ps: dict = _pload()

def pos_get(cid: int) -> list:
    return _ps.get(str(cid), {}).get("p", [])

def _pw(cid: int, positions: list):
    _ps.setdefault(str(cid), {})["p"] = positions
    _psave(_ps)

def pos_add(cid: int, pos: dict):
    lst = pos_get(cid)
    lst.append(pos)
    _pw(cid, lst)

def pos_update(cid: int, pid: str, updates: dict):
    lst = pos_get(cid)
    for p in lst:
        if p.get("id") == pid:
            p.update(updates)
    _pw(cid, lst)

def pos_active_today() -> list:
    today = datetime.now().date()
    out = []
    for cs, data in _ps.items():
        for p in data.get("p", []):
            if p.get("status") != "active":
                continue
            try:
                if datetime.fromisoformat(p["target_date"]).date() == today:
                    out.append((int(cs), p))
            except Exception:
                pass
    return out

# -- METAR trend alert logic --------------------------------------------------
def metar_trend_alert(pos: dict, city: dict, md: list) -> Optional[str]:
    if not isinstance(md, list) or not md:
        return None
    raw = md[0].get("temp")
    if raw is None:
        return None
    unit  = city["unit"]
    curr  = c_to_f(raw) if unit == "F" else float(raw)
    mtype = pos["market_type"]
    us    = "\u00b0" + unit
    flag  = city["flag"]
    disp  = city["display"]

    hist = pos.get("metar_history", [])
    hist.append({"time": datetime.now().isoformat(), "temp": curr})
    hist = hist[-10:]
    pos["metar_history"] = hist
    if len(hist) < 2:
        return None

    temps  = [h["temp"] for h in hist]
    recent = temps[-4:] if len(temps) >= 4 else temps
    delta  = recent[-1] - recent[0]
    if   delta >  0.5: trend = "rising"
    elif delta < -0.5: trend = "falling"
    else:              trend = "flat"

    brackets  = pos.get("brackets", [])
    if not brackets:
        return None
    labels    = [bk["label"] for bk in brackets]
    parsed    = [parse_bracket(bk["label"]) for bk in brackets]
    parsed    = [p for p in parsed if p]
    if not parsed:
        return None
    pos_lo    = min(p[0] for p in parsed if p[0] != -INF)
    pos_hi    = max(p[1] for p in parsed if p[1] !=  INF)
    ctr_bk    = brackets[len(brackets) // 2]
    ctr_p     = parse_bracket(ctr_bk["label"])
    if not ctr_p:
        return None
    ctr_lo, ctr_hi = ctr_p
    lh        = datetime.now().hour
    alerts    = pos.get("alerts_sent", {})
    now_s     = datetime.now().isoformat()

    def sent(key, h=2.0):
        last = alerts.get(key)
        if not last:
            return False
        try:
            return (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600 < h
        except Exception:
            return False

    def mark(key):
        alerts[key] = now_s
        pos["alerts_sent"] = alerts

    hl = hours_left_to(datetime.fromisoformat(pos["target_date"]))

    if hl <= 1.0 and not sent("final", 1.0):
        mark("final")
        oc   = "inside \u2705" if pos_lo <= curr <= pos_hi else "outside \u274c"
        cs   = "{:.1f}{}".format(curr, us)
        rs   = "{:.0f}\u2013{:.0f}{}".format(pos_lo, pos_hi, us)
        bks  = "  ".join(labels)
        return ("\u23f0 " + b("FINAL HOUR") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "METAR:  " + c(cs) + "\n"
                + "Range:  " + c(rs) + "  " + oc + "\n"
                + "Brackets: " + c(bks))

    if lh < 9:
        return None

    if (trend == "flat" and mtype == "highest"
            and curr < ctr_lo - 1.5 and lh >= 12 and not sent("plateau")):
        mark("plateau")
        return ("\u26a0\ufe0f " + b("METAR PLATEAU") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "Flat at " + c("{:.1f}{}".format(curr, us)) + " for " + str(len(recent)*30) + "min\n"
                + "Center: " + c(ctr_bk["label"]) + "\n"
                + "\U0001f4c9 High may not reach target. Consider exiting outer brackets.")

    if (len(temps) >= 4 and mtype == "highest"
            and max(temps) < ctr_lo and temps[-1] < max(temps) - 1.0
            and not sent("peak")):
        mark("peak")
        pk = max(temps)
        return ("\U0001f534 " + b("PEAK MAY BE IN") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "Peaked " + c("{:.1f}{}".format(pk, us)) + " now " + c("{:.1f}{}".format(curr, us)) + "\n"
                + "Center: " + c(ctr_bk["label"]) + "\n"
                + "\u26a0\ufe0f High may be set below your position range.")

    if (trend == "rising" and mtype == "highest"
            and ctr_lo - 3 <= curr <= ctr_lo and not sent("approach")):
        mark("approach")
        return ("\U0001f4c8 " + b("APPROACHING TARGET") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "METAR " + c("{:.1f}{}".format(curr, us)) + " and rising\n"
                + "Center: " + c(ctr_bk["label"]) + "\n"
                + "\U0001f7e2 Tracking toward position.")

    if ctr_lo <= curr <= ctr_hi and not sent("inside", 3.0):
        mark("inside")
        return ("\u2705 " + b("INSIDE TARGET") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "METAR " + c("{:.1f}{}".format(curr, us)) + " inside " + c(ctr_bk["label"]) + "\n"
                + "\U0001f7e2 Hold position.")

    if curr > pos_hi + 1 and mtype == "highest" and not sent("exceeded"):
        mark("exceeded")
        return ("\U0001f525 " + b("EXCEEDED RANGE") + "  " + flag + " " + esc(disp) + "\n"
                + DIV + "\n"
                + "METAR " + c("{:.1f}{}".format(curr, us)) + " above " + c("{:.0f}{}".format(pos_hi, us)) + "\n"
                + "Consider exiting highest bracket early.")

    return None

# -- Background METAR alert job (every 30 min) --------------------------------
async def metar_alert_job(context) -> None:
    for cid, pos in pos_active_today():
        city = CITY_DB.get(pos.get("city_key"))
        if not city:
            continue
        try:
            md    = await asyncio.to_thread(fetch_metar, city["metar"])
            alert = metar_trend_alert(pos, city, md)
            _pw(cid, pos_get(cid))
            if alert:
                await context.bot.send_message(cid, alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass

# -- Position UI --------------------------------------------------------------
def msg_positions(cid: int) -> str:
    positions = pos_get(cid)
    active    = [p for p in positions if p.get("status") == "active"]
    closed    = [p for p in positions if p.get("status") != "active"]

    if not positions:
        return "\n".join([
            b("\U0001f4cb  My Positions"), DIV, "",
            "No positions recorded yet.", "",
            "Open a market analysis and tap",
            b("\U0001f4cc  Enter Position") + " to start tracking.",
        ])

    lines = [b("\U0001f4cb  My Positions"), DIV]
    if active:
        lines += ["", b("Active  \u00b7  " + str(len(active)))]
        for p in active:
            city = CITY_DB.get(p.get("city_key", ""), {})
            flag = city.get("flag", "\U0001f30d")
            disp = city.get("display", p.get("city_key", "?"))
            unit = city.get("unit", "F")
            typ  = "\U0001f321\ufe0f" if p.get("market_type") == "highest" else "\u2744\ufe0f"
            try:
                dt = datetime.fromisoformat(p["target_date"])
                dl = day_label(dt)
                h  = hours_left_to(dt)
            except Exception:
                dl, h = "?", 0
            bks = "  ".join(bk["label"] for bk in p.get("brackets", []))
            mt  = ""
            if p.get("metar_history"):
                last = p["metar_history"][-1].get("temp")
                if last is not None:
                    mt = "  METAR {:.1f}\u00b0{}".format(last, unit)
            lines.append(
                "\n" + flag + "  " + b(esc(disp)) + "  " + typ + "  " + esc(dl)
                + "  " + hours_label(h) + " left\n  " + c(bks) + mt
            )

    if closed:
        lines += ["", b("Closed")]
        for p in closed[-3:]:
            city = CITY_DB.get(p.get("city_key", ""), {})
            flag = city.get("flag", "\U0001f30d")
            disp = city.get("display", "?")
            try:
                dl = datetime.fromisoformat(p["target_date"]).strftime("%b %-d")
            except Exception:
                dl = "?"
            lines.append("  " + flag + " " + esc(disp) + "  " + esc(dl))

    return "\n".join(lines)


def kb_positions(positions: list) -> InlineKeyboardMarkup:
    active = [p for p in positions if p.get("status") == "active"]
    rows   = []
    for p in active:
        city = CITY_DB.get(p.get("city_key", ""), {})
        flag = city.get("flag", "\U0001f30d")
        disp = city.get("display", p.get("city_key", "?"))[:12]
        typ  = "\U0001f321\ufe0f" if p.get("market_type") == "highest" else "\u2744\ufe0f"
        try:
            dl = day_label(datetime.fromisoformat(p["target_date"]))
        except Exception:
            dl = "?"
        rows.append([InlineKeyboardButton(
            flag + typ + " " + disp + "  \u00b7  " + dl,
            callback_data="pos_detail_" + p["id"]
        )])
    rows.append([InlineKeyboardButton("\u2190  Main Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_enter_pos(brackets: list, center_idx: int) -> InlineKeyboardMarkup:
    pos_bks  = [brackets[i] for i in range(
        max(0, center_idx - 1), min(len(brackets), center_idx + 2)
    )]
    lbl_str  = "  ".join(bk["label"] for bk in pos_bks)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "\u2705  Confirm: " + lbl_str,
            callback_data="enter_pos_confirm"
        )],
        [InlineKeyboardButton("\u2715  Cancel", callback_data="cancel_enter_pos")],
    ])


def make_pos(state: dict, city: dict, brackets: list, center_idx: int) -> dict:
    active  = state["active"]
    pos_bks = [brackets[i] for i in range(
        max(0, center_idx - 1), min(len(brackets), center_idx + 2)
    )]
    return {
        "id":            str(uuid.uuid4())[:8],
        "city_key":      active["city_key"],
        "market_type":   active["market_type"],
        "target_date":   active["target_date"].isoformat(),
        "event_slug":    active.get("event_slug", ""),
        "brackets":      [
            {"label": bk["label"],
             "entry_price": bk.get("manual_price") or bk.get("yes_price"),
             "amount": round(state["budget"] / 3, 2)}
            for bk in pos_bks
        ],
        "entered_at":    datetime.now().isoformat(),
        "status":        "active",
        "metar_history": [],
        "alerts_sent":   {},
    }

"""

replace(
    "user_states: Dict[int, Dict] = {}",
    "user_states: Dict[int, Dict] = {}" + CORE,
    "core additions"
)

# ── 3. Enter Position button ──────────────────────────────────────────────────
replace(
    """def kb_analysis():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  Distribution Chart",  callback_data="send_chart"),
         InlineKeyboardButton("💡  Strategy",            callback_data="show_strategy")],
        [InlineKeyboardButton("🤖  AI Signal",           callback_data="run_ai"),
         InlineKeyboardButton("🌡  Browse Markets",      callback_data="browse_markets")],
        [InlineKeyboardButton("←  Menu",                 callback_data="back_main")],
    ])""",
    """def kb_analysis():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌  Enter Position",      callback_data="show_enter_pos")],
        [InlineKeyboardButton("📊  Distribution Chart",  callback_data="send_chart"),
         InlineKeyboardButton("💡  Strategy",            callback_data="show_strategy")],
        [InlineKeyboardButton("🤖  AI Signal",           callback_data="run_ai"),
         InlineKeyboardButton("🌡  Browse Markets",      callback_data="browse_markets")],
        [InlineKeyboardButton("←  Menu",                 callback_data="back_main")],
    ])""",
    "Enter Position button"
)

# ── 4. New command handlers ───────────────────────────────────────────────────
NEW_CMDS = """
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        msg_positions(cid),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_positions(pos_get(cid)),
    )


async def handle_kb_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    text = (update.message.text or "").strip()
    if   text.endswith("Markets"):    await cmd_markets(update, context)
    elif text.endswith("Positions"):  await cmd_positions(update, context)
    elif text.endswith("Refresh"):    await cmd_refresh(update, context)
    elif text.endswith("Settings"):
        state  = get_state(cid)
        bs  = "${:.2f}".format(state["budget"])
        ps  = "${:.2f}".format(state["budget"] / 3)
        ss  = "{}%".format(state["stop_loss"])
        await update.message.reply_text(
            b("\u2699\ufe0f  Settings") + "\\n" + DIV + "\\n\\n"
            + "Budget:      " + b(bs) + "\\n"
            + "Per bracket: " + b(ps) + "\\n"
            + "Stop loss:   " + b(ss) + "\\n\\n"
            + "Use " + c("/budget [amount]") + " and " + c("/stoploss [%]") + " to update.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back(),
        )

"""

replace(
    "async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):",
    NEW_CMDS + "async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):",
    "new command handlers"
)

# ── 5. Send BOTTOM_KB in cmd_start ────────────────────────────────────────────
replace(
    "    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())",
    ("    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())\n"
     '    await update.message.reply_text(\n'
     '        it("Shortcuts always available below \u2193"),\n'
     '        parse_mode=ParseMode.HTML,\n'
     '        reply_markup=BOTTOM_KB,\n'
     '    )'),
    "send BOTTOM_KB in /start"
)

# ── 6. Position callbacks ─────────────────────────────────────────────────────
POS_CB = """
    elif d == "show_enter_pos":
        result = get_active_analysis(state)
        if not result:
            await q.edit_message_text(
                b("\\u274c  No Data") + "\\n\\nFetch a market first.",
                parse_mode=ParseMode.HTML, reply_markup=kb_back()
            )
            return
        city, con, bks, ctr = result
        active  = state["active"]
        ts = "High \\U0001f321\\ufe0f" if active["market_type"] == "highest" else "Low \\u2744\\ufe0f"
        pb = [bks[i] for i in range(max(0, ctr-1), min(len(bks), ctr+2))]
        bk_str = "  ".join(bk["label"] for bk in pb)
        await q.edit_message_text(
            "\\n".join([
                b("\\U0001f4cc  Enter Position"), DIV,
                city["flag"] + "  " + b(esc(city["display"])) + "  \\u00b7  " + ts,
                "\\U0001f4c5  " + day_label(active["target_date"]),
                "",
                b("Brackets you will track:"),
                c(bk_str),
                "",
                it("Tap Confirm to record and start 30-min METAR alerts."),
            ]),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_enter_pos(bks, ctr)
        )

    elif d == "enter_pos_confirm":
        result = get_active_analysis(state)
        if not result:
            await q.answer("No analysis loaded.", show_alert=True)
            return
        city, con, bks, ctr = result
        pos  = make_pos(state, city, bks, ctr)
        pos_add(q.message.chat_id, pos)
        active = state["active"]
        ts     = "High" if active["market_type"] == "highest" else "Low"
        bk_str = "  ".join(bk["label"] for bk in pos["brackets"])
        await q.edit_message_text(
            "\\n".join([
                b("\\u2705  Position Entered"), DIV,
                city["flag"] + "  " + b(esc(city["display"])) + "  \\u00b7  Daily " + ts,
                "\\U0001f4c5  " + day_label(active["target_date"]),
                "",
                b("Tracking:"),
                c(bk_str),
                "",
                "\\U0001f514  METAR alerts will fire every 30 min while this market is open.",
                "",
                it("ID: " + pos["id"]),
            ]),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back()
        )

    elif d == "cancel_enter_pos":
        result = get_active_analysis(state)
        if result:
            city, con, bks, ctr = result
            sl = "  ".join(k + " " + v for k, v in {
                "HRRR":  "\\u2705" if state["data"]["hrrr"]  else "\\u274c",
                "ECMWF": "\\u2705" if state["data"]["ecmwf"] else "\\u274c",
                "METAR": "\\u2705" if state["data"]["metar"] else "\\u274c",
            }.items())
            await q.edit_message_text(
                msg_analysis(state, city, con, bks, ctr) + "\\n\\n" + SDIV + "\\n" + it(sl),
                parse_mode=ParseMode.HTML, reply_markup=kb_analysis()
            )
        else:
            await q.edit_message_text(
                b("\\u26c5  WeatherEdge") + "\\n" + DIV,
                parse_mode=ParseMode.HTML, reply_markup=kb_main()
            )

    elif d == "show_my_positions":
        await q.edit_message_text(
            msg_positions(q.message.chat_id),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_positions(pos_get(q.message.chat_id))
        )

    elif d.startswith("pos_detail_"):
        pid  = d[len("pos_detail_"):]
        poss = pos_get(q.message.chat_id)
        pos  = next((p for p in poss if p.get("id") == pid), None)
        if not pos:
            await q.answer("Position not found.", show_alert=True)
            return
        city = CITY_DB.get(pos.get("city_key", ""), {})
        flag = city.get("flag", "\\U0001f30d")
        disp = city.get("display", "?")
        unit = city.get("unit", "F")
        hist = pos.get("metar_history", [])
        try:
            dt = datetime.fromisoformat(pos["target_date"])
            h  = hours_left_to(dt)
            dl = day_label(dt)
        except Exception:
            h, dl = 0, "?"
        bk_str = "  ".join(bk["label"] for bk in pos.get("brackets", []))
        hs, ts = "", ""
        if hist:
            hs = "\\n" + b("METAR readings:") + " " + c("  ".join(
                "{:.1f}\\u00b0".format(r["temp"]) for r in hist[-5:]
            ))
            if len(hist) >= 2:
                d_ = hist[-1]["temp"] - hist[-2]["temp"]
                ts = ("\\n\\U0001f4c8 Trend: rising" if d_ > 0.3
                      else "\\n\\U0001f4c9 Trend: falling" if d_ < -0.3
                      else "\\n\\u27a1\\ufe0f Trend: flat")
        ts2 = "Daily High \\U0001f321\\ufe0f" if pos.get("market_type") == "highest" else "Daily Low \\u2744\\ufe0f"
        text = "\\n".join(filter(None, [
            b("\\U0001f4ca  Position Detail"), DIV,
            flag + "  " + b(esc(disp)) + "  \\u00b7  " + ts2,
            "\\U0001f4c5  " + dl + "  \\u00b7  " + hours_label(h) + " left",
            "", b("Brackets:"), c(bk_str), hs, ts,
        ]))
        await q.edit_message_text(text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\\U0001f5d1  Close Position", callback_data="pos_close_" + pid)],
                [InlineKeyboardButton("\\u2190  Back",               callback_data="show_my_positions")],
            ]))

    elif d.startswith("pos_close_"):
        pid = d[len("pos_close_"):]
        pos_update(q.message.chat_id, pid, {"status": "closed"})
        await q.edit_message_text(
            b("\\u2705  Position Closed") + "\\n" + DIV + "\\n\\n" + msg_positions(q.message.chat_id),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_positions(pos_get(q.message.chat_id))
        )

"""

replace(
    '    elif d == "show_settings":',
    POS_CB + '    elif d == "show_settings":',
    "position callbacks"
)

# ── 7. Register in main() ─────────────────────────────────────────────────────
replace(
    ('        ("reset",    cmd_reset),\n'
     '    ]:\n'
     '        app.add_handler(CommandHandler(cmd, handler))\n'
     '    app.add_handler(CallbackQueryHandler(on_callback))'),
    ('        ("reset",     cmd_reset),\n'
     '        ("positions", cmd_positions),\n'
     '    ]:\n'
     '        app.add_handler(CommandHandler(cmd, handler))\n'
     '    app.add_handler(CallbackQueryHandler(on_callback))\n'
     '    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_kb_text))\n'
     '    app.job_queue.run_repeating(metar_alert_job, interval=1800, first=120)'),
    "register handlers + JobQueue"
)

# ── Write + validate ──────────────────────────────────────────────────────────
with open("bot.py", "w") as f:
    f.write(src)

print("\nValidating...")
try:
    ast.parse(src)
    print("OK  Syntax clean  --  {} lines".format(len(src.splitlines())))
except SyntaxError as e:
    lines = src.splitlines()
    print("ERR Line {}: {}".format(e.lineno, e.msg))
    for j in range(max(0, e.lineno - 4), min(len(lines), e.lineno + 4)):
        print("  {}: {}".format(j + 1, repr(lines[j][:100])))

if errors:
    print("\nMissed sections (check manually):")
    for err in errors:
        print("  - " + err)
else:
    print("\nAll patches applied.")
    print("Run:  systemctl restart weatheredge")
