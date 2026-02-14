#!/usr/bin/env python3
"""
技术指标数据库初始化脚本

创建 SQLite 数据库及表结构，用于存储预计算的技术指标。

Usage:
    python scripts/init_indicator_db.py --db ./data/indicators.db
"""

import argparse
import sqlite3
from pathlib import Path


def create_database(db_path: str):
    """创建数据库并初始化表结构"""

    # 确保父目录存在
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # 连接数据库（如果不存在会自动创建）
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"Creating database at: {db_path}")

    # ========== 创建主表：indicators ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            -- 主键
            code TEXT NOT NULL,                    -- 股票代码 (e.g., '000001')
            date TEXT NOT NULL,                    -- 交易日期 (YYYY-MM-DD)

            -- OHLCV 原始数据（冗余存储，加速查询）
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,

            -- KDJ 指标 (9日)
            kdj_k REAL,                            -- K 值
            kdj_d REAL,                            -- D 值
            kdj_j REAL,                            -- J 值

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
            bbi REAL,                              -- (MA3+MA6+MA12+MA24)/4

            -- MACD 指标
            dif REAL,                              -- DIF线 (12,26)

            -- 知行线 (ZX Lines)
            zxdq REAL,                             -- 短期线 EMA(EMA(C,10),10)
            zxdkx REAL,                            -- 长期线 (MA14+MA28+MA57+MA114)/4

            -- RSV 指标（多周期）
            rsv_9 REAL,                            -- 9日 RSV (KDJ 用)
            rsv_8 REAL,                            -- 8日 RSV (某些选股器用)
            rsv_30 REAL,                           -- 30日 RSV (某些选股器用)

            -- ATR 指标（真实波幅，用于仓位管理和卖出策略）
            atr_14 REAL,                           -- 14日 ATR (标准周期)
            atr_22 REAL,                           -- 22日 ATR (月度波动)

            -- 布尔型派生指标 (0/1)
            day_constraints_pass INTEGER,          -- 是否通过日内约束 (涨跌幅<2%, 振幅<7%)
            zx_close_gt_long INTEGER,              -- close > ZXDKX
            zx_short_gt_long INTEGER,              -- ZXDQ > ZXDKX

            -- 元数据
            updated_at TEXT,                       -- 最后更新时间戳

            PRIMARY KEY (code, date)
        );
    """)

    print("✓ Created table: indicators")

    # ========== 创建性能优化索引 ==========
    indexes = [
        ("idx_date", "date"),
        ("idx_code", "code"),
        ("idx_kdj_j", "kdj_j"),           # 常用于筛选低 J 值
        ("idx_bbi", "bbi"),
        ("idx_ma60", "ma60"),
        ("idx_code_date", "code, date"),  # 复合索引
    ]

    for idx_name, idx_columns in indexes:
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS {idx_name}
            ON indicators({idx_columns});
        """)
        print(f"✓ Created index: {idx_name} on ({idx_columns})")

    # ========== 创建元数据表 ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            code TEXT PRIMARY KEY,
            last_date TEXT,                        -- 该股票最后一个有数据的日期
            last_updated TEXT,                     -- 最后更新时间戳
            row_count INTEGER                      -- 该股票的记录数
        );
    """)

    print("✓ Created table: metadata")

    # 提交并关闭
    conn.commit()
    conn.close()

    print(f"\n✅ Database initialized successfully at: {db_path}")
    print(f"   Tables: indicators, metadata")
    print(f"   Indexes: {len(indexes)} indexes created")


def main():
    parser = argparse.ArgumentParser(
        description="Initialize technical indicators database"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="./data/indicators.db",
        help="Database file path (default: ./data/indicators.db)"
    )

    args = parser.parse_args()

    create_database(args.db)


if __name__ == "__main__":
    main()
