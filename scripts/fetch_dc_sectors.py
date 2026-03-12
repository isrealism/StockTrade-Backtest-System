#!/usr/bin/env python3
"""
东方财富概念板块数据拉取脚本

功能：
  1. 拉取东财概念板块基本信息（dc_index）
  2. 拉取各板块成分股列表（dc_member）
  3. 将两表拼接后 UPSERT 进 indicators.duckdb 的 dc_sectors 表
  4. 同时将合并数据写入 data/concepts/<YYYYMMDD>.csv

表结构（dc_sectors）：
  - con_code    VARCHAR  PRIMARY KEY  成分股代码（用于关联 indicators 表的 code 字段）
  - trade_date  VARCHAR  交易日期 YYYYMMDD
  - ts_code     VARCHAR  概念板块代码
  - name        VARCHAR  概念名称
  - total_mv    DOUBLE   总市值（万元）
  - idx_type    VARCHAR  板块类型（行业板块/概念板块/地域板块）
  - level       VARCHAR  行业层级
  - con_name    VARCHAR  成分股名称

用法：
  python fetch_dc_sectors.py                        # 拉最新交易日
  python fetch_dc_sectors.py --date 20250103        # 拉指定日期
  python fetch_dc_sectors.py --db ./data/indicators.duckdb

环境变量：
  TUSHARE_TOKEN   Tushare API Token（必填）
  DB_PATH         数据库路径（可选，默认 ./data/indicators.duckdb）
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import tushare as ts

# 自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

# ── 路径配置 ──────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
DB_PATH      = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "indicators.duckdb")))
CONCEPTS_DIR = ROOT / "data" / "concepts"

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("fetch_dc_sectors")

# ── Tushare 限流配置 ───────────────────────────────────────────────────────────
BAN_PATTERNS  = ("访问频繁", "请稍后", "超过频率", "too many requests", "429", "403")
COOLDOWN_SECS = 60   # 触发限流后冷却时间（秒）
RETRY_TIMES   = 3    # 每次接口最多重试次数


# ══════════════════════════════════════════════════════════════════════════════
# 一、工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _looks_like_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(p in msg for p in BAN_PATTERNS)


def _cool_sleep(base: int = COOLDOWN_SECS) -> None:
    secs = max(1, int(base * random.uniform(0.9, 1.2)))
    logger.warning("疑似限流，冷却 %d 秒...", secs)
    time.sleep(secs)


def _call_with_retry(func, *args, **kwargs):
    """带重试 & 限流冷却的 Tushare 接口调用。"""
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            result = func(*args, **kwargs)
            time.sleep(0.3)   # 礼貌性延迟，避免频繁触发限流
            return result
        except Exception as e:
            if _looks_like_ban(e):
                _cool_sleep()
            elif attempt >= RETRY_TIMES:
                raise
            else:
                logger.warning("第 %d 次调用失败：%s，1 秒后重试...", attempt, e)
                time.sleep(1)
    return None


def get_latest_trade_date(pro) -> str:
    """从 Tushare 交易日历获取最新交易日（格式 YYYYMMDD）。"""
    import datetime as dt
    today    = dt.date.today().strftime("%Y%m%d")
    lookback = (dt.date.today() - dt.timedelta(days=15)).strftime("%Y%m%d")
    cal_df   = _call_with_retry(
        pro.trade_cal, exchange="SSE", start_date=lookback, end_date=today, is_open="1"
    )
    if cal_df is None or cal_df.empty:
        raise ValueError("无法获取交易日历，请检查 Token 或网络")
    latest = cal_df["cal_date"].max()
    logger.info("最新交易日：%s", latest)
    return latest


# ══════════════════════════════════════════════════════════════════════════════
# 二、DuckDB 建表 & UPSERT
# ══════════════════════════════════════════════════════════════════════════════

DDL = """
CREATE TABLE IF NOT EXISTS dc_sectors (
    con_code    VARCHAR NOT NULL,   -- 成分股代码（关联 indicators.code）
    trade_date  VARCHAR NOT NULL,   -- 交易日期 YYYYMMDD
    ts_code     VARCHAR,            -- 概念板块代码
    name        VARCHAR,            -- 概念名称
    total_mv    DOUBLE,             -- 总市值（万元）
    idx_type    VARCHAR,            -- 板块类型
    level       VARCHAR,            -- 行业层级
    con_name    VARCHAR,            -- 成分股名称
    PRIMARY KEY (con_code, ts_code, trade_date)
)
"""

def ensure_table(conn: duckdb.DuckDBPyConnection) -> None:
    """确保 dc_sectors 表存在。"""
    conn.execute(DDL)
    logger.info("✓ dc_sectors 表已就绪")


def upsert_df(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """
    将 DataFrame UPSERT 进 dc_sectors。
    DuckDB 支持 INSERT OR REPLACE，通过 PRIMARY KEY 去重。
    """
    if df.empty:
        logger.warning("传入的 DataFrame 为空，跳过写入")
        return 0

    # 确保列顺序与建表一致
    cols = ["con_code", "trade_date", "ts_code", "name", "total_mv", "idx_type", "level", "con_name"]
    df = df[cols].copy()

    # DuckDB INSERT OR REPLACE（等价于 UPSERT by PK）
    conn.register("_upsert_staging", df)
    conn.execute("""
        INSERT OR REPLACE INTO dc_sectors
        SELECT con_code, trade_date, ts_code, name, total_mv, idx_type, level, con_name
        FROM _upsert_staging
    """)
    conn.unregister("_upsert_staging")

    logger.info("✓ UPSERT %d 行到 dc_sectors", len(df))
    return len(df)


# ══════════════════════════════════════════════════════════════════════════════
# 三、CSV 写出
# ══════════════════════════════════════════════════════════════════════════════

def save_csv(df: pd.DataFrame, trade_date: str, csv_dir: Path = CONCEPTS_DIR) -> Path:
    """将合并后的 DataFrame 写入 data/concepts/<YYYYMMDD>.csv。"""
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"{trade_date}.csv"

    cols = ["con_code", "trade_date", "ts_code", "name", "total_mv", "idx_type", "level", "con_name"]
    df[cols].to_csv(csv_path, index=False, encoding="utf-8-sig")

    logger.info("✓ CSV 已写出：%s（%d 行）", csv_path, len(df))
    return csv_path


# ══════════════════════════════════════════════════════════════════════════════
# 四、Tushare 数据拉取 & 拼接
# ══════════════════════════════════════════════════════════════════════════════

def fetch_dc_index(pro, trade_date: str) -> pd.DataFrame:
    """拉取指定交易日的东财概念板块基本信息。"""
    logger.info("拉取板块基本信息：trade_date=%s", trade_date)
    df = _call_with_retry(
        pro.dc_index,
        trade_date=trade_date,
        fields="ts_code,trade_date,name,total_mv,idx_type,level"
    )
    if df is None or df.empty:
        logger.warning("dc_index 返回空数据，trade_date=%s", trade_date)
        return pd.DataFrame()
    logger.info("  获取到 %d 个板块", len(df))
    return df


def fetch_dc_member_single(pro, trade_date: str, ts_code: str) -> pd.DataFrame:
    """拉取单个板块的成分股列表。"""
    df = _call_with_retry(
        pro.dc_member,
        trade_date=trade_date,
        ts_code=ts_code,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def fetch_and_merge(pro, trade_date: str) -> pd.DataFrame:
    """
    拉取指定交易日所有概念板块信息 + 成分股，合并成宽表。

    最终列：con_code, trade_date, ts_code, name, total_mv, idx_type, level, con_name
    """
    # 1. 拉基本信息
    index_df = fetch_dc_index(pro, trade_date)
    if index_df.empty:
        return pd.DataFrame()

    # 2. 逐板块拉成分股，拼接成大表
    all_members = []
    total = len(index_df)
    for i, row in enumerate(index_df.itertuples(), 1):
        sector_code = row.ts_code
        logger.info("  [%d/%d] 拉取板块成分：%s %s", i, total, sector_code, row.name)
        member_df = fetch_dc_member_single(pro, trade_date, sector_code)
        if member_df.empty:
            continue
        # 重命名成分股字段，避免与板块字段冲突
        member_df = member_df.rename(columns={"name": "con_name", "con_code": "con_code"})
        # 只保留需要的成分字段
        member_df = member_df[["con_code", "con_name"]].copy()
        # 拼接板块元信息
        member_df["ts_code"]    = row.ts_code
        member_df["trade_date"] = trade_date
        member_df["name"]       = row.name
        member_df["total_mv"]   = getattr(row, "total_mv", None)
        member_df["idx_type"]   = getattr(row, "idx_type", None)
        member_df["level"]      = getattr(row, "level", None)
        all_members.append(member_df)

    if not all_members:
        logger.warning("所有板块成分均为空，trade_date=%s", trade_date)
        return pd.DataFrame()

    merged = pd.concat(all_members, ignore_index=True)

    # 确保 total_mv 为数值
    merged["total_mv"] = pd.to_numeric(merged["total_mv"], errors="coerce")

    logger.info("合并完成，共 %d 行（板块×成分）", len(merged))
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# 五、主流程
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="拉取东财概念板块数据并写入 DuckDB")
    parser.add_argument("--date",  help="指定交易日 YYYYMMDD（默认取最新交易日）")
    parser.add_argument("--db",    default=str(DB_PATH), help="DuckDB 路径")
    args = parser.parse_args()

    # ── 初始化 Tushare ────────────────────────────────────────────────────
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        raise EnvironmentError("请设置环境变量 TUSHARE_TOKEN")
    ts.set_token(ts_token)
    pro = ts.pro_api()
    logger.info("✓ Tushare 初始化完成")

    # ── 确定交易日 ────────────────────────────────────────────────────────
    trade_date = args.date.replace("-", "") if args.date else get_latest_trade_date(pro)
    logger.info("目标交易日：%s", trade_date)

    # ── 拉取 & 合并数据 ───────────────────────────────────────────────────
    merged_df = fetch_and_merge(pro, trade_date)
    if merged_df.empty:
        logger.error("未获取到任何数据，退出")
        sys.exit(1)

    # ── 写入 DuckDB ───────────────────────────────────────────────────────
    db_path = args.db
    if not Path(db_path).exists():
        logger.warning("数据库文件不存在，将自动创建：%s", db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(db_path)
    try:
        ensure_table(conn)
        rows_written = upsert_df(conn, merged_df)
        conn.commit()
    finally:
        conn.close()

    # ── 写出 CSV ──────────────────────────────────────────────────────────
    csv_path = save_csv(merged_df, trade_date)

    logger.info("=" * 60)
    logger.info("✅ 完成！交易日 %s，写入 %d 行到 dc_sectors", trade_date, rows_written)
    logger.info("   CSV：%s", csv_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()