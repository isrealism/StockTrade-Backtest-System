#!/usr/bin/env python3
"""
技术指标数据库初始化脚本（改进版）

创建 SQLite 数据库及表结构，用于存储预计算的技术指标。

改进点：
1. 添加数据约束，确保数据有效性
2. 优化索引策略，提升查询性能
3. 添加性能优化 PRAGMA
4. 添加数据完整性检查工具
5. 支持数据版本控制
6. 添加统计表

Usage:
    # 创建数据库
    python scripts/init_indicator_db.py --db ./data/indicators.db
    
    # 验证数据库
    python scripts/init_indicator_db.py --db ./data/indicators.db --validate
"""

import argparse
import sqlite3
from pathlib import Path
from datetime import datetime


def create_database(db_path: str, use_timestamp: bool = False):
    """创建数据库并初始化表结构"""

    # 确保父目录存在
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # 连接数据库（如果不存在会自动创建）
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"Creating database at: {db_path}")

    # ========== 性能优化配置 ==========
    print("\nApplying performance optimizations...")
    cursor.execute("PRAGMA journal_mode = WAL")          # 写前日志模式
    cursor.execute("PRAGMA synchronous = NORMAL")        # 降低同步级别
    cursor.execute("PRAGMA cache_size = -64000")         # 64MB 缓存
    cursor.execute("PRAGMA temp_store = MEMORY")         # 临时表存内存
    cursor.execute("PRAGMA auto_vacuum = INCREMENTAL")   # 增量 VACUUM
    print("✓ Performance optimizations applied")

    # ========== 创建主表：indicators ==========
    date_type = "INTEGER" if use_timestamp else "TEXT"
    date_check = "" if use_timestamp else "CHECK(date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]')"
    
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS indicators (
            -- 主键
            code TEXT NOT NULL CHECK(length(code) = 6),  -- 股票代码 (固定6位)
            date {date_type} NOT NULL {date_check},      -- 交易日期

            -- OHLCV 原始数据（带约束）
            open REAL CHECK(open > 0),
            close REAL CHECK(close > 0),
            high REAL CHECK(high > 0),
            low REAL CHECK(low > 0),
            volume REAL CHECK(volume >= 0),

            -- KDJ 指标 (9日) 带范围约束
            kdj_k REAL CHECK(kdj_k BETWEEN -100 AND 200),
            kdj_d REAL CHECK(kdj_d BETWEEN -100 AND 200),
            kdj_j REAL CHECK(kdj_j BETWEEN -200 AND 300),

            -- 移动平均线
            ma3 REAL,
            ma6 REAL,
            ma10 REAL,
            ma12 REAL,
            ma14 REAL,
            ma24 REAL,
            ma28 REAL,
            ma57 REAL,
            ma60 REAL,
            ma114 REAL,

            -- BBI 指标
            bbi REAL,

            -- MACD 指标
            dif REAL,

            -- 知行线 (ZX Lines)
            zxdq REAL,
            zxdkx REAL,

            -- RSV 指标（多周期）
            rsv_9 REAL,
            rsv_8 REAL,
            rsv_30 REAL,

            -- ATR 指标
            atr_14 REAL CHECK(atr_14 >= 0),
            atr_22 REAL CHECK(atr_22 >= 0),

            -- 布尔型派生指标 (0/1)
            day_constraints_pass INTEGER CHECK(day_constraints_pass IN (0, 1)),
            zx_close_gt_long INTEGER CHECK(zx_close_gt_long IN (0, 1)),
            zx_short_gt_long INTEGER CHECK(zx_short_gt_long IN (0, 1)),

            -- 元数据（版本控制）
            version INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT,

            -- 主键和约束
            PRIMARY KEY (code, date),
            CHECK(high >= low),
            CHECK(high >= open),
            CHECK(high >= close),
            CHECK(low <= open),
            CHECK(low <= close)
        );
    """)

    print("✓ Created table: indicators")

    # ========== 创建优化索引 ==========
    print("\nCreating indexes...")
    
    indexes = [
        # 核心复合索引（利用最左前缀原则）
        ("idx_code_date", "code, date"),
        ("idx_date_code", "date, code"),
        
        # 覆盖索引（避免回表）
        ("idx_code_date_close", "code, date, close"),
        
        # 常用筛选字段索引
        ("idx_kdj_j_code", "kdj_j, code"),
        ("idx_bbi_code", "bbi, code"),
        ("idx_ma60_code", "ma60, code"),
        
        # 布尔筛选索引
        ("idx_day_pass_code", "day_constraints_pass, code"),
    ]

    for idx_name, idx_columns in indexes:
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_name}
            ON indicators({idx_columns});
        """)
        print(f"  ✓ {idx_name} on ({idx_columns})")

    # ========== 创建元数据表 ==========
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS metadata (
            code TEXT PRIMARY KEY,
            last_date {date_type},
            last_updated TEXT,
            row_count INTEGER,
            first_date {date_type},                 -- 新增：首个数据日期
            data_quality_score REAL DEFAULT 1.0,    -- 新增：数据质量评分 (0-1)
            notes TEXT                              -- 新增：备注信息
        );
    """)

    print("✓ Created table: metadata")

    # ========== 创建统计表 ==========
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date {date_type} PRIMARY KEY,
            total_stocks INTEGER,
            avg_close REAL,
            avg_volume REAL,
            high_kdj_j_count INTEGER,              -- J > 80 的股票数
            low_kdj_j_count INTEGER,               -- J < 20 的股票数
            strong_stocks_count INTEGER,           -- 收盘价 > MA60 的股票数
            computed_at TEXT
        );
    """)

    print("✓ Created table: daily_stats")

    # ========== 创建审计日志表（可选）==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,                  -- INSERT, UPDATE, DELETE
            table_name TEXT NOT NULL,
            record_key TEXT,                       -- 记录的主键
            changed_fields TEXT,                   -- JSON 格式的变更内容
            timestamp TEXT DEFAULT (datetime('now')),
            user TEXT DEFAULT 'system'
        );
    """)

    print("✓ Created table: audit_log")

    # 提交并关闭
    conn.commit()
    conn.close()

    print(f"\n✅ Database initialized successfully!")
    print(f"   Location: {db_path}")
    print(f"   Tables: indicators, metadata, daily_stats, audit_log")
    print(f"   Indexes: {len(indexes)} indexes created")
    print(f"   Date format: {'Unix timestamp' if use_timestamp else 'YYYY-MM-DD string'}")


def validate_database(db_path: str):
    """数据完整性检查"""
    
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        return

    print(f"\n{'='*60}")
    print("  Database Validation Report")
    print(f"{'='*60}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. SQLite 内置完整性检查
    print("1. Running SQLite integrity check...")
    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()[0]
    if result == "ok":
        print("   ✓ Database integrity: OK")
    else:
        print(f"   ❌ Database integrity: {result}")

    # 2. 检查表是否存在
    print("\n2. Checking table existence...")
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        ORDER BY name
    """)
    tables = [row[0] for row in cursor.fetchall()]
    expected_tables = ['indicators', 'metadata', 'daily_stats', 'audit_log']
    
    for table in expected_tables:
        if table in tables:
            print(f"   ✓ Table '{table}' exists")
        else:
            print(f"   ❌ Table '{table}' missing")

    # 3. 检查索引
    print("\n3. Checking indexes...")
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='index' AND sql IS NOT NULL
    """)
    indexes = [row[0] for row in cursor.fetchall()]
    print(f"   Found {len(indexes)} indexes")

    # 4. 检查数据量
    print("\n4. Checking data volume...")
    cursor.execute("SELECT COUNT(*) FROM indicators")
    total_rows = cursor.fetchone()[0]
    print(f"   Total rows in indicators: {total_rows:,}")

    cursor.execute("SELECT COUNT(DISTINCT code) FROM indicators")
    unique_codes = cursor.fetchone()[0]
    print(f"   Unique stock codes: {unique_codes:,}")

    # 5. 检查数据逻辑错误
    print("\n5. Checking data logic errors...")
    
    # 检查 OHLC 逻辑
    cursor.execute("""
        SELECT COUNT(*) FROM indicators 
        WHERE high < low OR high < open OR high < close 
           OR low > open OR low > close
    """)
    invalid_ohlc = cursor.fetchone()[0]
    if invalid_ohlc == 0:
        print("   ✓ OHLC data logic: OK")
    else:
        print(f"   ❌ Found {invalid_ohlc} invalid OHLC records")

    # 检查缺失的关键数据
    cursor.execute("""
        SELECT COUNT(*) FROM indicators 
        WHERE close IS NULL OR volume IS NULL
    """)
    missing = cursor.fetchone()[0]
    if missing == 0:
        print("   ✓ No missing critical values")
    else:
        print(f"   ⚠️  Found {missing} records with missing values")

    # 6. 检查孤立数据
    print("\n6. Checking orphaned records...")
    cursor.execute("""
        SELECT COUNT(DISTINCT code) FROM indicators 
        WHERE code NOT IN (SELECT code FROM metadata)
    """)
    orphaned = cursor.fetchone()[0]
    if orphaned == 0:
        print("   ✓ No orphaned records")
    else:
        print(f"   ⚠️  Found {orphaned} codes in indicators but not in metadata")

    # 7. 数据库大小
    print("\n7. Database statistics...")
    db_size = Path(db_path).stat().st_size / (1024**2)
    print(f"   Database size: {db_size:.2f} MB")
    
    if total_rows > 0:
        avg_row_size = (db_size * 1024 * 1024) / total_rows
        print(f"   Average row size: {avg_row_size:.1f} bytes")

    # 8. 性能检查
    print("\n8. Performance check (PRAGMA settings)...")
    pragmas = [
        ("journal_mode", "WAL"),
        ("synchronous", "1"),  # NORMAL
        ("cache_size", None),
    ]
    
    for pragma_name, expected in pragmas:
        cursor.execute(f"PRAGMA {pragma_name}")
        actual = cursor.fetchone()[0]
        if expected is None or str(actual) == str(expected):
            print(f"   ✓ {pragma_name}: {actual}")
        else:
            print(f"   ⚠️  {pragma_name}: {actual} (expected: {expected})")

    conn.close()

    print(f"\n{'='*60}")
    print("  Validation Complete")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Initialize technical indicators database (improved version)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="./data/indicators.db",
        help="Database file path (default: ./data/indicators.db)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation checks on existing database"
    )
    parser.add_argument(
        "--use-timestamp",
        action="store_true",
        help="Use Unix timestamp for date column instead of TEXT (better performance)"
    )

    args = parser.parse_args()

    if args.validate:
        validate_database(args.db)
    else:
        create_database(args.db, use_timestamp=args.use_timestamp)


if __name__ == "__main__":
    main()
