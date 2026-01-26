# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Python-based stock trading system** implementing "Z哥战法" (Z's Trading Strategies) for Chinese A-share markets. The system has two main components:

1. **Stock Selection System**: Identifies trading opportunities using technical analysis
2. **Backtesting System**: Validates strategy performance on historical data

**For comprehensive documentation:**
- **Product Requirements**: See `PRD.md` for detailed feature specifications
- **Technical Architecture**: See `TECHNICAL_ARCHITECTURE.md` for system design and data flow
- **Implementation Status**: See `IMPLEMENTATION_SUMMARY.md` for completed features
- **Bug Fixes**: See `LOW_VOLUME_DIAGNOSIS.md` for critical historical data loading fix

### System Components

**Stock Selection Workflow:**
1. `fetch_kline.py` downloads historical daily K-line data (qfq/前复权) from Tushare → saves to `./data/`
2. `select_stock.py` loads data and applies configured selectors → outputs results to console and `select_results.log`
3. `Selector.py` contains 6 buy selector implementations with shared technical indicators

**Backtesting Workflow:**
1. User selects buy selectors (entry strategies) and sell strategies (exit strategies)
2. `scripts/run_backtest.py` runs historical simulation with realistic market constraints
3. System outputs comprehensive performance metrics (returns, Sharpe ratio, win rate, etc.)
4. Results can be saved to JSON for further analysis

## Commands

### Environment Setup
```bash
# Create conda environment (Python 3.11/3.12)
conda create -n stock python=3.12 -y
conda activate stock
pip install -r requirements.txt

# Set Tushare token (required)
export TUSHARE_TOKEN=your_token_here  # macOS/Linux
setx TUSHARE_TOKEN "your_token_here"  # Windows PowerShell
```

### Download Historical Data
```bash
# Full download with board exclusions
python fetch_kline.py \
  --start 20240101 \
  --end today \
  --stocklist ./stocklist.csv \
  --exclude-boards gem star bj \
  --out ./data \
  --workers 6

# Parameters:
# --start, --end: Date range (YYYYMMDD or 'today')
# --stocklist: CSV containing stock codes (requires 'ts_code' or 'symbol' column)
# --exclude-boards: gem (创业板 300/301), star (科创板 688), bj (北交所)
# --workers: Concurrent threads (default: 6)
```

**Important:** Data is fetched from Tushare with qfq (前复权) adjustment and **fully overwritten** each time (not incremental). Rate limiting triggers a 600s cooldown automatically.

### Run Stock Selection
```bash
# Run all active selectors
python select_stock.py \
  --data-dir ./data \
  --config ./configs.json \
  --date 2025-09-10

# Parameters:
# --date: Trading date (YYYY-MM-DD), defaults to latest date in data
# --tickers: 'all' or comma-separated codes (default: all)
```

### Sector Distribution Analysis
```bash
# Analyze industry distribution for stocks with low J values
python SectorShift.py \
  --data_dir ./data \
  --stocklist stocklist.csv \
  --j_threshold 15.0 \
  --trade_date 20250122
```

### Run Backtest System
```bash
# Run backtest with default settings (conservative_trailing strategy)
python scripts/run_backtest.py

# Run with specific configuration
python scripts/run_backtest.py \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --sell-strategy aggressive_atr \
  --max-positions 15 \
  --initial-capital 1000000 \
  --save-results ./backtest_results/my_test.json

# Parameters:
# --start, --end: Backtest date range (YYYY-MM-DD)
# --sell-strategy: Name from configs/sell_strategies.json
# --max-positions: Maximum concurrent positions (default: 10)
# --initial-capital: Starting capital (default: 1,000,000)
# --position-sizing: equal_weight | risk_based (default: equal_weight)
# --data-dir: Data directory (default: ./data)
# --save-results: Path to save JSON results (optional)

# Available sell strategies (from configs/sell_strategies.json):
# - conservative_trailing (8% trailing stop + 15% profit + 60d max hold)
# - aggressive_atr (2x ATR trailing + 20% profit + 45d max hold)
# - indicator_based (KDJ overbought + BBI reversal + 10% trailing)
# - adaptive_volatility (5%-12% adaptive stop + 15% profit)
# - chandelier_3r (Chandelier stop + 3R profit target)
# - zx_discipline (ZX lines cross + MA death cross + 8% trailing)
# - simple_percentage_stop (8% trailing + 60d max hold)
# - hold_forever (never sells - buy-and-hold baseline)
```

