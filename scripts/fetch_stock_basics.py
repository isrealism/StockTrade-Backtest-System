#!/usr/bin/env python3
"""
股票基础数据拉取脚本

写入 indicators.duckdb 的两张独立表：

  ┌─────────────────────────────────────────────────────────┐
  │  stock_daily_basic   主键 (code, trade_date)            │
  │  来源：daily_basic + stock_basic                        │
  │  内容：每日估值/市值/流动性 + ST标记/上市日期            │
  │  更新：每个交易日增量拉取                                │
  ├─────────────────────────────────────────────────────────┤
  │  fina_indicators     主键 (code, end_date)              │
  │  来源：fina_indicator_vip（5000积分）                   │
  │  内容：ROE/营收增速/净利增速/毛利率/负债率/自由现金流    │
  │  更新：按季度末（0331/0630/0930/1231）拉取               │
  └─────────────────────────────────────────────────────────┘

用法：
  python fetch_stock_basics.py                   # 每日增量（两张表都更新）
  python fetch_stock_basics.py --mode full       # 首次全量
  python fetch_stock_basics.py --date 20250103   # 指定单日
  python fetch_stock_basics.py --only daily      # 只更新 stock_daily_basic
  python fetch_stock_basics.py --only fina       # 只更新 fina_indicators

环境变量：
  TUSHARE_TOKEN   必填
  DB_PATH         可选，默认 ./data/indicators.duckdb
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import queue
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set

import duckdb
import pandas as pd
import tushare as ts
from tqdm import tqdm

# 自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "data"

# 三个独立数据库，各自独占连接，彻底避免 DuckDB 写入锁冲突
# 可通过环境变量覆盖路径
DAILY_DB_PATH   = Path(os.environ.get("DAILY_DB_PATH",   str(DATA_DIR / "daily_basic.duckdb")))
FINA_DB_PATH    = Path(os.environ.get("FINA_DB_PATH",    str(DATA_DIR / "fina_indicators.duckdb")))
DERIVED_DB_PATH = Path(os.environ.get("DERIVED_DB_PATH", str(DATA_DIR / "valuation_derived.duckdb")))

STOCKLIST = ROOT / "stocklist.csv"

# ── 日志 ──────────────────────────────────────────────────────────────────────
(ROOT / "logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "logs" / "fetch_stock_basics.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fetch_stock_basics")

# ── 限流配置 ──────────────────────────────────────────────────────────────────
BAN_PATTERNS  = ("访问频繁", "请稍后", "超过频率", "too many requests", "429", "403")
COOLDOWN_SECS = 60
RETRY_TIMES   = 3
FETCH_WORKERS = 4


# ══════════════════════════════════════════════════════════════════════════════
# 一、工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _looks_like_ban(exc: Exception) -> bool:
    return any(p in (str(exc) or "").lower() for p in BAN_PATTERNS)


def _cool_sleep(base: int = COOLDOWN_SECS) -> None:
    secs = max(1, int(base * random.uniform(0.9, 1.2)))
    logger.warning("疑似限流，冷却 %d 秒...", secs)
    time.sleep(secs)


def _call_with_retry(func, *args, **kwargs):
    """带重试 & 冷却（只在 worker 线程调用，不碰 DuckDB）。"""
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            result = func(*args, **kwargs)
            time.sleep(0.3)
            return result
        except Exception as e:
            if _looks_like_ban(e):
                _cool_sleep()
            elif attempt >= RETRY_TIMES:
                raise
            else:
                logger.warning("第 %d 次失败：%s，1s 后重试...", attempt, e)
                time.sleep(1)
    return None


def _strip_suffix(code: str) -> str:
    """000001.SH → 000001"""
    s = str(code)
    return s.split(".")[0].zfill(6) if "." in s else s.zfill(6)


def load_codes() -> List[str]:
    if not STOCKLIST.exists():
        raise FileNotFoundError(f"找不到 stocklist.csv：{STOCKLIST}")
    df  = pd.read_csv(STOCKLIST)
    col = "ts_code" if "ts_code" in df.columns else "symbol"
    codes = df[col].astype(str).tolist()
    logger.info("从 stocklist.csv 读取 %d 只股票", len(codes))
    return list(dict.fromkeys(codes))


def get_latest_trade_date(pro) -> str:
    today    = dt.date.today().strftime("%Y%m%d")
    lookback = (dt.date.today() - dt.timedelta(days=15)).strftime("%Y%m%d")
    cal_df   = _call_with_retry(
        pro.trade_cal, exchange="SSE", start_date=lookback, end_date=today, is_open="1"
    )
    if cal_df is None or cal_df.empty:
        raise ValueError("无法获取交易日历")
    latest = cal_df["cal_date"].max()
    logger.info("最新交易日：%s", latest)
    return latest


def get_all_trade_dates(pro, start: str, end: str) -> List[str]:
    cal_df = _call_with_retry(
        pro.trade_cal, exchange="SSE", start_date=start, end_date=end, is_open="1"
    )
    return sorted(cal_df["cal_date"].tolist()) if (cal_df is not None and not cal_df.empty) else []


def get_quarter_end_dates(start: str, end: str) -> List[str]:
    """生成 [start, end] 区间内所有季度末日期：0331/0630/0930/1231。"""
    quarters = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        for mmdd in ("0331", "0630", "0930", "1231"):
            d = f"{y}{mmdd}"
            if start <= d <= end:
                quarters.append(d)
    return sorted(quarters)


# ══════════════════════════════════════════════════════════════════════════════
# 一·五、元数据表（每个库各自一张，记录表级别的更新状态）
# ══════════════════════════════════════════════════════════════════════════════

META_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    table_name      VARCHAR PRIMARY KEY, -- 表名
    first_date      VARCHAR,             -- 数据起始日期 YYYYMMDD
    last_date       VARCHAR,             -- 数据最新日期 YYYYMMDD
    total_rows      BIGINT,              -- 当前表总行数
    is_full_init    INTEGER DEFAULT 0,   -- 是否完成全量初始化 1=是
    last_run_at     VARCHAR,             -- 上次脚本运行时间（ISO 8601）
    last_run_rows   BIGINT               -- 上次写入行数
)
"""


