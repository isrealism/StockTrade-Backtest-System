#!/usr/bin/env python3
"""
一次性迁移脚本：将 indicators.db（SQLite）迁移至 indicators.duckdb（DuckDB）

迁移内容：indicators、metadata、daily_stats、audit_log 四张表的全部数据。

Usage:
    python scripts/migrate_to_duckdb.py
    python scripts/migrate_to_duckdb.py --sqlite ./data/indicators.db --duckdb ./data/indicators.duckdb

迁移完成后请运行验证：
    python scripts/migrate_to_duckdb.py --verify
"""

import argparse
import sqlite3
import time
from pathlib import Path

import duckdb
import pandas as pd


# 需要迁移的所有表
TABLES = ["indicators", "metadata", "daily_stats", "audit_log"]


def migrate(sqlite_path: str, duckdb_path: str) -> None:
    """将 SQLite 数据库中的所有表迁移到 DuckDB。"""

    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"SQLite 数据库不存在：{sqlite_path}")

    if Path(duckdb_path).exists():
        answer = input(f"⚠️  {duckdb_path} 已存在，将覆盖。继续？(yes/no): ")
        if answer.lower() != "yes":
            print("已取消。")
            return
        Path(duckdb_path).unlink()

    print(f"\n源数据库（SQLite）: {sqlite_path}")
    print(f"目标数据库（DuckDB）: {duckdb_path}\n")

    sqlite_conn = sqlite3.connect(sqlite_path)
    duck_conn = duckdb.connect(duckdb_path)

    total_start = time.time()

    for table in TABLES:
        print(f"  迁移表 '{table}' ...", end=" ", flush=True)
        t0 = time.time()

        # 从 SQLite 读出整张表
        df = pd.read_sql_query(f"SELECT * FROM {table}", sqlite_conn)

        if df.empty:
            print("空表，跳过。")
            continue

        # 直接从 DataFrame 在 DuckDB 里建表并写入数据
        # DuckDB 会自动推断每列的数据类型，无需手动建表
        duck_conn.execute(f"DROP TABLE IF EXISTS {table}")
        duck_conn.execute(f"CREATE TABLE {table} AS SELECT * FROM df")

        elapsed = time.time() - t0
        print(f"✓  {len(df):,} 行，耗时 {elapsed:.2f}s")

    sqlite_conn.close()
    duck_conn.close()

    total_elapsed = time.time() - total_start
    duck_size_mb = Path(duckdb_path).stat().st_size / 1024 / 1024
    sqlite_size_mb = Path(sqlite_path).stat().st_size / 1024 / 1024

    print(f"\n✅ 迁移完成，总耗时 {total_elapsed:.2f}s")
    print(f"   SQLite 文件大小: {sqlite_size_mb:.1f} MB")
    print(f"   DuckDB 文件大小: {duck_size_mb:.1f} MB")
    print(f"   压缩比: {sqlite_size_mb / duck_size_mb:.1f}x")
    print(f"\n下一步：运行验证确认数据完整性")
    print(f"   python scripts/migrate_to_duckdb.py --verify --sqlite {sqlite_path} --duckdb {duckdb_path}")


def verify(sqlite_path: str, duckdb_path: str) -> None:
    """逐表对比 SQLite 和 DuckDB 的行数，确认数据完整性。"""

    print(f"\n验证数据完整性...\n")

    sqlite_conn = sqlite3.connect(sqlite_path)
    duck_conn = duckdb.connect(duckdb_path, read_only=True)

    all_ok = True

    for table in TABLES:
        sqlite_rows = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        duck_rows = duck_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        match = sqlite_rows == duck_rows
        status = "✓" if match else "❌"
        print(f"  {status} {table}: SQLite={sqlite_rows:,}  DuckDB={duck_rows:,}")
        if not match:
            all_ok = False

    # 额外验证：抽查 indicators 表按 code 分组的行数
    print("\n  抽查 indicators 表（按 code 统计行数差异）...")
    sqlite_counts = pd.read_sql_query(
        "SELECT code, COUNT(*) as cnt FROM indicators GROUP BY code", sqlite_conn
    ).set_index("code")["cnt"]

    duck_counts = duck_conn.execute(
        "SELECT code, COUNT(*) as cnt FROM indicators GROUP BY code"
    ).df().set_index("code")["cnt"]

    diff = (sqlite_counts - duck_counts).dropna()
    diff = diff[diff != 0]
    if diff.empty:
        print("  ✓ 所有股票的行数完全一致")
    else:
        print(f"  ❌ 发现 {len(diff)} 只股票行数不一致：{diff.head().to_dict()}")
        all_ok = False

    sqlite_conn.close()
    duck_conn.close()

    if all_ok:
        print("\n✅ 验证通过！数据完全一致。")
        print("   可以安全地将代码切换到 DuckDB 模式。")
    else:
        print("\n❌ 验证失败，请检查迁移日志后重新迁移。")


def main():
    parser = argparse.ArgumentParser(description="SQLite → DuckDB 迁移工具")
    parser.add_argument("--sqlite", default="./data/indicators.db")
    parser.add_argument("--duckdb", default="./data/indicators.duckdb")
    parser.add_argument("--verify", action="store_true", help="只做验证，不迁移")
    args = parser.parse_args()

    if args.verify:
        verify(args.sqlite, args.duckdb)
    else:
        migrate(args.sqlite, args.duckdb)


if __name__ == "__main__":
    main()