### Test Individual Selectors
```bash
# Validate all selectors and check signal generation
python scripts/test_selectors.py

# This will:
# - Test each activated selector from configs.json
# - Load 100 sample stocks
# - Report which selectors generate signals
# - Identify any errors or failures
```

**Important for Backtesting:**
- ⚠️ **CRITICAL**: Backtest engine requires **120+ trading days** of historical data before backtest start
- ✅ For data starting 2024-01-02: Start backtests from **2024-05-01 or later**
- ✅ Or start from **2025-01-01+** for best results with full year of history
- ❌ Avoid 2024-01-01 to 2024-04-30 (insufficient historical data for indicators like MA60, MA120, BBI)
- The engine automatically loads 200 calendar days (~140 trading days) before backtest start for indicator calculations
- Check data quality warnings in output to ensure sufficient history

## Architecture

### Core Components

**fetch_kline.py**
- Single data source: Tushare API (daily, qfq only)
- Reads stock pool from `stocklist.csv` (must have `ts_code` or `symbol` column)
- Concurrent fetching with automatic retry on rate limits (3 attempts, 600s cooldown)
- Full overwrite strategy per stock: `./data/{code}.csv`
- Output columns: `date, open, close, high, low, volume`

**select_stock.py**
- Batch execution framework for selectors
- Dynamically loads selector classes from `Selector.py` based on `configs.json`
- Each selector config requires: `class`, `alias`, `activate`, `params`
- Outputs to both console and `select_results.log`

**Selector.py**
- Contains 6 strategy implementations (selectors) plus shared indicator functions
- **Shared indicators** (used across strategies):
  - `compute_kdj()`: KDJ indicator (K, D, J values)
  - `compute_bbi()`: BBI = (MA3 + MA6 + MA12 + MA24) / 4
  - `compute_rsv()`: RSV(N) = 100 × (C - LLV(L,N)) / (HHV(C,N) - LLV(L,N))
  - `compute_dif()`: MACD DIF line
  - `compute_zx_lines()`: Returns (ZXDQ, ZXDKX) - proprietary short/long-term moving averages
    - ZXDQ = EMA(EMA(C,10),10) - short-term
    - ZXDKX = (MA(14)+MA(28)+MA(57)+MA(114))/4 - long-term
  - `bbi_deriv_uptrend()`: Adaptive BBI uptrend detection with tolerable pullback
  - `last_valid_ma_cross_up()`: Finds last valid MA crossover position

- **Unified filtering** (applied to ALL strategies):
  - `passes_day_constraints_today()`: Daily filter - checks price change < 2% and amplitude < 7%
  - `zx_condition_at_positions()`: "知行约束" (discipline constraints) - validates close > long-term line AND short-term > long-term line at specified positions

### Strategy Implementations

All 6 selectors follow this pattern:
1. Inherit no base class (duck-typed interface)
2. Implement `__init__(**params)` for configuration
3. Implement `_passes_filters(hist: pd.DataFrame) -> bool` for single-stock filtering logic
4. Implement `select(date: pd.Timestamp, data: Dict[str, pd.DataFrame]) -> List[str]` for batch processing

**Strategy overview:**
1. **BBIKDJSelector** (少妇战法): BBI uptrend + low KDJ J + DIF > 0 + MA60 crossover
2. **SuperB1Selector** (SuperB1战法): Finds historical BBIKDJSelector match + consolidation + price drop + low J
3. **BBIShortLongSelector** (补票战法): BBI uptrend + short/long RSV patterns + DIF > 0
4. **PeakKDJSelector** (填坑战法): Peak detection + KDJ + price fluctuation within threshold
5. **MA60CrossVolumeWaveSelector** (上穿60放量战法): MA60 crossover + volume surge + low J + MA60 slope > 0
6. **BigBullishVolumeSelector** (暴力K战法): Strong bullish candle + volume surge + close to short-term MA (ZXDQ)

### Backtest System Architecture