def _ensure_meta_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(META_DDL)


def _upsert_meta(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    last_run_rows: int,
    is_full_init: bool = False,
) -> None:
    """
    写入/更新 meta 表。
    first_date / last_date / total_rows 直接从目标表动态查询，保证准确。
    """
    _ensure_meta_table(conn)

    # 动态查当前表的实际状态
    date_col = "trade_date" if table_name in ("stock_daily_basic", "valuation_derived") else "end_date"
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


# ══════════════════════════════════════════════════════════════════════════════
# 二、stock_basic（股票基础信息，静态表，每次全量覆盖）
# ══════════════════════════════════════════════════════════════════════════════
#
# 用途：
#   - 回测股票池过滤：剔除ST（name LIKE '%ST%'）、退市、次新股等
#   - 获取上市日期、交易所、市场板块等基础属性
#   - 不需要按日快照，直接全量覆盖，保持最新状态即可
#
# ST判断（回测时）：
#   WHERE name NOT LIKE '%ST%' AND list_status = 'L'
# ══════════════════════════════════════════════════════════════════════════════

STOCK_BASIC_TABLE = "stock_basic"

STOCK_BASIC_DDL = f"""
CREATE TABLE IF NOT EXISTS {STOCK_BASIC_TABLE} (
    code        VARCHAR PRIMARY KEY,  -- 股票代码（去掉交易所后缀，如 000001）
    ts_code     VARCHAR,              -- Tushare 完整代码（如 000001.SZ）
    symbol      VARCHAR,              -- 股票代码（纯数字，如 000001）
    name        VARCHAR,              -- 股票名称（含ST/*ST前缀，直接用于过滤）
    fullname    VARCHAR,              -- 股票全称
    enname      VARCHAR,              -- 英文名称
    cnspell     VARCHAR,              -- 拼音缩写
    area        VARCHAR,              -- 所属地域
    industry    VARCHAR,              -- 所属行业（申万一级，供参考）
    market      VARCHAR,              -- 市场类型（主板/创业板/科创板/北交所）
    exchange    VARCHAR,              -- 交易所（SSE/SZSE/BSE）
    curr_type   VARCHAR,              -- 交易货币
    list_status VARCHAR,              -- 上市状态：L上市 D退市 P暂停
    list_date   VARCHAR,              -- 上市日期 YYYYMMDD
    delist_date VARCHAR,              -- 退市日期 YYYYMMDD
    is_hs       VARCHAR,              -- 是否沪深港通：N否 H沪股通 S深股通
    updated_at  VARCHAR               -- 本条记录更新时间
)
"""

STOCK_BASIC_IDX = [
    f"CREATE INDEX IF NOT EXISTS idx_sb_list_status ON {STOCK_BASIC_TABLE}(list_status)",
    f"CREATE INDEX IF NOT EXISTS idx_sb_market      ON {STOCK_BASIC_TABLE}(market)",
    f"CREATE INDEX IF NOT EXISTS idx_sb_exchange    ON {STOCK_BASIC_TABLE}(exchange)",
]


def _ensure_stock_basic_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(STOCK_BASIC_DDL)
    for idx in STOCK_BASIC_IDX:
        conn.execute(idx)
    _ensure_meta_table(conn)
    logger.info("✓ %s 表就绪", STOCK_BASIC_TABLE)


