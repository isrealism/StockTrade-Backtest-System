# New Features Implementation Guide

This document describes two major features added to the backtesting system:
1. **Selector Combination Logic** (PRD Section 9)
2. **Benchmark Analysis** (PRD Section 8)

## Feature 1: Selector Combination Logic

### Overview

The system now supports three modes for combining signals from multiple buy selectors:

- **OR Mode** (default): Accept signals from ANY active selector
- **AND Mode**: Only signal when ALL specified selectors agree on the same stock
- **TIME_WINDOW Mode**: Signal when multiple selectors pick the same stock within N days

### Configuration

Edit `configs.json` to add a `selector_combination` section at the root level:

```json
{
  "selector_combination": {
    "mode": "OR",
    "time_window_days": 5,
    "required_selectors": []
  },
  "selectors": [
    // ... your selectors here ...
  ]
}
```

#### Configuration Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `mode` | string | Combination mode: "OR", "AND", or "TIME_WINDOW" | `"OR"` |
| `time_window_days` | integer | Days to look back for TIME_WINDOW mode | `5` |
| `required_selectors` | array | List of selector class names that must agree (for AND/TIME_WINDOW modes). Empty array means ALL active selectors. | `["BBIKDJSelector", "SuperB1Selector"]` |

### Usage Examples

#### Example 1: OR Mode (Default Behavior)

Accept signals from any selector. This is the current default behavior, providing maximum signal coverage.

```json
{
  "selector_combination": {
    "mode": "OR",
    "time_window_days": 5,
    "required_selectors": []
  },
  "selectors": [
    {"class": "BBIKDJSelector", "alias": "少妇战法", "activate": true, "params": {...}},
    {"class": "SuperB1Selector", "alias": "SuperB1战法", "activate": true, "params": {...}},
    {"class": "PeakKDJSelector", "alias": "填坑战法", "activate": true, "params": {...}}
  ]
}
```

**Result**: If BBIKDJSelector picks stock A, SuperB1Selector picks stock B, and PeakKDJSelector picks stock C on the same day, all three stocks (A, B, C) will be in the signal pool.

#### Example 2: AND Mode (Consensus Required)

Only signal when specified selectors ALL agree on the same stock. This reduces noise and increases confidence.

```json
{
  "selector_combination": {
    "mode": "AND",
    "time_window_days": 5,
    "required_selectors": ["BBIKDJSelector", "SuperB1Selector"]
  },
  "selectors": [
    {"class": "BBIKDJSelector", "alias": "少妇战法", "activate": true, "params": {...}},
    {"class": "SuperB1Selector", "alias": "SuperB1战法", "activate": true, "params": {...}},
    {"class": "PeakKDJSelector", "alias": "填坑战法", "activate": true, "params": {...}}
  ]
}
```

**Result**: Only stocks selected by BOTH BBIKDJSelector AND SuperB1Selector on the same day will be included. PeakKDJSelector signals are ignored (not in required_selectors list).

**Note**: If `required_selectors` is empty (`[]`), ALL active selectors must agree. This is very strict and will likely produce few signals.

#### Example 3: TIME_WINDOW Mode (Time-Delayed Consensus)

Signal when multiple selectors pick the same stock within N days. This captures momentum confirmed by different selectors over time.

```json
{
  "selector_combination": {
    "mode": "TIME_WINDOW",
    "time_window_days": 5,
    "required_selectors": ["BBIKDJSelector", "MA60CrossVolumeWaveSelector"]
  },
  "selectors": [
    {"class": "BBIKDJSelector", "alias": "少妇战法", "activate": true, "params": {...}},
    {"class": "MA60CrossVolumeWaveSelector", "alias": "上穿60放量战法", "activate": true, "params": {...}}
  ]
}
```

**Result**:
- Day 1: BBIKDJSelector picks stock X → No signal yet (only 1 selector)
- Day 3: MA60CrossVolumeWaveSelector picks stock X → Signal triggered! (both selectors picked X within 5 days)
- The signal uses the data from Day 3 (when the 2nd selector confirmed)

**Use Case**: Capture stocks where technical setup (e.g., BBI uptrend) appears first, then volume confirmation comes 2-3 days later.

### Backward Compatibility

