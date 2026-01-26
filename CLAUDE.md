# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based stock selection system implementing "Z哥战法" (Z's Trading Strategies) for Chinese A-share markets. The system fetches historical K-line data from Tushare and applies multiple technical analysis strategies (selectors) to identify trading opportunities.

**Data Flow:**
1. `fetch_kline.py` downloads historical daily K-line data (qfq/前复权) from Tushare → saves to `./data/`
2. `select_stock.py` loads data and applies configured selectors → outputs results to console and `select_results.log`
3. `Selector.py` contains all strategy implementations with shared technical indicators

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

### Configuration System

**configs.json** structure:
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

To add a new selector:
1. Implement class in `Selector.py` with `__init__()`, `_passes_filters()`, `select()` methods
2. Add configuration entry to `configs.json`
3. Ensure it calls `passes_day_constraints_today()` and `zx_condition_at_positions()` for consistency

### Data Files

- `stocklist.csv`: Stock universe (must contain `ts_code` or `symbol` + optionally `industry`/`行业`)
- `./data/`: CSV files per stock (XXXXXX.csv), sorted by date ascending
- `fetch.log`: Download logs
- `select_results.log`: Selection results with timestamps
- `appendix.json`: Additional metadata (purpose unclear from codebase)

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

When testing or debugging selectors:
1. Ensure adequate historical data length (strategies need 120-150+ days)
2. Check for NaN values in computed indicators (especially MA60, ZXDKX which need min samples)
3. Test edge cases: empty data, single-row data, missing columns
4. Verify date filtering logic (`df["date"] <= target_date`)
5. Confirm KDJ calculations match expected behavior (initial K=D=50)

## Environment Variables

- `TUSHARE_TOKEN` (required): Tushare API token
- `NO_PROXY` / `no_proxy`: Set to "api.waditu.com,.waditu.com,waditu.com" (auto-configured in fetch_kline.py)
