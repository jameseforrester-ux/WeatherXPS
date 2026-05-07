# ⛅ WeatherEdge — Polymarket Weather Trading Bot

A Telegram bot that combines ECMWF ensemble (51 members), HRRR, METAR/ASOS,
and OpenWeather into a time-weighted temperature consensus for Polymarket daily
high/low markets. Recommends 3 adjacent positions with confidence scoring,
edge calculation, and a dark-themed distribution chart.

---

## ⚠️ Security Notice

**Your `.env` file contains your API keys and bot token.**
It is listed in `.gitignore` and will NOT be committed to GitHub automatically.
Never manually add `.env` to your repository.
If you accidentally expose your keys, rotate them immediately:
- Telegram token: message @BotFather → `/mybots` → Revoke token
- OpenWeather: https://home.openweathermap.org/api_keys

---

## How the methodology works

**Why METAR matters most near resolution:**
Polymarket temperature markets resolve using Weather Underground, which reads
from METAR weather stations at the target airport. This means METAR is the
ground truth — every other model is just a predictor of what METAR will report.

**Time-decay model weighting:**

```
Hours left  │  ECMWF   HRRR    OpenWx   METAR
────────────┼──────────────────────────────────
60h+        │   50%     20%     25%       5%
36–60h      │   40%     30%     20%      10%
24–36h      │   25%     45%     15%      15%
12–24h      │   10%     40%     15%      35%
0–12h       │    5%     30%     10%      55%
```

**Confidence score (0–100):**
The score penalizes inter-model spread (±1° costs –12pts), ECMWF ensemble
spread (±1° costs –8pts), and lead time (–0.25pts/hour). Clamped to 10–95.

**3-Position strategy:**
ECMWF's 51-member ensemble gives a real probability distribution across 1°
buckets. You're buying underpriced buckets vs ensemble probability.
Edge = model probability − market price. Positive = +EV.

---

## Step-by-Step Setup

### Step 1 — Install Python

You need Python 3.10 or newer.

**Windows:**
1. Go to https://www.python.org/downloads/
2. Download the latest Python 3.x installer
3. Run the installer — **check the box that says "Add Python to PATH"**
4. Click Install Now
5. Open Command Prompt (`Win + R`, type `cmd`, press Enter)
6. Type `python --version` — you should see something like `Python 3.12.0`

**Mac:**
1. Open Terminal (Cmd + Space, type Terminal)
2. Install Homebrew if you don't have it:
   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
3. Then install Python:
   ```
   brew install python
   ```
4. Verify: `python3 --version`

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

---

### Step 2 — Download and extract the bot

1. Download the ZIP file from this repository
2. Extract it to a folder you'll remember, e.g.:
   - Windows: `C:\weatheredge\`
   - Mac/Linux: `~/weatheredge/`

---

### Step 3 — Open a terminal in the project folder

**Windows:**
1. Open the folder in File Explorer
2. Click the address bar at the top
3. Type `cmd` and press Enter
   (This opens Command Prompt directly in that folder)

**Mac:**
1. Open Terminal
2. Type `cd ` (with a space), then drag the folder into the Terminal window
3. Press Enter

**Linux:**
```bash
cd ~/weatheredge
```

---

### Step 4 — Create a virtual environment

A virtual environment keeps the bot's dependencies separate from your system Python.

**Windows:**
```
python -m venv venv
venv\Scripts\activate
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You'll know it worked when you see `(venv)` at the start of your terminal prompt.

---

### Step 5 — Install dependencies

With your virtual environment active, run:

```bash
pip install -r requirements.txt
```

This installs the Telegram library, requests, matplotlib, and dotenv.
It takes about 30–60 seconds. You'll see a list of packages being installed.

---

### Step 6 — Check your .env file

Your `.env` file is already filled in with your keys. Open it to verify:

```
TELEGRAM_TOKEN=your_token_here
OPENWEATHER_KEY=your_key_here
ANTHROPIC_KEY=          ← leave blank unless you have an Anthropic key
```

If anything looks wrong, edit the `.env` file in any text editor.

---

### Step 7 — Run the bot

```bash
python bot.py
```

You should see:
```
⛅  WeatherEdge bot started successfully
   Telegram token: set
   OpenWeather:    set
   Anthropic AI:   not set (optional)
```

Now open Telegram, find your bot (search for its username), and send `/start`.

---

### Step 8 — Keep it running (optional)

By default, the bot stops when you close the terminal. To run it continuously:

**Using screen (Mac/Linux):**
```bash
# Install screen if needed:  sudo apt install screen
screen -S weatheredge
python bot.py
# Press Ctrl+A then D to detach — bot keeps running
# To reattach later:  screen -r weatheredge
```