✅ **Fully backward compatible**: If the `selector_combination` section is missing from `configs.json`, the system defaults to "OR" mode (current behavior).

✅ **Existing backtests unchanged**: All previous backtest results remain valid and reproducible.

### Expected Signal Counts

Based on typical behavior:

```
Signal Count: OR Mode > TIME_WINDOW Mode > AND Mode
```

- **OR Mode**: Highest signal count (union of all selectors)
- **TIME_WINDOW Mode**: Medium signal count (requires confirmation within window)
- **AND Mode**: Lowest signal count (requires same-day consensus)

### Verification

Check backtest logs for combination mode confirmation:

```
Loading buy selectors...
Selector combination mode: AND
  Required selectors: BBIKDJSelector, SuperB1Selector
Loaded 6 buy selectors
```

During backtest, you'll see:

```
2025-06-03: Getting buy signals...
  少妇战法: 45 signals
  SuperB1战法: 12 signals
  Total signals after AND logic: 3
```

This shows that only 3 stocks were picked by both selectors.

---

## Feature 2: Benchmark Analysis

### Overview

The backtesting system now supports performance comparison against market indices. Calculates:

- **Benchmark Returns**: Total and annualized returns of the index
- **Excess Return**: Portfolio return - Benchmark return
- **Alpha**: Jensen's alpha (risk-adjusted excess return)
- **Beta**: Portfolio volatility relative to benchmark
- **Tracking Error**: Standard deviation of excess returns
- **Information Ratio**: Excess return / Tracking error

### Supported Benchmarks

| Benchmark Name | Index Code | Description |
|----------------|------------|-------------|
| 沪深300 | 000300_SH | CSI 300 Index |
| 上证指数 | 000001_SH | Shanghai Composite |
| 中证500 | 000905_SH | CSI 500 Index |
| 创业板指 | 399006_SZ | ChiNext Index |
| 科创50 | 000688_SH | STAR 50 Index |

### Benchmark Data Location

Benchmark CSV files should be placed in:
```
/index_data/{index_code}.csv
```

For example:
- `/index_data/000300_SH.csv` (沪深300)
- `/index_data/000001_SH.csv` (上证指数)

**CSV Format**: Same as stock data (columns: `date, open, close, high, low, volume`)

### Usage with Python API

```python
from backtest.performance import PerformanceAnalyzer

# Initialize analyzer with benchmark
analyzer = PerformanceAnalyzer(
    equity_curve=equity_df,
    trades=trades_df,
    initial_capital=1000000,
    benchmark_name="沪深300"  # Specify benchmark here
)

# Run analysis
results = analyzer.analyze()

# Access benchmark metrics
if 'benchmark' in results:
    benchmark_metrics = results['benchmark']
    print(f"Benchmark Return: {benchmark_metrics['benchmark_total_return_pct']:.2f}%")
    print(f"Excess Return: {benchmark_metrics['excess_return_pct']:.2f}%")
    print(f"Alpha: {benchmark_metrics['alpha_pct']:.2f}%")
    print(f"Beta: {benchmark_metrics['beta']:.2f}")
    print(f"Tracking Error: {benchmark_metrics['tracking_error_pct']:.2f}%")
    print(f"Information Ratio: {benchmark_metrics['information_ratio']:.2f}")
```

### Usage with Backend API

**Request Payload**:
```json
{
  "start_date": "2025-01-01",
  "end_date": "2025-06-30",
  "initial_capital": 1000000,
  "max_positions": 10,
  "sell_strategy": "conservative_trailing",
  "benchmark_name": "沪深300"
}
```

**Response** (in results):
```json
{
  "benchmark": {
    "benchmark_name": "沪深300",
    "benchmark_total_return_pct": 12.5,
    "benchmark_annualized_return_pct": 25.8,
    "excess_return_pct": 3.2,
    "alpha_pct": 2.8,
    "beta": 1.15,
    "tracking_error_pct": 8.5,
    "information_ratio": 0.38
  },
  "benchmark_curve": [
    {"date": "2025-01-01", "benchmark_value": 1000000},
    {"date": "2025-01-02", "benchmark_value": 1012000},
    ...
  ]
}
```

### Benchmark Equity Curve

Get benchmark equity curve normalized to initial capital for charting:

