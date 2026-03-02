#!/usr/bin/env python3
"""
技术指标数据库初始化脚本（DuckDB 版）

创建 DuckDB 数据库及表结构，用于存储预计算的技术指标。

1. 添加数据约束，确保数据有效性
2. 优化索引策略，提升查询性能
3. 添加性能优化 PRAGMA
4. 添加数据完整性检查工具
5. 支持数据版本控制
6. 添加统计表

与 SQLite 版的主要区别：
- 无需 PRAGMA 性能配置（DuckDB 内部自动优化列式存储）
- 使用 information_schema 代替 sqlite_master 查询表结构
- 使用 SEQUENCE 实现 audit_log 的自增主键
- 日期默认值使用标准 SQL 的 current_timestamp

Usage:
    python scripts/init_indicator_db.py --db ./data/indicators.duckdb
    python scripts/init_indicator_db.py --db ./data/indicators.duckdb --validate
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

import duckdb


def create_database(db_path: str) -> None:
    """创建 DuckDB 数据库并初始化表结构。"""

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"正在创建数据库：{db_path}")
    conn = duckdb.connect(db_path)

    # ── 主表：indicators ─────────────────────────────────────────────────
    # DuckDB 是列式存储，天生适合分析型查询，无需像 SQLite 那样手动配置
    # cache_size / journal_mode 等参数。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            -- 主键
            code    VARCHAR NOT NULL,
            date    VARCHAR NOT NULL,

            -- OHLCV 原始数据
            open    DOUBLE,
            close   DOUBLE,
            high    DOUBLE,
            low     DOUBLE,
            volume  DOUBLE,

            -- KDJ 指标
            kdj_k   DOUBLE,
            kdj_d   DOUBLE,
            kdj_j   DOUBLE,

            -- 移动平均线
            ma3     DOUBLE,
            ma6     DOUBLE,
            ma10    DOUBLE,
            ma12    DOUBLE,
            ma14    DOUBLE,
            ma24    DOUBLE,
            ma28    DOUBLE,
            ma57    DOUBLE,
            ma60    DOUBLE,
            ma114   DOUBLE,

            -- BBI 指标
            bbi     DOUBLE,

            -- MACD 指标
            dif     DOUBLE,

            -- 知行线
            zxdq    DOUBLE,
            zxdkx   DOUBLE,

            -- RSV 多周期
            rsv_9   DOUBLE,
            rsv_8   DOUBLE,
            rsv_30  DOUBLE,
            rsv_3   DOUBLE,
            rsv_5   DOUBLE,
            rsv_21  DOUBLE,

            -- ATR 指标
            atr_14  DOUBLE,
            atr_22  DOUBLE,

            -- 布尔派生指标 (0/1)
            day_constraints_pass  INTEGER,
            zx_close_gt_long      INTEGER,
            zx_short_gt_long      INTEGER,

            -- 成交量均线
            vol_ma20 DOUBLE,

            -- 元数据
            updated_at VARCHAR,

            PRIMARY KEY (code, date)
        )
    """)
    print("✓ 创建表 indicators")

    # ── 元数据表 ──────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            code                VARCHAR PRIMARY KEY,
            last_date           VARCHAR,
            last_updated        VARCHAR,
            row_count           INTEGER,
            first_date          VARCHAR,
            data_quality_score  DOUBLE DEFAULT 1.0,
            notes               VARCHAR
        )
    """)
    print("✓ 创建表 metadata")

    # ── 每日统计表 ────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date                VARCHAR PRIMARY KEY,
            total_stocks        INTEGER,
            avg_close           DOUBLE,
            avg_volume          DOUBLE,
            high_kdj_j_count    INTEGER,
            low_kdj_j_count     INTEGER,
            strong_stocks_count INTEGER,
            computed_at         VARCHAR
        )
    """)
    print("✓ 创建表 daily_stats")

    # ── 审计日志表 ────────────────────────────────────────────────────────
    # DuckDB 用 SEQUENCE 实现自增主键
    conn.execute("CREATE SEQUENCE IF NOT EXISTS audit_log_seq START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            BIGINT DEFAULT nextval('audit_log_seq') PRIMARY KEY,
            action        VARCHAR NOT NULL,
            table_name    VARCHAR NOT NULL,
            record_key    VARCHAR,
            changed_fields VARCHAR,
            timestamp     VARCHAR DEFAULT current_timestamp::VARCHAR,
            user_name     VARCHAR DEFAULT 'system'
        )
    """)
    print("✓ 创建表 audit_log")

    # ── 索引 ──────────────────────────────────────────────────────────────
    # DuckDB 是列式存储，对全表扫描（分析型查询）已经很快，索引主要用于
    # 点查询（按 code 查单只股票）和范围查询（按 date 过滤）。
    print("\n创建索引...")
    indexes = [
        ("idx_code_date",       "indicators(code, date)"),
        ("idx_date_code",       "indicators(date, code)"),
        ("idx_day_pass_code",   "indicators(day_constraints_pass, code)"),
    ]
    for idx_name, idx_def in indexes:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
        print(f"  ✓ {idx_name}")

    conn.close()

    print(f"\n✅ 数据库初始化完成：{db_path}")


def validate_database(db_path: str) -> None:
    """数据库完整性检查。"""

    if not Path(db_path).exists():
        print(f"❌ 数据库不存在：{db_path}")
        return

    print(f"\n{'='*60}")
    print("  数据库验证报告（DuckDB）")
    print(f"{'='*60}\n")

    conn = duckdb.connect(db_path, read_only=True)

    # 1. 检查表是否存在
    print("1. 检查表结构...")
    # DuckDB 用 information_schema.tables 代替 sqlite_master
    existing = {
        row[0] for row in
        conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    }
    for table in ["indicators", "metadata", "daily_stats", "audit_log"]:
        status = "✓" if table in existing else "❌"
        print(f"   {status} 表 '{table}'")

    # 2. 行数统计
    print("\n2. 数据量统计...")
    total_rows = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
    unique_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM indicators").fetchone()[0]
    min_date, max_date = conn.execute("SELECT MIN(date), MAX(date) FROM indicators").fetchone()
    print(f"   总行数: {total_rows:,}")
    print(f"   股票数: {unique_codes:,}")
    print(f"   日期范围: {min_date} ~ {max_date}")

    # 3. OHLC 逻辑检查
    print("\n3. 数据逻辑检查...")
    invalid_ohlc = conn.execute("""
        SELECT COUNT(*) FROM indicators
        WHERE high < low OR high < open OR high < close
           OR low > open OR low > close
    """).fetchone()[0]
    if invalid_ohlc == 0:
        print("   ✓ OHLC 数据逻辑正常")
    else:
        print(f"   ❌ 发现 {invalid_ohlc} 条 OHLC 逻辑错误记录")

    missing = conn.execute("""
        SELECT COUNT(*) FROM indicators WHERE close IS NULL OR volume IS NULL
    """).fetchone()[0]
    if missing == 0:
        print("   ✓ 无缺失关键字段")
    else:
        print(f"   ⚠️  {missing} 条记录存在缺失值")

    # 4. 文件大小
    print("\n4. 文件信息...")
    db_size_mb = Path(db_path).stat().st_size / (1024 ** 2)
    print(f"   数据库大小: {db_size_mb:.2f} MB")
    if total_rows > 0:
        print(f"   平均行大小: {db_size_mb * 1024 * 1024 / total_rows:.1f} bytes")

    conn.close()
    print(f"\n{'='*60}")
    print("  验证完成")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="初始化 DuckDB 技术指标数据库")
    parser.add_argument("--db", default="./data/indicators.duckdb")
    parser.add_argument("--validate", action="store_true", help="验证已有数据库")
    args = parser.parse_args()

    if args.validate:
        validate_database(args.db)
    else:
        create_database(args.db)


if __name__ == "__main__":
    main()