def run_stock_basic(pro, db_path: str) -> None:
    """
    拉取全量股票基础信息（L上市 + D退市 + P暂停），全量覆盖写入。
    一次请求拿全部，几秒内完成，建议每周跑一次保持最新。
    """
    logger.info("=" * 60)
    logger.info("stock_basic：拉取全量股票基础信息")

    all_frames = []
    for status in ("L", "D", "P"):
        df = _call_with_retry(
            pro.stock_basic,
            list_status=status,
            fields="ts_code,symbol,name,fullname,enname,cnspell,area,industry,"
                   "market,exchange,curr_type,list_status,list_date,delist_date,is_hs",
        )
        if df is not None and not df.empty:
            all_frames.append(df)
            logger.info("  list_status=%s：%d 条", status, len(df))
        time.sleep(0.3)

    if not all_frames:
        logger.error("stock_basic：未获取到任何数据")
        return

    df = pd.concat(all_frames, ignore_index=True)

    # 提取纯代码（去掉交易所后缀）作为 code 主键，与其他表对齐
    df["code"]       = df["ts_code"].str.split(".").str[0]
    df["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    cols = ["code", "ts_code", "symbol", "name", "fullname", "enname", "cnspell",
            "area", "industry", "market", "exchange", "curr_type",
            "list_status", "list_date", "delist_date", "is_hs", "updated_at"]
    # 补齐缺失列
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    try:
        _ensure_stock_basic_table(conn)

        # 全量覆盖：先清空再写入，保证退市/改名等变更被正确反映
        conn.execute(f"DELETE FROM {STOCK_BASIC_TABLE}")
        conn.register("_sb_staging", df)
        conn.execute(f"""
            INSERT INTO {STOCK_BASIC_TABLE} ({', '.join(cols)})
            SELECT {', '.join(cols)} FROM _sb_staging
        """)
        conn.unregister("_sb_staging")

        # 更新 meta（stock_basic 没有日期列，first_date/last_date 用 list_date 范围）
        first_date = df["list_date"].dropna().min()
        last_date  = df["list_date"].dropna().max()
        now        = dt.datetime.now(dt.timezone.utc).isoformat()
        _ensure_meta_table(conn)
        conn.execute("""
            INSERT INTO meta (table_name, first_date, last_date, total_rows,
                              is_full_init, last_run_at, last_run_rows)
            VALUES ('stock_basic', ?, ?, ?, 1, ?, ?)
            ON CONFLICT (table_name) DO UPDATE SET
                first_date    = excluded.first_date,
                last_date     = excluded.last_date,
                total_rows    = excluded.total_rows,
                is_full_init  = 1,
                last_run_at   = excluded.last_run_at,
                last_run_rows = excluded.last_run_rows
        """, [first_date, last_date, len(df), now, len(df)])

        conn.commit()
        logger.info("✅ stock_basic 完成：写入 %d 条（L/D/P 全状态）", len(df))

    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 三、表一：stock_daily_basic（每日估值 + 市值 + 流动性 + 基础信息）
# ══════════════════════════════════════════════════════════════════════════════

DAILY_TABLE = "stock_daily_basic"

DAILY_DDL = f"""
CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
    -- 主键
    code            VARCHAR NOT NULL,   -- 股票代码（关联 indicators.code）
    trade_date      VARCHAR NOT NULL,   -- 交易日期 YYYYMMDD

    -- 价格
    close           DOUBLE,             -- 收盘价（用于判断停牌）

    -- 估值（来自 daily_basic）
    pe_ttm          DOUBLE,             -- 市盈率 TTM
    pb              DOUBLE,             -- 市净率
    dv_ttm          DOUBLE,             -- 股息率 TTM %

    -- 市值（万元，来自 daily_basic）
    total_mv        DOUBLE,             -- 总市值
    circ_mv         DOUBLE,             -- 流通市值
    total_share     DOUBLE,             -- 总股本 万股（用于 PCF 计算）

    -- 流动性（来自 daily_basic）
    turnover_rate   DOUBLE,             -- 换手率 %
    volume_ratio    DOUBLE,             -- 量比

    -- 基础信息（来自 stock_basic，每日快照）
    is_st           INTEGER DEFAULT 0,  -- 是否ST 1=是
    list_date       VARCHAR,            -- 上市日期 YYYYMMDD

    PRIMARY KEY (code, trade_date)
)
"""

DAILY_IDX = [
    f"CREATE INDEX IF NOT EXISTS idx_sdb_date_code ON {DAILY_TABLE}(trade_date, code)",
    f"CREATE INDEX IF NOT EXISTS idx_sdb_code_date ON {DAILY_TABLE}(code, trade_date)",
    f"CREATE INDEX IF NOT EXISTS idx_sdb_total_mv  ON {DAILY_TABLE}(trade_date, total_mv)",
]


