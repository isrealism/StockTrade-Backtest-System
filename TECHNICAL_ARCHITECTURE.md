# Technical Architecture
# StockTradebyZ Backtest Platform

This document describes the end-to-end platform flow (frontend + backend + backtest engine),
including where parameters are provided, how data is processed, and where outputs are stored.

## Architecture Graph

```mermaid
flowchart TD
  A[User] -->|Select buy selector(s), sell strategy, date range, capital, costs| B[Frontend UI]
  B -->|POST /backtest/run| C[Backend API]
  C -->|Validate request + load configs| D[Backtest Runner]
  D -->|Read OHLCV data| E[data/ *.csv]
  D -->|Read selector config| F[configs.json]
  D -->|Read sell strategies| G[configs/sell_strategies.json]
  D --> H[Backtest Engine]
  H --> I[Execution Engine]
  H --> J[Portfolio Manager]
  H --> K[Performance Analyzer]
  I -->|fills + costs| J
  J -->|equity curve + trades| K
  K -->|metrics + charts data| L[Results Payload]
  L -->|JSON save| M[backtest_results/ *.json]
  L -->|API response| C
  C -->|Return results| B
  B -->|Render charts + trades| N[UI: equity curve, trade list, metrics]
```

## Directory and File Relationships

```
.
├── frontend/                       # Web UI (selector/strategy choice, run backtest, view results)
├── backend/                        # API service (orchestrates backtest and returns results)
├── scripts/
│   └── run_backtest.py             # CLI runner used by backend
├── backtest/
│   ├── engine.py                   # Event-driven loop
│   ├── execution.py                # Order execution, limits, costs
│   ├── portfolio.py                # Positions, cash, equity curve, trades
│   ├── performance.py              # Metrics and report
│   └── sell_strategies/            # Modular sell strategies
├── Selector.py                     # Buy selectors
├── configs.json                    # Buy selectors config
├── configs/
│   └── sell_strategies.json        # Sell strategies config
├── data/                           # Input OHLCV CSVs
├── backtest_results/               # Output results (JSON)
└── fetch_kline.py                  # Data acquisition (Tushare)
```

## Parameter Inputs (Platform)

### Frontend UI Inputs
- Buy selector(s) choice (from `Selector.py` via `configs.json`).
- Sell strategy choice (from `configs/sell_strategies.json`).
- Date range (`start`, `end`).
- Capital, max positions, position sizing method.
- Transaction costs (commission, stamp tax, slippage).

### Backend API Inputs
- Receives the UI payload and validates it.
- Maps UI fields to CLI params for `scripts/run_backtest.py`.
- May override defaults or lock system-level constraints.

### CLI Inputs (Backtest Runner)
- `--data-dir`, `--start`, `--end`
- `--buy-config`, `--sell-strategy`
- `--initial-capital`, `--max-positions`, `--position-sizing`
- `--commission`, `--stamp-tax`, `--slippage`
- `--save-results`

## Data Processing Flow

1. **Data Load**
   - Historical OHLCV CSVs read from `data/`.
2. **Selector Load**
   - Active selectors instantiated from `configs.json` and `Selector.py`.
3. **Sell Strategy Load**
   - Strategy loaded from `configs/sell_strategies.json`.
4. **Backtest Run**
   - Engine iterates dates, generates buy signals, submits orders.
   - Execution engine applies T+1 rules, price limits, and costs.
   - Portfolio manager updates cash, positions, equity curve, trades.
5. **Analysis**
   - Performance analyzer computes metrics and builds chart-ready series.

## Outputs

### Backend Output Payload
- Summary metrics (return, drawdown, Sharpe, win rate).
- Equity curve time series.
- Trade list with entry/exit details and reason.
- Metadata (configs used, date range, parameters).

### File Outputs
- JSON results saved under `backtest_results/` when requested.
- Logs printed to stdout (or captured by backend).

## Platform Notes
- Frontend renders:
  - Selector/strategy pickers
  - Run button
  - Results: performance metrics, trade table, equity curve chart
- Backend is responsible for:
  - Request validation
  - Running backtest job
  - Returning results payload to frontend
