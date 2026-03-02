"""
技术指标数据库查询模块（DuckDB 版）

提供高效的技术指标数据查询接口，用于回测系统和选股器。

与 SQLite 版的核心区别：
- 使用 duckdb.connect() 代替 sqlite3.connect()
- 使用 conn.execute(sql).df() 代替 pd.read_sql_query()
  → 直接产出 Arrow 格式的 DataFrame，跳过 Python 对象层，速度快 5-10 倍
- 新增 load_all() 方法供 LazyIndicatorData.preload_all() 调用

Usage:
    from backtest.indicator_store import IndicatorStore

    store = IndicatorStore("./data/indicators.duckdb")
    df = store.get_indicators('000001', start_date='2025-01-01', end_date='2025-12-31')
"""

import duckdb
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class IndicatorStore:
    """技术指标数据库查询接口（DuckDB 版）"""

    def __init__(self, db_path: str = "./data/indicators.duckdb"):
        self.db_path = db_path

        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"Database not found: {db_path}\n"
                f"Please run: python scripts/init_indicator_db.py --db {db_path}\n"
                f"Or migrate:  python scripts/migrate_to_duckdb.py --duckdb {db_path}"
            )

        # read_only=True：允许多个进程同时读取，不阻塞彼此
        # 写入操作由 precompute_indicators.py 负责，彼此不会同时运行
        self.conn = duckdb.connect(db_path, read_only=True)

    # ── 核心读取接口 ──────────────────────────────────────────────────────

    def load_all(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        批量加载指定日期范围内所有股票的数据，供 LazyIndicatorData.preload_all() 调用。

        这是整个系统最重要的读取方法。DuckDB 的列式存储在这里充分发挥优势：
        一次 SQL 扫描，直接用 Arrow 格式输出 DataFrame，比 SQLite 快 5-10 倍。

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date:   结束日期 YYYY-MM-DD

        Returns:
            包含所有股票、所有列的大 DataFrame，按 code ASC, date ASC 排序
        """
        df = self.conn.execute(
            """
            SELECT * FROM indicators
            WHERE date >= ? AND date <= ?
            ORDER BY code ASC, date ASC
            """,
            [start_date, end_date]
        ).df()

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])

        return df

    def get_indicators(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """获取指定股票的技术指标数据。"""
        sql = "SELECT * FROM indicators WHERE code = ?"
        params = [code]

        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)

        sql += " ORDER BY date ASC"

        df = self.conn.execute(sql, params).df()

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])

        return df

    def get_indicator_at_date(self, code: str, date: str, indicator: str) -> Optional[float]:
        """获取指定股票在指定日期的单个指标值。"""
        allowed = self._get_column_names()
        if indicator not in allowed:
            raise ValueError(f"Invalid indicator: {indicator}. Allowed: {allowed}")

        row = self.conn.execute(
            f"SELECT {indicator} FROM indicators WHERE code = ? AND date = ?",
            [code, date]
        ).fetchone()

        return row[0] if row else None

    def batch_get_indicators(self, codes: List[str], date: str) -> Dict[str, pd.Series]:
        """批量获取多只股票在指定日期的所有指标。"""
        if not codes:
            return {}

        placeholders = ", ".join(["?" ] * len(codes))
        df = self.conn.execute(
            f"SELECT * FROM indicators WHERE code IN ({placeholders}) AND date = ?",
            codes + [date]
        ).df()

        return {row["code"]: row for _, row in df.iterrows()}

    def get_indicators_for_codes(
        self,
        codes: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """批量获取多只股票在给定时间区间内的所有指标。"""
        if not codes:
            return pd.DataFrame()

        placeholders = ", ".join(["?"] * len(codes))
        sql = f"SELECT * FROM indicators WHERE code IN ({placeholders})"
        params: List = list(codes)

        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)

        sql += " ORDER BY code, date ASC"

        df = self.conn.execute(sql, params).df()
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])

        return df

    # ── 元数据接口 ────────────────────────────────────────────────────────

    def get_all_codes(self) -> List[str]:
        """获取数据库中所有股票代码。"""
        return [
            row[0] for row in
            self.conn.execute("SELECT DISTINCT code FROM indicators ORDER BY code").fetchall()
        ]

    def get_date_range(self, code: str):
        """获取指定股票的数据日期范围，返回 (min_date, max_date)。"""
        row = self.conn.execute(
            "SELECT MIN(date), MAX(date) FROM indicators WHERE code = ?", [code]
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def get_database_stats(self) -> Dict:
        """获取数据库统计信息。"""
        total_stocks = self.conn.execute(
            "SELECT COUNT(DISTINCT code) FROM indicators"
        ).fetchone()[0]

        total_rows = self.conn.execute(
            "SELECT COUNT(*) FROM indicators"
        ).fetchone()[0]

        min_date, max_date = self.conn.execute(
            "SELECT MIN(date), MAX(date) FROM indicators"
        ).fetchone()

        db_size_mb = Path(self.db_path).stat().st_size / (1024 ** 2)

        return {
            "total_stocks": total_stocks,
            "total_rows": total_rows,
            "min_date": min_date,
            "max_date": max_date,
            "db_size_mb": round(db_size_mb, 2),
            "db_path": self.db_path,
        }

    def _get_column_names(self) -> List[str]:
        """获取 indicators 表的所有列名。"""
        # DuckDB 用 DESCRIBE 代替 SQLite 的 PRAGMA table_info
        rows = self.conn.execute("DESCRIBE indicators").fetchall()
        return [row[0] for row in rows]

    # ── 连接管理 ──────────────────────────────────────────────────────────

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self):
        stats = self.get_database_stats()
        return (
            f"IndicatorStore(db='{self.db_path}', "
            f"stocks={stats['total_stocks']}, "
            f"rows={stats['total_rows']:,})"
        )


if __name__ == "__main__":
    store = IndicatorStore("./data/indicators.duckdb")
    print(store)
    stats = store.get_database_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    store.close()