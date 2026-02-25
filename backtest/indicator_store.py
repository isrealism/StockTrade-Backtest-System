"""
技术指标数据库查询模块

提供高效的技术指标数据查询接口，用于回测系统和选股器。

Usage:
    from backtest.indicator_store import IndicatorStore

    store = IndicatorStore("./data/indicators.db")

    # 获取单只股票的所有指标
    df = store.get_indicators('000001', start_date='2025-01-01', end_date='2025-12-31')

    # 获取单个指标值
    j_value = store.get_indicator_at_date('000001', '2025-06-15', 'kdj_j')

    # 批量获取多只股票的指标
    data = store.batch_get_indicators(['000001', '000002'], '2025-06-15')
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class IndicatorStore:
    """技术指标数据库查询接口"""

    def __init__(self, db_path: str = "./data/indicators.db"):
        """
        初始化 IndicatorStore

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

        # 检查数据库文件是否存在
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"Database not found: {db_path}\n"
                f"Please run: python scripts/init_indicator_db.py --db {db_path}"
            )

        # 创建连接（使用 check_same_thread=False 支持多线程）
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # 支持按列名访问

    def get_indicators(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取指定股票的技术指标数据

        Args:
            code: 股票代码 (e.g., '000001')
            start_date: 开始日期 (YYYY-MM-DD)，可选
            end_date: 结束日期 (YYYY-MM-DD)，可选

        Returns:
            包含所有指标的 DataFrame，按日期升序排列

        Example:
            >>> store = IndicatorStore()
            >>> df = store.get_indicators('000001', start_date='2025-01-01', end_date='2025-12-31')
            >>> print(df[['date', 'close', 'kdj_j', 'ma60']])
        """
        query = "SELECT * FROM indicators WHERE code = ?"
        params = [code]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"

        df = pd.read_sql_query(query, self.conn, params=params)

        # 转换日期列为 datetime
        if not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        return df

    def get_indicator_at_date(
        self,
        code: str,
        date: str,
        indicator: str
    ) -> Optional[float]:
        """
        获取指定股票在指定日期的单个指标值

        Args:
            code: 股票代码
            date: 日期 (YYYY-MM-DD)
            indicator: 指标名称 (e.g., 'kdj_j', 'ma60', 'bbi')

        Returns:
            指标值（浮点数），如果不存在则返回 None

        Example:
            >>> store = IndicatorStore()
            >>> j_value = store.get_indicator_at_date('000001', '2025-06-15', 'kdj_j')
            >>> print(f"KDJ J value: {j_value}")
        """
        # 防止 SQL 注入：验证列名
        allowed_columns = self._get_column_names()
        if indicator not in allowed_columns:
            raise ValueError(f"Invalid indicator: {indicator}. Allowed: {allowed_columns}")

        query = f"SELECT {indicator} FROM indicators WHERE code = ? AND date = ?"
        cursor = self.conn.execute(query, (code, date))
        row = cursor.fetchone()

        if row:
            return row[indicator]
        else:
            return None

    def batch_get_indicators(
        self,
        codes: List[str],
        date: str
    ) -> Dict[str, pd.Series]:
        """
        批量获取多只股票在指定日期的所有指标

        Args:
            codes: 股票代码列表
            date: 日期 (YYYY-MM-DD)

        Returns:
            字典 {code: Series(indicators)}

        Example:
            >>> store = IndicatorStore()
            >>> data = store.batch_get_indicators(['000001', '000002'], '2025-06-15')
            >>> for code, indicators in data.items():
            ...     print(f"{code}: KDJ J = {indicators['kdj_j']}")
        """
        if not codes:
            return {}

        placeholders = ','.join(['?'] * len(codes))
        query = f"SELECT * FROM indicators WHERE code IN ({placeholders}) AND date = ?"
        params = codes + [date]

        df = pd.read_sql_query(query, self.conn, params=params)

        # 转换为字典 {code: Series}
        result = {}
        for _, row in df.iterrows():
            code = row['code']
            result[code] = row

        return result

    def get_all_codes(self) -> List[str]:
        """
        获取数据库中所有股票代码

        Returns:
            股票代码列表（排序）

        Example:
            >>> store = IndicatorStore()
            >>> codes = store.get_all_codes()
            >>> print(f"Total stocks: {len(codes)}")
        """
        query = "SELECT DISTINCT code FROM indicators ORDER BY code"
        df = pd.read_sql_query(query, self.conn)
        return df['code'].tolist()

    def get_date_range(self, code: str) -> tuple[Optional[str], Optional[str]]:
        """
        获取指定股票的数据日期范围

        Args:
            code: 股票代码

        Returns:
            (最早日期, 最晚日期)

        Example:
            >>> store = IndicatorStore()
            >>> start, end = store.get_date_range('000001')
            >>> print(f"Data range: {start} to {end}")
        """
        query = """
            SELECT MIN(date) as min_date, MAX(date) as max_date
            FROM indicators
            WHERE code = ?
        """
        cursor = self.conn.execute(query, (code,))
        row = cursor.fetchone()

        if row:
            return (row['min_date'], row['max_date'])
        else:
            return (None, None)

    def get_database_stats(self) -> Dict[str, any]:
        """
        获取数据库统计信息

        Returns:
            统计信息字典

        Example:
            >>> store = IndicatorStore()
            >>> stats = store.get_database_stats()
            >>> print(f"Total stocks: {stats['total_stocks']}")
            >>> print(f"Total rows: {stats['total_rows']}")
        """
        cursor = self.conn.cursor()

        # 总股票数
        cursor.execute("SELECT COUNT(DISTINCT code) FROM indicators")
        total_stocks = cursor.fetchone()[0]

        # 总行数
        cursor.execute("SELECT COUNT(*) FROM indicators")
        total_rows = cursor.fetchone()[0]

        # 日期范围
        cursor.execute("SELECT MIN(date), MAX(date) FROM indicators")
        min_date, max_date = cursor.fetchone()

        # 数据库文件大小
        db_size_mb = Path(self.db_path).stat().st_size / (1024 ** 2)

        return {
            'total_stocks': total_stocks,
            'total_rows': total_rows,
            'min_date': min_date,
            'max_date': max_date,
            'db_size_mb': round(db_size_mb, 2),
            'db_path': self.db_path
        }

    def _get_column_names(self) -> List[str]:
        """获取 indicators 表的所有列名"""
        cursor = self.conn.execute("PRAGMA table_info(indicators)")
        columns = [row[1] for row in cursor.fetchall()]
        return columns

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """支持 with 语句"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """自动关闭连接"""
        self.close()

    def __repr__(self):
        """字符串表示"""
        stats = self.get_database_stats()
        return (
            f"IndicatorStore(db='{self.db_path}', "
            f"stocks={stats['total_stocks']}, "
            f"rows={stats['total_rows']:,})"
        )


# 示例用法
if __name__ == "__main__":
    # 创建 IndicatorStore 实例
    store = IndicatorStore("./data/indicators.db")

    # 打印统计信息
    print(store)
    print()

    # 获取数据库统计
    stats = store.get_database_stats()
    print("Database Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()

    # 获取所有股票代码
    codes = store.get_all_codes()
    print(f"Available stocks: {codes[:5]}... (total: {len(codes)})")
    print()

    # 获取单只股票的数据
    if codes:
        code = codes[0]
        df = store.get_indicators(code, start_date='2025-01-01', end_date='2025-12-31')
        print(f"\nData for {code} (first 5 rows):")
        print(df[['date', 'close', 'kdj_j', 'ma60', 'bbi']].head())
        print()

        # 获取单个指标值
        date = df.iloc[-1]['date'].strftime('%Y-%m-%d')
        j_value = store.get_indicator_at_date(code, date, 'kdj_j')
        print(f"KDJ J value on {date}: {j_value}")
        print()

    # 批量获取指标
    if len(codes) >= 2:
        batch_data = store.batch_get_indicators(codes[:2], date)
        print(f"\nBatch data for {codes[:2]} on {date}:")
        for code, indicators in batch_data.items():
            print(f"  {code}: J={indicators['kdj_j']:.2f}, MA60={indicators['ma60']:.2f}")

    # 关闭连接
    store.close()
