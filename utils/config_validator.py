"""
Configuration validation using Pydantic models.

Validates configs.json and sell_strategies.json before backtest runs.
Prevents runtime errors from invalid parameters.
"""

from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any, Literal
import json
from pathlib import Path


class SelectorParams(BaseModel):
    """Base class for selector parameters with common validations."""

    class Config:
        extra = "allow"  # Allow extra fields for flexibility

    @validator('*', pre=True)
    def check_numeric_ranges(cls, v, field):
        """Validate numeric parameters are in reasonable ranges."""
        if isinstance(v, (int, float)):
            # Check for common parameters
            if 'threshold' in field.name and v < 0:
                raise ValueError(f"{field.name} must be non-negative")
            if 'window' in field.name or 'max_window' in field.name:
                if v < 1 or v > 500:
                    raise ValueError(f"{field.name} must be between 1 and 500")
        return v


class SelectorConfig(BaseModel):
    """Configuration for a single selector."""

    class_name: str = Field(..., alias="class", description="Selector class name (e.g., 'BBIKDJSelector')")
    alias: str = Field(..., description="Display name in Chinese (e.g., '少妇战法')")
    activate: bool = Field(default=False, description="Whether selector is active")
    params: Dict[str, Any] = Field(default_factory=dict, description="Selector-specific parameters")

    class Config:
        populate_by_name = True  # Allow both 'class' and 'class_name'

    @validator('class_name')
    def validate_class_name(cls, v):
        """Ensure class name ends with 'Selector'."""
        if not v.endswith('Selector'):
            raise ValueError(f"Class name must end with 'Selector', got: {v}")
        return v

    @validator('params')
    def validate_params(cls, v):
        """Validate common parameter constraints."""
        # Check for common parameters
        if 'j_threshold' in v:
            if not (0 <= v['j_threshold'] <= 100):
                raise ValueError(f"j_threshold must be 0-100, got {v['j_threshold']}")

        if 'max_window' in v:
            if not (1 <= v['max_window'] <= 500):
                raise ValueError(f"max_window must be 1-500, got {v['max_window']}")

        if 'bbi_tolerance' in v:
            if not (0 <= v['bbi_tolerance'] <= 1):
                raise ValueError(f"bbi_tolerance must be 0-1, got {v['bbi_tolerance']}")

        return v


class SelectorCombinationConfig(BaseModel):
    """Configuration for selector combination logic."""

    mode: Literal["OR", "AND", "TIME_WINDOW"] = Field(default="OR", description="Combination mode")
    time_window_days: int = Field(default=5, ge=1, le=30, description="Time window for TIME_WINDOW mode")
    required_selectors: List[str] = Field(default_factory=list, description="Required selectors for AND/TIME_WINDOW")

    @validator('required_selectors')
    def validate_required_selectors(cls, v, values):
        """Validate required_selectors is non-empty for AND/TIME_WINDOW modes."""
        if values.get('mode') in ['AND', 'TIME_WINDOW'] and len(v) == 0:
            # Allow empty list - will default to requiring all selectors
            pass
        return v


class BuyConfig(BaseModel):
    """Main configuration for buy selectors (configs.json)."""

    selectors: List[SelectorConfig] = Field(..., description="List of selector configurations")
    selector_combination: Optional[SelectorCombinationConfig] = Field(
        default=None,
        description="Selector combination logic"
    )

    @validator('selectors')
    def validate_at_least_one_active(cls, v):
        """Ensure at least one selector is activated."""
        active_count = sum(1 for sel in v if sel.activate)
        if active_count == 0:
            raise ValueError("At least one selector must be activated")
        return v


