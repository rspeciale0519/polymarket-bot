# Polymarket Copy-Trading Bot - Quick Start (30 min to Live)

## Step 0: Prerequisites (5 min)

### Get Wallet Private Key
```bash
# If you don't have one, create with ethers:
python3 << 'EOF'
from eth_account import Account
acct = Account.create()
print(f"Address: {acct.address}")
print(f"Private Key: {acct.key.hex()}")
EOF
```

Save both values somewhere safe.

### Fund Wallet (Polygon)
1. Send USDC.e to your address via https://bridge.fun.xyz/
   - Source: Ethereum
   - Dest: Polygon
   - Amount: $100+
   - Arrives in ~2 min

2. Send small POL amount for gas (~$1)
   - Via Uniswap or any Polygon faucet

### Create Telegram Bot
1. Message @BotFather on Telegram
2. `/newbot` → name it "PolyBot"
3. Copy the **Token** → `TELEGRAM_TOKEN`
4. Get your **Chat ID**:
   - Message your bot anything
   - Go to: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find your chat ID → `TELEGRAM_CHAT_ID`

---

## Step 1: Clone & Install (5 min)

```bash
git clone <repo>
cd polymarket-bot
pip install -r requirements.txt
```

---

## Step 2: Configure (10 min)

```bash
cp .env.example .env
nano .env  # or vim/code
```

Fill in:

```dotenv
# From Step 0
PRIVATE_KEY=0x...your...key...
WALLET_ADDRESS=0x...your...address...
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321

# These are good defaults
DRY_RUN=true              # Set to false after testing
CAPITAL=100
MAX_POSITION_SIZE=50
POLL_INTERVAL_SECONDS=300  # 5 minutes
```

**Optional: Get top traders**
```bash
curl "https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=MONTH&limit=5" | jq '.[] | .proxyWallet'
```

Copy top 3 addresses into `TRACKED_TRADERS` (comma-separated).

---

## Step 3: Test (Dry Run) - 5 min

```bash
python main.py
```

**Expected output:**
```
INFO - Bot initialized. Dry run: True
INFO - Starting monitor loop...
INFO - Fetched 5 leaderboard entries
INFO - Fetched 12 positions for 0x...
INFO - Detected 2 new positions
INFO - DRY RUN: Would place BUY order...
```

**Check Telegram:**
- You should get: "🔧 Bot started in DRY RUN mode"
- You should get: "📊 COPY: [Market Name]..."

If you see these → **READY TO GO LIVE** ✅

---

## Step 4: Go Live (5 min)

Edit `.env`:
```dotenv
DRY_RUN=false  # Change from true
```

Start bot:
```bash
python main.py
```

**Monitor first trade:**
- Bot will find top traders' positions
- First new position → real trade executes (within 5 min)
- You'll get Telegram alert: "📊 COPY: [Market] BUY 5x @ $0.50"

**Check database:**
```bash
sqlite3 trades.db "SELECT * FROM trades LIMIT 1"
```

---

## Step 5: Keep Running (VPS)

### Option A: Local (Simple)
```bash
# Terminal 1: Run bot
python main.py

# Terminal 2: Monitor logs
tail -f bot.log
```

### Option B: VPS ($5/month Linode/DigitalOcean)

```bash
# SSH to VPS
ssh user@your-vps

# Install Python & git
sudo apt update && sudo apt install python3-pip git -y

# Clone & install
git clone <repo> polymarket-bot
cd polymarket-bot
pip3 install -r requirements.txt
cp .env.example .env
nano .env  # Fill in values

# Install PM2 (process manager)
npm install -g pm2  # (if npm not available: sudo apt install npm)

# Start bot
pm2 start main.py --name polymarket-bot --interpreter python3
pm2 startup     # Auto-start on reboot
pm2 save        # Save config

# Monitor
pm2 logs polymarket-bot
```

---

## Monitoring Checklist

### Daily
- [ ] Check Telegram P&L report (hourly auto-sent)
- [ ] Run: `sqlite3 trades.db "SELECT COUNT(*) FROM trades WHERE timestamp > datetime('now', '-1 day')"`
- [ ] Verify no errors in logs

### Weekly
- [ ] Check win rate: `sqlite3 trades.db "SELECT SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins, COUNT(*) as total FROM trades WHERE timestamp > datetime('now', '-7 days')"`
- [ ] Review top traders (still profitable?)
- [ ] Check equity: `sqlite3 trades.db "SELECT SUM(equity) as total FROM portfolio ORDER BY timestamp DESC LIMIT 1"`

### Monthly
- [ ] Analyze which traders to keep/drop
- [ ] Update TRACKED_TRADERS if needed
- [ ] Decide to scale capital

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "PRIVATE_KEY not found" | Check `.env`, make sure `PRIVATE_KEY=0x...` is there |
| "Spread too wide" | Market is illiquid, bot correctly skips it |
| No Telegram messages | Verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` |
| No trades after 1 hour | Check if tracked traders have new positions (may be inactive) |
| `ModuleNotFoundError` | Run: `pip install -r requirements.txt` |

---

## What's Happening (Under the Hood)

```
Every 5 minutes:
1. Fetch leaderboard (top traders)
2. Get their positions
3. Compare to previous snapshot
4. Detect NEW positions
5. Check: spread < 5%, capital available, not at max drawdown
6. Place proportional copy trade
7. Log to SQLite
8. Send Telegram alert

Every 60 minutes:
1. Calculate P&L
2. Send Telegram report: "P&L: +$5.23 | Equity: $105.23"
```

---

## Safety Reminders

⚠️ **Before going live:**
- Test DRY_RUN for at least 1 hour
- Verify first few simulated trades look reasonable
- Check Telegram is receiving messages

⚠️ **Security:**
- **NEVER** commit `.env` to git
- **NEVER** share your `PRIVATE_KEY`
- Keep `.env` secure on VPS
- Backup `trades.db` weekly

⚠️ **Risk:**
- Start with $100 (not $1000)
- Monitor first week manually
- Max drawdown: -10% → bot stops automatically
- Adjust `MAX_POSITION_SIZE` lower if uncomfortable

---

## Next Steps

1. ✅ Run in dry mode 1 hour
2. ✅ Verify Telegram working
3. ✅ Set `DRY_RUN=false`
4. ✅ Deploy to VPS with PM2
5. ✅ Monitor P&L for 1 week
6. ✅ Scale from $100 → $500 → $1000 (if profitable)

---

## Questions?

- **Logs:** `python main.py 2>&1 | tee bot.log`
- **Database:** `sqlite3 trades.db ".schema"` (see tables)
- **API Docs:** https://docs.polymarket.com
- **Code:** All functions documented in `.py` files

**Ready?** Start with Step 1! 🚀