```python
benchmark_curve = analyzer.get_benchmark_equity_curve()
# Returns DataFrame with columns: [date, benchmark_value]
# benchmark_value is normalized to match initial_capital
```

This allows overlaying the benchmark on the portfolio equity curve for visual comparison.

### Metrics Explanation

#### Alpha (α)
- **Formula**: α = Portfolio Return - (Risk-Free Rate + β × (Benchmark Return - Risk-Free Rate))
- **Interpretation**: Measures skill/outperformance beyond market movements
- **Example**: α = 2.8% means the strategy generated 2.8% annual return above what CAPM predicts

#### Beta (β)
- **Formula**: β = Cov(Portfolio, Benchmark) / Var(Benchmark)
- **Interpretation**: Measures portfolio volatility relative to market
- **Example**:
  - β = 1.15 means portfolio is 15% more volatile than benchmark
  - β = 0.85 means portfolio is 15% less volatile than benchmark
  - β = 1.00 means portfolio moves in sync with benchmark

#### Tracking Error
- **Formula**: σ(Portfolio Returns - Benchmark Returns) × √252
- **Interpretation**: Volatility of excess returns (annualized)
- **Example**: 8.5% tracking error means daily excess returns have 8.5% annual volatility

#### Information Ratio
- **Formula**: IR = Excess Return / Tracking Error
- **Interpretation**: Risk-adjusted excess return (similar to Sharpe, but vs. benchmark)
- **Example**: IR = 0.38 means 0.38 units of excess return per unit of tracking risk
- **Good values**: IR > 0.5 is considered good, IR > 1.0 is excellent

### Example Interpretation

```json
{
  "benchmark_name": "沪深300",
  "benchmark_total_return_pct": 12.5,
  "excess_return_pct": 3.2,
  "alpha_pct": 2.8,
  "beta": 1.15,
  "tracking_error_pct": 8.5,
  "information_ratio": 0.38
}
```

**Interpretation**:
- ✅ **Outperformance**: Portfolio returned 15.7% vs. benchmark 12.5% (+3.2% excess)
- ✅ **Skill**: α = 2.8% suggests genuine alpha generation (not just riding market beta)
- ⚠️ **Higher volatility**: β = 1.15 means portfolio is more volatile than 沪深300
- ✅ **Consistent**: IR = 0.38 shows excess return is not purely from taking more risk

### Backward Compatibility

✅ **Fully backward compatible**: If `benchmark_name` is not specified or `None`, the system works exactly as before without benchmark analysis.

✅ **No breaking changes**: Existing code continues to work without modification.

### Verification

When benchmark is loaded successfully:

```python
INFO:root:Loaded benchmark 沪深300: 120 records
```

If benchmark file is missing:

```python
WARNING:root:Benchmark file not found: /path/to/index_data/000300_SH.csv
```

The backtest continues normally without benchmark metrics.

---

## Testing

### Test Selector Combinations

```bash
# Test OR mode
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30

# Verify in configs.json:
# "mode": "OR"  # Should see sum of all selector signals

# Test AND mode
# Edit configs.json: "mode": "AND", "required_selectors": ["BBIKDJSelector", "SuperB1Selector"]
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30
# Should see much fewer signals (only consensus picks)

# Test TIME_WINDOW mode
# Edit configs.json: "mode": "TIME_WINDOW", "time_window_days": 5
python scripts/run_backtest.py --start 2025-06-01 --end 2025-06-30
# Should see medium signal count (time-delayed confirmations)
```

### Test Benchmark Analysis

```bash
# Run test script
python test_implementation.py

# Or manually test with Python:
python -c "
from backtest.performance import PerformanceAnalyzer
import pandas as pd

# Create sample equity curve
equity = pd.DataFrame({
    'date': pd.date_range('2025-01-01', '2025-06-30'),
    'total_value': [1000000 * (1 + i*0.001) for i in range(181)]
})

analyzer = PerformanceAnalyzer(
    equity_curve=equity,
    trades=pd.DataFrame(),
    initial_capital=1000000,
    benchmark_name='沪深300'
)

results = analyzer.analyze()
print('Benchmark metrics:', results.get('benchmark'))
"
```

---

## Migration Guide

### For Existing Users

**No action required!** Both features are additive and fully backward compatible.

Your existing `configs.json` will continue to work:
- Selector combination defaults to "OR" mode (current behavior)
- Benchmark analysis is disabled by default

