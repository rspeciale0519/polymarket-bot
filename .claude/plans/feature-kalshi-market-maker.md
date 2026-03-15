# Feature: Kalshi Automated Market Making Bot

## Context

The user has a Polymarket copy-trading bot (Python) that cannot be used because Polymarket blocks US traders. We are rebuilding the system as an automated market maker on **Kalshi** (CFTC-regulated, US-legal). The strategy shifts from copy-trading (not feasible on Kalshi — no public trader data) to **hybrid market making**: posting two-sided limit orders to profit from the bid-ask spread, with directional skewing when statistical signals suggest mispricing.

**Goal:** Compound $100-1,000 starting capital to generate $1,000/month in passive income within 8-18 months.

**Architecture:** Two-process system — Python trading engine + Next.js web dashboard — communicating through a shared PostgreSQL database.

---

## Competitive Reality Check

Professional market makers on Kalshi run co-located servers with sub-millisecond execution. Our Python async loop will be slower. Mitigations built into the design:

1. **Wider minimum spreads** — accept lower fill rate for safer fills (3-5 cent floor vs 1 cent)
2. **Focus on less competitive markets** — weather, niche events, economic indicators rather than headline politics
3. **Always use `post_only` flag** — ensures we're always the maker (4x cheaper fees, never adversely crossed)
4. **Prefer order amendment over cancel-replace** — preserves queue position
5. **Accept our role** — we're a retail market maker capturing wide spreads on thin markets, not competing with institutions on headline events

## Capital Allocation Model

| Capital | Markets | Max Position/Market | Total Exposure |
|---------|---------|--------------------| --------------|
| $100-250 | 1-2 | 5-10 contracts | $50-100 |
| $250-500 | 2-3 | 10-20 contracts | $100-250 |
| $500-1,000 | 3-5 | 15-30 contracts | $250-500 |
| $1,000-2,500 | 5-8 | 25-50 contracts | $500-1,250 |
| $2,500+ | 8-15 | 50-100 contracts | $1,250-2,500 |

The market scanner and position sizing auto-adjust as balance grows. Each market requires enough capital for both a resting bid and ask.

## Strategy Calibration Approach

The Avellaneda-Stoikov model was designed for continuous equity markets. Prediction markets are bounded [1-99 cents] with resolution jumps. Our adaptation:

1. **Phase 3 builds the AS model with conservative defaults:**
   - `gamma = 0.3` (high risk aversion — wider spreads, safer)
   - `sigma = 0.15` (15% — overestimates volatility, which means wider spreads)
   - `min_spread = 3 cents` (floor — never quote tighter than this)
   - `signal_weight = 0.0` (pure market making, no directional bias initially)

2. **Phase 7 adds a data collection mode** — the engine logs every orderbook snapshot, trade, and fill for 1-2 weeks while paper trading with these conservative defaults.

3. **Post-launch calibration** — use collected data to compute actual `sigma` per market (observed price variance), estimate `kappa` (order arrival rate), and tighten spreads where profitable. This happens via the Settings page — no code changes needed.

This means the bot starts safe (wide spreads, low fill rate, minimal risk) and tightens as we learn the actual market dynamics.

---

## Phase 1: Foundation + Database + First API Connection

### Engine Files

**`engine/core/types.py`** — All shared dataclasses and enums
- `Mode` enum: `BACKTEST`, `PAPER`, `LIVE`
- `Side` enum: `YES`, `NO`; `Action` enum: `BUY`, `SELL`
- Dataclasses: `OrderbookLevel`, `Orderbook`, `InventoryState`, `Quote`, `OrderRequest`, `OrderAck`, `Fill`, `RiskViolation`, `EngineConfig`
- Fee functions: `taker_fee(count, price_cents)`, `maker_fee(count, price_cents)`
- Formula: taker = `ceil(0.07 × C × P/100 × (1 - P/100))`, maker = `ceil(0.0175 × C × P/100 × (1 - P/100))`
- All prices in **cents (1-99)**; all balances in **cents**

**`engine/core/config.py`** — Configuration loader
- Loads `.env` on startup (API keys, DB connection, Telegram tokens)
- Polls `bot_settings` DB table every 5s for hot-reloadable settings
- Returns `EngineConfig` dataclass
- Sensitive values only from env, never DB

