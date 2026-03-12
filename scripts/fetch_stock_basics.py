#!/usr/bin/env python3
"""
股票每日财务 & 估值数据拉取脚本（配置化版）

════════════════════════════════════════════════════════════
  ★ 扩展新数据只需修改 DATA_SOURCES 字典，无需改其他代码 ★
════════════════════════════════════════════════════════════

DATA_SOURCES 中每个条目描述一个 Tushare 接口：
  fetch_mode:
    "by_date" → pro.<api>(trade_date=...) 按日全量拉，一次返回全市场
    "by_code" → pro.<api>(ts_code=...)    按股逐只拉，取 sort_by 最新一条
    "once"    → 启动时拉一次，广播给每个交易日（静态信息，如 stock_basic）

表名：stock_daily_basic
主键：(code, trade_date)

架构：
  Worker 线程池 → 只做 Tushare HTTP（严禁碰 DuckDB）
  主线程 writer → 消费 Queue，串行写 DuckDB（唯一持有连接，彻底避免文件锁）

用法：
  python fetch_stock_basics.py                       # 每日增量
  python fetch_stock_basics.py --mode full           # 首次全量
  python fetch_stock_basics.py --date 20250103       # 指定单日
  python fetch_stock_basics.py --sources daily_basic # 只跑指定数据源

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
from typing import Any, Dict, List, Optional

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
DB_PATH   = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "indicators.duckdb")))
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

# ── 限流 ──────────────────────────────────────────────────────────────────────
BAN_PATTERNS  = ("访问频繁", "请稍后", "超过频率", "too many requests", "429", "403")
COOLDOWN_SECS = 60
RETRY_TIMES   = 3
FETCH_WORKERS = 4


# ══════════════════════════════════════════════════════════════════════════════
#  ★ 核心配置：在这里增删改数据源，其他代码完全不需要动 ★
#
#  col_defs 格式：{ 列名: ("DuckDB类型", "注释") }
#  字段定义写一次，自动驱动：建表 DDL / ALTER TABLE 补列 / 类型转换 / UPSERT
# ══════════════════════════════════════════════════════════════════════════════

DATA_SOURCES: Dict[str, Dict[str, Any]] = {

    # ── 1. 每日行情基础（估值 + 市值 + 流动性）────────────────────────────
    "daily_basic": {
        "fetch_mode" : "by_date",
        "api_func"   : "daily_basic",
        "fields"     : "ts_code,trade_date,pe_ttm,pb,dv_ttm,total_mv,circ_mv,"
                       "turnover_rate,volume_ratio,amount",
        "rename"     : {"ts_code": "code"},
        "key_col"    : "code",
        "extra_args" : {},
        "sort_by"    : None,
        "merge_on"   : ["code", "trade_date"],
        "col_defs"   : {
            "pe_ttm"        : ("DOUBLE", "市盈率 TTM"),
            "pb"            : ("DOUBLE", "市净率"),
            "dv_ttm"        : ("DOUBLE", "股息率 近12月 %"),
            "total_mv"      : ("DOUBLE", "总市值 万元"),
            "circ_mv"       : ("DOUBLE", "流通市值 万元"),
            "turnover_rate" : ("DOUBLE", "换手率 %"),
            "volume_ratio"  : ("DOUBLE", "量比"),
            "amount"        : ("DOUBLE", "成交额 万元"),
        },
    },

    # ── 2. 财务质量指标（季报/年报最新一期）──────────────────────────────
    "fina_indicator": {
        "fetch_mode" : "by_code",
        "api_func"   : "fina_indicator",
        "fields"     : "ts_code,ann_date,end_date,roe,or_yoy,netprofit_yoy,"
                       "grossprofit_margin,debt_to_assets,fcff",
        "rename"     : {"ts_code": "code"},
        "key_col"    : "code",
        "extra_args" : {"start_date": "20100101"},
        "sort_by"    : "end_date",      # 取报告期最新一条
        "merge_on"   : ["code"],        # 财务数据无 trade_date，只按 code merge
        "col_defs"   : {
            "roe"                : ("DOUBLE", "净资产收益率 %"),
            "or_yoy"             : ("DOUBLE", "营业收入同比增长率 %"),
            "netprofit_yoy"      : ("DOUBLE", "净利润同比增长率 %"),
            "grossprofit_margin" : ("DOUBLE", "毛利率 %"),
            "debt_to_assets"     : ("DOUBLE", "资产负债率 %"),
            "fcff"               : ("DOUBLE", "企业自由现金流 万元"),
        },
    },

    # ── 3. 股票基础信息（ST标记、上市日期）—— 只拉一次 ───────────────────
    "stock_basic": {
        "fetch_mode" : "once",
        "api_func"   : "stock_basic",
        "fields"     : "ts_code,name,list_date",
        "rename"     : {"ts_code": "code"},
        "key_col"    : "code",
        "extra_args" : {"exchange": "", "list_status": "L"},
        "sort_by"    : None,
        "merge_on"   : ["code"],
        "postprocess": "stock_basic",   # 注册在 _POSTPROCESS_REGISTRY 里的函数名
        "col_defs"   : {
            "is_st"     : ("INTEGER", "是否ST 1=是"),
            "list_date" : ("VARCHAR",  "上市日期 YYYYMMDD"),
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    # ★ 在下方粘贴新数据源条目，其余代码零改动 ★
    #
    # 示例 A：资金流向（by_date）
    # "moneyflow": {
    #     "fetch_mode" : "by_date",
    #     "api_func"   : "moneyflow",
    #     "fields"     : "ts_code,trade_date,net_mf_amount,net_mf_vol",
    #     "rename"     : {"ts_code": "code"},
    #     "key_col"    : "code",
    #     "extra_args" : {},
    #     "sort_by"    : None,
    #     "merge_on"   : ["code", "trade_date"],
    #     "col_defs"   : {
    #         "net_mf_amount" : ("DOUBLE", "净流入额 万元"),
    #         "net_mf_vol"    : ("DOUBLE", "净流入量 手"),
    #     },
    # },
    #
    # 示例 B：龙虎榜（by_date）
    # "top_list": {
    #     "fetch_mode" : "by_date",
    #     "api_func"   : "top_list",
    #     "fields"     : "ts_code,trade_date,net_amount,buy_amount,sell_amount",
    #     "rename"     : {"ts_code": "code"},
    #     "key_col"    : "code",
    #     "extra_args" : {},
    #     "sort_by"    : None,
    #     "merge_on"   : ["code", "trade_date"],
    #     "col_defs"   : {
    #         "lhb_net_amount"  : ("DOUBLE", "龙虎榜净买入额 万元"),
    #         "lhb_buy_amount"  : ("DOUBLE", "龙虎榜买入额 万元"),
    #         "lhb_sell_amount" : ("DOUBLE", "龙虎榜卖出额 万元"),
    #     },
    # },
    # ══════════════════════════════════════════════════════════════════════
}

# ── 主表固定列（主键，不来自任何数据源）────────────────────────────────────
_BASE_COLS: Dict[str, tuple] = {
    "code"       : ("VARCHAR NOT NULL", "股票代码 关联 indicators.code"),
    "trade_date" : ("VARCHAR NOT NULL", "交易日期 YYYYMMDD"),
}

TABLE_NAME = "stock_daily_basic"
TABLE_IDX  = [
    f"CREATE INDEX IF NOT EXISTS idx_sdb_date_code ON {TABLE_NAME}(trade_date, code)",
    f"CREATE INDEX IF NOT EXISTS idx_sdb_code_date ON {TABLE_NAME}(code, trade_date)",
]


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
            time.sleep(0.2)
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


def _to_ts_code(code: str) -> str:
    if "." in code:
        return code
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


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


# ══════════════════════════════════════════════════════════════════════════════
# 二、后处理函数注册表
#   某些接口需要在原始 DataFrame 上做额外变换，在此注册。
#   若新数据源也需要后处理，只需在此添加函数，并在 DATA_SOURCES 里写 "postprocess": "函数名"
# ══════════════════════════════════════════════════════════════════════════════

def _pp_stock_basic(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_st"] = df["name"].str.contains("ST", na=False).astype(int)
    return df[["code", "list_date", "is_st"]]


_POSTPROCESS_REGISTRY: Dict[str, Any] = {
    "stock_basic": _pp_stock_basic,
    # "my_source": _pp_my_source,
}


# ══════════════════════════════════════════════════════════════════════════════
# 三、动态建表 & 写入（仅主线程调用）
# ══════════════════════════════════════════════════════════════════════════════

def _build_ddl(sources: Dict[str, Any]) -> str:
    """根据 DATA_SOURCES 动态生成建表 DDL，字段定义零重复。"""
    lines = []
    for col, (dtype, comment) in _BASE_COLS.items():
        lines.append(f"    {col:<28} {dtype},  -- {comment}")
    seen = set(_BASE_COLS.keys())
    for src_name, src in sources.items():
        lines.append(f"\n    -- [{src_name}]")
        for col, (dtype, comment) in src["col_defs"].items():
            if col in seen:
                continue
            seen.add(col)
            lines.append(f"    {col:<28} {dtype},  -- {comment}")
    lines.append(f"\n    PRIMARY KEY (code, trade_date)")
    return f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} (\n" + "\n".join(lines) + "\n)"


def ensure_table(conn: duckdb.DuckDBPyConnection, sources: Dict[str, Any]) -> None:
    """建表 + 索引（幂等）；若后续新增数据源，自动 ALTER TABLE 补列。"""
    conn.execute(_build_ddl(sources))
    for idx in TABLE_IDX:
        conn.execute(idx)
    # 自动补列：新增数据源时无需手动 ALTER TABLE
    existing_cols = {row[0] for row in conn.execute(f"DESCRIBE {TABLE_NAME}").fetchall()}
    for src in sources.values():
        for col, (dtype, _) in src["col_defs"].items():
            if col not in existing_cols:
                base_type = dtype.split()[0]
                conn.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS {col} {base_type}")
                logger.info("  ✓ 自动新增列：%s %s", col, base_type)
    logger.info("✓ %s 表 & 索引已就绪", TABLE_NAME)


def upsert_batch(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """动态 UPSERT，列名完全从 df.columns 推断，无任何硬编码。主线程专用。"""
    if df.empty:
        return 0
    cols     = df.columns.tolist()
    col_list = ", ".join(cols)
    conn.register("_staging", df)
    conn.execute(f"INSERT OR REPLACE INTO {TABLE_NAME} ({col_list}) SELECT {col_list} FROM _staging")
    conn.unregister("_staging")
    return len(df)


def get_existing_dates(conn: duckdb.DuckDBPyConnection) -> set:
    try:
        return {r[0] for r in conn.execute(f"SELECT DISTINCT trade_date FROM {TABLE_NAME}").fetchall()}
    except Exception:
        return set()


# ══════════════════════════════════════════════════════════════════════════════
# 四、通用 Tushare 拉取器（worker 线程，严禁碰 DuckDB）
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(df: pd.DataFrame, src: Dict) -> pd.DataFrame:
    """统一后处理：rename → strip code suffix → postprocess → 数值类型转换。"""
    if src.get("rename"):
        df = df.rename(columns=src["rename"])
    if src["key_col"] in df.columns:
        df[src["key_col"]] = df[src["key_col"]].apply(_strip_suffix)
    pp_key = src.get("postprocess")
    if pp_key and pp_key in _POSTPROCESS_REGISTRY:
        df = _POSTPROCESS_REGISTRY[pp_key](df)
    for col, (dtype, _) in src["col_defs"].items():
        if col not in df.columns:
            continue
        if dtype.upper() == "DOUBLE":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif "INTEGER" in dtype.upper():
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def _fetch_by_date(pro, src: Dict, trade_date: str) -> pd.DataFrame:
    api_fn = getattr(pro, src["api_func"])
    df = _call_with_retry(api_fn, trade_date=trade_date,
                          fields=src["fields"], **src.get("extra_args", {}))
    if df is None or df.empty:
        return pd.DataFrame()
    df = _normalize(df, src)
    df["trade_date"] = trade_date
    return df


def _fetch_by_code(pro, src: Dict, code: str, trade_date: str) -> pd.DataFrame:
    api_fn = getattr(pro, src["api_func"])
    df = _call_with_retry(api_fn, ts_code=_to_ts_code(code),
                          fields=src["fields"], end_date=trade_date,
                          **src.get("extra_args", {}))
    if df is None or df.empty:
        return pd.DataFrame()
    df = _normalize(df, src)
    if src.get("sort_by") and src["sort_by"] in df.columns:
        df = df.sort_values(src["sort_by"], ascending=False).head(1)
    df["trade_date"] = trade_date
    return df


def _fetch_once(pro, src: Dict) -> pd.DataFrame:
    api_fn = getattr(pro, src["api_func"])
    df = _call_with_retry(api_fn, fields=src["fields"], **src.get("extra_args", {}))
    if df is None or df.empty:
        return pd.DataFrame()
    return _normalize(df, src)


# ══════════════════════════════════════════════════════════════════════════════
# 五、单日数据拼装（worker 线程，严禁碰 DuckDB）
# ══════════════════════════════════════════════════════════════════════════════

def fetch_one_date(
    pro,
    trade_date: str,
    codes: List[str],
    once_data: Dict[str, pd.DataFrame],
    active_sources: Dict[str, Dict],
) -> pd.DataFrame:
    """拉取单个交易日所有数据源，合并成宽表返回。不碰 DuckDB。"""
    result_df: Optional[pd.DataFrame] = None

    for src_name, src in active_sources.items():
        mode = src["fetch_mode"]
        try:
            if mode == "by_date":
                src_df = _fetch_by_date(pro, src, trade_date)

            elif mode == "by_code":
                parts = []
                for code in codes:
                    try:
                        part = _fetch_by_code(pro, src, code, trade_date)
                        if not part.empty:
                            parts.append(part)
                    except Exception as e:
                        logger.debug("by_code %s %s 失败：%s", src_name, code, e)
                src_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

            elif mode == "once":
                src_df = once_data.get(src_name, pd.DataFrame()).copy()
                if not src_df.empty:
                    src_df["trade_date"] = trade_date
            else:
                logger.warning("未知 fetch_mode：%s，跳过 %s", mode, src_name)
                continue

        except Exception as e:
            logger.error("拉取 %s @ %s 失败：%s", src_name, trade_date, e)
            continue

        if src_df.empty:
            logger.debug("%s @ %s 返回空", src_name, trade_date)
            continue

        # 合并到主宽表
        merge_keys = src["merge_on"]
        if result_df is None:
            result_df = src_df
        else:
            keep_cols = merge_keys + [c for c in src["col_defs"] if c in src_df.columns]
            result_df = result_df.merge(
                src_df[keep_cols].drop_duplicates(subset=merge_keys),
                on=merge_keys,
                how="left",
            )

    return result_df if result_df is not None else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# 六、调度主循环（Producer-Consumer，DuckDB 只在主线程）
# ══════════════════════════════════════════════════════════════════════════════

def run(pro, trade_dates: List[str], codes: List[str],
        db_path: str, active_sources: Dict[str, Dict]) -> None:
    """
    Worker 线程池 → 只做 Tushare 网络 I/O，结果放入 Queue
    主线程 writer  → 消费 Queue，串行写 DuckDB（唯一持有连接）
    """
    result_queue: queue.Queue = queue.Queue(maxsize=20)
    done_event  = threading.Event()
    write_stats = {"rows": 0, "dates": 0, "errors": 0}

    # ── 预拉 once 数据 ───────────────────────────────────────────────────
    once_data: Dict[str, pd.DataFrame] = {}
    for src_name, src in active_sources.items():
        if src["fetch_mode"] == "once":
            logger.info("预拉 %s ...", src_name)
            once_data[src_name] = _fetch_once(pro, src)
            logger.info("  → %d 行", len(once_data[src_name]))

    # ── 建表（主线程）────────────────────────────────────────────────────
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    ensure_table(conn, active_sources)

    # ── writer loop（主线程）─────────────────────────────────────────────
    def writer_loop():
        pbar = tqdm(total=len(trade_dates), desc="写入进度", unit="日")
        while True:
            try:
                item = result_queue.get(timeout=180)
            except queue.Empty:
                logger.warning("writer 等待超时，退出")
                break
            if item is None:
                break
            trade_date, df = item
            if df is not None and not df.empty:
                try:
                    write_stats["rows"]  += upsert_batch(conn, df)
                    write_stats["dates"] += 1
                except Exception as e:
                    logger.error("写入 %s 失败：%s", trade_date, e)
                    write_stats["errors"] += 1
            else:
                write_stats["errors"] += 1
            result_queue.task_done()
            pbar.update(1)
        pbar.close()
        conn.commit()
        conn.close()
        done_event.set()

    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    # ── worker 线程池（只做网络 I/O）────────────────────────────────────
    def fetch_worker(trade_date: str):
        try:
            df = fetch_one_date(pro, trade_date, codes, once_data, active_sources)
            result_queue.put((trade_date, df))
        except Exception as e:
            logger.error("拉取 %s 失败：%s", trade_date, e)
            result_queue.put((trade_date, None))

    logger.info("开始拉取 %d 个交易日（%d worker）...", len(trade_dates), FETCH_WORKERS)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = [executor.submit(fetch_worker, d) for d in trade_dates]
        for _ in as_completed(futures):
            pass

    result_queue.put(None)
    done_event.wait(timeout=600)
    writer_thread.join(timeout=60)

    logger.info("✅ 完成！写入 %d 行 / %d 日，失败 %d 日",
                write_stats["rows"], write_stats["dates"], write_stats["errors"])


# ══════════════════════════════════════════════════════════════════════════════
# 七、主入口
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="拉取每日财务&估值数据 → stock_daily_basic")
    parser.add_argument("--mode",    choices=["full", "incremental"], default="incremental")
    parser.add_argument("--date",    help="指定单日 YYYYMMDD（覆盖 mode）")
    parser.add_argument("--start",   default="20150101", help="全量起始日期")
    parser.add_argument("--db",      default=str(DB_PATH))
    parser.add_argument("--workers", type=int, default=FETCH_WORKERS)
    parser.add_argument(
        "--sources", nargs="*", default=None,
        choices=list(DATA_SOURCES.keys()),
        help="只运行指定数据源（默认全部）",
    )
    args = parser.parse_args()

    global FETCH_WORKERS
    FETCH_WORKERS = args.workers

    # Tushare 初始化
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        raise EnvironmentError("请设置环境变量 TUSHARE_TOKEN")
    ts.set_token(ts_token)
    pro = ts.pro_api()
    logger.info("✓ Tushare 初始化完成")

    # 选择激活数据源
    active_sources = (
        {k: DATA_SOURCES[k] for k in args.sources} if args.sources else DATA_SOURCES
    )
    logger.info("激活数据源：%s", list(active_sources.keys()))

    # 股票池
    codes = load_codes()

    # 确定交易日列表
    if args.date:
        trade_dates = [args.date.replace("-", "")]
        logger.info("单日模式：%s", trade_dates[0])

    elif args.mode == "full":
        end_ts = dt.date.today().strftime("%Y%m%d")
        logger.info("全量模式：%s → %s", args.start, end_ts)
        trade_dates = get_all_trade_dates(pro, args.start, end_ts)
        logger.info("共 %d 个交易日", len(trade_dates))

    else:  # incremental
        latest = get_latest_trade_date(pro)
        existing: set = set()
        if Path(args.db).exists():
            tmp = duckdb.connect(args.db, read_only=True)
            existing = get_existing_dates(tmp)
            tmp.close()
        if latest in existing:
            logger.info("已有最新交易日 %s，无需更新 ✅", latest)
            return
        trade_dates = [latest]
        logger.info("增量模式：拉取 %s", latest)

    if not trade_dates:
        logger.warning("没有需要拉取的交易日，退出")
        return

    run(pro=pro, trade_dates=trade_dates, codes=codes,
        db_path=args.db, active_sources=active_sources)


if __name__ == "__main__":
    main()