#!/usr/bin/env python
"""
Test individual selectors to diagnose signal generation issues.

Usage:
    python scripts/test_selectors.py

This script:
1. Loads all activated selectors from configs.json
2. Tests each selector individually with a DB-backed data dict
3. Reports which selectors are working and which are failing

Data is loaded from indicators.db in a SINGLE bulk query (preload_all),
then cached in memory. Subsequent selector runs hit the in-memory cache only.
"""

import sys
import json
from pathlib import Path
import inspect
import pandas as pd
import time
from datetime import timedelta

# Add parent directory to path to import Selector module
sys.path.insert(0, str(Path(__file__).parent.parent))
import backtest.Selector as Selector
from backtest.indicator_store import IndicatorStore


# --------------------------------------------------------------------------- #
# Bulk-preloaded data dict                                                      #
# --------------------------------------------------------------------------- #

class LazyIndicatorData:
    """
    dict-like 容器，支持两种模式：
    - preload_all() 调用后：所有数据已在内存中，访问 O(1)
    - 未调用时：仍可按需懒加载单只股票（fallback）

    实现了完整的 dict 协议，兼容所有 Selector 的 select(date, data) 调用。
    """

    def __init__(self, store: IndicatorStore, start_date: str, end_date: str):
        self._store = store
        self._start = start_date
        self._end = end_date
        self._cache: dict[str, pd.DataFrame] = {}
        self._all_codes: list[str] = store.get_all_codes()
        self._code_set: set[str] = set(self._all_codes)
        self._preloaded = False

    # ------------------------------------------------------------------ #
    # 核心优化：单条 SQL 批量加载所有股票                                   #
    # ------------------------------------------------------------------ #

    def preload_all(self):
        """
        用一条查询把所有股票在 [start_date, end_date] 内的数据全部取出，
        按 code 分组存入缓存。

        DuckDB 版：调用 IndicatorStore.load_all()，底层使用 Arrow 格式直接
        输出 DataFrame，跳过 Python 对象层，比原来的 pd.read_sql_query 快 5-10 倍。
        """
        print(f"  正在执行批量查询 (DuckDB，日期范围 {self._start} ~ {self._end})...")
        t0 = time.time()

        # 通过 IndicatorStore 封装的方法读取，不直接操作 conn
        df_all = self._store.load_all(self._start, self._end)

        if df_all.empty:
            print("  ⚠ 查询结果为空，请检查日期范围或数据库内容")
            self._preloaded = True
            return

        # date 列已在 load_all() 内部转换为 datetime，无需重复转换

        # 按 code 分组，存入缓存
        for code, group in df_all.groupby("code", sort=False):
            self._cache[code] = group.reset_index(drop=True)

        elapsed = time.time() - t0
        print(f"  ✓ 批量加载完成：{len(self._cache)} 只股票，耗时 {elapsed:.2f}s")
        self._preloaded = True

    # ------------------------------------------------------------------ #
    # 单只懒加载（fallback，preload_all 后基本不会走到这里）               #
    # ------------------------------------------------------------------ #

    def _fetch(self, code: str) -> pd.DataFrame:
        if code not in self._cache:
            df = self._store.get_indicators(code, start_date=self._start, end_date=self._end)
            self._cache[code] = df
        return self._cache[code]

    # ------------------------------------------------------------------ #
    # dict 协议
    # ------------------------------------------------------------------ #

    def __getitem__(self, code: str) -> pd.DataFrame:
        if code not in self._code_set:
            raise KeyError(code)
        return self._fetch(code)

    def __contains__(self, code: object) -> bool:
        return code in self._code_set

    def __len__(self) -> int:
        return len(self._all_codes)

    def __iter__(self):
        return iter(self._all_codes)

    def keys(self):
        return self._all_codes

    def items(self):
        for code in self._all_codes:
            yield code, self._fetch(code)

    def values(self):
        for code in self._all_codes:
            yield self._fetch(code)

    def get(self, code: str, default=None):
        if code not in self._code_set:
            return default
        return self._fetch(code)

    def cache_stats(self) -> str:
        mode = "预加载" if self._preloaded else "懒加载"
        return f"[{mode}] 已缓存 {len(self._cache)}/{len(self._all_codes)} 只股票"


# --------------------------------------------------------------------------- #

def test_selector(selector_class, selector_name, params, indicator_store, test_date, data):
    """
    Test a single selector.

    Args:
        selector_class:  Selector 类
        selector_name:   展示名称
        params:          Selector 参数
        indicator_store: IndicatorStore 实例
        test_date:       测试日期 (YYYY-MM-DD)
        data:            LazyIndicatorData 实例（已预加载）
    """
    print(f"\n{'='*80}")
    print(f"Testing: {selector_name}")
    print(f"{'='*80}")

    # 创建 selector 实例
    print(f"\nCreating selector instance...")
    try:
        selector_params = params.copy()
        if 'indicator_store' in inspect.signature(selector_class.__init__).parameters:
            selector_params['indicator_store'] = indicator_store

        selector = selector_class(**selector_params)
        print(f"✓ Selector created successfully")
    except Exception as e:
        print(f"✗ ERROR creating selector: {e}")
        import traceback
        traceback.print_exc()
        return

    # 运行 selector
    print(f"\nRunning selector.select()...")
    start_time = time.time()
    try:
        selected = selector.select(pd.Timestamp(test_date), data)
        elapsed = time.time() - start_time
        print(f"✓ Selector ran successfully in {elapsed:.3f}s")
        print(f"✓ Signals generated: {len(selected)}")
        print(f"  {data.cache_stats()}")

        if len(selected) > 0:
            print(f"  Sample signals (first 10): {selected[:10]}")
        else:
            print(f"  No signals generated (this may be normal if criteria are very specific)")

    except Exception as e:
        print(f"✗ ERROR running selector: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Test all selectors from buy_selectors.json."""
    config_path = Path(__file__).parent.parent / "configs/buy_selectors.json"

    print("="*80)
    print("SELECTOR VALIDATION TEST  (bulk preload mode)")
    print("="*80)
    print(f"Config: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    test_date = "2026-01-07"
    lookback_days = 365
    db_path = Path(__file__).parent.parent / "data" / "indicators.duckdb"

    print(f"Test date:  {test_date}")
    print(f"Lookback:   {lookback_days} days")
    print(f"Database:   {db_path}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return

    store = IndicatorStore(str(db_path))

    end_ts = pd.Timestamp(test_date)
    start_date = (end_ts - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    # 创建数据容器并预加载（一条 SQL 搞定所有股票）
    print(f"\n[数据预加载]")
    data = LazyIndicatorData(store, start_date=start_date, end_date=test_date)
    data.preload_all()

    if len(data._cache) == 0:
        print("❌ 无数据，退出")
        return

    # 测试每个已激活的 selector
    activated_selectors = [s for s in config['selectors'] if s.get('activate', False)]
    print(f"\nFound {len(activated_selectors)} activated selectors")

    for selector_config in activated_selectors:
        class_name = selector_config['class']
        params = selector_config.get('params', {})
        alias = selector_config.get('alias', class_name)

        if hasattr(Selector, class_name):
            selector_class = getattr(Selector, class_name)
            test_selector(selector_class, alias, params, store, test_date, data)
        else:
            print(f"\n{'='*80}")
            print(f"Testing: {alias}")
            print(f"{'='*80}")
            print(f"✗ WARNING: {class_name} not found in Selector.py")

    print(f"\n{'='*80}")
    print("TEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()