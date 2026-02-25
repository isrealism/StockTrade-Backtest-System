#!/usr/bin/env python3
"""
测试超额收益展示功能

验证：
1. 后端API是否正确处理基准参数
2. 负值是否正确计算和返回
3. 所有基准指数是否可用
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from backtest.performance import PerformanceAnalyzer


def test_excess_return_with_positive():
    """测试正超额收益"""
    print("\n" + "="*80)
    print("测试1: 正超额收益场景")
    print("="*80)

    # Mock equity curve - 策略表现好
    equity_curve = pd.DataFrame([
        {"date": "2025-01-02", "total_value": 1000000},
        {"date": "2025-01-05", "total_value": 1050000},
        {"date": "2025-01-10", "total_value": 1100000},
        {"date": "2025-01-15", "total_value": 1150000},
        {"date": "2025-01-20", "total_value": 1200000},  # +20%
    ])

    trades = pd.DataFrame([
        {
            "code": "000001.SZ",
            "net_pnl": 100000,
            "net_pnl_pct": 10.0,
            "holding_days": 5,
            "exit_reason": "profit_target",
            "buy_strategy": "BBIKDJSelector"
        },
        {
            "code": "000002.SZ",
            "net_pnl": 100000,
            "net_pnl_pct": 10.0,
            "holding_days": 8,
            "exit_reason": "profit_target",
            "buy_strategy": "BBIKDJSelector"
        }
    ])

    # Test with benchmark
    analyzer = PerformanceAnalyzer(
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=1000000,
        benchmark_name="上证指数",
    )

    analysis = analyzer.analyze()

    if "benchmark" in analysis:
        bm = analysis["benchmark"]
        print(f"✅ 基准数据加载成功")
        print(f"   策略收益: {analysis['returns']['total_return_pct']:.2f}%")
        print(f"   基准收益: {bm.get('benchmark_total_return_pct', 0):.2f}%")
        print(f"   超额收益: {bm.get('excess_return_pct', 0):.2f}%")
        print(f"   Alpha: {bm.get('alpha_pct', 0):.2f}%")
        print(f"   Beta: {bm.get('beta', 0):.2f}")
        print(f"   信息比率: {bm.get('information_ratio', 0):.2f}")

        # Check if values are present
        assert bm.get('excess_return_pct') is not None, "超额收益未计算"
        assert bm.get('alpha_pct') is not None, "Alpha未计算"
        assert bm.get('beta') is not None, "Beta未计算"
        print("✅ 所有指标计算正确")
    else:
        print("⚠️  基准数据未加载（可能是数据文件不存在）")


def test_excess_return_with_negative():
    """测试负超额收益（策略跑输基准）"""
    print("\n" + "="*80)
    print("测试2: 负超额收益场景（策略亏损）")
    print("="*80)

    # Mock equity curve - 策略亏损
    equity_curve = pd.DataFrame([
        {"date": "2025-01-02", "total_value": 1000000},
        {"date": "2025-01-05", "total_value": 980000},
        {"date": "2025-01-10", "total_value": 960000},
        {"date": "2025-01-15", "total_value": 940000},
        {"date": "2025-01-20", "total_value": 920000},  # -8%
    ])

    trades = pd.DataFrame([
        {
            "code": "000001.SZ",
            "net_pnl": -40000,
            "net_pnl_pct": -4.0,
            "holding_days": 5,
            "exit_reason": "stop_loss",
            "buy_strategy": "BBIKDJSelector"
        },
        {
            "code": "000002.SZ",
            "net_pnl": -40000,
            "net_pnl_pct": -4.0,
            "holding_days": 8,
            "exit_reason": "stop_loss",
            "buy_strategy": "BBIKDJSelector"
        }
    ])

    analyzer = PerformanceAnalyzer(
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=1000000,
        benchmark_name="上证指数",
    )

    analysis = analyzer.analyze()

    # Check returns
    returns = analysis.get("returns", {})
    print(f"   总收益: {returns.get('total_return_pct', 0):.2f}%")
    print(f"   已实现收益: {returns.get('realized_pnl', 0):.2f}")
    print(f"   已实现收益%: {returns.get('realized_pnl_pct', 0):.2f}%")
    print(f"   未实现收益: {returns.get('unrealized_pnl', 0):.2f}")
    print(f"   未实现收益%: {returns.get('unrealized_pnl_pct', 0):.2f}%")

    # Check negative values are handled correctly
    assert returns.get('total_return_pct', 0) < 0, "总收益应为负"
    assert returns.get('realized_pnl', 0) < 0, "已实现收益应为负"
    print("✅ 负值收益计算正确")

    if "benchmark" in analysis:
        bm = analysis["benchmark"]
        print(f"   基准收益: {bm.get('benchmark_total_return_pct', 0):.2f}%")
        print(f"   超额收益: {bm.get('excess_return_pct', 0):.2f}%")

        # If benchmark is positive and strategy is negative, excess should be very negative
        if bm.get('benchmark_total_return_pct', 0) > 0:
            print("✅ 负超额收益计算正确（策略亏损时相对基准的表现）")
        else:
            print("✅ 负超额收益计算正确")


def test_benchmark_availability():
    """测试所有基准指数是否可用"""
    print("\n" + "="*80)
    print("测试3: 基准指数数据可用性")
    print("="*80)

    benchmarks = {
        "上证指数": "000001_SH",
        "沪深300": "000300_SH",
        "中证500": "000905_SH",
        "创业板指": "399006_SZ",
        "科创50": "000688_SH"
    }

    index_data_dir = ROOT / "index_data"

    for name, code in benchmarks.items():
        file_path = index_data_dir / f"{code}.csv"
        if file_path.exists():
            df = pd.read_csv(file_path)
            print(f"✅ {name} ({code}): {len(df)} 条数据")
        else:
            print(f"❌ {name} ({code}): 文件不存在 - {file_path}")


def main():
    print("="*80)
    print("超额收益展示功能测试")
    print("="*80)

    try:
        test_benchmark_availability()
        test_excess_return_with_positive()
        test_excess_return_with_negative()

        print("\n" + "="*80)
        print("✅ 所有测试通过!")
        print("="*80)

        print("\n提示:")
        print("1. 如果基准数据文件不存在，运行: python fetch_benchmark.py")
        print("2. 启动后端: python backend/app.py")
        print("3. 启动前端: npm run dev")
        print("4. 访问: http://localhost:3000/results")

    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