**`engine/core/event_bus.py`** — Internal asyncio pub/sub
- Typed event channels: `OrderbookUpdate`, `FillEvent`, `OrderAck`, `RiskViolation`, `ConfigChanged`, `ConnectionLost`, `MarketExpired`
- `subscribe(event_type, callback)` and `publish(event)`
- Purely in-process; callbacks are async via `asyncio.create_task`

**`engine/api/auth.py`** — Kalshi RSA-PSS signature builder
- Loads RSA private key from PEM file path in env
- `sign_request(method, path, timestamp_ms, private_key)` → `(signature_b64, timestamp_str)`
- Message: `{timestamp_ms}{HTTP_METHOD}{path_without_query}`
- Algorithm: RSASSA-PSS with SHA-256, MGF1(SHA-256), salt_length=DIGEST_LENGTH

**`engine/api/kalshi_rest.py`** — Async Kalshi REST client
- Single `httpx.AsyncClient` with connection pooling
- All requests through `_signed_request()` via `auth.sign_request()`
- Key methods: `get_markets()`, `get_orderbook()`, `get_trades()`, `create_order()`, `amend_order()`, `cancel_order()`, `batch_create_orders()`, `get_balance()`, `get_positions()`, `get_fills()`, `get_exchange_status()`
- Retry: exponential backoff on 429/5xx, single retry on 401
- Base URL switchable: production (`https://api.elections.kalshi.com/trade-api/v2`) vs demo (`https://demo-api.kalshi.co/trade-api/v2`)

**`engine/storage/db_writer.py`** — PostgreSQL writer via asyncpg
- Raw SQL writes (schema owned by Prisma on Next.js side)
- Batch insert buffer: flushes every 1s or when buffer full
- Tables written: `orders`, `fills`, `portfolio_snapshots`, `market_metrics`, `engine_status`, `notifications`
- Tables read: `bot_settings`, `market_configs`

### Dashboard Files (schema only this phase)

**`dashboard/prisma/schema.prisma`** — Full database schema:
```
bot_settings        — singleton config (dashboard writes, engine reads)
engine_status       — singleton heartbeat (engine writes, dashboard reads)
orders              — every order submitted (all modes, tracks mode column)
fills               — every fill received
positions           — current open positions
portfolio_snapshots — equity time-series (every 5 min)
market_metrics      — per-market daily performance
market_configs      — per-market overrides (enabled/disabled)
deposits            — manual capital event tracking (deposits vs trading profit)
paper_milestone     — paper trading progress tracking
notifications       — events for dashboard toasts
```

### Verification
- Unit tests for `auth.py` against known signature test vectors
- Integration test: connect to Kalshi demo API, fetch markets, fetch an orderbook
- `db_writer` round-trip: write to and read from PostgreSQL
- Prisma migration runs cleanly, creates all tables

---

## Phase 2: Market Data + Orderbook + Paper Executor + First Paper Trades

This phase delivers the first working paper trades.

### Engine Files

**`engine/market_data/ws_client.py`** — Kalshi WebSocket manager
- Connects to `wss://api.elections.kalshi.com/trade-api/ws/v2`
- Auth via headers during handshake (same 3 headers as REST)
- Subscribes to: `orderbook_delta`, `trade`, `fill`, `user_orders`, `market_lifecycle_v2`
- On message: parse JSON → typed event → publish to event bus
- Reconnection: exponential backoff (1s base, 30s max, 25% jitter)
- **CRITICAL:** On any disconnect or sequence gap → publish `ConnectionLost` → cancel all resting orders
- On reconnect: re-subscribe, request `send_initial_snapshot: true`
- **Market lifecycle handling:**
  - On `market_determined` / `market_closed` event → stop quoting that market, record settlement P&L, remove from active rotation
  - On `market_paused` / exchange halt → immediately pull all quotes on affected markets, resume when `market_active` received
  - On `market_expired` → same as closed: stop quoting, settle, remove

**`engine/market_data/orderbook.py`** — Orderbook state manager
- One `Orderbook` instance per market ticker
- `apply_snapshot()`, `apply_delta()` for state management
- `mid_price()`, `spread_cents()`, `best_bid()`, `best_ask()` accessors
- Kalshi quirk: YES bids and NO bids returned separately; `best_yes_ask = 100 - best_no_bid`
- Publishes `OrderbookUpdate` to bus after each state change