def _ensure_daily_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(DAILY_DDL)
    for idx in DAILY_IDX:
        conn.execute(idx)
    _ensure_meta_table(conn)
    logger.info("✓ %s 表就绪", DAILY_TABLE)


def _get_existing_daily_dates(conn: duckdb.DuckDBPyConnection) -> Set[str]:
    try:
        rows = conn.execute(f"SELECT DISTINCT trade_date FROM {DAILY_TABLE}").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _fetch_stock_basic(pro) -> pd.DataFrame:
    """拉取全市场股票基础信息（ST标记、上市日期），启动时拉一次复用。"""
    df = _call_with_retry(
        pro.stock_basic, exchange="", list_status="L",
        fields="ts_code,name,list_date"
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["code"]    = df["ts_code"].apply(_strip_suffix)
    df["is_st"]   = df["name"].str.contains("ST", na=False).astype(int)
    return df[["code", "list_date", "is_st"]]


# 期望的数值列，接口早期数据可能缺失部分列，一律补 NaN 不报错
_DAILY_BASIC_NUM_COLS = [
    "close", "pe_ttm", "pb", "dv_ttm",
    "total_mv", "circ_mv", "total_share",
    "turnover_rate", "volume_ratio",
]

_DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,pe_ttm,pb,dv_ttm,"
    "total_mv,circ_mv,total_share,turnover_rate,volume_ratio"
)

# 写入时的列顺序（动态过滤存在的列）
_DAILY_WRITE_COLS = [
    "code", "trade_date", "close",
    "pe_ttm", "pb", "dv_ttm",
    "total_mv", "circ_mv", "total_share",
    "turnover_rate", "volume_ratio",
    "is_st", "list_date",
]