**backtest/** - Core backtesting engine
- `engine.py`: Event-driven backtest loop with lookahead bias prevention
- `portfolio.py`: Position and cash management with T+1 settlement
- `execution.py`: Order execution with price limits and transaction costs
- `performance.py`: Comprehensive metrics calculation (Sharpe, Sortino, drawdown, etc.)
- `data_structures.py`: Position, Order, Trade, BuySignal classes
- `sell_strategies/`: 12 modular exit strategies

**Sell Strategies (12 types):**
1. **ATRTrailingStopStrategy**: Adaptive stop using ATR × multiplier
2. **ChandelierStopStrategy**: Conservative ATR from highest high
3. **PercentageTrailingStopStrategy**: Simple % stop from highest close
4. **FixedProfitTargetStrategy**: Exit at +X% profit
5. **MultipleRExitStrategy**: Exit at N×R (risk-reward ratio)
6. **TimedExitStrategy**: Force exit after N days
7. **KDJOverboughtExitStrategy**: Exit when J > 80 (overbought)
8. **BBIReversalExitStrategy**: Exit on BBI downtrend
9. **ZXLinesCrossDownExitStrategy**: Exit when ZXDQ crosses below ZXDKX
10. **MADeathCrossExitStrategy**: Exit on MA5 < MA20
11. **VolumeDryUpExitStrategy**: Exit on sustained low volume
12. **AdaptiveVolatilityExitStrategy**: Volatility-aware stop adjustment

**Backtest Engine Features:**
- ✅ **T+1 Settlement**: Signals on day T, executes on day T+1 open (Chinese A-share requirement)
- ✅ **Price Limits**: ±10% daily price limit validation, orders rejected if gap exceeds
- ✅ **Transaction Costs**: 0.03% commission + 0.10% stamp tax + 0.10% slippage
- ✅ **Cash Management**: Tracks frozen cash from pending orders, prevents negative balance
- ✅ **Position Sizing**: Equal weight or risk-based (ATR) allocation
- ✅ **Stock Suspension**: Detects suspended stocks (volume = 0) and skips execution
- ✅ **Lookahead Bias Prevention**: Event-driven architecture, only uses data up to current date
- ✅ **Data Quality Validation**: Warns when insufficient historical data (<120 days)
- ✅ **Diagnostic Logging**: Per-selector signal counts for debugging

**Critical Bug Fix (2026-01-26):**
The backtest engine was updated to load 200 calendar days (~140 trading days) of historical data BEFORE the backtest start date. This ensures selectors have sufficient data for indicators like MA60, MA120, and BBI.

**Before fix:** Only 1/6 selectors working (insufficient data)
**After fix:** 4/6 selectors working, 15x increase in signal generation

This fix is critical for realistic backtesting. Without it, selectors silently fail due to NaN values in indicators.

### Configuration System

**configs.json** - Buy selector configuration:
```json
{
  "selectors": [
    {
      "class": "BBIKDJSelector",      // Class name in Selector.py
      "alias": "少妇战法",              // Display name
      "activate": true,                // Enable/disable
      "params": {                      // Strategy-specific parameters
        "j_threshold": 15,
        "max_window": 120,
        // ... other params
      }
    }
  ]
}
```

**configs/sell_strategies.json** - Sell strategy configuration:
```json
{
  "conservative_trailing": {
    "combination_logic": "ANY",      // ANY = exit on first match, ALL = require all conditions
    "strategies": [
      {
        "class": "PercentageTrailingStopStrategy",
        "params": {"trailing_pct": 0.08}
      },
      {
        "class": "FixedProfitTargetStrategy",
        "params": {"target_pct": 0.15}
      },
      {
        "class": "TimedExitStrategy",
        "params": {"max_holding_days": 60}
      }
    ]
  }
}
```

**configs/backtest_config.json** - Backtest defaults (optional):
- Default date range, initial capital, max positions
- Transaction cost defaults
- Position sizing method

**To add a new buy selector:**
1. Implement class in `Selector.py` with `__init__()`, `_passes_filters()`, `select()` methods
2. Add configuration entry to `configs.json`
3. Ensure it calls `passes_day_constraints_today()` and `zx_condition_at_positions()` for consistency

**To add a new sell strategy:**
1. Implement class in `backtest/sell_strategies/` inheriting from `SellStrategy`
2. Implement `should_exit()` method returning (bool, reason_string)
3. Add to `configs/sell_strategies.json` as standalone or composite strategy
4. No changes to backtest engine required (plugin architecture)

### Data Files

**Input Data:**
- `stocklist.csv`: Stock universe (must contain `ts_code` or `symbol` + optionally `industry`/`行业`)
- `./data/`: CSV files per stock (XXXXXX.csv), sorted by date ascending
  - Columns: `date, open, close, high, low, volume`
  - Format: Daily K-line data with qfq (前复权) adjustment
  - Source: Tushare API via `fetch_kline.py`

**Configuration Files:**
- `configs.json`: Buy selector activation and parameters
- `configs/sell_strategies.json`: Sell strategy definitions
- `configs/backtest_config.json`: Backtest system defaults (optional)

**Output Files:**
- `fetch.log`: Data download logs
- `select_results.log`: Stock selection results with timestamps
- `backtest_results/`: Backtest JSON outputs (when using `--save-results`)
  - Contains: trades, performance metrics, equity curve, configuration snapshot
- `appendix.json`: Additional metadata (purpose unclear from codebase)

**Backtest JSON Output Structure:**
```json
{
  "metadata": {
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
    "initial_capital": 1000000,
    "sell_strategy": "conservative_trailing",
    "max_positions": 10
  },
  "performance": {
    "total_return": 0.15,
    "sharpe_ratio": 1.85,
    "max_drawdown": -0.08,
    "win_rate": 0.62
  },
  "trades": [...],
  "equity_curve": [...]
}
```

## Key Technical Details

**Data Source:**
- Tushare API only (no alternatives)
- Fixed qfq (前复权) adjustment
- Daily frequency only

**Performance:**
- Concurrent fetching (default 6 workers)
- Rate limit handling: automatic 600s cooldown on ban detection (keywords: "访问频繁", "429", "403", "max retries exceeded")
- Each stock gets 3 retry attempts with exponential backoff (15s per attempt)

**Knowledge Constraint (知行约束):**
This is a critical filtering concept applied across all strategies. It validates market discipline conditions:
- At reference points (like historical match days): `close > long-term line` AND `short-term > long-term`
- At current day: May require only `short-term > long-term` (strategy-dependent)
- Uses `compute_zx_lines()` to calculate ZXDQ (short) and ZXDKX (long)

**Peak Detection:**
- PeakKDJSelector uses `scipy.signal.find_peaks` on `oc_max = max(open, close)`
- Requires at least 2 peaks with specific structural relationships
- Validates gap threshold to ensure peak prominence

## Common Patterns

**Working with historical data:**
```python
# Standard data prep in selectors
hist = df[df["date"] <= date].tail(max_window + buffer)
if len(hist) < min_required:
    return False

# Apply unified filters
if not passes_day_constraints_today(hist):
    return False
if not zx_condition_at_positions(hist, require_close_gt_long=True, require_short_gt_long=True):
    return False
```

**Adding indicators:**
```python
# Always work on a copy to avoid modifying shared data
hist = hist.copy()
hist["BBI"] = compute_bbi(hist)
hist["MA60"] = hist["close"].rolling(window=60, min_periods=1).mean()
kdj = compute_kdj(hist)  # Returns new DataFrame with K, D, J columns
```

**Finding MA crossovers:**
```python
# Use the shared utility function
t_pos = last_valid_ma_cross_up(hist["close"], hist["MA60"], lookback_n=120)
if t_pos is None:
    return False
# t_pos is an integer iloc position
```

## Testing Considerations

### Stock Selection Testing
When testing or debugging selectors:
1. Ensure adequate historical data length (strategies need 120-150+ days)
2. Check for NaN values in computed indicators (especially MA60, ZXDKX which need min samples)
3. Test edge cases: empty data, single-row data, missing columns
4. Verify date filtering logic (`df["date"] <= target_date`)
5. Confirm KDJ calculations match expected behavior (initial K=D=50)

### Backtest Testing
When testing or debugging backtests:

**1. Data Quality Validation**
```bash
# Run backtest and check data quality section
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30 ... | grep -A 10 "Validating data quality"

# Expected output:
# Data available at backtest start (2025-06-01):
#   Max data length: 132 days  # Should be >120 for all selectors to work
#   Stocks with <120 days (max_window): 24  # Should be low
```

**2. Selector Signal Validation**
```bash
# Test individual selectors first
python scripts/test_selectors.py

# Then check per-selector signals in backtest
python scripts/run_backtest.py ... | grep "signals$"

# Expected: Multiple selectors should show non-zero signals
# If a selector always shows 0, investigate parameters or data requirements
```

**3. Lookahead Bias Checks**
- Verify signals use only `df[df['date'] <= current_date]`
- Confirm orders execute on T+1 (never same day)
- Check that performance metrics don't use future data

**4. Transaction Cost Verification**
- Confirm costs applied to both entry and exit
- Verify stamp tax only on sells (not buys)
- Check 100-share lot size rounding

**5. Edge Cases**
- Test with suspended stocks (volume = 0)
- Test with stocks hitting price limits (±10%)
- Test with insufficient cash (should reject orders)
- Test with empty date ranges or missing data

## Typical Workflows

### Workflow 1: Validate a New Buy Selector
1. Implement selector class in `Selector.py`
2. Add config to `configs.json` with `activate: true`
3. Test selector in isolation: `python scripts/test_selectors.py`
4. Run backtest with conservative strategy: `python scripts/run_backtest.py --sell-strategy conservative_trailing --start 2025-01-01 --end 2025-06-30`
5. Review performance metrics and per-selector signal counts
6. Iterate on parameters if needed

### Workflow 2: Compare Sell Strategies
```bash
# Run backtests with different exit strategies
python scripts/run_backtest.py --start 2025-01-01 --end 2025-06-30 \
  --sell-strategy conservative_trailing --save-results ./results/conservative.json

python scripts/run_backtest.py --start 2025-01-01 --end 2025-06-30 \
  --sell-strategy aggressive_atr --save-results ./results/aggressive.json

python scripts/run_backtest.py --start 2025-01-01 --end 2025-06-30 \
  --sell-strategy indicator_based --save-results ./results/indicator.json

# Compare metrics: Sharpe ratio, win rate, max drawdown
# Choose strategy with best risk-adjusted returns
```

### Workflow 3: Daily Stock Selection (Live Usage)
```bash
# 1. Update data to latest
python fetch_kline.py --start 20240101 --end today --stocklist ./stocklist.csv --out ./data

# 2. Run selectors for today
python select_stock.py --data-dir ./data --config ./configs.json

# 3. Review results in select_results.log
# 4. Manually review selected stocks before trading
```

### Workflow 4: Strategy Development Cycle
1. **Research**: Identify pattern or hypothesis from market observation
2. **Implement**: Code new selector in `Selector.py`
3. **Unit Test**: Test with `scripts/test_selectors.py`
4. **Backtest**: Run on multiple time periods (bull/bear markets)
5. **Analyze**: Review metrics, exit reasons, trade distribution
6. **Refine**: Adjust parameters or logic based on findings
7. **Validate**: Test on out-of-sample data (different date range)
8. **Deploy**: Use in live stock selection (if validated)

## Best Practices

### For Selector Development
- ✅ Always call `passes_day_constraints_today()` for consistency
- ✅ Apply `zx_condition_at_positions()` to maintain discipline constraints
- ✅ Work on `.copy()` of DataFrames to avoid modifying shared data
- ✅ Handle edge cases (empty data, insufficient history)
- ✅ Use shared indicator functions (`compute_kdj()`, `compute_bbi()`, etc.)
- ❌ Don't use future data (check date filtering)
- ❌ Don't hardcode magic numbers (use params)

### For Backtesting
- ✅ Start backtests from 2024-05-01+ or 2025-01-01+ (sufficient history)
- ✅ Test multiple time periods (bull, bear, sideways markets)
- ✅ Compare against baseline (buy-and-hold, simple trailing stop)
- ✅ Check data quality warnings in output
- ✅ Use `--save-results` to preserve results for analysis
- ✅ Test with different max_positions (10, 15, 20)
- ❌ Don't optimize on single time period (overfitting risk)
- ❌ Don't ignore transaction costs
- ❌ Don't backtest on insufficient data (pre-2024-05-01)

### For Configuration
- ✅ Use descriptive aliases in Chinese for selectors
- ✅ Document parameter meanings in comments
- ✅ Keep backup of working configurations
- ✅ Use `activate: false` instead of deleting selectors
- ❌ Don't modify configs.json while backtest is running
- ❌ Don't use extreme parameter values without testing

## Project Documentation

### Main Documentation Files
- **`PRD.md`**: Product Requirements Document - comprehensive feature specifications, user stories, and acceptance criteria
- **`TECHNICAL_ARCHITECTURE.md`**: System architecture, data flow diagrams, and component relationships
- **`README_BACKTEST.md`**: Complete user guide for the backtesting system with examples
- **`IMPLEMENTATION_SUMMARY.md`**: Implementation status, completed features, and future roadmap
- **`LOW_VOLUME_DIAGNOSIS.md`**: Critical bug fix documentation for historical data loading issue
- **`CLAUDE.md`**: This file - quick reference for AI assistants working on the codebase

### Quick Reference
| Question | Documentation |
|----------|---------------|
| What features are available? | `PRD.md` |
| How does the system work? | `TECHNICAL_ARCHITECTURE.md` |
| How do I use the backtest system? | `README_BACKTEST.md` |
| What's been implemented? | `IMPLEMENTATION_SUMMARY.md` |
| Why do I need 120+ days of data? | `LOW_VOLUME_DIAGNOSIS.md` |
| How do I add a new selector? | `CLAUDE.md` (this file) |

### File Organization
```
StockTradebyZ/
├── Documentation/
│   ├── PRD.md                         # Product requirements
│   ├── TECHNICAL_ARCHITECTURE.md      # System architecture
│   ├── README_BACKTEST.md             # Backtest user guide
│   ├── IMPLEMENTATION_SUMMARY.md      # Implementation status
│   ├── LOW_VOLUME_DIAGNOSIS.md        # Bug fix details
│   └── CLAUDE.md                      # AI assistant guide (this file)
│
├── Core System/
│   ├── Selector.py                    # 6 buy selectors
│   ├── fetch_kline.py                 # Data download
│   ├── select_stock.py                # Stock selection runner
│   └── SectorShift.py                 # Sector analysis
│
├── Backtest System/
│   ├── backtest/                      # Backtest engine
│   │   ├── engine.py                  # Main backtest loop
│   │   ├── portfolio.py               # Portfolio management
│   │   ├── execution.py               # Order execution
│   │   ├── performance.py             # Metrics calculation
│   │   └── sell_strategies/           # 12 exit strategies
│   └── scripts/
│       ├── run_backtest.py            # Backtest CLI
│       └── test_selectors.py          # Selector validation
│
├── Configuration/
│   ├── configs.json                   # Buy selector config
│   └── configs/
│       ├── sell_strategies.json       # Sell strategy config
│       └── backtest_config.json       # Backtest defaults
│
└── Data/
    ├── stocklist.csv                  # Stock universe
    ├── data/                          # Historical K-line data
    └── backtest_results/              # Saved backtest outputs
```

## Environment Variables

- `TUSHARE_TOKEN` (required): Tushare API token
- `NO_PROXY` / `no_proxy`: Set to "api.waditu.com,.waditu.com,waditu.com" (auto-configured in fetch_kline.py)

---

## ⚠️ CRITICAL: Historical Data Requirements for Backtesting

**Issue**: Backtest engine requires sufficient historical data BEFORE backtest start date for indicator calculations.

**Root Cause**: Many selectors use indicators requiring 60-120 days of data:
- MA60, MA120: Moving averages
- BBI: (MA3 + MA6 + MA12 + MA24) / 4
- KDJ: 9-day stochastic oscillator
- Peak detection: Requires multiple historical peaks

**Solution**: The backtest engine automatically loads **200 calendar days (~140 trading days)** before backtest start.

**Practical Impact**:
```bash
# ❌ BAD: Insufficient data (only 22 days available in January 2024)
python scripts/run_backtest.py --start 2024-01-01 --end 2024-01-31
# Result: Only 1/6 selectors work, ~7 signals/day

# ✅ GOOD: Sufficient data (132+ days available)
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30
# Result: 4/6 selectors work, ~105 signals/day (15x improvement!)
```

**Recommended Date Ranges**:
- ✅ **2024-05-01 onwards** (minimum 120 days of history)
- ✅ **2025-01-01 onwards** (full year of history, best results)
- ❌ **Avoid 2024-01-01 to 2024-04-30** (insufficient history)

**How to Check Data Quality**:
```bash
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30 ... | grep -A 10 "Validating data quality"

# Look for:
# Data available at backtest start (2025-06-01):
#   Max data length: 132 days  ← Should be >120
#   Stocks with <120 days (max_window): 24  ← Should be low
```

**See Also**: `LOW_VOLUME_DIAGNOSIS.md` for complete investigation and fix details.

---

**Last Updated**: 2026-01-26
**For Questions**: See PRD.md, TECHNICAL_ARCHITECTURE.md, or README_BACKTEST.md