**`engine/market_data/market_scanner.py`** — Automated market selection
- Runs on startup + daily scheduled task
- Filters markets by: `volume_24h >= min_volume`, `spread <= max_spread`, `time_to_expiry >= min_time`, `market_type == "binary"`
- Writes to `market_configs` table; respects dashboard overrides
- Capital-aware: limits active markets based on current balance (see Capital Allocation Model above)
- Handles market resolution: when a tracked market settles, records final P&L and removes from active list

**`engine/execution/base_executor.py`** — Abstract execution interface
```python
class ExecutionAdapter(ABC):
    submit_order(req: OrderRequest) -> OrderAck
    amend_order(order_id, new_price, new_count) -> OrderAck
    cancel_order(order_id) -> bool
    cancel_all() -> int
    get_positions() -> list[InventoryState]
    get_balance() -> int  # cents
```

**`engine/execution/paper_executor.py`** — Simulated execution against live data
- Maintains in-memory book of "resting paper orders"
- Fills when live orderbook would have crossed paper order price
- Simulates partial fills based on available size
- Applies maker fee formula
- Publishes synthetic `FillEvent` to event bus
- Maintains virtual balance; records to DB with `mode='paper'`

**`engine/strategy/simple_quoter.py`** — Initial simple quoting strategy
- Midpoint + fixed spread (no AS model yet — that's Phase 4)
- `bid = mid_price - half_spread`, `ask = mid_price + half_spread`
- Clamp to [1, 99], enforce `min_spread` floor
- Emit `Quote` event to bus
- This gets paper trades running immediately while AS model is built next

**`engine/main.py`** — Entry point (minimal version)
- Loads config, creates paper executor, launches: WS client, market scanner, simple quoter, db_writer
- Logs all activity to stdout + DB

### Verification
- Connect to Kalshi demo WebSocket, receive orderbook snapshots
- Paper executor generates simulated fills
- Trades logged to PostgreSQL `orders` and `fills` tables
- **First paper trades running end-to-end**

---

## Phase 3: Risk Engine + Circuit Breakers + Telegram

After this phase, the engine runs autonomously with safety controls and alerts.

### Engine Files

**`engine/risk/risk_engine.py`** — Central pre-trade gate
- `check(request) -> list[RiskViolation]`
- Checks: per-market inventory cap, global exposure cap, per-market P&L stop, daily loss limit, circuit breaker state
- All limits from `EngineConfig` (hot-reloadable)

**`engine/risk/position_tracker.py`** — Aggregated position state
- Listens to `FillEvent`; maintains `InventoryState` per market
- Computes net position, cost basis, unrealized P&L, total cross-market exposure
- Writes to DB `positions` table

**`engine/risk/circuit_breakers.py`** — Stateful pattern monitors
- **Rapid Loss Detector**: 3+ losing fills in 60-min window → HALT
- **Toxicity Detector**: adverse fill ratio scoring (0-100); >70 widens spreads 2x; >85 pulls quotes
- **Connection Loss Breaker**: `ConnectionLost` → HALT + `cancel_all()`
- **Daily Loss Breaker**: cumulative daily P&L below limit → HALT until next day
- Each has `trip()`, `reset()`, `is_tripped()`; all thresholds configurable

**`engine/notifications/telegram_bot.py`** — Async Telegram integration
- **Outbound:** fill alerts, circuit breaker alerts, daily P&L summary, paper milestone, connection status
- **Inbound commands:** `/status`, `/pause`, `/resume`, `/risk`, `/positions`

**`engine/notifications/formatters.py`** — Message formatting helpers

**`engine/dashboard_bridge/settings_poller.py`** — DB settings watcher
- Polls `bot_settings` every 5s; publishes `ConfigChanged` on change
- Hot-reloadable: risk limits, strategy params, market list, spread floor

**`engine/execution/order_reconciler.py`** — Periodic state reconciliation
- Runs every 30 seconds (configurable)
- Calls `GET /portfolio/orders?status=resting` to get actual resting orders from Kalshi
- Compares against engine's internal tracking of what it believes is resting
- Fixes discrepancies:
  - Order exists on Kalshi but not in engine state → cancel it (orphaned order)
  - Order in engine state but not on Kalshi → remove from internal state (was cancelled externally — market close, self-trade prevention, etc.)
- Logs all discrepancies for debugging
- In paper mode: reconciles against paper executor's internal order book (no API call needed)

Update **`engine/main.py`** — Full orchestrator
- All async tasks: WS client, settings poller, market scanner, circuit breakers, db_writer flush, Telegram, portfolio snapshots (every 5 min), **order reconciler (every 30s)**
- Graceful shutdown: SIGINT/SIGTERM → cancel all orders → flush DB → exit

### Verification
- Engine runs in paper mode with risk controls active
- Circuit breakers trip and halt trading correctly
- Telegram sends fill alerts and responds to commands
- Settings changes from DB propagate within 10s
- Order reconciler detects and fixes state discrepancies
- Market resolution events correctly stop quoting and record settlement P&L
- Market pause events correctly pull quotes and resume on unpause
- **Autonomous paper trading with safety controls**

---

## Phase 4: Avellaneda-Stoikov Strategy + Inventory Management

Replaces the simple quoter from Phase 2 with the full AS model.

### Engine Files

**`engine/strategy/avellaneda_stoikov.py`** — Core market making math
- `compute_reservation_price(mid, inventory, gamma, sigma, time_remaining)` → float
  - `r = mid - inventory * gamma * sigma^2 * time_remaining`
  - Inventory normalized: `net_position / max_position` (-1 to 1)
- `compute_spread(gamma, sigma, time_remaining, kappa)` → float
  - `spread = gamma * sigma^2 * time_remaining + (2/gamma) * ln(1 + gamma/kappa)`
- `compute_dynamic_gamma(base_gamma, inventory_ratio)` → float
  - `gamma_eff = base_gamma * (1 + 4 * inventory_ratio^2)` (quadratic increase)
- Pure functions, no state, no I/O — trivially testable
- **Initial conservative defaults:** gamma=0.3, sigma=0.15, min_spread=3 cents

**`engine/strategy/inventory_manager.py`** — Position tracking and skew
- `get_inventory_skew(ticker)` → asymmetric spread multiplier
  - Long: widen ask, tighten bid; Short: widen bid, tighten ask
- `should_flatten(ticker)` → bool (> 80% of max)
- `get_all_exposure_cents()` → total notional

**`engine/strategy/signal_integrator.py`** — Directional signal aggregation
- Per-market signal [-1.0, 1.0]: volume imbalance + trade momentum
- `get_directional_skew(ticker)` → float shift for reservation price
- Default `signal_weight = 0.0` (pure MM); hook for future external signals

**`engine/strategy/quote_generator.py`** — Orchestrates strategy → quotes (replaces `simple_quoter.py`)
- On `OrderbookUpdate`: snapshot → inventory → dynamic gamma → reservation price → spread → signal skew → bid/ask → clamp [1,99] → enforce min spread → emit `Quote`
- Tracks resting orders per market: amend if price change <= 3 cents, cancel-replace otherwise
- Minimum reprice interval: 500ms
- Uses `post_only` flag on all orders

### Verification
- Unit tests: AS model known inputs → expected outputs
- Unit tests: inventory skew direction correctness
- Integration: feed mock orderbook updates, verify full quote pipeline
- Paper trading P&L improves vs simple quoter baseline
- Data collection mode: logs all orderbook snapshots and trades for future calibration

---

## Phase 5: Live Executor + Backtest Infrastructure

After this phase, the engine can trade real money and backtest strategies.

### Engine Files

**`engine/execution/live_executor.py`** — Real Kalshi API execution
- Implements `ExecutionAdapter` via `kalshi_rest.py`
- Batch order submission (up to 20); order amendment for small price changes
- Rate limiter: token bucket at 20 ops/second
- Records all orders/fills to DB
- Always sets `post_only=True` on limit orders

**`engine/execution/backtest_executor.py`** — Historical replay execution
- Same fill logic as paper executor
- Receives `HistoricalTick` events from backtest runner
- Virtual clock controlled by `backtest_runner.py`

**`engine/backtest/data_loader.py`** — Historical data fetcher
- Downloads from Kalshi: `GET /historical/trades`, candlesticks at 1-min interval
- Caches to local JSON files
- Returns iterator of `HistoricalTick` events

**`engine/backtest/backtest_runner.py`** — Simulation controller
- Replays historical data through event bus at configurable speed
- Uses `BacktestExecutor` for fills
- Computes summary: P&L, max drawdown, Sharpe ratio, fill rate, per-market breakdown
- Writes results to DB

### Verification
- Live executor: place and cancel a test order on Kalshi demo API
- Backtest: run 1 month of historical data, verify P&L consistency
- All three executors produce identical DB records (differing only by `mode` column)
- **System ready for real capital deployment**

---

## Phase 6: Next.js Dashboard — Full Build

All dashboard pages built in one phase. Components follow established patterns from mlm2.

### Project Setup

**Root:** `/home/rob/dev/polybot/dashboard/`
- `npx create-next-app@latest dashboard --typescript --tailwind --eslint --app --src-dir`
- Dark trading terminal theme (slate-blue primary, dark backgrounds)
- HSL CSS variables; P&L colors (green/red); Mode colors (amber PAPER / green LIVE)

### Shared Infrastructure
- `lib/prisma.ts` — Singleton PrismaClient (globalThis pattern)
- `lib/api/response.ts` — `successResponse`/`errorResponse`/`validationErrorResponse` (from mlm2)
- `lib/utils.ts` — `cn()` utility
- `components/ui/` — Radix primitives (button, card, badge, dialog, alert-dialog, switch, tabs, table, input, select, progress, skeleton, dropdown-menu, tooltip, data-table)
- `stores/bot-mode.ts` — zustand store: `"paper" | "live"`
- `hooks/use-polling.ts` — Base polling hook with Page Visibility pause

### Layout Shell
- `app/(dashboard)/layout.tsx` — Sidebar + header
- `components/layout/sidebar.tsx` — Left nav: Overview, Positions, Markets, Analytics, Settings
- `components/layout/header.tsx` — Page title, ModeBadge, ModeToggle, NotificationBell
- `components/layout/mode-toggle.tsx` — Switch + AlertDialog confirmation for live
- `components/layout/mode-badge.tsx` — cva pill: amber PAPER / green LIVE
- `components/layout/notification-bell.tsx` — Unread count + dropdown

### Overview Page (`/overview`)
- API: `GET /api/overview` (balance, P&L periods, counts, status)
- API: `GET /api/portfolio-history?hours=N` (equity curve, time-bucketed)
- Hook: `use-overview.ts` (polls every 7s)
- Components: `metrics-row.tsx` (7 metric cards), `equity-curve-card.tsx` (recharts AreaChart), `system-status-card.tsx`, `paper-milestone-card.tsx` (advisory progress bar, visible in paper mode only)

### Positions Page (`/positions`)
- Tabs: Active Positions, Open Orders, Trade History
- APIs: `GET /api/positions`, `GET /api/orders`, `GET /api/trades`, `DELETE /api/orders/[id]`, `POST /api/orders/cancel-all`
- Components: positions-table, orders-table, trades-table (each with separate column definition files)
- TanStack Table v8 with server-side pagination (mlm2 DataTable pattern)
- Cancel individual orders and cancel-all button

### Markets Page (`/markets`)
- API: `GET /api/markets`, `PATCH /api/markets/[id]`
- Table: market, volume, spread, inventory, P&L, status badge (Active/Paused/Excluded), toggle switch
- Search/filter bar

### Analytics Page (`/analytics`)
- API: `GET /api/analytics?period=N`
- Stats cards: win rate, profit factor, Sharpe approximation, maker ratio
- Charts: cumulative P&L (AreaChart), P&L by market (PieChart), P&L by day/week (BarChart), fee breakdown, deposits vs trading profit (PieChart)

### Settings Page (`/settings`)
- API: `GET /api/settings`, `PUT /api/settings` (Zod validated)
- Tabbed layout with react-hook-form:
  - **Risk:** max position/market, global exposure, daily loss limit, drawdown
  - **Strategy:** base gamma, sigma, min spread, order size
  - **Market Selection:** min volume, max spread, min time-to-expiry
  - **Milestones:** paper milestone days (configurable, advisory only)
  - **Notifications:** Telegram token + chat ID
  - **API Keys:** Kalshi API key ID (display + rotate)
  - **Polling:** interval setting
- Each tab is a separate form component (keeps files under 450 lines)

### Notifications System
- Engine writes to `notifications` table
- `use-notifications.ts` polls every 5s, fires sonner toasts for new items
- Types: trade_filled, circuit_breaker, milestone, daily_loss_limit, error

### Verification
- Dashboard builds clean (`npm run build`)
- All pages render with data from engine's DB writes
- Settings changes propagate to engine within 10s
- Mode toggle switches with confirmation dialog
- Order cancellation works end-to-end
- Equity curve updates in real-time

---

## Phase 7: Integration Testing + Optimization + Paper Trading Launch

### End-to-End Validation
- Run both processes simultaneously: engine (paper) + dashboard
- Verify data flows: engine → PostgreSQL → dashboard
- Verify settings flows: dashboard → PostgreSQL → engine
- Paper trade on Kalshi production API (not demo) for 24+ hours
- Verify: quotes generated, paper fills realistic, P&L accurate, fees calculated, circuit breakers work, Telegram alerts fire, dashboard accurate, mode toggle seamless, graceful shutdown cancels all, WS reconnection recovers cleanly

### Strategy Calibration
- Analyze 1-2 weeks of collected data from paper trading
- Compute actual `sigma` per market from observed price variance
- Estimate `kappa` from observed trade frequency
- Tighten spreads on markets showing profitable fill patterns
- Adjust via Settings page — no code changes

### Performance Optimization
- Profile engine: ensure quote generation < 10ms per market
- Verify DB write batching doesn't create backpressure
- Dashboard: ensure polling doesn't cause memory leaks over 24+ hours
- Test with 10+ simultaneous markets

### Launch Readiness Checklist
- [ ] 24-hour uninterrupted paper trading run
- [ ] P&L matches manual calculation
- [ ] No memory leaks or unhandled exceptions
- [ ] All circuit breakers tested and verified
- [ ] Telegram commands all working
- [ ] Dashboard fully functional on all pages
- [ ] Graceful shutdown verified
- [ ] WebSocket reconnection verified
- [ ] Ready for user to switch to LIVE mode when they choose

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python HTTP | `httpx` (async) | Cleaner than aiohttp, native async |
| Python WebSocket | `websockets` | Standard async WS library |
| Python DB | `asyncpg` | Fastest PostgreSQL driver, native async |
| Python ORM | None (raw SQL) | Schema owned by Prisma; raw asyncpg for write speed |
| Frontend | Next.js App Router | User's established pattern |
| UI components | Custom Radix UI primitives | User's pattern (not shadcn CLI) |
| Charts | recharts | User's established choice |
| Tables | TanStack Table v8 | User's established choice |
| State | zustand | User's pattern for cross-component state |
| IPC | Shared PostgreSQL | Simple, reliable, no extra infra |
| Strategy | Avellaneda-Stoikov (adapted) | Industry standard, calibrated post-launch |
| Initial strategy | Simple midpoint + spread | Gets paper trades running fast, replaced by AS in Phase 4 |

## Dependencies

### Python Engine
```
httpx>=0.27.0
websockets>=12.0
asyncpg>=0.29.0
python-telegram-bot>=21.0
cryptography>=42.0
pydantic>=2.0
python-dotenv>=1.0
structlog>=24.0
pytest>=8.0
pytest-asyncio>=0.23
```

### Next.js Dashboard
```
next, react, react-dom, typescript
tailwindcss, tailwindcss-animate
@radix-ui/* (dialog, switch, tabs, select, dropdown-menu, progress, tooltip, alert-dialog)
@tanstack/react-table, recharts, zustand
zod, react-hook-form, @hookform/resolvers
lucide-react, class-variance-authority, clsx, tailwind-merge
sonner, framer-motion, @prisma/client, prisma
```

## Reference Files (Existing Patterns to Reuse)

- `/home/rob/dev/mlm2/src/app/(dashboard)/layout.tsx` — Dashboard layout shell
- `/home/rob/dev/mlm2/src/components/ui/data-table.tsx` — TanStack Table pattern
- `/home/rob/dev/mlm2/src/lib/api/response.ts` — API response utilities
- `/home/rob/dev/mlm2/src/components/ui/` — Full set of Radix UI primitives
- `/home/rob/dev/mlm2/src/app/globals.css` — CSS variable theming structure
