#!/usr/bin/env python3
"""
板块数据拉取脚本（东财概念板块 + 主要指数成分权重）

写入 dc_sectors.duckdb 的两张表：

  ┌─────────────────────────────────────────────────────────┐
  │  dc_sectors      主键 (con_code, ts_code, trade_date)   │
  │  来源：dc_index + dc_member                             │
  │  内容：东财概念/行业/地域板块成分                        │
  │  更新：每个交易日拉一次                                  │
  ├─────────────────────────────────────────────────────────┤
  │  index_weight    主键 (index_code, con_code, trade_date)│
  │  来源：pro.index_weight                                  │
  │  内容：沪深300/中证500/中证1000/上证50 成分权重          │
  │  更新：每月初拉一次，历史从 2018-01 起                   │
  └─────────────────────────────────────────────────────────┘

用法：
  python fetch_dc_sectors.py                        # 拉最新交易日（两张表都更新）
  python fetch_dc_sectors.py --date 20250103        # 指定交易日（dc_sectors）
  python fetch_dc_sectors.py --only sectors         # 只更新 dc_sectors
  python fetch_dc_sectors.py --only index_weight    # 只更新 index_weight
  python fetch_dc_sectors.py --mode full            # index_weight 全量拉取（从2018）
  python fetch_dc_sectors.py --db ./data/dc_sectors.duckdb

环境变量：
  TUSHARE_TOKEN   Tushare API Token（必填）
  DC_SECTORS_DB_PATH  数据库路径（可选，默认 ./data/dc_sectors.duckdb）
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import List, Optional

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
DB_PATH      = Path(os.environ.get("DC_SECTORS_DB_PATH", str(ROOT / "data" / "dc_sectors.duckdb")))
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


def _connect_with_retry(db_path: str, retries: int = 10, interval: int = 6) -> duckdb.DuckDBPyConnection:
    """
    尝试获取 DuckDB 写连接。
    若其他进程持有写锁（IOException），每隔 interval 秒重试，最多 retries 次。
    """
    for attempt in range(1, retries + 1):
        try:
            return duckdb.connect(db_path)
        except duckdb.IOException as e:
            if "Conflicting lock" in str(e) or "Could not set lock" in str(e):
                logger.warning(
                    "DuckDB 文件被占用，%d 秒后重试（%d/%d）...", interval, attempt, retries
                )
                time.sleep(interval)
            else:
                raise
    raise RuntimeError(f"无法获取 DuckDB 写锁，已重试 {retries} 次：{db_path}")


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

META_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    table_name      VARCHAR PRIMARY KEY,
    first_date      VARCHAR,
    last_date       VARCHAR,
    total_rows      BIGINT,
    is_full_init    INTEGER DEFAULT 0,
    last_run_at     VARCHAR,
    last_run_rows   BIGINT
)
"""


def _ensure_meta_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(META_DDL)


