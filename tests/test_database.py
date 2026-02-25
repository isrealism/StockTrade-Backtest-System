#!/usr/bin/env python3
"""
简化版数据库对比脚本

专门处理时间戳vs字符串格式的差异，只对比关键指标列
"""

import sqlite3
import pandas as pd
import numpy as np


# 读取原版数据（旧版，字符串日期）
conn1 = sqlite3.connect('./data/indicators_backup.db')
df1 = pd.read_sql("SELECT * FROM indicators WHERE code='000001'", conn1)
conn1.close()

# 读取改进版数据（新版，时间戳日期）
conn2 = sqlite3.connect('./data/indicators_test.db')
df2 = pd.read_sql("SELECT * FROM indicators WHERE code='000001'", conn2)
conn2.close()

print(f"{'='*70}")
print(f"数据行数对比")
print(f"{'='*70}")
print(f"旧版 (indicators_backup.db):  {len(df1)} 行")
print(f"新版 (indicators_test.db):     {len(df2)} 行")
print()

# 定义要对比的关键列（排除元数据列）
key_columns = [
    'date',  # 日期（需要特殊处理）
    'open', 'close', 'high', 'low', 'volume',  # OHLCV
    'kdj_k', 'kdj_d', 'kdj_j',  # KDJ
    'ma60', 'bbi',  # 常用指标
    'zxdq', 'zxdkx',  # 知行线
    'day_constraints_pass', 'zx_close_gt_long', 'zx_short_gt_long'  # 布尔指标
]

# 只保留两个数据库都有的列
key_columns = [col for col in key_columns if col in df1.columns and col in df2.columns]

print(f"{'='*70}")
print(f"将对比以下 {len(key_columns)} 列:")
print(f"{'='*70}")
print(', '.join(key_columns))
print()

# 处理日期格式差异
print("处理日期格式...")

# 检测并转换日期格式
if df1['date'].dtype in ['int64', 'int32']:
    print("  旧版: Unix 时间戳 → 转换为字符串")
    df1['date'] = pd.to_datetime(df1['date'], unit='s').dt.strftime('%Y-%m-%d')
elif df1['date'].dtype == 'object':
    print("  旧版: 字符串格式")
    df1['date'] = pd.to_datetime(df1['date']).dt.strftime('%Y-%m-%d')

if df2['date'].dtype in ['int64', 'int32']:
    print("  新版: Unix 时间戳 → 转换为字符串")
    df2['date'] = pd.to_datetime(df2['date'], unit='s').dt.strftime('%Y-%m-%d')
elif df2['date'].dtype == 'object':
    print("  新版: 字符串格式")
    df2['date'] = pd.to_datetime(df2['date']).dt.strftime('%Y-%m-%d')

print()

# 按日期排序对齐
df1 = df1.sort_values('date').reset_index(drop=True)
df2 = df2.sort_values('date').reset_index(drop=True)

# 逐列对比
print(f"{'='*70}")
print(f"逐列对比结果")
print(f"{'='*70}")

all_match = True
mismatches = []

for col in key_columns:
    if col == 'date':
        # 日期精确匹配
        match = (df1[col] == df2[col]).all()
        print(f"{'✅' if match else '❌'}  {col:30s} {'匹配' if match else '不匹配'}")
        if not match:
            all_match = False
            mismatch_count = (df1[col] != df2[col]).sum()
            mismatches.append((col, mismatch_count))
    
    elif col in ['day_constraints_pass', 'zx_close_gt_long', 'zx_short_gt_long']:
        # 布尔指标（0/1整数）
        match = (df1[col] == df2[col]).all()
        mismatch_count = (df1[col] != df2[col]).sum()
        print(f"{'✅' if match else '❌'}  {col:30s} {'匹配' if match else f'不匹配 ({mismatch_count} 行)'}")
        if not match:
            all_match = False
            mismatches.append((col, mismatch_count))
    
    else:
        # 数值列（浮点数）
        # 考虑 NaN 和小数误差
        both_nan = df1[col].isna() & df2[col].isna()
        diff = (df1[col] - df2[col]).abs()
        match = ((diff < 1e-6) | both_nan).all()
        
        if not match:
            max_diff = diff.max()
            mismatch_count = ((diff >= 1e-6) & ~both_nan).sum()
            print(f"❌  {col:30s} 不匹配 ({mismatch_count} 行, 最大差异: {max_diff:.2e})")
            all_match = False
            mismatches.append((col, mismatch_count))
        else:
            print(f"✅  {col:30s} 匹配")

print()

# 如果有不匹配，显示详细信息
if mismatches:
    print(f"{'='*70}")
    print(f"详细不匹配信息")
    print(f"{'='*70}")
    
    for col, count in mismatches:
        print(f"\n❌ 列: {col}")
        print(f"   不匹配行数: {count} / {len(df1)}")
        
        # 找到第一个不匹配的位置
        if col in ['day_constraints_pass', 'zx_close_gt_long', 'zx_short_gt_long']:
            mask = df1[col] != df2[col]
        else:
            mask = (df1[col] - df2[col]).abs() >= 1e-6
        
        if mask.any():
            idx = mask.idxmax()
            print(f"   首个不匹配位置: 第 {idx} 行")
            print(f"   日期: {df1.loc[idx, 'date']}")
            print(f"   旧版值: {df1.loc[idx, col]}")
            print(f"   新版值: {df2.loc[idx, col]}")

print()

# 显示前几行样本对比
print(f"{'='*70}")
print(f"数据样本对比（前5行）")
print(f"{'='*70}")

sample_cols = ['date', 'close', 'kdj_j', 'ma60', 'zx_close_gt_long', 'zx_short_gt_long']
sample_cols = [c for c in sample_cols if c in df1.columns]

print("\n旧版数据 (indicators_backup.db):")
print(df1[sample_cols].head())

print("\n新版数据 (indicators_test.db):")
print(df2[sample_cols].head())

print()

# 最终结果
print(f"{'='*70}")
if all_match:
    print("✅ 所有关键列完全匹配！数据一致。")
else:
    print(f"❌ 发现 {len(mismatches)} 列不匹配")
    print("   不匹配的列:", [col for col, _ in mismatches])
print(f"{'='*70}")