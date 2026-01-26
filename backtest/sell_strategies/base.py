"""
Base classes for sell strategies.

Defines abstract SellStrategy class and composite pattern for combining strategies.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, List, Tuple
import pandas as pd

from ..data_structures import Position


class SellStrategy(ABC):
    """
    Abstract base class for sell strategies.

    All sell strategies must implement should_sell() method.
    """

    def __init__(self, **params):
        """
        Initialize strategy with parameters.

        Args:
            **params: Strategy-specific parameters
        """
        self.params = params

    @abstractmethod
    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """
        Determine if position should be sold.

        CRITICAL: Only use data up to current_date to prevent lookahead bias.

        Args:
            position: Current position
            current_date: Current date
            current_data: Current day's OHLCV data
            hist_data: Historical data up to current_date (inclusive)

        Returns:
            (should_sell, reason) tuple
        """
        pass

    def get_name(self) -> str:
        """Get strategy name."""
        return self.__class__.__name__


class CompositeSellStrategy(SellStrategy):
    """
    Composite sell strategy combining multiple strategies.

    Can use AND (all must trigger) or OR (any can trigger) logic.
    """

    def __init__(self, strategies: List[SellStrategy], combination_logic: str = "ANY", **params):
        """
        Initialize composite strategy.

        Args:
            strategies: List of sell strategies
            combination_logic: "ANY" (OR) or "ALL" (AND)
            **params: Additional parameters
        """
        super().__init__(**params)
        self.strategies = strategies
        self.combination_logic = combination_logic.upper()

        if self.combination_logic not in ["ANY", "ALL"]:
            raise ValueError(f"Invalid combination_logic: {combination_logic}. Must be 'ANY' or 'ALL'")

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """
        Check all strategies and combine results.

        Args:
            position: Current position
            current_date: Current date
            current_data: Current day's data
            hist_data: Historical data up to current_date

        Returns:
            (should_sell, reason) tuple
        """
        results = []

        for strategy in self.strategies:
            try:
                should_sell, reason = strategy.should_sell(
                    position, current_date, current_data, hist_data
                )
                results.append((should_sell, reason, strategy.get_name()))
            except Exception as e:
                # Log error but continue
                results.append((False, f"Error: {e}", strategy.get_name()))

        if self.combination_logic == "ANY":
            # OR logic: sell if any strategy triggers
            for should_sell, reason, strategy_name in results:
                if should_sell:
                    return True, f"{strategy_name}: {reason}"
            return False, ""

        else:  # ALL
            # AND logic: sell only if all strategies trigger
            if all(result[0] for result in results):
                reasons = [f"{name}: {reason}" for _, reason, name in results if reason]
                combined_reason = " AND ".join(reasons)
                return True, combined_reason
            return False, ""

    def get_name(self) -> str:
        """Get composite strategy name."""
        strategy_names = [s.get_name() for s in self.strategies]
        logic = " OR " if self.combination_logic == "ANY" else " AND "
        return f"Composite({logic.join(strategy_names)})"


class SimpleHoldStrategy(SellStrategy):
    """
    Simple hold strategy - never sells (for testing).

    Useful for buy-and-hold baseline comparison.
    """

    def should_sell(
        self,
        position: Position,
        current_date: datetime,
        current_data: pd.Series,
        hist_data: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Never sell."""
        return False, ""

    def get_name(self) -> str:
        return "HoldForever"


def create_sell_strategy(config: Dict[str, Any]) -> SellStrategy:
    """
    Factory function to create sell strategy from configuration.

    Args:
        config: Strategy configuration dict with 'class' or 'combination_logic' key

    Returns:
        SellStrategy instance

    Examples:
        Simple strategy:
        {
            "class": "PercentageTrailingStopStrategy",
            "params": {"trailing_pct": 0.08}
        }

        Composite strategy:
        {
            "name": "conservative",
            "combination_logic": "ANY",
            "strategies": [
                {"class": "PercentageTrailingStopStrategy", "params": {...}},
                {"class": "FixedProfitTargetStrategy", "params": {...}}
            ]
        }
    """
    # Check if composite strategy
    if "combination_logic" in config or "strategies" in config:
        return _create_composite_strategy(config)

    # Simple strategy
    class_name = config.get('class')
    params = config.get('params', {})

    if class_name is None:
        # Default to SimpleHoldStrategy for testing
        return SimpleHoldStrategy()

    # Import strategy class dynamically
    strategy_class = _import_strategy_class(class_name)
    return strategy_class(**params)


def _create_composite_strategy(config: Dict[str, Any]) -> CompositeSellStrategy:
    """Create composite strategy from configuration."""
    strategies = []

    for strategy_config in config.get('strategies', []):
        strategy = create_sell_strategy(strategy_config)
        strategies.append(strategy)

    combination_logic = config.get('combination_logic', 'ANY')

    return CompositeSellStrategy(
        strategies=strategies,
        combination_logic=combination_logic
    )


def _import_strategy_class(class_name: str):
    """
    Dynamically import strategy class.

    Args:
        class_name: Name of strategy class

    Returns:
        Strategy class
    """
    # Map of class names to modules
    module_map = {
        'SimpleHoldStrategy': 'backtest.sell_strategies.base',
        'PercentageTrailingStopStrategy': 'backtest.sell_strategies.trailing_stops',
        'ATRTrailingStopStrategy': 'backtest.sell_strategies.trailing_stops',
        'ChandelierStopStrategy': 'backtest.sell_strategies.trailing_stops',
        'FixedProfitTargetStrategy': 'backtest.sell_strategies.profit_targets',
        'MultipleRExitStrategy': 'backtest.sell_strategies.profit_targets',
        'TimedExitStrategy': 'backtest.sell_strategies.time_based',
        'KDJOverboughtExitStrategy': 'backtest.sell_strategies.indicator_exits',
        'BBIReversalExitStrategy': 'backtest.sell_strategies.indicator_exits',
        'ZXLinesCrossDownExitStrategy': 'backtest.sell_strategies.indicator_exits',
        'MADeathCrossExitStrategy': 'backtest.sell_strategies.indicator_exits',
        'VolumeDryUpExitStrategy': 'backtest.sell_strategies.volume_exits',
        'AdaptiveVolatilityExitStrategy': 'backtest.sell_strategies.adaptive',
    }

    module_name = module_map.get(class_name)

    if module_name is None:
        raise ValueError(f"Unknown strategy class: {class_name}")

    # Import module
    import importlib
    module = importlib.import_module(module_name)

    # Get class
    strategy_class = getattr(module, class_name)

    return strategy_class