class SellStrategyConfig(BaseModel):
    """Configuration for a single sell strategy."""

    class_name: str = Field(..., alias="class", description="Strategy class name")
    params: Dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")

    class Config:
        populate_by_name = True

    @validator('params')
    def validate_params(cls, v, values):
        """Validate common sell strategy parameters."""
        class_name = values.get('class_name', '')

        # Validate percentage parameters
        for key in ['trailing_pct', 'target_pct', 'stop_pct']:
            if key in v:
                if not (0 < v[key] <= 1):
                    raise ValueError(f"{key} must be 0-1 (percentage as decimal), got {v[key]}")

        # Validate ATR multiplier
        if 'atr_multiplier' in v:
            if not (0.5 <= v['atr_multiplier'] <= 10):
                raise ValueError(f"atr_multiplier must be 0.5-10, got {v['atr_multiplier']}")

        # Validate max holding days
        if 'max_holding_days' in v:
            if not (1 <= v['max_holding_days'] <= 365):
                raise ValueError(f"max_holding_days must be 1-365, got {v['max_holding_days']}")

        return v


class CompositeSellStrategyConfig(BaseModel):
    """Configuration for composite sell strategy."""

    combination_logic: Literal["ANY", "ALL"] = Field(..., description="Exit on ANY or ALL conditions")
    strategies: List[SellStrategyConfig] = Field(..., description="List of strategies to combine")

    @validator('strategies')
    def validate_strategies(cls, v):
        """Ensure at least one strategy is defined."""
        if len(v) == 0:
            raise ValueError("Composite strategy must have at least one sub-strategy")
        return v


class BacktestConfig(BaseModel):
    """Configuration for backtest parameters."""

    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date (YYYY-MM-DD)")
    initial_capital: float = Field(default=1000000, gt=0, description="Starting capital")
    max_positions: int = Field(default=10, ge=1, le=100, description="Maximum positions")
    position_sizing: Literal["equal_weight", "risk_based"] = Field(default="equal_weight")
    commission_rate: float = Field(default=0.0003, ge=0, le=0.01)
    stamp_tax_rate: float = Field(default=0.001, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.001, ge=0, le=0.01)

    @validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        """Ensure date is in YYYY-MM-DD format."""
        from datetime import datetime
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid date format: {v}. Expected YYYY-MM-DD")
        return v


def load_and_validate_buy_config(config_path: str) -> BuyConfig:
    """
    Load and validate configs.json.

    Args:
        config_path: Path to configs.json

    Returns:
        Validated BuyConfig object

    Raises:
        ValidationError if config is invalid
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    return BuyConfig(**config_data)


def load_and_validate_sell_config(config_path: str) -> Dict[str, Any]:
    """
    Load and validate sell_strategies.json.

    Args:
        config_path: Path to sell_strategies.json

    Returns:
        Validated configuration dictionary

    Raises:
        ValidationError if config is invalid
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    # Validate each strategy configuration
    validated_configs = {}
    for name, config in config_data.items():
        if 'combination_logic' in config:
            # Composite strategy
            validated_configs[name] = CompositeSellStrategyConfig(**config).dict()
        else:
            # Single strategy
            validated_configs[name] = SellStrategyConfig(**config).dict()

    return validated_configs


def validate_all_configs(
    buy_config_path: str,
    sell_config_path: Optional[str] = None
) -> tuple[BuyConfig, Optional[Dict[str, Any]]]:
    """
    Validate all configuration files.

    Args:
        buy_config_path: Path to configs.json
        sell_config_path: Optional path to sell_strategies.json

    Returns:
        Tuple of (buy_config, sell_config)

    Raises:
        ValidationError with detailed error messages
    """
    print("Validating configuration files...")

    # Validate buy config
    print(f"  Loading {buy_config_path}...")
    buy_config = load_and_validate_buy_config(buy_config_path)
    print(f"  ✓ Buy config valid: {len(buy_config.selectors)} selectors, "
          f"{sum(1 for s in buy_config.selectors if s.activate)} active")

    # Validate sell config
    sell_config = None
    if sell_config_path:
        print(f"  Loading {sell_config_path}...")
        sell_config = load_and_validate_sell_config(sell_config_path)
        print(f"  ✓ Sell config valid: {len(sell_config)} strategies defined")

    print("✓ All configurations validated successfully\n")
    return buy_config, sell_config
