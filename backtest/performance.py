"""
Performance analysis module.

Calculates comprehensive metrics for backtest results.
"""

from typing import Dict, List, Any
import pandas as pd
import numpy as np
from datetime import datetime


class PerformanceAnalyzer:
    """
    Analyzes backtest performance and generates comprehensive metrics.

    Metrics calculated:
    - Returns: Total return, annualized return, monthly/yearly breakdown
    - Risk-Adjusted: Sharpe ratio, Sortino ratio, Calmar ratio
    - Drawdown: Max drawdown, max drawdown duration
    - Trade Stats: Win rate, profit factor, avg win/loss, avg holding days
    - Distribution: Returns histogram, exit reason breakdown, by buy strategy
    """

    def __init__(
        self,
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        initial_capital: float,
        risk_free_rate: float = 0.03
    ):
        """
        Initialize analyzer.

        Args:
            equity_curve: DataFrame with columns [date, total_value, ...]
            trades: DataFrame with trade history
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate (default 3%)
        """
        self.equity_curve = equity_curve
        self.trades = trades
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate

    def analyze(self) -> Dict[str, Any]:
        """
        Run complete analysis.

        Returns:
            Dictionary with all metrics
        """
        results = {}

        # Return metrics
        results['returns'] = self._calculate_returns()

        # Risk-adjusted metrics
        results['risk_adjusted'] = self._calculate_risk_adjusted_metrics()

        # Drawdown metrics
        results['drawdown'] = self._calculate_drawdown_metrics()

        # Trade statistics
        results['trade_stats'] = self._calculate_trade_stats()

        # Distribution analysis
        results['distributions'] = self._calculate_distributions()

        # Summary
        results['summary'] = self._generate_summary(results)

        return results

    def _calculate_returns(self) -> Dict[str, Any]:
        """Calculate return metrics."""
        if len(self.equity_curve) == 0:
            return {}

        final_value = self.equity_curve['total_value'].iloc[-1]
        total_return = (final_value - self.initial_capital) / self.initial_capital

        # Annualized return
        start_date = pd.to_datetime(self.equity_curve['date'].iloc[0])
        end_date = pd.to_datetime(self.equity_curve['date'].iloc[-1])
        days = (end_date - start_date).days

        if days > 0:
            years = days / 365.25
            annualized_return = (1 + total_return) ** (1 / years) - 1
        else:
            annualized_return = 0.0

        # Monthly returns
        equity = self.equity_curve.copy()
        equity['date'] = pd.to_datetime(equity['date'])
        equity['year_month'] = equity['date'].dt.to_period('M')

        monthly_returns = equity.groupby('year_month').agg({
            'total_value': ['first', 'last']
        })

        monthly_returns.columns = ['start_value', 'end_value']
        monthly_returns['return'] = (
            (monthly_returns['end_value'] - monthly_returns['start_value']) /
            monthly_returns['start_value']
        )

        monthly_returns_dict = {
            str(k): float(v)
            for k, v in monthly_returns['return'].to_dict().items()
        } if not monthly_returns.empty else {}

        return {
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'annualized_return': annualized_return,
            'annualized_return_pct': annualized_return * 100,
            'final_value': final_value,
            'total_profit': final_value - self.initial_capital,
            'trading_days': len(self.equity_curve),
            'calendar_days': days,
            'monthly_returns': monthly_returns_dict
        }

    def _calculate_risk_adjusted_metrics(self) -> Dict[str, Any]:
        """Calculate risk-adjusted metrics."""
        if len(self.equity_curve) < 2:
            return {}

        # Calculate daily returns
        equity = self.equity_curve.copy()
        equity['daily_return'] = equity['total_value'].pct_change()

        # Drop NaN
        daily_returns = equity['daily_return'].dropna()

        if len(daily_returns) == 0:
            return {}

        # Mean and std of daily returns
        mean_daily_return = daily_returns.mean()
        std_daily_return = daily_returns.std()

        # Sharpe ratio (annualized)
        if std_daily_return > 0:
            daily_rf = self.risk_free_rate / 252  # Daily risk-free rate
            sharpe_ratio = (mean_daily_return - daily_rf) / std_daily_return * np.sqrt(252)
        else:
            sharpe_ratio = 0.0

        # Sortino ratio (uses downside deviation)
        negative_returns = daily_returns[daily_returns < 0]

        if len(negative_returns) > 0:
            downside_std = negative_returns.std()
            if downside_std > 0:
                sortino_ratio = (mean_daily_return - daily_rf) / downside_std * np.sqrt(252)
            else:
                sortino_ratio = 0.0
        else:
            sortino_ratio = 0.0

        # Max drawdown (for Calmar ratio)
        max_dd = self._calculate_max_drawdown()

        # Calmar ratio = annualized_return / abs(max_drawdown)
        if max_dd['max_drawdown_pct'] != 0:
            returns = self._calculate_returns()
            calmar_ratio = returns['annualized_return'] / abs(max_dd['max_drawdown_pct'] / 100)
        else:
            calmar_ratio = 0.0

        return {
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'calmar_ratio': calmar_ratio,
            'mean_daily_return_pct': mean_daily_return * 100,
            'std_daily_return_pct': std_daily_return * 100,
            'downside_deviation_pct': negative_returns.std() * 100 if len(negative_returns) > 0 else 0.0
        }

    def _calculate_drawdown_metrics(self) -> Dict[str, Any]:
        """Calculate drawdown metrics."""
        max_dd = self._calculate_max_drawdown()

        # Calculate drawdown duration
        equity = self.equity_curve.copy()
        equity['cummax'] = equity['total_value'].cummax()
        equity['drawdown'] = (equity['total_value'] - equity['cummax']) / equity['cummax']

        # Find drawdown periods
        in_drawdown = equity['drawdown'] < 0
        drawdown_periods = []
        current_period_length = 0

        for is_dd in in_drawdown:
            if is_dd:
                current_period_length += 1
            else:
                if current_period_length > 0:
                    drawdown_periods.append(current_period_length)
                current_period_length = 0

        if current_period_length > 0:
            drawdown_periods.append(current_period_length)

        max_dd_duration = max(drawdown_periods) if drawdown_periods else 0
        avg_dd_duration = np.mean(drawdown_periods) if drawdown_periods else 0

        return {
            **max_dd,
            'max_drawdown_duration_days': max_dd_duration,
            'avg_drawdown_duration_days': avg_dd_duration,
            'num_drawdown_periods': len(drawdown_periods)
        }

    def _calculate_max_drawdown(self) -> Dict[str, Any]:
        """Calculate maximum drawdown."""
        if len(self.equity_curve) == 0:
            return {'max_drawdown': 0, 'max_drawdown_pct': 0}

        equity = self.equity_curve.copy()
        equity['cummax'] = equity['total_value'].cummax()
        equity['drawdown'] = equity['total_value'] - equity['cummax']
        equity['drawdown_pct'] = equity['drawdown'] / equity['cummax'] * 100

        max_dd_idx = equity['drawdown'].idxmin()
        max_dd = equity.loc[max_dd_idx, 'drawdown']
        max_dd_pct = equity.loc[max_dd_idx, 'drawdown_pct']

        # Find peak before max drawdown
        peak_idx = equity.loc[:max_dd_idx, 'total_value'].idxmax()

        return {
            'max_drawdown': max_dd,
            'max_drawdown_pct': max_dd_pct,
            'max_drawdown_date': str(equity.loc[max_dd_idx, 'date']),
            'peak_date': str(equity.loc[peak_idx, 'date']) if peak_idx in equity.index else None
        }

    def _calculate_trade_stats(self) -> Dict[str, Any]:
        """Calculate trade statistics."""
        if len(self.trades) == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0
            }

        trades = self.trades.copy()

        # Winning and losing trades
        winning_trades = trades[trades['net_pnl'] > 0]
        losing_trades = trades[trades['net_pnl'] < 0]
        breakeven_trades = trades[trades['net_pnl'] == 0]

        total_trades = len(trades)
        num_winners = len(winning_trades)
        num_losers = len(losing_trades)

        # Win rate
        win_rate = num_winners / total_trades if total_trades > 0 else 0.0

        # Average win/loss
        avg_win = winning_trades['net_pnl'].mean() if num_winners > 0 else 0.0
        avg_loss = losing_trades['net_pnl'].mean() if num_losers > 0 else 0.0

        # Profit factor = gross_profit / abs(gross_loss)
        gross_profit = winning_trades['net_pnl'].sum() if num_winners > 0 else 0.0
        gross_loss = abs(losing_trades['net_pnl'].sum()) if num_losers > 0 else 0.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Holding period
        avg_holding_days = trades['holding_days'].mean() if total_trades > 0 else 0.0

        # Best and worst trades
        best_trade_pnl_pct = trades['net_pnl_pct'].max() if total_trades > 0 else 0.0
        worst_trade_pnl_pct = trades['net_pnl_pct'].min() if total_trades > 0 else 0.0

        return {
            'total_trades': total_trades,
            'winning_trades': num_winners,
            'losing_trades': num_losers,
            'breakeven_trades': len(breakeven_trades),
            'win_rate': win_rate,
            'win_rate_pct': win_rate * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_win_pct': winning_trades['net_pnl_pct'].mean() if num_winners > 0 else 0.0,
            'avg_loss_pct': losing_trades['net_pnl_pct'].mean() if num_losers > 0 else 0.0,
            'profit_factor': profit_factor,
            'gross_profit': gross_profit,
            'gross_loss': -gross_loss,
            'avg_holding_days': avg_holding_days,
            'best_trade_pct': best_trade_pnl_pct,
            'worst_trade_pct': worst_trade_pnl_pct
        }

    def _calculate_distributions(self) -> Dict[str, Any]:
        """Calculate distribution statistics."""
        if len(self.trades) == 0:
            return {}

        trades = self.trades.copy()

        # Exit reason distribution
        exit_reasons = trades['exit_reason'].value_counts().to_dict()

        # Buy strategy distribution
        buy_strategies = trades['buy_strategy'].value_counts().to_dict()

        # Return distribution (histogram bins)
        returns_pct = trades['net_pnl_pct']
        bins = [-float('inf'), -20, -10, -5, 0, 5, 10, 20, float('inf')]
        bin_labels = ['<-20%', '-20% to -10%', '-10% to -5%', '-5% to 0%',
                     '0% to 5%', '5% to 10%', '10% to 20%', '>20%']

        returns_hist = pd.cut(returns_pct, bins=bins, labels=bin_labels).value_counts().to_dict()

        # Holding period distribution
        holding_bins = [0, 5, 10, 20, 30, 60, float('inf')]
        holding_labels = ['0-5d', '6-10d', '11-20d', '21-30d', '31-60d', '>60d']

        holding_hist = pd.cut(
            trades['holding_days'],
            bins=holding_bins,
            labels=holding_labels
        ).value_counts().to_dict()

        return {
            'exit_reasons': exit_reasons,
            'buy_strategies': buy_strategies,
            'returns_histogram': {str(k): v for k, v in returns_hist.items()},
            'holding_period_histogram': {str(k): v for k, v in holding_hist.items()}
        }

    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary of key metrics."""
        summary = {
            'initial_capital': self.initial_capital,
            'final_value': results['returns'].get('final_value', 0),
            'total_return_pct': results['returns'].get('total_return_pct', 0),
            'annualized_return_pct': results['returns'].get('annualized_return_pct', 0),
            'sharpe_ratio': results['risk_adjusted'].get('sharpe_ratio', 0),
            'sortino_ratio': results['risk_adjusted'].get('sortino_ratio', 0),
            'calmar_ratio': results['risk_adjusted'].get('calmar_ratio', 0),
            'max_drawdown_pct': results['drawdown'].get('max_drawdown_pct', 0),
            'total_trades': results['trade_stats'].get('total_trades', 0),
            'win_rate_pct': results['trade_stats'].get('win_rate_pct', 0),
            'profit_factor': results['trade_stats'].get('profit_factor', 0),
            'avg_holding_days': results['trade_stats'].get('avg_holding_days', 0)
        }

        return summary

    def print_report(self):
        """Print formatted performance report."""
        results = self.analyze()

        print("\n" + "="*80)
        print("PERFORMANCE REPORT")
        print("="*80)

        # Returns
        print("\n--- RETURNS ---")
        print(f"Initial Capital:       {self.initial_capital:>15,.0f}")
        print(f"Final Value:           {results['returns']['final_value']:>15,.0f}")
        print(f"Total Return:          {results['returns']['total_return_pct']:>14.2f}%")
        print(f"Annualized Return:     {results['returns']['annualized_return_pct']:>14.2f}%")
        print(f"Total Profit:          {results['returns']['total_profit']:>15,.0f}")

        # Risk-Adjusted
        print("\n--- RISK-ADJUSTED METRICS ---")
        print(f"Sharpe Ratio:          {results['risk_adjusted']['sharpe_ratio']:>15.2f}")
        print(f"Sortino Ratio:         {results['risk_adjusted']['sortino_ratio']:>15.2f}")
        print(f"Calmar Ratio:          {results['risk_adjusted']['calmar_ratio']:>15.2f}")

        # Drawdown
        print("\n--- DRAWDOWN ---")
        print(f"Max Drawdown:          {results['drawdown']['max_drawdown_pct']:>14.2f}%")
        print(f"Max DD Duration:       {results['drawdown']['max_drawdown_duration_days']:>11.0f} days")

        # Trade Stats
        print("\n--- TRADE STATISTICS ---")
        print(f"Total Trades:          {results['trade_stats']['total_trades']:>15}")

        if results['trade_stats']['total_trades'] > 0:
            print(f"Winning Trades:        {results['trade_stats']['winning_trades']:>15}")
            print(f"Losing Trades:         {results['trade_stats']['losing_trades']:>15}")
            print(f"Win Rate:              {results['trade_stats']['win_rate_pct']:>14.2f}%")
            print(f"Profit Factor:         {results['trade_stats']['profit_factor']:>15.2f}")
            print(f"Avg Win:               {results['trade_stats']['avg_win']:>15,.0f}")
            print(f"Avg Loss:              {results['trade_stats']['avg_loss']:>15,.0f}")
            print(f"Avg Holding Days:      {results['trade_stats']['avg_holding_days']:>15.1f}")
            print(f"Best Trade:            {results['trade_stats']['best_trade_pct']:>14.2f}%")
            print(f"Worst Trade:           {results['trade_stats']['worst_trade_pct']:>14.2f}%")
        else:
            print("  (No completed trades)")

        # Exit Reasons
        if 'exit_reasons' in results.get('distributions', {}):
            print("\n--- EXIT REASONS ---")
            for reason, count in sorted(
                results['distributions']['exit_reasons'].items(),
                key=lambda x: x[1],
                reverse=True
            ):
                print(f"  {reason[:50]:50} {count:>5}")

        print("\n" + "="*80)
