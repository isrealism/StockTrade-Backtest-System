# Backtesting System for Z's Trading Strategies

Comprehensive backtesting framework with sophisticated sell strategies and performance analysis for the existing 6 buy strategies (Z's Trading Methods).

## Recent Updates

### v1.1 - Cash Management Fix (2026-01-22)

**Critical Bug Fixed:** Over-leveraging issue that allowed negative cash balances.

**What was fixed:**
- Portfolio manager now properly tracks pending buy orders
- Position sizing accounts for available cash and pending orders
- Prevents multiple simultaneous orders from exceeding capital

**Impact:**
- More realistic backtesting results
- Cash never goes negative
- Max drawdown calculations are now accurate

See `CASH_MANAGEMENT_FIX.md` for technical details.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Sell Strategies](#sell-strategies)
- [Usage Examples](#usage-examples)
- [Performance Metrics](#performance-metrics)
- [File Structure](#file-structure)
- [Configuration](#configuration)
- [Roadmap](#roadmap)

---

## Overview

This backtesting system implements an **event-driven architecture** specifically designed for Chinese A-share market with:

- **T+1 settlement** - Realistic order execution with next-day settlement
- **Price limits (±10%)** - Orders fail if price gaps beyond limits
- **Transaction costs** - Commission (0.03%), stamp tax (0.1% on sells), slippage (0.1%)
- **Lookahead bias prevention** - Strict data isolation ensures no future data leakage
- **12 sophisticated sell strategies** - From simple trailing stops to adaptive volatility exits

The system integrates seamlessly with existing 6 buy selectors from `Selector.py` (少妇战法, SuperB1战法, 补票战法, 填坑战法, 上穿60放量战法, 暴力K战法).

---

## Features

### Core Capabilities

✅ **Event-Driven Backtesting**
- Date-by-date iteration prevents lookahead bias
- T+1 settlement with frozen cash tracking
- Realistic order execution with price limit checks

✅ **12 Sell Strategies**
- **Trailing Stops**: ATR-based, Chandelier, Percentage
- **Profit Targets**: Fixed percentage, R-multiples
- **Time-Based**: Maximum holding period
- **Indicator Exits**: KDJ overbought, BBI reversal, ZX lines cross, MA death cross
- **Adaptive**: Volatility-adjusted stops, volume dry-up detection

✅ **Comprehensive Performance Analysis**
- Returns: Total, annualized, monthly breakdown
- Risk-Adjusted: Sharpe, Sortino, Calmar ratios
- Drawdown: Maximum drawdown, drawdown duration
- Trade Stats: Win rate, profit factor, average win/loss
- Distributions: Exit reasons, buy strategies, returns histogram

✅ **Modular Design**
- Composite sell strategies (combine multiple exits)
- Configurable via JSON
- Easy to add custom strategies

---

## Quick Start

### 1. Ensure Data is Available

```bash
# Download historical data first (if not already done)
python fetch_kline.py --start 20240101 --end today --stocklist ./stocklist.csv --out ./data
```

### 2. Run a Backtest

```bash
# Basic backtest with default settings
python scripts/run_backtest.py

# Specify sell strategy
python scripts/run_backtest.py --sell-strategy conservative_trailing

# Custom date range
python scripts/run_backtest.py --start 2023-01-01 --end 2024-12-31

# Save results to file
python scripts/run_backtest.py --save-results ./backtest_results/my_test.json
```

### 3. View Results

The backtest will output:
- Real-time execution logs (buy/sell signals, order execution)
- Comprehensive performance report
- Equity curve data
- Trade-by-trade history

Example output:

```
================================================================================
PERFORMANCE REPORT
================================================================================

--- RETURNS ---
Initial Capital:          1,000,000
Final Value:              1,234,567
Total Return:                23.46%
Annualized Return:           23.46%
Total Profit:               234,567

--- RISK-ADJUSTED METRICS ---
Sharpe Ratio:                  1.85
Sortino Ratio:                 2.34
Calmar Ratio:                  3.21

--- DRAWDOWN ---
Max Drawdown:                -8.45%
Max DD Duration:             12 days

--- TRADE STATISTICS ---
Total Trades:                    87
Winning Trades:                  54
Losing Trades:                   33
Win Rate:                     62.07%
Profit Factor:                  2.14
Avg Win:                       8,234
Avg Loss:                     -4,123
```

---

## Architecture

### Event-Driven Flow

```
[Market Data] → [BacktestEngine (event loop)]
                       ↓
    ┌──────────────────┼──────────────────┐
    ↓                  ↓                  ↓
[Buy Selectors]  [Sell Strategies]  [PortfolioManager]
    ↓                  ↓                  ↓
[Buy Signals]    [Sell Signals]    [Order Execution]
    └──────────────────┼──────────────────┘
                       ↓
              [T+1 Settlement]
                       ↓
           [Performance Analysis]
```

### Key Components

**1. BacktestEngine** (`backtest/engine.py`)
- Main event loop over trading dates
- Integrates buy selectors from `Selector.py`
- Manages order queue and execution

**2. PortfolioManager** (`backtest/portfolio.py`)
- Position tracking with T+1 settlement
- Cash management with frozen cash
- Position sizing (equal weight, risk-based)

**3. ExecutionEngine** (`backtest/execution.py`)
- T+1 order execution
- Price limit validation (±10%)
- Transaction cost calculation

**4. SellStrategies** (`backtest/sell_strategies/`)
- Modular exit logic
- Composite pattern for combining strategies
- 12 pre-built strategies

**5. PerformanceAnalyzer** (`backtest/performance.py`)
- Comprehensive metrics calculation
- Risk-adjusted returns
- Trade distribution analysis

---

## Sell Strategies

### Pre-Configured Strategies

The system includes 8 pre-configured composite strategies in `configs/sell_strategies.json`:

#### 1. **conservative_trailing** (Recommended for beginners)
- 8% trailing stop
- 15% profit target
- 60-day max hold

#### 2. **aggressive_atr**
- 2x ATR trailing stop
- 20% profit target
- 45-day max hold

#### 3. **indicator_based**
- KDJ overbought exit (J > 85)
- BBI reversal (3-day decline)
- 10% trailing stop
- 60-day max hold

#### 4. **adaptive_volatility**
- Volatility-adjusted stop (5%-12%)
- 15% profit target
- 60-day max hold

#### 5. **chandelier_3r**
- Chandelier stop (3x ATR from highest high)
- 3R profit target
- 60-day max hold

#### 6. **zx_discipline**
- ZX lines cross down
- MA death cross (MA5 < MA20)
- 8% trailing stop
- 60-day max hold

#### 7. **simple_percentage_stop** (Baseline)
- Simple 8% trailing stop
- 60-day max hold

#### 8. **hold_forever** (Buy-and-hold baseline)
- Never sells

### Individual Strategies

All 12 individual strategies available:

| Category | Strategy | Description |
|----------|----------|-------------|
| **Trailing Stops** | ATRTrailingStopStrategy | Adaptive stop using ATR |
| | ChandelierStopStrategy | Conservative ATR variant |
| | PercentageTrailingStopStrategy | Simple percentage stop |
| **Profit Targets** | FixedProfitTargetStrategy | Exit at +X% profit |
| | MultipleRExitStrategy | Exit at N×R profit |
| **Time-Based** | TimedExitStrategy | Max holding period |
| **Indicator Exits** | KDJOverboughtExitStrategy | Exit on J > 80 |
| | BBIReversalExitStrategy | Exit on BBI downtrend |
| | ZXLinesCrossDownExitStrategy | Exit on ZXDQ < ZXDKX |
| | MADeathCrossExitStrategy | Exit on MA cross down |
| **Others** | VolumeDryUpExitStrategy | Exit on volume decline |
| | AdaptiveVolatilityExitStrategy | Volatility-aware stop |

---

## Usage Examples

### Example 1: Compare Multiple Strategies

```bash
# Conservative strategy
python scripts/run_backtest.py \\
    --sell-strategy conservative_trailing \\
    --save-results ./backtest_results/conservative.json

# Aggressive strategy
python scripts/run_backtest.py \\
    --sell-strategy aggressive_atr \\
    --save-results ./backtest_results/aggressive.json

# Compare results from saved JSON files
```

### Example 2: Custom Transaction Costs

```bash
# Higher commission (e.g., 0.05%)
python scripts/run_backtest.py \\
    --commission 0.0005 \\
    --stamp-tax 0.001 \\
    --slippage 0.002
```

### Example 3: Different Position Sizing

```bash
# Risk-based position sizing (using ATR)
python scripts/run_backtest.py \\
    --position-sizing risk_based \\
    --max-positions 8
```

### Example 4: Quiet Mode (Summary Only)

```bash
# Suppress detailed logs, show only summary
python scripts/run_backtest.py --quiet
```

---

## Performance Metrics

### Returns Metrics

- **Total Return**: (Final Value - Initial Capital) / Initial Capital
- **Annualized Return**: Geometric mean return per year
- **Monthly Returns**: Month-by-month return breakdown

### Risk-Adjusted Metrics

- **Sharpe Ratio**: (Return - Risk-Free Rate) / Volatility
  - \> 1.0 = Good, > 2.0 = Very Good, > 3.0 = Excellent

- **Sortino Ratio**: (Return - Risk-Free Rate) / Downside Deviation
  - Only penalizes downside volatility

- **Calmar Ratio**: Annualized Return / Max Drawdown
  - Measures return per unit of drawdown risk

### Drawdown Metrics

- **Max Drawdown**: Largest peak-to-trough decline
- **Max Drawdown Duration**: Longest time in drawdown
- **Average Drawdown Duration**: Mean time in drawdown

### Trade Statistics

- **Win Rate**: Winning Trades / Total Trades
- **Profit Factor**: Gross Profit / |Gross Loss|
  - \> 1.0 = Profitable, > 1.5 = Good, > 2.0 = Very Good
- **Average Win/Loss**: Mean P&L per trade
- **Holding Period**: Average days held

---

## File Structure

```
StockTradebyZ/
├── backtest/                          # Backtesting module
│   ├── __init__.py
│   ├── engine.py                      # Main backtesting engine
│   ├── portfolio.py                   # Portfolio management
│   ├── execution.py                   # Order execution (T+1, costs)
│   ├── performance.py                 # Performance analysis
│   ├── data_structures.py             # Position, Order, Trade classes
│   └── sell_strategies/               # Sell strategy implementations
│       ├── base.py                    # Abstract base class
│       ├── trailing_stops.py          # ATR, Chandelier, Percentage
│       ├── profit_targets.py          # Fixed, MultipleR
│       ├── time_based.py              # TimedExit
│       ├── indicator_exits.py         # KDJ, BBI, ZX, MA exits
│       ├── volume_exits.py            # VolumeDryUp
│       └── adaptive.py                # AdaptiveVolatility
│
├── configs/
│   ├── configs.json                   # Buy strategies (existing)
│   ├── sell_strategies.json           # Sell strategies (NEW)
│   └── backtest_config.json           # Default backtest settings (NEW)
│
├── scripts/
│   ├── run_backtest.py                # Main CLI runner (NEW)
│   └── test_backtest.py               # Simple test script (NEW)
│
├── backtest_results/                  # Saved results (NEW)
│   └── (JSON files saved here)
│
├── data/                              # Historical K-line data (existing)
├── Selector.py                        # 6 buy strategies (existing)
└── README_BACKTEST.md                 # This file
```

---

## Configuration

### Sell Strategy Configuration (`configs/sell_strategies.json`)

Create custom composite strategies:

```json
{
  "my_custom_strategy": {
    "name": "my_custom_strategy",
    "combination_logic": "ANY",
    "strategies": [
      {
        "class": "PercentageTrailingStopStrategy",
        "params": {"trailing_pct": 0.10}
      },
      {
        "class": "FixedProfitTargetStrategy",
        "params": {"target_pct": 0.20}
      }
    ]
  }
}
```

### Buy Strategy Configuration (`configs/configs.json`)

Existing file controlling which buy selectors are active. No changes needed.

---

## Roadmap

### ✅ Phase 1-3 Complete (Current State)

- [x] Core backtesting engine with T+1 settlement
- [x] Portfolio management with realistic costs
- [x] All 12 sell strategies implemented
- [x] Comprehensive performance analysis
- [x] CLI runner with full configuration

### 🔜 Phase 4: Backend API (Next)

- [ ] FastAPI server for web interface
- [ ] Background job management
- [ ] Results persistence and retrieval
- [ ] Parameter optimization endpoints

### 🔜 Phase 5: Frontend Dashboard

- [ ] React + TypeScript web application
- [ ] Interactive configuration panel
- [ ] Equity curve visualization (Recharts)
- [ ] Trade history table (AG Grid)
- [ ] Strategy comparison tool
- [ ] Parameter optimizer UI

### 🔜 Phase 6: Advanced Features

- [ ] Walk-forward optimization
- [ ] Monte Carlo simulation
- [ ] Portfolio-level risk management
- [ ] Real-time paper trading mode
- [ ] Multi-strategy portfolio allocation

---

## Critical Implementation Notes

### Lookahead Bias Prevention

**CORRECT**:
```python
# Only use data up to current date
df_up_to_today = df[df['date'] <= current_date]
kdj = compute_kdj(df_up_to_today)
```

**WRONG**:
```python
# This uses future data!
kdj = compute_kdj(full_dataframe)
```

### T+1 Settlement

- Signal generated on day T → Order executes on day T+1 open
- Cash frozen until settlement
- Positions sellable on T+1

### Chinese A-Share Specifics

- **Price Limits**: ±10% (orders fail if price gaps beyond)
- **Transaction Costs**: 0.03% commission + 0.1% stamp tax (sells) + 0.1% slippage
- **Lot Size**: 100 shares (round down to nearest 100)
- **Suspensions**: Detected by volume = 0

---

## Contributing

To add a new sell strategy:

1. Create class inheriting from `SellStrategy` in `backtest/sell_strategies/`
2. Implement `should_sell()` method
3. Add to module map in `base.py`
4. Add configuration to `sell_strategies.json`

Example:

```python
from .base import SellStrategy

class MyCustomExitStrategy(SellStrategy):
    def __init__(self, my_param: float = 0.5, **params):
        super().__init__(**params)
        self.my_param = my_param

    def should_sell(self, position, current_date, current_data, hist_data):
        # Your logic here
        if some_condition:
            return True, "Exit reason"
        return False, ""
```

---

## FAQ

**Q: Why are my results different from production?**
A: Backtesting can never perfectly replicate live trading due to:
- Execution assumptions (slippage, price limits)
- Data quality issues
- Survivorship bias (delisted stocks not in data)

**Q: How do I validate the backtest?**
A: Use walk-forward testing:
1. Optimize on 2020-2022
2. Validate on 2023-2024
3. If out-of-sample degrades significantly, you're overfitting

**Q: Which sell strategy should I use?**
A: Start with `conservative_trailing` for robustness, then experiment with others.

**Q: Can I use multiple buy strategies simultaneously?**
A: Yes! All active selectors in `configs.json` run in parallel.

---

## License

Part of the StockTradebyZ project. For internal use.

---

## Contact

For questions or issues, please check the main project README.md.
