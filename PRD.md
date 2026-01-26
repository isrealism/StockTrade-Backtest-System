# Product Requirements Document (PRD)
# Project: StockTradebyZ Backtest System

## Summary
This project provides a backtesting system for stock trading strategies. Users choose one of six built-in selectors (buy signals) and a sell strategy, run a backtest over historical data, and review performance results. The system is designed to be extensible so new selectors and strategies can be added over time.

## Problem Statement
Strategy ideas often look good in hindsight but fail in real market conditions. The project needs a repeatable, realistic way to evaluate strategy performance across historical data, with guardrails against lookahead bias and realistic execution constraints.

## Goals
- Allow users to select a buy selector and sell strategy, run a backtest, and review results.
- Provide realistic market simulation (T+1, price limits, transaction costs).
- Produce consistent, comparable performance metrics for strategy evaluation.
- Make it easy to add new selectors and sell strategies.

## Non-Goals
- Live trading execution or broker integration.
- Portfolio optimization or ML-based strategy discovery.
- Real-time data streaming.
- Multi-asset classes beyond A-share equities.

## Target Users
- Individual traders testing strategy ideas.
- Researchers comparing selector/strategy combinations.
- Developers extending the system with new selectors or exits.

## User Stories
- As a user, I can choose a buy selector and sell strategy and run a backtest over a date range.
- As a user, I can review key performance metrics (return, drawdown, Sharpe, win rate).
- As a user, I can save backtest results to a file for later analysis.
- As a developer, I can add a new selector or sell strategy with minimal changes.

## Functional Requirements
1. **Backtest Execution**
   - Load historical OHLCV data from a specified `--data-dir` with per-symbol CSVs.
   - Enforce date range filtering (`--start`, `--end`) with daily iteration.
   - Prevent lookahead bias by using only data available up to the current date.
   - Simulate T+1 settlement with pending order tracking and cash freezing.
   - Enforce daily price limits (±10%) and reject orders that cross limits.
   - Apply transaction costs (commission, stamp tax, slippage) to every fill.
   - Support position sizing (`equal_weight`, `risk_based`) and a `--max-positions` cap.
   - Ensure cash never goes negative; reject or defer orders as needed.
2. **Strategy Selection and Signal Generation**
   - Load buy selectors from `configs.json` with class, alias, activation flag, and params.
   - Support the six built-in selectors from `Selector.py` without code changes.
   - Load sell strategy definition by name from `configs/sell_strategies.json`.
   - Support composite sell strategies that combine multiple exit rules.
   - Allow multiple buy selectors to run in the same backtest and tag trades by selector.
3. **Configuration and CLI Controls**
   - Provide a single CLI entry point (`scripts/run_backtest.py`) for backtest execution.
   - Allow overrides for date range, capital, position sizing, costs, and output path.
   - Validate configuration files and surface clear errors when missing or invalid.
4. **Results and Reporting**
   - Print a performance report including returns, drawdown, and risk ratios.
   - Generate equity curve and trade history data for analysis.
   - Optionally persist results to JSON via `--save-results`.
   - Include run metadata (date range, strategy, capital, config counts) in results.
5. **Extensibility**
   - New buy selectors can be added by implementing a class in `Selector.py`
     and registering parameters in `configs.json`.
   - New sell strategies can be added in `backtest/sell_strategies/`
     and referenced in `configs/sell_strategies.json`.

## Non-Functional Requirements
- **Accuracy**: No future data leakage; strict date-based iteration.
- **Performance**: Handle multi-year backtests with reasonable runtime.
- **Extensibility**: New selectors/strategies can be added without rewriting core engine.
- **Usability**: Clear CLI entry points and readable reports.
- **Reliability**: Prevent negative cash balances; validate order constraints.

## Data Requirements
- Historical daily data with fields: `date, open, close, high, low, volume`.
- Data sourced from Tushare (qfq daily K-line).
- Stock universe provided via `stocklist.csv`.

## Core Components (High-Level)
- **Backtest Engine**: Main event loop, signal evaluation, order processing.
- **Portfolio Manager**: Positions, cash, T+1 settlement, position sizing.
- **Execution Engine**: Price limit checks and transaction cost model.
- **Selectors**: Buy signal generation.
- **Sell Strategies**: Exit logic (modular and composable).
- **Performance Analyzer**: Returns, risk metrics, and trade statistics.

## Metrics for Success
- Strategy comparisons produce consistent, repeatable results.
- Backtests complete without errors on standard data ranges.
- Easy addition of new selector/strategy with minimal code changes.
- Users can identify top-performing strategy combinations.

## Risks and Mitigations
- **Data quality**: Missing or inconsistent data can skew results.
  - Mitigation: Validate inputs and fail fast on missing fields.
- **Simulation realism**: Over-simplified execution can inflate results.
  - Mitigation: Use T+1 settlement, price limits, transaction costs.
- **Overfitting**: Users may optimize too heavily on past data.
  - Mitigation: Encourage out-of-sample testing and walk-forward runs.

## Future Enhancements
- Multi-asset support or additional markets.
- Strategy grid search and automated comparison reports.
- Visualization dashboards for equity curves and distributions.
- Portfolio-level constraints (sector/position limits).

## Technical Architecture
### Directory Map
- `backtest/` Core backtest modules (engine, portfolio, execution, performance).
- `backtest/sell_strategies/` Modular sell strategy implementations.
- `scripts/` CLI entry points (e.g., `run_backtest.py`).
- `configs/` Backtest configuration and sell strategy presets.
- `data/` Historical OHLCV CSV files per symbol (input).
- `backtest_results/` Saved backtest outputs (JSON results).
- `backend/` Service-side code (not used in backtest CLI flow).
- `frontend/` UI code (not used in backtest CLI flow).
- `test_data/` Sample datasets for testing.
- `Selector.py` Buy selector implementations.
- `configs.json` Buy selector configuration (activation and params).
- `fetch_kline.py` Data acquisition script (Tushare OHLCV download).
- `select_stock.py` Standalone selector runner (non-backtest workflow).

### Processing Logic
1. **Data Preparation**
   - `fetch_kline.py` reads `stocklist.csv` and writes CSVs into `./data/`.
2. **Backtest Setup**
   - `scripts/run_backtest.py` parses CLI args and loads:
     - Buy selector config from `./configs.json`
     - Sell strategy config from `./configs/sell_strategies.json`
3. **Engine Execution**
   - `BacktestEngine.load_data()` loads OHLCV CSVs from `--data-dir`.
   - `BacktestEngine.load_buy_selectors()` instantiates active selectors.
   - `BacktestEngine.load_sell_strategy()` builds the configured exit strategy.
   - `BacktestEngine.run()` iterates dates, generates signals, and submits orders.
4. **Order Execution and Portfolio Updates**
   - `ExecutionEngine` applies T+1 settlement, price limits, and costs.
   - `PortfolioManager` updates positions, cash, equity curve, and trades.
5. **Analysis and Output**
   - `PerformanceAnalyzer` computes metrics and prints the report.
   - Results and metadata are saved to JSON if `--save-results` is set.

### Inputs
- `./data/*.csv` Historical OHLCV per symbol (required for backtests).
- `./configs.json` Buy selector activation and parameter settings.
- `./configs/sell_strategies.json` Sell strategy presets and parameters.
- `./stocklist.csv` Symbol universe for data download (used by `fetch_kline.py`).
- CLI arguments: date range, capital, costs, sizing, strategy selection.

### Outputs
- Console performance report and logs (default).
- `./backtest_results/*.json` Full results when `--save-results` is used.
- Equity curve and trade history included in results payload.