**Using nohup (Mac/Linux):**
```bash
nohup python bot.py > bot.log 2>&1 &
# To stop it:
pkill -f bot.py
```

**Windows — run minimized:**
1. Create a file called `run_bot.bat` with the content:
   ```bat
   @echo off
   call venv\Scripts\activate
   python bot.py
   ```
2. Right-click → Create shortcut → in Properties set "Run: Minimized"

---

## Using the Bot

### First time setup (30 seconds)

1. Send `/start` to see the main menu
2. Tap **🏢 Airport** and pick the airport matching your Polymarket market
3. Tap **🌡️ High / Low** to select daily high or low temperature
4. Tap **📅 Day** to select today, tomorrow, or +2 days
5. Tap **🔄 Fetch All Data** — the bot fetches everything and shows the analysis

### Entering market prices for edge calculation

Once you're looking at a Polymarket market, log the current "Yes" prices:

```
/price 72 0.35
/price 73 0.28
/price 74 0.18
```

The bot immediately shows each position's edge (model probability minus market price).
Positive edge = the market is underpricing that outcome.

### Setting your budget and stop loss

```
/budget 30        → $10.00 per leg
/stoploss 50      → exit any leg if it drops 50% from entry
```

### Overriding the center position

If you have information the models don't (warm front timing, sea breeze, etc.):

```
/override 73      → positions will be 72°, 73°, 74° regardless of model consensus
/reset            → go back to model-driven positioning
```

---

## All commands

| Command | What it does |
|---------|-------------|
| `/start` | Main menu with inline buttons |
| `/fetch` | Pull all data and show forecast |
| `/forecast` | Show current consensus (no re-fetch) |
| `/chart` | Send ECMWF distribution chart as image |
| `/markets` | Live Polymarket listings for your city |
| `/strategy` | 3-position plan with stop loss rules |
| `/analyze` | AI signal (requires Anthropic API key) |
| `/price 72 0.35` | Log market price for edge calc |
| `/budget 30` | Set total position budget |
| `/stoploss 50` | Set stop loss percentage |
| `/override 73` | Override model consensus center |
| `/reset` | Clear prices and override |
| `/help` | Command reference |

---

## Stop loss rules

1. **Price stop** — Exit any leg immediately if it drops your set % from entry. No exceptions.
2. **Consensus shift** — If model consensus moves >2° from your center, exit outer legs first.
3. **Hold winner** — If center position is above $0.75 with less than 6 hours to resolution, hold.
4. **Correlated drop** — If all 3 legs fall simultaneously, it's a regime change. Exit everything.

---

## Adding more airports

Edit the `AIRPORTS` dictionary at the top of `bot.py`:

```python
"KPHX": {"lat": 33.4373, "lon": -112.0078, "city": "Phoenix",     "name": "PHX", "tz": "America/Phoenix"},
"KLAS": {"lat": 36.0840, "lon": -115.1537, "city": "Las Vegas",   "name": "LAS", "tz": "America/Los_Angeles"},
"KMCO": {"lat": 28.4312, "lon": -81.3081,  "city": "Orlando",     "name": "MCO", "tz": "America/New_York"},
```

The ICAO code (K-prefix for US) must match the METAR station identifier.

---

## Troubleshooting

**"ModuleNotFoundError: No module named 'telegram'"**
Your virtual environment isn't active. Run:
- Windows: `venv\Scripts\activate`
- Mac/Linux: `source venv/bin/activate`
Then try again.

**"ERROR: TELEGRAM_TOKEN is not set"**
Your `.env` file isn't being read. Make sure you're running `python bot.py`
from inside the `weatheredge` folder, not from somewhere else.

**Bot doesn't respond**
Make sure you sent a message to the correct bot. Check that `python bot.py`
is still running in your terminal (it shows the cursor blinking or log lines
when messages come in).

**HRRR returns ❌**
HRRR is a US-only model. If you selected a non-US airport it automatically
falls back to GFS. This is expected.

**ECMWF takes a long time**
The ECMWF ensemble endpoint can take 15–25 seconds — this is normal. It's
fetching 51 forecast members. The bot shows a loading message while waiting.

**Chart looks blank or wrong**
The chart requires ECMWF data. If ECMWF shows ❌ in the status line after
fetching, the chart won't render. Try fetching again — the ensemble API
occasionally times out.

---

## Data sources

| Source | Provider | Needs key? | Best at |
|--------|----------|-----------|---------|
| HRRR (3km US) | Open-Meteo | No | 0–24h |
| ECMWF IFS ensemble | Open-Meteo | No | 24–72h |
| METAR/ASOS | aviationweather.gov | No | Current conditions |
| OpenWeather (GFS) | openweathermap.org | Yes (free) | Additional member |
| Polymarket | gamma-api.polymarket.com | No | Market prices |