### To Adopt New Features

#### Step 1: Add Selector Combination (Optional)

Edit `configs.json`:

```json
{
  "selector_combination": {
    "mode": "OR",  // or "AND" or "TIME_WINDOW"
    "time_window_days": 5,
    "required_selectors": []  // or ["SelectorA", "SelectorB"]
  },
  "selectors": [
    // ... existing selectors unchanged ...
  ]
}
```

#### Step 2: Add Benchmark Data (Optional)

1. Download benchmark index data (same format as stock data)
2. Place in `/index_data/` directory
3. Use `benchmark_name` parameter when creating PerformanceAnalyzer

Example:
```bash
# Download 沪深300 data using fetch_benchmark.py (if available)
python fetch_benchmark.py --index 000300_SH --start 20240101 --end today
```

Or manually create CSVs matching the stock data format.

---

## Troubleshooting

### Issue: "Selector combination mode: OR (default)" even though I set "AND"

**Solution**: Check `configs.json` syntax. Ensure `selector_combination` is at root level, not inside `selectors` array.

### Issue: Benchmark metrics not appearing in results

**Possible causes**:
1. `benchmark_name` not specified → Check PerformanceAnalyzer initialization
2. Benchmark file missing → Check `/index_data/{code}.csv` exists
3. Date mismatch → Benchmark data must overlap with backtest period

**Solution**:
```python
# Verify benchmark data exists
import pandas as pd
df = pd.read_csv('/index_data/000300_SH.csv')
print(df['date'].min(), df['date'].max())  # Check date range
```

### Issue: TIME_WINDOW mode shows very few signals

**Solution**:
- Increase `time_window_days` (try 7 or 10 days)
- Reduce `required_selectors` list (use fewer selectors)
- Check if selectors have overlapping signal patterns

### Issue: AND mode shows zero signals

**Solution**:
- Verify `required_selectors` class names match exactly
- Try with just 2 selectors first (e.g., `["BBIKDJSelector", "SuperB1Selector"]`)
- Check selector logs to ensure both are generating signals

---

## Performance Considerations

### Selector Combination Logic

- **OR Mode**: No performance impact (current implementation)
- **AND Mode**: Minimal impact (simple set intersection)
- **TIME_WINDOW Mode**: Small memory overhead (maintains signal history)
  - Memory: ~5 days × 6 selectors × 100 stocks = ~3000 entries
  - Cleanup: Automatic (history older than window is discarded)

### Benchmark Analysis

- **Disk I/O**: One additional CSV read per backtest (negligible)
- **Memory**: ~100-200 KB per benchmark (daily data for 1-2 years)
- **Computation**: O(n) where n = number of trading days (very fast)

---

## Future Enhancements

Potential future improvements:

1. **Frontend Integration**:
   - Dropdown to select combination mode in UI
   - Dropdown to select benchmark index in UI
   - Benchmark equity curve overlay on charts

2. **Advanced Combination Logic**:
   - Custom weighted voting (e.g., 60% BBISelector, 40% PeakSelector)
   - Threshold-based combination (e.g., at least 3 out of 5 selectors)

3. **Additional Benchmarks**:
   - Industry-specific indices (e.g., 中证医药, 中证消费)
   - Custom benchmark composition

4. **Benchmark Metrics**:
   - Downside Beta (volatility only on negative days)
   - Upside/Downside Capture Ratios
   - Rolling correlation with benchmark

---

## Summary

✅ **Selector Combination Logic**: Implemented with OR/AND/TIME_WINDOW modes
✅ **Benchmark Analysis**: Implemented with Alpha, Beta, IR, tracking error
✅ **Backward Compatible**: No breaking changes to existing code
✅ **Well Tested**: All unit tests passing
✅ **PRD Compliant**: Fully implements PRD Sections 8 & 9

**Files Modified**:
- `configs.json`: Added selector_combination section
- `backtest/engine.py`: Added combination logic methods
- `backtest/performance.py`: Added benchmark support

**Files Created**:
- `test_implementation.py`: Comprehensive test suite

For questions or issues, refer to:
- `CLAUDE.md`: System architecture and conventions
- `PRD.md`: Product requirements
- `TECHNICAL_ARCHITECTURE.md`: System design