def _upsert_meta_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    date_col: str,
    last_run_rows: int,
    is_full_init: bool = False,
) -> None:
    """写入/更新 meta 表（通用，支持任意表名和日期列）。"""
    _ensure_meta_table(conn)
    try:
        row = conn.execute(f"""
            SELECT MIN({date_col}), MAX({date_col}), COUNT(*)
            FROM {table_name}
        """).fetchone()
        first_date, last_date, total_rows = row if row else (None, None, 0)
    except Exception:
        first_date = last_date = None
        total_rows = 0

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO meta (table_name, first_date, last_date, total_rows,
                          is_full_init, last_run_at, last_run_rows)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (table_name) DO UPDATE SET
            first_date    = excluded.first_date,
            last_date     = excluded.last_date,
            total_rows    = excluded.total_rows,
            is_full_init  = CASE WHEN excluded.is_full_init = 1 THEN 1
                                 ELSE meta.is_full_init END,
            last_run_at   = excluded.last_run_at,
            last_run_rows = excluded.last_run_rows
    """, [table_name, first_date, last_date, total_rows,
          1 if is_full_init else 0, now, last_run_rows])
    logger.info("✓ meta 已更新：%s | last_date=%s | total_rows=%s | this_run=%d",
                table_name, last_date, total_rows, last_run_rows)


def _upsert_meta(conn: duckdb.DuckDBPyConnection, last_run_rows: int) -> None:
    """dc_sectors 专用的 meta 更新（向后兼容）。"""
    _upsert_meta_table(conn, "dc_sectors", "trade_date", last_run_rows)


DDL = """
CREATE TABLE IF NOT EXISTS dc_sectors (
    con_code    VARCHAR NOT NULL,   -- 成分股代码
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
    """确保 dc_sectors 和 meta 表存在。"""
    conn.execute(DDL)
    _ensure_meta_table(conn)
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
# 五、申万行业成分（sw_industry_member）
# ══════════════════════════════════════════════════════════════════════════════
#
# 接口：index_member_all（一次返回全部层级宽表）
# 字段：l1_code/l1_name, l2_code/l2_name, l3_code/l3_name,
#        ts_code, name, in_date, out_date, is_new
#
# 设计说明：
#   一张宽表存储所有层级，每行代表一只股票在某个 L3 行业下的一段归属期。
#   回测时查某日某只股票的行业：
#     WHERE ts_code = '000001.SZ'
#       AND in_date <= '20220601'
#       AND (out_date IS NULL OR out_date > '20220601')
#   只需运行一次（成分变动已通过 in_date/out_date 记录），用 --force-sw 强制重拉。
# ══════════════════════════════════════════════════════════════════════════════

SW_MEMBER_DDL = """
CREATE TABLE IF NOT EXISTS sw_industry_member (
    l1_code     VARCHAR,        -- 申万一级行业代码
    l1_name     VARCHAR,        -- 申万一级行业名称
    l2_code     VARCHAR,        -- 申万二级行业代码
    l2_name     VARCHAR,        -- 申万二级行业名称
    l3_code     VARCHAR,        -- 申万三级行业代码
    l3_name     VARCHAR,        -- 申万三级行业名称
    ts_code     VARCHAR NOT NULL, -- 成分股票代码（如 000001.SZ）
    name        VARCHAR,        -- 成分股票名称
    in_date     VARCHAR NOT NULL, -- 纳入日期 YYYYMMDD
    out_date    VARCHAR,        -- 剔除日期 YYYYMMDD（NULL=当前仍在）
    is_new      VARCHAR,        -- 是否最新 Y/N
    src         VARCHAR,        -- 版本 SW2021（目前只用2021版）
    PRIMARY KEY (ts_code, l3_code, in_date, src)
)
"""

SW_MEMBER_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_swm_ts_code  ON sw_industry_member(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_swm_l1_code  ON sw_industry_member(l1_code)",
    "CREATE INDEX IF NOT EXISTS idx_swm_l2_code  ON sw_industry_member(l2_code)",
    "CREATE INDEX IF NOT EXISTS idx_swm_l3_code  ON sw_industry_member(l3_code)",
    "CREATE INDEX IF NOT EXISTS idx_swm_in_date  ON sw_industry_member(in_date)",
    "CREATE INDEX IF NOT EXISTS idx_swm_out_date ON sw_industry_member(out_date)",
    "CREATE INDEX IF NOT EXISTS idx_swm_is_new   ON sw_industry_member(is_new)",
]

# index_member_all 只支持 SW2021，SW2014 已无法通过该接口拉取
SW_VERSIONS = ["SW2021"]


def ensure_sw_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(SW_MEMBER_DDL)
    for idx in SW_MEMBER_IDX:
        conn.execute(idx)
    logger.info("✓ sw_industry_member 表已就绪")


def run_sw_industry(pro, db_path: str, force: bool = False) -> None:
    """
    拉取申万行业成分股宽表，写入 sw_industry_member。
      - 只需运行一次，之后自动跳过
      - force=True 强制重新拉取覆盖
    """
    logger.info("=" * 60)
    logger.info("sw_industry：申万行业成分股（index_member_all）")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect_with_retry(db_path)
    ensure_sw_tables(conn)
    _ensure_meta_table(conn)

    # 检查是否已初始化
    if not force:
        try:
            done = {r[0] for r in conn.execute(
                "SELECT table_name FROM meta WHERE is_full_init = 1"
            ).fetchall()}
            if "sw_industry_member_SW2021" in done:
                logger.info("sw_industry：已完成初始化，跳过（用 --force-sw 强制重拉）")
                conn.close()
                return
        except Exception:
            pass

    total_rows = 0
    for src in SW_VERSIONS:
        logger.info("── 版本：%s ──", src)

        # index_member_all 一次拉全部，不需要循环行业
        df = _call_with_retry(pro.index_member_all)
        if df is None or df.empty:
            logger.warning("  %s 返回空数据，跳过", src)
            continue

        logger.info("  原始数据：%d 行，列：%s", len(df), df.columns.tolist())

        # 字段映射（接口实际返回的列名）
        df = df.rename(columns={
            "l1_code": "l1_code", "l1_name": "l1_name",
            "l2_code": "l2_code", "l2_name": "l2_name",
            "l3_code": "l3_code", "l3_name": "l3_name",
            "ts_code": "ts_code", "name": "name",
            "in_date": "in_date", "out_date": "out_date",
            "is_new":  "is_new",
        })
        df["src"] = src

        # 补齐缺失列
        all_cols = ["l1_code", "l1_name", "l2_code", "l2_name",
                    "l3_code", "l3_name", "ts_code", "name",
                    "in_date", "out_date", "is_new", "src"]
        for c in all_cols:
            if c not in df.columns:
                df[c] = None

        # l3_code 缺失时用 l2_code 填充（主键不能为 NULL）
        if "l3_code" in df.columns:
            df["l3_code"] = df["l3_code"].fillna(df.get("l2_code", "UNKNOWN"))
        df["l3_code"] = df["l3_code"].fillna("UNKNOWN")
        df["in_date"] = df["in_date"].fillna("19900101")

        # 过滤主键 NULL
        before = len(df)
        df = df.dropna(subset=["ts_code"])
        if len(df) < before:
            logger.warning("  过滤掉 %d 行 ts_code 为 NULL 的记录", before - len(df))

        if df.empty:
            logger.warning("  %s 过滤后为空，跳过", src)
            continue

        df = df[all_cols]

        # 全量覆盖该版本数据
        conn.execute(f"DELETE FROM sw_industry_member WHERE src = '{src}'")
        conn.register("_sw_staging", df)
        conn.execute(f"""
            INSERT INTO sw_industry_member ({', '.join(all_cols)})
            SELECT {', '.join(all_cols)} FROM _sw_staging
        """)
        conn.unregister("_sw_staging")
        conn.commit()

        rows = len(df)
        total_rows += rows
        logger.info("  ✓ %s 写入 %d 行", src, rows)

        # 更新 meta
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO meta (table_name, first_date, last_date, total_rows,
                              is_full_init, last_run_at, last_run_rows)
            VALUES (?, NULL, NULL, ?, 1, ?, ?)
            ON CONFLICT (table_name) DO UPDATE SET
                total_rows    = excluded.total_rows,
                is_full_init  = 1,
                last_run_at   = excluded.last_run_at,
                last_run_rows = excluded.last_run_rows
        """, [f"sw_industry_member_{src}", rows, now, rows])
        conn.commit()

    conn.close()
    logger.info("✅ sw_industry 完成：共写入 %d 行", total_rows)


# ══════════════════════════════════════════════════════════════════════════════
# 六、index_weight（指数成分权重）
# ══════════════════════════════════════════════════════════════════════════════

# 目标指数
INDEX_CODES = [
    "399300.SZ",   # 沪深300
    "000905.SH",   # 中证500
    "000852.SH",   # 中证1000
    "000016.SH",   # 上证50
]

INDEX_WEIGHT_DDL = """
CREATE TABLE IF NOT EXISTS index_weight (
    index_code  VARCHAR NOT NULL,   -- 指数代码
    con_code    VARCHAR NOT NULL,   -- 成分股代码
    trade_date  VARCHAR NOT NULL,   -- 交易日期 YYYYMMDD（每月某交易日）
    weight      DOUBLE,             -- 权重 %
    PRIMARY KEY (index_code, con_code, trade_date)
)
"""

INDEX_WEIGHT_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_iw_date_index ON index_weight(trade_date, index_code)",
    "CREATE INDEX IF NOT EXISTS idx_iw_code       ON index_weight(con_code)",
]


def ensure_index_weight_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(INDEX_WEIGHT_DDL)
    for idx in INDEX_WEIGHT_IDX:
        conn.execute(idx)
    logger.info("✓ index_weight 表已就绪")


def get_month_ranges(start_ym: str, end_ym: str) -> List[tuple]:
    """
    生成 (start_date, end_date) 列表，每个元素代表一个自然月。
    start_ym / end_ym 格式：YYYYMM
    """
    ranges = []
    y, m = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]), int(end_ym[4:])
    while (y, m) <= (ey, em):
        month_start = f"{y}{m:02d}01"
        # 月末：下个月1号减1天
        if m == 12:
            month_end = f"{y+1}0101"
        else:
            month_end = f"{y}{m+1:02d}01"
        last_day = (dt.date(int(month_end[:4]), int(month_end[4:6]), 1)
                    - dt.timedelta(days=1))
        month_end = last_day.strftime("%Y%m%d")
        ranges.append((month_start, month_end))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return ranges


def get_existing_index_weight_months(conn: duckdb.DuckDBPyConnection) -> set:
    """返回已拉取的 (index_code, YYYYMM) 集合。"""
    try:
        rows = conn.execute("""
            SELECT DISTINCT index_code, LEFT(trade_date, 6)
            FROM index_weight
        """).fetchall()
        return {(r[0], r[1]) for r in rows}
    except Exception:
        return set()


def fetch_index_weight_one_month(
    pro, index_code: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """拉取单个指数单月的成分权重。"""
    df = _call_with_retry(
        pro.index_weight,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"con_code": "con_code"})
    df["index_code"] = index_code
    df["trade_date"] = df["trade_date"].astype(str)
    df["weight"]     = pd.to_numeric(df.get("weight", None), errors="coerce")
    return df[["index_code", "con_code", "trade_date", "weight"]]


def run_index_weight(pro, db_path: str, mode: str = "incremental") -> None:
    """
    拉取并写入 index_weight 表。
      - full：从 2018-01 拉到当月
      - incremental：只拉还没有的月份（已有的自动跳过）
    """
    logger.info("=" * 60)
    logger.info("index_weight：mode=%s", mode)

    today  = dt.date.today()
    end_ym = today.strftime("%Y%m")
    start_ym = "201801" if mode == "full" else end_ym  # 增量只看当月

    month_ranges = get_month_ranges(start_ym, end_ym)

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect_with_retry(db_path)
    ensure_index_weight_table(conn)
    existing = get_existing_index_weight_months(conn)

    # 计算待拉取的 (index_code, start, end) 任务列表，跳过已有的
    todo = []
    for index_code in INDEX_CODES:
        for start_date, end_date in month_ranges:
            ym = start_date[:6]
            if (index_code, ym) not in existing:
                todo.append((index_code, start_date, end_date))

    if not todo:
        logger.info("index_weight：所有月份已存在，无需更新 ✅")
        conn.close()
        return

    logger.info("index_weight：需拉取 %d 个任务（%d 指数 × 约 %d 月）",
                len(todo), len(INDEX_CODES), len(month_ranges))

    stats = {"rows": 0, "ok": 0, "err": 0}
    from tqdm import tqdm
    pbar = tqdm(total=len(todo), desc="[index_weight]", unit="次")

    for index_code, start_date, end_date in todo:
        pbar.set_description(f"[index_weight] {index_code} {start_date[:6]}")
        try:
            df = fetch_index_weight_one_month(pro, index_code, start_date, end_date)
            if df.empty:
                logger.warning("  %s %s 返回空", index_code, start_date[:6])
                stats["err"] += 1
                pbar.update(1)
                continue

            conn.register("_iw_staging", df)
            conn.execute("""
                INSERT OR REPLACE INTO index_weight
                    (index_code, con_code, trade_date, weight)
                SELECT index_code, con_code, trade_date, weight
                FROM _iw_staging
            """)
            conn.unregister("_iw_staging")
            conn.commit()
            stats["rows"] += len(df)
            stats["ok"]   += 1

        except Exception as e:
            logger.error("  %s %s 失败：%s", index_code, start_date[:6], e)
            stats["err"] += 1

        pbar.update(1)
        time.sleep(0.3)

    pbar.close()

    # 更新 meta
    try:
        _upsert_meta_table(conn, "index_weight", "trade_date", stats["rows"],
                           is_full_init=(mode == "full"))
        conn.commit()
    except Exception as e:
        logger.warning("meta 更新失败：%s", e)

    conn.close()
    logger.info("✅ index_weight 完成：写入 %d 行，失败 %d 次", stats["rows"], stats["err"])


# ══════════════════════════════════════════════════════════════════════════════
# 六、主流程
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="拉取板块数据（东财概念 + 指数成分权重）")
    parser.add_argument("--date",  help="指定交易日 YYYYMMDD（dc_sectors 用，默认取最新）")
    parser.add_argument("--db",    default=str(DB_PATH), help="DuckDB 路径")
    parser.add_argument("--mode",  choices=["full", "incremental"], default="incremental",
                        help="index_weight 拉取模式（full=从2018全量，incremental=只拉当月）")
    parser.add_argument("--only",  choices=["sectors", "index_weight", "sw"], default=None,
                        help="只更新指定表（默认全部）")
    parser.add_argument("--force-sw", action="store_true",
                        help="强制重新拉取申万行业（版本升级时用）")
    args = parser.parse_args()

    # ── 初始化 Tushare ────────────────────────────────────────────────────
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        raise EnvironmentError("请设置环境变量 TUSHARE_TOKEN")
    ts.set_token(ts_token)
    pro = ts.pro_api()
    logger.info("✓ Tushare 初始化完成")

    db_path = args.db

    # ══════════════════════════════════════════════════════════════════════
    # dc_sectors
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "sectors"):
        trade_date = args.date.replace("-", "") if args.date else get_latest_trade_date(pro)
        logger.info("目标交易日：%s", trade_date)

        merged_df = fetch_and_merge(pro, trade_date)
        if merged_df.empty:
            logger.error("dc_sectors：未获取到任何数据，跳过")
        else:
            if not Path(db_path).exists():
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = _connect_with_retry(db_path)
            try:
                ensure_table(conn)
                rows_written = upsert_df(conn, merged_df)
                _upsert_meta(conn, rows_written)
                conn.commit()
            finally:
                conn.close()
            save_csv(merged_df, trade_date)
            logger.info("✅ dc_sectors 完成：写入 %d 行", rows_written)

    # ══════════════════════════════════════════════════════════════════════
    # 申万行业分类（只需初始化一次，之后自动跳过）
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "sw"):
        run_sw_industry(pro, db_path, force=args.force_sw)

    # ══════════════════════════════════════════════════════════════════════
    # index_weight
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "index_weight"):
        run_index_weight(pro, db_path, mode=args.mode)


if __name__ == "__main__":
    main()