def _fetch_daily_basic_one_date(pro, trade_date: str) -> pd.DataFrame:
    """按交易日拉全市场估值/市值/流动性，一次请求返回所有股票。"""
    df = _call_with_retry(
        pro.daily_basic,
        trade_date=trade_date,
        fields=_DAILY_BASIC_FIELDS,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["code"] = df["ts_code"].apply(_strip_suffix)
    df = df.drop(columns=["ts_code"])
    # 缺失列补 NaN，不 KeyError
    for col in _DAILY_BASIC_NUM_COLS:
        if col not in df.columns:
            df[col] = float("nan")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def run_daily_basic(pro, trade_dates: List[str], db_path: str) -> None:
    """
    拉取 stock_daily_basic：
      - Worker 线程池：按交易日并发拉 daily_basic（by_date，一次全市场）
      - 主线程 writer：消费队列，merge stock_basic 后串行写 DuckDB
    """
    if not trade_dates:
        logger.info("stock_daily_basic：无需更新")
        return

    logger.info("=" * 60)
    logger.info("stock_daily_basic：拉取 %d 个交易日", len(trade_dates))

    # 预拉 stock_basic（只需一次）
    logger.info("预拉 stock_basic ...")
    basic_df = _fetch_stock_basic(pro)
    logger.info("  → %d 只股票基础信息", len(basic_df))

    result_queue: queue.Queue = queue.Queue(maxsize=20)
    done_event  = threading.Event()
    stats = {"rows": 0, "ok": 0, "err": 0}
    pbar_lock = threading.Lock()

    fetch_pbar = tqdm(total=len(trade_dates), desc="[daily_basic] 拉取", unit="日", position=0)
    write_pbar = tqdm(total=len(trade_dates), desc="[daily_basic] 写入", unit="日", position=1, leave=True)

    # ── Writer（主线程独占 DuckDB 连接）──────────────────────────────────
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    _ensure_daily_table(conn)

    def writer_loop():
        while True:
            try:
                item = result_queue.get(timeout=120)
            except queue.Empty:
                logger.warning("[daily_basic] writer 超时退出")
                break
            if item is None:
                break
            trade_date, df = item
            if df is not None and not df.empty:
                # merge stock_basic（is_st / list_date）
                if not basic_df.empty:
                    df = df.merge(basic_df, on="code", how="left")
                    df["is_st"] = df["is_st"].fillna(0).astype(int)
                try:
                    cols = [c for c in _DAILY_WRITE_COLS if c in df.columns]
                    df = df[cols]
                    conn.register("_staging", df)
                    conn.execute(f"""
                        INSERT OR REPLACE INTO {DAILY_TABLE} ({', '.join(cols)})
                        SELECT {', '.join(cols)} FROM _staging
                    """)
                    conn.unregister("_staging")
                    stats["rows"] += len(df)
                    stats["ok"]   += 1
                except Exception as e:
                    logger.error("[daily_basic] 写入 %s 失败：%s", trade_date, e)
                    stats["err"] += 1
            else:
                stats["err"] += 1
            result_queue.task_done()
            write_pbar.set_postfix({"行": stats["rows"], "❌": stats["err"]})
            write_pbar.update(1)
        write_pbar.close()
        # meta 在 writer 线程里更新（持有连接）
        try:
            _upsert_meta(conn, DAILY_TABLE, stats["rows"],
                         is_full_init=(len(trade_dates) > 100))
            conn.commit()
        except Exception as e:
            logger.warning("meta 更新失败：%s", e)
        conn.close()
        done_event.set()

    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    # ── Worker（只做网络 I/O）────────────────────────────────────────────
    def fetch_worker(trade_date: str):
        try:
            df = _fetch_daily_basic_one_date(pro, trade_date)
            result_queue.put((trade_date, df))
            with pbar_lock:
                stats["ok"] += 0   # ok 在 writer 里统计
                fetch_pbar.update(1)
        except Exception as e:
            logger.error("[daily_basic] 拉取 %s 失败：%s", trade_date, e)
            result_queue.put((trade_date, None))
            with pbar_lock:
                fetch_pbar.update(1)

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = [executor.submit(fetch_worker, d) for d in trade_dates]
        for _ in as_completed(futures):
            pass

    fetch_pbar.close()
    result_queue.put(None)
    done_event.wait(timeout=600)
    writer_thread.join(timeout=60)

    logger.info("✅ stock_daily_basic 完成：写入 %d 行 / %d 日，失败 %d 日",
                stats["rows"], stats["ok"], stats["err"])


# ══════════════════════════════════════════════════════════════════════════════
# 三、表二：fina_indicators（财务指标，按报告期）
# ══════════════════════════════════════════════════════════════════════════════

FINA_TABLE = "fina_indicators"

FINA_DDL = f"""
CREATE TABLE IF NOT EXISTS {FINA_TABLE} (
    -- 主键
    code                VARCHAR NOT NULL,  -- 股票代码
    end_date            VARCHAR NOT NULL,  -- 报告期 YYYYMMDD（季度末）

    -- 附属信息
    ann_date            VARCHAR,           -- 公告日期

    -- 盈利能力
    roe                 DOUBLE,            -- 净资产收益率 %
    roa                 DOUBLE,            -- 总资产报酬率 %
    roic                DOUBLE,            -- 投入资本回报率 %
    netprofit_margin    DOUBLE,            -- 销售净利率 %
    grossprofit_margin  DOUBLE,            -- 销售毛利率 %

    -- 增长
    or_yoy              DOUBLE,            -- 营业收入同比增长率 %
    netprofit_yoy       DOUBLE,            -- 净利润同比增长率 %
    tr_yoy              DOUBLE,            -- 营业总收入同比增长率 %

    -- 偿债
    debt_to_assets      DOUBLE,            -- 资产负债率 %
    current_ratio       DOUBLE,            -- 流动比率
    quick_ratio         DOUBLE,            -- 速动比率

    -- 现金流
    fcff                DOUBLE,            -- 企业自由现金流 万元
    ocf_yoy             DOUBLE,            -- 经营现金流同比增长率 %
    ocfps               DOUBLE,            -- 每股经营现金流（用于 PCF 计算）

    -- EV/EBITDA 所需
    ebitda              DOUBLE,            -- 息税折旧摊销前利润 万元
    netdebt             DOUBLE,            -- 净债务 万元（EV = 总市值 + 净债务）
    interestdebt        DOUBLE,            -- 带息债务 万元

    -- 每股
    eps                 DOUBLE,            -- 基本每股收益
    bps                 DOUBLE,            -- 每股净资产

    PRIMARY KEY (code, end_date)
)
"""

FINA_IDX = [
    f"CREATE INDEX IF NOT EXISTS idx_fina_code_end  ON {FINA_TABLE}(code, end_date)",
    f"CREATE INDEX IF NOT EXISTS idx_fina_end_code  ON {FINA_TABLE}(end_date, code)",
]

FINA_FIELDS = (
    "ts_code,ann_date,end_date,"
    "roe,roa,roic,netprofit_margin,grossprofit_margin,"
    "or_yoy,netprofit_yoy,tr_yoy,"
    "debt_to_assets,current_ratio,quick_ratio,"
    "fcff,ocf_yoy,ocfps,"
    "ebitda,netdebt,interestdebt,"
    "eps,bps"
)

_FINA_NUM_COLS = [
    "roe", "roa", "roic", "netprofit_margin", "grossprofit_margin",
    "or_yoy", "netprofit_yoy", "tr_yoy",
    "debt_to_assets", "current_ratio", "quick_ratio",
    "fcff", "ocf_yoy", "ocfps",
    "ebitda", "netdebt", "interestdebt",
    "eps", "bps",
]

_FINA_WRITE_COLS = [
    "code", "end_date", "ann_date",
    "roe", "roa", "roic", "netprofit_margin", "grossprofit_margin",
    "or_yoy", "netprofit_yoy", "tr_yoy",
    "debt_to_assets", "current_ratio", "quick_ratio",
    "fcff", "ocf_yoy", "ocfps",
    "ebitda", "netdebt", "interestdebt",
    "eps", "bps",
]


def _ensure_fina_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(FINA_DDL)
    for idx in FINA_IDX:
        conn.execute(idx)
    _ensure_meta_table(conn)
    logger.info("✓ %s 表就绪", FINA_TABLE)


def _get_existing_fina_periods(conn: duckdb.DuckDBPyConnection) -> Set[str]:
    try:
        rows = conn.execute(f"SELECT DISTINCT end_date FROM {FINA_TABLE}").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _fetch_fina_one_period(pro, period: str) -> pd.DataFrame:
    """按报告期拉全市场财务数据（fina_indicator_vip，一次返回所有股票）。"""
    df = _call_with_retry(
        pro.fina_indicator_vip,
        period=period,
        fields=FINA_FIELDS,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df["code"] = df["ts_code"].apply(_strip_suffix)
    df = df.drop(columns=["ts_code"])
    for col in _FINA_NUM_COLS:
        if col not in df.columns:
            df[col] = float("nan")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def run_fina_indicators(pro, start: str, end: str, db_path: str) -> None:
    """
    拉取 fina_indicators：
      - 按季度末（0331/0630/0930/1231）逐个拉全市场
      - 已存在的报告期跳过（增量）
      - 单线程顺序拉取（每期间隔 0.5s，不会限流）
      - 主线程直接写入 DuckDB（无需 Queue，数据量小）
    """
    logger.info("=" * 60)
    logger.info("fina_indicators：计算报告期范围 %s → %s", start, end)

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    _ensure_fina_table(conn)

    # 查已有报告期，跳过已拉取的
    existing_periods = _get_existing_fina_periods(conn)
    all_periods      = get_quarter_end_dates(start, end)
    todo_periods     = [p for p in all_periods if p not in existing_periods]

    if not todo_periods:
        logger.info("fina_indicators：所有报告期已存在，无需更新 ✅")
        conn.close()
        return

    logger.info("fina_indicators：共 %d 个报告期，需拉取 %d 个（跳过 %d 个已有）",
                len(all_periods), len(todo_periods), len(existing_periods))

    stats = {"rows": 0, "ok": 0, "err": 0}
    pbar  = tqdm(total=len(todo_periods), desc="[fina_indicators]", unit="期")

    for period in todo_periods:
        pbar.set_description(f"[fina] 报告期 {period}")
        try:
            df = _fetch_fina_one_period(pro, period)
            if df.empty:
                logger.warning("  %s 返回空，跳过", period)
                stats["err"] += 1
                pbar.update(1)
                continue

            cols = [c for c in _FINA_WRITE_COLS if c in df.columns]
            df = df[cols]
            conn.register("_staging", df)
            conn.execute(f"""
                INSERT OR REPLACE INTO {FINA_TABLE} ({', '.join(cols)})
                SELECT {', '.join(cols)} FROM _staging
            """)
            conn.unregister("_staging")
            conn.commit()

            stats["rows"] += len(df)
            stats["ok"]   += 1
            logger.info("  ✓ %s：%d 只股票", period, len(df))

        except Exception as e:
            logger.error("  ✗ %s 失败：%s", period, e)
            stats["err"] += 1

        pbar.update(1)
        time.sleep(0.5)   # 礼貌延迟

    pbar.close()
    try:
        _upsert_meta(conn, FINA_TABLE, stats["rows"],
                     is_full_init=(len(todo_periods) > 20))
        conn.commit()
    except Exception as e:
        logger.warning("meta 更新失败：%s", e)
    conn.close()

    logger.info("✅ fina_indicators 完成：写入 %d 行 / %d 期，失败 %d 期",
                stats["rows"], stats["ok"], stats["err"])


# ══════════════════════════════════════════════════════════════════════════════
# 四、衍生估值指标计算（PE/PB/PCF/PEG/EV_EBITDA/PB_ROE）
# ══════════════════════════════════════════════════════════════════════════════

DERIVED_TABLE = "valuation_derived"

DERIVED_DDL = f"""
CREATE TABLE IF NOT EXISTS {DERIVED_TABLE} (
    -- 主键
    code            VARCHAR NOT NULL,   -- 股票代码
    trade_date      VARCHAR NOT NULL,   -- 交易日期 YYYYMMDD

    -- 匹配的财务报告期
    fina_end_date   VARCHAR,            -- 使用的财务数据报告期

    -- 衍生估值指标
    pe              DOUBLE,             -- 市盈率（pe_ttm，直接来自 daily_basic）
    pb              DOUBLE,             -- 市净率（直接来自 daily_basic）
    pcf             DOUBLE,             -- 市现率（总市值 / 经营现金流）
    peg             DOUBLE,             -- PEG（pe_ttm / 净利润增速）
    ev_ebitda       DOUBLE,             -- EV/EBITDA（(总市值+净债务) / EBITDA）
    pb_roe          DOUBLE,             -- PB/ROE（衡量估值性价比）

    PRIMARY KEY (code, trade_date)
)
"""

DERIVED_IDX = [
    f"CREATE INDEX IF NOT EXISTS idx_der_date_code ON {DERIVED_TABLE}(trade_date, code)",
    f"CREATE INDEX IF NOT EXISTS idx_der_code_date ON {DERIVED_TABLE}(code, trade_date)",
]


def _ensure_derived_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(DERIVED_DDL)
    for idx in DERIVED_IDX:
        conn.execute(idx)
    _ensure_meta_table(conn)
    logger.info("✓ %s 表就绪", DERIVED_TABLE)


def run_derived_valuation(
    daily_db: str,
    fina_db: str,
    derived_db: str,
    trade_dates: List[str],
) -> None:
    """
    从 daily_basic.duckdb 和 fina_indicators.duckdb 计算衍生估值指标，
    写入 valuation_derived.duckdb。

    用 DuckDB ATTACH 跨库读取，各库仍然独立，不共享连接。
    不调 Tushare，纯 SQL + pandas 计算。
    """
    if not trade_dates:
        return

    logger.info("=" * 60)
    logger.info("valuation_derived：计算 %d 个交易日的衍生估值指标", len(trade_dates))

    # derived 库作为主连接，ATTACH 另外两个库只读
    conn = duckdb.connect(derived_db)
    _ensure_derived_table(conn)
    conn.execute(f"ATTACH '{daily_db}' AS daily_db (READ_ONLY)")
    conn.execute(f"ATTACH '{fina_db}'  AS fina_db  (READ_ONLY)")

    dates_list = ", ".join(f"'{d}'" for d in trade_dates)

    # DuckDB 对 INSERT + CTE 有内部 bug，改为：
    # 1. 用纯 SELECT + CTE 把结果拉成 DataFrame
    # 2. 在 Python 里计算衍生指标
    # 3. 用 register + INSERT 写入（不带 CTE）
    select_sql = f"""
    WITH latest_fina AS (
        SELECT
            d.code,
            d.trade_date,
            f.end_date          AS fina_end_date,
            d.pe_ttm,
            d.pb,
            d.total_mv,
            d.total_share,
            f.netprofit_yoy,
            f.ocfps,
            f.ebitda,
            f.netdebt,
            f.roe,
            ROW_NUMBER() OVER (
                PARTITION BY d.code, d.trade_date
                ORDER BY f.ann_date DESC
            ) AS rn
        FROM daily_db.{DAILY_TABLE} d
        LEFT JOIN fina_db.{FINA_TABLE} f
            ON  d.code = f.code
            AND f.ann_date <= d.trade_date
        WHERE d.trade_date IN ({dates_list})
    )
    SELECT * FROM latest_fina WHERE rn = 1
    """

    try:
        # SELECT 拉成 DataFrame
        df = conn.execute(select_sql).df()

        if df.empty:
            logger.warning("valuation_derived：查询结果为空，跳过")
            return

        # 在 pandas 里计算衍生指标
        df["pe"]       = pd.to_numeric(df["pe_ttm"], errors="coerce")
        df["pb"]       = pd.to_numeric(df["pb"],     errors="coerce")

        ocf_total      = df["ocfps"] * df["total_share"]
        df["pcf"]      = df["total_mv"].where(ocf_total > 0) / ocf_total

        df["peg"]      = df["pe_ttm"].where(
                             (df["pe_ttm"] > 0) & (df["netprofit_yoy"] > 0)
                         ) / df["netprofit_yoy"]

        ev             = df["total_mv"] + df["netdebt"].fillna(0)
        df["ev_ebitda"]= ev.where(df["ebitda"] > 0) / df["ebitda"]

        df["pb_roe"]   = df["pb"].where(df["roe"] > 0) / df["roe"]

        # 只保留目标列
        out_cols = ["code", "trade_date", "fina_end_date",
                    "pe", "pb", "pcf", "peg", "ev_ebitda", "pb_roe"]
        df = df[out_cols]

        # 先删旧数据，再插入
        conn.execute(f"DELETE FROM {DERIVED_TABLE} WHERE trade_date IN ({dates_list})")
        conn.register("_derived_staging", df)
        conn.execute(f"""
            INSERT INTO {DERIVED_TABLE} ({', '.join(out_cols)})
            SELECT {', '.join(out_cols)} FROM _derived_staging
        """)
        conn.unregister("_derived_staging")
        conn.commit()

        _upsert_meta(conn, DERIVED_TABLE, len(df),
                     is_full_init=(len(trade_dates) > 100))
        conn.commit()
        logger.info("✅ valuation_derived 完成：写入 %d 行", len(df))

    except Exception as e:
        logger.error("valuation_derived 计算失败：%s", e)
        raise
    finally:
        try:
            conn.execute("DETACH daily_db")
            conn.execute("DETACH fina_db")
        except Exception:
            pass
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 五、主入口
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    global FETCH_WORKERS

    parser = argparse.ArgumentParser(description="拉取每日估值 & 财务数据写入 DuckDB")
    parser.add_argument("--mode",       choices=["full", "incremental"], default="incremental",
                        help="full=全量历史，incremental=增量（默认）")
    parser.add_argument("--date",       help="指定单日 YYYYMMDD（仅影响 stock_daily_basic）")
    parser.add_argument("--start",      default="20150101", help="全量起始日期（默认 20150101）")
    parser.add_argument("--daily-db",   default=str(DAILY_DB_PATH),
                        help="stock_daily_basic 库路径")
    parser.add_argument("--fina-db",    default=str(FINA_DB_PATH),
                        help="fina_indicators 库路径")
    parser.add_argument("--derived-db", default=str(DERIVED_DB_PATH),
                        help="valuation_derived 库路径")
    parser.add_argument("--workers",    type=int, default=FETCH_WORKERS,
                        help=f"daily_basic 并发线程数（默认 {FETCH_WORKERS}）")
    parser.add_argument("--only",       choices=["stock_basic", "daily", "fina", "derived"],
                        default=None, help="只更新指定表（默认全部）")
    args = parser.parse_args()
    FETCH_WORKERS = args.workers

    # ── Tushare 初始化 ────────────────────────────────────────────────────
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        raise EnvironmentError("请设置环境变量 TUSHARE_TOKEN")
    ts.set_token(ts_token)
    pro = ts.pro_api()
    logger.info("✓ Tushare 初始化完成")

    daily_db   = args.daily_db
    fina_db    = args.fina_db
    derived_db = args.derived_db
    today      = dt.date.today().strftime("%Y%m%d")

    logger.info("数据库路径：")
    logger.info("  daily    → %s", daily_db)
    logger.info("  fina     → %s", fina_db)
    logger.info("  derived  → %s", derived_db)

    trade_dates: List[str] = []

    # ══════════════════════════════════════════════════════════════════════
    # stock_basic → daily_basic.duckdb（全量覆盖，每次都跑）
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "stock_basic", "daily"):
        run_stock_basic(pro, daily_db)

    # ══════════════════════════════════════════════════════════════════════
    # stock_daily_basic → daily_basic.duckdb
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "daily"):

        if args.date:
            trade_dates = [args.date.replace("-", "")]

        elif args.mode == "full":
            trade_dates = get_all_trade_dates(pro, args.start, today)
            logger.info("全量模式：共 %d 个交易日", len(trade_dates))

        else:  # incremental
            latest = get_latest_trade_date(pro)
            existing: Set[str] = set()
            if Path(daily_db).exists():
                tmp = duckdb.connect(daily_db, read_only=True)
                existing = _get_existing_daily_dates(tmp)
                tmp.close()
            trade_dates = [latest] if latest not in existing else []
            if not trade_dates:
                logger.info("stock_daily_basic 已是最新（%s），跳过", latest)

        run_daily_basic(pro, trade_dates, daily_db)

    # ══════════════════════════════════════════════════════════════════════
    # fina_indicators → fina_indicators.duckdb
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "fina"):

        if args.mode == "full":
            fina_start = args.start
        else:
            fina_start = (dt.date.today() - dt.timedelta(days=200)).strftime("%Y%m%d")

        run_fina_indicators(pro, fina_start, today, fina_db)

    # ══════════════════════════════════════════════════════════════════════
    # valuation_derived → valuation_derived.duckdb（跨库 ATTACH 读取）
    # ══════════════════════════════════════════════════════════════════════
    if args.only in (None, "daily", "fina", "derived"):
        if not trade_dates:
            latest = get_latest_trade_date(pro)
            derived_dates = [latest]
        else:
            derived_dates = trade_dates
        run_derived_valuation(daily_db, fina_db, derived_db, derived_dates)


if __name__ == "__main__":
    main()