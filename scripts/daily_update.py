#!/usr/bin/env python3
"""
每日数据更新脚本

功能：
1. 通过 Tushare pro_bar（qfq 前复权）获取最新一个交易日的 OHLCV 数据
2. 可选地将新行追加到本地 CSV 文件（与 fetch_kline.py 格式保持一致）
3. 从数据库直接读取 lookback 历史数据，计算最新一天的技术指标（无需重算历史）
4. UPSERT 到 SQLite 数据库（indicators / metadata / daily_stats / audit_log）
5. 输出 JSON 运行报告

Usage:
    # 更新今天数据（自动取最新交易日）
    python daily_update.py --db ./data/indicators.db --data-dir ./data

    # 更新指定日期（补数据用）
    python daily_update.py --db ./data/indicators.db --trade-date 20240315

    # 只更新部分股票
    python daily_update.py --db ./data/indicators.db --codes 000001,600000

    # 不写 CSV，只更新数据库
    python daily_update.py --db ./data/indicators.db --no-csv

环境变量：
    TUSHARE_TOKEN  Tushare API Token（与 fetch_kline.py 保持一致）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import random
import sqlite3
import sys
import time
import warnings
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import tushare as ts
from tqdm import tqdm

warnings.filterwarnings("ignore")

# 添加项目根目录到 sys.path（与 precompute_indicators.py 保持一致）
sys.path.insert(0, str(Path(__file__).parent.parent))

from Selector import (
    compute_kdj,
    compute_bbi,
    compute_dif,
    compute_zx_lines,
    compute_rsv,
    compute_atr,
    passes_day_constraints_today,
)

# ========== 日志配置（与 fetch_kline.py 风格对齐）==========
LOG_FILE = Path("daily_update.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("daily_update")

# ========== 限流配置（与 fetch_kline.py 保持一致）==========
COOLDOWN_SECS = 600
BAN_PATTERNS = (
    "访问频繁", "请稍后", "超过频率", "频繁访问",
    "too many requests", "429",
    "forbidden", "403",
    "max retries exceeded",
)


def _looks_like_ip_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(pat in msg for pat in BAN_PATTERNS)


def _cool_sleep(base_seconds: int) -> None:
    jitter = random.uniform(0.9, 1.2)
    sleep_s = max(1, int(base_seconds * jitter))
    logger.warning("疑似被限流/封禁，进入冷却期 %d 秒...", sleep_s)
    time.sleep(sleep_s)


# ========== Tushare 工具函数（直接复用 fetch_kline.py 的逻辑）==========

pro: Optional[ts.pro_api] = None  # 模块级会话


def _to_ts_code(code: str) -> str:
    """把6位 code 映射到标准 ts_code 后缀（与 fetch_kline.py 完全一致）"""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


def _get_kline_tushare(code: str, start: str, end: str) -> pd.DataFrame:
    """
    通过 Tushare pro_bar 获取前复权日线数据（与 fetch_kline.py 完全一致）
    返回列：date(datetime64), open, close, high, low, volume
    """
    ts_code = _to_ts_code(code)
    try:
        df = ts.pro_bar(
            ts_code=ts_code,
            adj="qfq",
            start_date=start,
            end_date=end,
            freq="D",
            api=pro,
        )
    except Exception as e:
        if _looks_like_ip_ban(e):
            raise RuntimeError(f"[RateLimit] {e}") from e
        raise

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def get_latest_trade_date(trade_date_arg: Optional[str] = None) -> str:
    """
    获取最近一个交易日（格式：YYYYMMDD）。
    若指定 trade_date_arg 则直接返回；否则通过 Tushare trade_cal 查询。
    """
    if trade_date_arg:
        return trade_date_arg

    today = dt.date.today().strftime("%Y%m%d")
    lookback = (dt.date.today() - dt.timedelta(days=15)).strftime("%Y%m%d")
    cal_df = pro.trade_cal(exchange="SSE", start_date=lookback, end_date=today, is_open="1")
    if cal_df is None or cal_df.empty:
        raise ValueError("无法从 Tushare 获取交易日历，请检查 Token 或网络")
    latest = cal_df["cal_date"].max()
    logger.info("最新交易日：%s", latest)
    return latest


def fetch_new_bar(code: str, trade_date: str) -> Optional[pd.Series]:
    """
    获取单只股票指定交易日的 OHLCV 数据（一行）。
    trade_date 格式：YYYYMMDD

    Returns:
        pd.Series（date 为 YYYY-MM-DD 字符串格式）或 None（无数据/停牌）
    """
    for attempt in range(1, 4):
        try:
            df = _get_kline_tushare(code, trade_date, trade_date)
            if df.empty:
                return None
            row = df.iloc[-1].copy()
            # 统一日期格式为 YYYY-MM-DD（与数据库一致）
            row["date"] = pd.to_datetime(row["date"]).strftime("%Y-%m-%d")
            row["code"] = code
            return row
        except Exception as e:
            if _looks_like_ip_ban(e):
                logger.error("%s 第 %d 次抓取疑似被封禁，冷却 %d 秒", code, attempt, COOLDOWN_SECS)
                _cool_sleep(COOLDOWN_SECS)
            else:
                wait = 15 * attempt
                logger.debug("%s 第 %d 次抓取失败，%d 秒后重试：%s", code, attempt, wait, e)
                time.sleep(wait)
    logger.error("%s 三次抓取均失败，已跳过", code)
    return None


# ========== 数据库：读取 lookback 历史数据 ==========

def load_history_from_db(
    code: str,
    before_date: str,
    lookback_days: int,
    db_path: str,
) -> pd.DataFrame:
    """
    直接从数据库的 indicators 表读取历史 OHLCV（不重算任何指标）。
    这是关键优化：利用数据库中已有的数据作为滑动窗口，
    避免每次更新都重新读 CSV 和重算所有历史指标。

    Args:
        code: 股票代码
        before_date: 不包含当天，只取此日期之前的数据（YYYY-MM-DD）
        lookback_days: 最多往前取多少天（建议 >= 最长指标周期，如 MA114 需要 114+ 天）
        db_path: SQLite 数据库路径

    Returns:
        DataFrame，列：date(str), open, high, low, close, volume，已升序排序
    """
    cutoff = (
        pd.to_datetime(before_date) - pd.Timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT date, open, high, low, close, volume
              FROM indicators
             WHERE code = ?
               AND date >= ?
               AND date < ?
             ORDER BY date ASC
            """,
            conn,
            params=(code, cutoff, before_date),
        )
    finally:
        conn.close()

    return df


# ========== 指标计算 ==========

def compute_indicators_latest_day(
    code: str,
    history_df: pd.DataFrame,
    new_row: pd.Series,
) -> Optional[pd.DataFrame]:
    """
    计算最新一天的全部技术指标。

    核心思路：
      - history_df：从数据库取出的历史 OHLCV 窗口（已排好序）
      - new_row：当天新抓的 OHLCV
      - 拼接后对整个窗口跑一次指标计算，只取最后一行（当天）写库
      - 历史数据的指标值不被触碰，计算量极小（只需当天那一行结果）

    Args:
        code: 股票代码
        history_df: 历史 OHLCV（含 date str, open/high/low/close/volume float）
        new_row: 当天数据 Series（含 date, open, high, low, close, volume）

    Returns:
        单行 DataFrame（含所有指标列）或 None（失败）
    """
    # 1. 拼接历史 + 新行
    new_row_df = pd.DataFrame([{
        "date": new_row["date"],
        "open": float(new_row["open"]),
        "high": float(new_row["high"]),
        "low": float(new_row["low"]),
        "close": float(new_row["close"]),
        "volume": float(new_row["volume"]),
    }])

    if not history_df.empty:
        combined = pd.concat([history_df, new_row_df], ignore_index=True)
        combined = (
            combined.drop_duplicates(subset=["date"])
            .sort_values("date")
            .reset_index(drop=True)
        )
    else:
        combined = new_row_df.copy()

    for col in ["open", "high", "low", "close", "volume"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")

    if combined.empty:
        return None

    # 2. 在窗口上计算全部指标
    result_df = combined.copy()
    result_df["date"] = pd.to_datetime(result_df["date"]).dt.strftime("%Y-%m-%d")

    # KDJ
    kdj_df = compute_kdj(combined, n=9)
    result_df["kdj_k"] = kdj_df["K"]
    result_df["kdj_d"] = kdj_df["D"]
    result_df["kdj_j"] = kdj_df["J"]

    # 移动平均线
    for period in [3, 6, 10, 12, 14, 24, 28, 57, 60, 114]:
        result_df[f"ma{period}"] = combined["close"].rolling(window=period, min_periods=1).mean()

    # BBI
    result_df["bbi"] = compute_bbi(combined)

    # MACD DIF
    result_df["dif"] = compute_dif(combined, fast=12, slow=26)

    # 知行线
    zxdq, zxdkx = compute_zx_lines(combined)
    result_df["zxdq"] = zxdq
    result_df["zxdkx"] = zxdkx

    # RSV
    result_df["rsv_9"] = compute_rsv(combined, n=9)
    result_df["rsv_8"] = compute_rsv(combined, n=8)
    result_df["rsv_30"] = compute_rsv(combined, n=30)

    # ATR
    result_df["atr_14"] = compute_atr(combined, n=14)
    result_df["atr_22"] = compute_atr(combined, n=22)

    # 布尔衍生指标（向量化）
    result_df["zx_close_gt_long"] = (
        result_df["close"].notna() &
        result_df["zxdkx"].notna() &
        (result_df["close"] > result_df["zxdkx"])
    ).astype(int)

    result_df["zx_short_gt_long"] = (
        result_df["zxdq"].notna() &
        result_df["zxdkx"].notna() &
        (result_df["zxdq"] > result_df["zxdkx"])
    ).astype(int)

    # day_constraints_pass（需逐行，只计算至最后一行）
    n = len(combined)
    constraints = np.zeros(n, dtype=int)
    for i in range(1, n):
        constraints[i] = int(passes_day_constraints_today(combined.iloc[: i + 1]))
    result_df["day_constraints_pass"] = constraints

    result_df["code"] = code
    result_df["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    # 3. 只返回最后一行（当天）
    today_str = new_row["date"]
    latest = result_df[result_df["date"] == today_str]

    if latest.empty:
        logger.warning("%s：计算结果中找不到目标日期 %s", code, today_str)
        return None

    columns = [
        "code", "date", "open", "close", "high", "low", "volume",
        "kdj_k", "kdj_d", "kdj_j",
        "ma3", "ma6", "ma10", "ma12", "ma14", "ma24", "ma28", "ma57", "ma60", "ma114",
        "bbi", "dif", "zxdq", "zxdkx",
        "rsv_9", "rsv_8", "rsv_30",
        "atr_14", "atr_22",
        "day_constraints_pass", "zx_close_gt_long", "zx_short_gt_long",
        "updated_at",
    ]
    return latest[columns].reset_index(drop=True)


# ========== CSV 追加（与 fetch_kline.py 格式对齐）==========

def append_to_csv(code: str, new_row: pd.Series, data_dir: Path) -> bool:
    """
    将新的 OHLCV 行追加到对应 CSV 文件（与 fetch_kline.py 列顺序一致）。

    Returns:
        True = 成功写入，False = 该日期已存在（跳过）
    """
    csv_path = data_dir / f"{code}.csv"
    new_date = str(new_row["date"])

    row_df = pd.DataFrame([{
        "date": new_date,
        "open": new_row["open"],
        "close": new_row["close"],
        "high": new_row["high"],
        "low": new_row["low"],
        "volume": new_row["volume"],
    }])

    if csv_path.exists():
        existing_dates = pd.read_csv(csv_path, usecols=["date"])["date"].astype(str)
        if new_date in existing_dates.values:
            return False
        row_df.to_csv(csv_path, mode="a", header=False, index=False)
    else:
        row_df.to_csv(csv_path, mode="w", header=True, index=False)

    return True


# ========== 数据库写入 ==========

def upsert_indicators(cursor: sqlite3.Cursor, df: pd.DataFrame) -> None:
    """将指标 DataFrame UPSERT 进 indicators 表"""
    if df.empty:
        return
    columns = df.columns.tolist()
    placeholders = ",".join(["?"] * len(columns))
    column_names = ",".join(columns)
    update_clause = ",".join(
        [f"{col}=excluded.{col}" for col in columns if col not in ("code", "date")]
    )
    sql = f"""
        INSERT INTO indicators ({column_names})
        VALUES ({placeholders})
        ON CONFLICT(code, date) DO UPDATE SET {update_clause}
    """
    cursor.executemany(sql, df.values.tolist())


def upsert_metadata(cursor: sqlite3.Cursor, code: str, new_date: str) -> None:
    """增量更新 metadata 表（last_date / last_updated / row_count）"""
    cursor.execute(
        "SELECT row_count, first_date FROM metadata WHERE code = ?", (code,)
    )
    row = cursor.fetchone()
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    if row:
        new_count = (row[0] or 0) + 1
        cursor.execute(
            """
            UPDATE metadata
               SET last_date    = ?,
                   last_updated = ?,
                   row_count    = ?
             WHERE code = ?
            """,
            (new_date, now, new_count, code),
        )
    else:
        # 新股票（metadata 中不存在）
        cursor.execute(
            """
            INSERT INTO metadata
                (code, first_date, last_date, last_updated, row_count, data_quality_score)
            VALUES (?, ?, ?, ?, 1, 1.0)
            """,
            (code, new_date, new_date, now),
        )


def upsert_daily_stats(
    cursor: sqlite3.Cursor, trade_date: str, all_df: pd.DataFrame
) -> None:
    """为当天生成 daily_stats 聚合记录"""
    if all_df.empty:
        return
    today_df = all_df[all_df["date"] == trade_date]
    if today_df.empty:
        return

    cursor.execute(
        """
        INSERT INTO daily_stats
            (date, total_stocks, avg_close, avg_volume,
             high_kdj_j_count, low_kdj_j_count, strong_stocks_count, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_stocks      = excluded.total_stocks,
            avg_close         = excluded.avg_close,
            avg_volume        = excluded.avg_volume,
            high_kdj_j_count  = excluded.high_kdj_j_count,
            low_kdj_j_count   = excluded.low_kdj_j_count,
            strong_stocks_count = excluded.strong_stocks_count,
            computed_at       = excluded.computed_at
        """,
        (
            trade_date,
            len(today_df),
            round(float(today_df["close"].mean()), 4),
            round(float(today_df["volume"].mean()), 2),
            int((today_df["kdj_j"] > 80).sum()),
            int((today_df["kdj_j"] < 20).sum()),
            int((today_df["close"] > today_df["ma60"]).sum()),
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    )


def write_audit_log(cursor: sqlite3.Cursor, trade_date: str, summary: dict) -> None:
    cursor.execute(
        """
        INSERT INTO audit_log (action, table_name, record_key, changed_fields)
        VALUES ('UPSERT', 'indicators', ?, ?)
        """,
        (trade_date, json.dumps(summary, ensure_ascii=False)),
    )


# ========== 主流程 ==========

def run_daily_update(
    db_path: str,
    data_dir: str,
    trade_date_arg: Optional[str] = None,
    codes_filter: Optional[List[str]] = None,
    write_csv: bool = True,
    lookback_days: int = 250,
) -> dict:
    """
    每日更新主流程。

    步骤：
      1. 确认最新交易日
      2. 从 metadata 表获取所有需要更新的股票代码
      3. 逐只股票：Tushare 拉当天数据 → 从数据库读 lookback → 计算指标 → 收集结果
      4. 批量 UPSERT 数据库（indicators / metadata / daily_stats / audit_log）
      5. 可选追加 CSV
      6. 输出报告
    """
    total_start = time.time()
    data_dir_path = Path(data_dir)
    data_dir_path.mkdir(parents=True, exist_ok=True)

    if not Path(db_path).exists():
        logger.error("数据库不存在：%s，请先运行 init_indicator_db.py", db_path)
        sys.exit(1)

    # ── 1. 确认交易日 ─────────────────────────────────────────────────
    trade_date_ts = get_latest_trade_date(trade_date_arg)           # YYYYMMDD
    trade_date_db = dt.datetime.strptime(trade_date_ts, "%Y%m%d").strftime("%Y-%m-%d")  # YYYY-MM-DD

    logger.info("\n%s", "=" * 60)
    logger.info("  每日更新 — %s", trade_date_db)
    logger.info("%s\n", "=" * 60)

    # ── 2. 确定需要更新的股票代码 ─────────────────────────────────────
    if codes_filter:
        all_codes = codes_filter
    else:
        conn = sqlite3.connect(db_path)
        try:
            meta_df = pd.read_sql_query("SELECT code FROM metadata", conn)
        finally:
            conn.close()

        if meta_df.empty:
            logger.error("metadata 表为空，请先运行 precompute_indicators.py 进行全量初始化")
            sys.exit(1)

        all_codes = meta_df["code"].tolist()

    logger.info("共需更新 %d 只股票", len(all_codes))

    # ── 3. 逐只股票处理 ───────────────────────────────────────────────
    success_indicators: list[pd.DataFrame] = []
    results: list[dict] = []

    with tqdm(total=len(all_codes), desc="计算指标", ncols=100) as pbar:
        for code in all_codes:
            result: dict = {"code": code, "status": "ERROR", "rows": 0, "error": None}

            try:
                # 3a. Tushare 拉取当天 OHLCV（复用 fetch_kline.py 的接口和重试逻辑）
                new_row = fetch_new_bar(code, trade_date_ts)
                if new_row is None:
                    result["status"] = "SKIP"
                    result["error"] = "Tushare 无数据（可能停牌）"
                    results.append(result)
                    pbar.update(1)
                    continue

                # 3b. 可选写 CSV
                if write_csv:
                    append_to_csv(code, new_row, data_dir_path)

                # 3c. 从数据库读取 lookback 历史 OHLCV（不重算指标，直接复用已存数据）
                history_df = load_history_from_db(
                    code=code,
                    before_date=trade_date_db,
                    lookback_days=lookback_days,
                    db_path=db_path,
                )

                # 3d. 计算最新一天指标
                indicator_row = compute_indicators_latest_day(code, history_df, new_row)
                if indicator_row is None:
                    result["error"] = "指标计算失败"
                    results.append(result)
                    pbar.update(1)
                    continue

                success_indicators.append(indicator_row)
                result["status"] = "SUCCESS"
                result["rows"] = len(indicator_row)

            except Exception as e:
                result["error"] = str(e)
                logger.error("%s 处理异常：%s", code, e, exc_info=False)

            results.append(result)
            pbar.update(1)

    # ── 4. 批量写入数据库 ─────────────────────────────────────────────
    if success_indicators:
        all_indicators = pd.concat(success_indicators, ignore_index=True)
        logger.info("\n写入数据库：%d 行...", len(all_indicators))

        write_start = time.time()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")

            # indicators 表
            upsert_indicators(cursor, all_indicators)

            # metadata 表（每只股票单独更新）
            for r in results:
                if r["status"] == "SUCCESS":
                    upsert_metadata(cursor, r["code"], trade_date_db)

            # daily_stats 表
            upsert_daily_stats(cursor, trade_date_db, all_indicators)

            # audit_log
            write_audit_log(cursor, trade_date_db, {
                "stocks_updated": sum(1 for r in results if r["status"] == "SUCCESS"),
                "stocks_skipped": sum(1 for r in results if r["status"] == "SKIP"),
                "stocks_failed":  sum(1 for r in results if r["status"] == "ERROR"),
                "triggered_by": "daily_update.py",
            })

            conn.commit()
            logger.info("✓ 数据库写入完成（%.2f 秒）", time.time() - write_start)

        except Exception as e:
            conn.rollback()
            logger.error("❌ 数据库写入失败：%s", e)
            raise
        finally:
            conn.close()
    else:
        logger.warning("没有有效的指标数据可写入。")

    # ── 5. 汇总报告 ───────────────────────────────────────────────────
    total_time = time.time() - total_start
    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    skip_count    = sum(1 for r in results if r["status"] == "SKIP")
    error_count   = sum(1 for r in results if r["status"] == "ERROR")
    total_rows    = sum(r["rows"] for r in results)

    logger.info("\n%s", "=" * 60)
    logger.info("  汇总 — %s", trade_date_db)
    logger.info("%s", "=" * 60)
    logger.info("✅ 成功：%d 只", success_count)
    logger.info("⊘  跳过：%d 只（停牌等）", skip_count)
    logger.info("❌ 失败：%d 只", error_count)
    logger.info("📊 写入行数：%d", total_rows)
    logger.info("⏱  总耗时：%.2f 秒", total_time)
    logger.info("%s\n", "=" * 60)

    if error_count > 0:
        logger.warning("失败明细：")
        for r in results:
            if r["status"] == "ERROR":
                logger.warning("  %s：%s", r["code"], r["error"])

    report = {
        "trade_date": trade_date_db,
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "success": success_count,
        "skipped": skip_count,
        "errors": error_count,
        "total_rows": total_rows,
        "total_time_sec": round(total_time, 2),
        "failed_stocks": [r["code"] for r in results if r["status"] == "ERROR"],
    }

    report_file = f"daily_update_report_{trade_date_ts}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("报告已保存：%s", report_file)

    return report


# ========== CLI 入口 ==========

def main():
    parser = argparse.ArgumentParser(
        description="每日 OHLCV + 技术指标数据库更新脚本（基于 Tushare pro_bar qfq）"
    )
    parser.add_argument("--db", type=str, default="./data/indicators.db",
                        help="SQLite 数据库路径（默认：./data/indicators.db）")
    parser.add_argument("--data-dir", type=str, default="./data",
                        help="本地 CSV 数据目录（默认：./data）")
    parser.add_argument("--trade-date", type=str, default=None,
                        help="指定交易日（格式 YYYYMMDD），不填则自动取最新交易日")
    parser.add_argument("--codes", type=str, default=None,
                        help="只更新指定股票，逗号分隔，如 000001,600000")
    parser.add_argument("--no-csv", action="store_true",
                        help="不更新本地 CSV 文件，只更新数据库")
    parser.add_argument("--lookback", type=int, default=250,
                        help="从数据库读取的历史天数（默认：250，足够覆盖 MA114 等长周期指标）")
    args = parser.parse_args()

    # Token 读取（与 fetch_kline.py 完全一致，只用环境变量）
    os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        logger.error("请先设置环境变量 TUSHARE_TOKEN，例如：export TUSHARE_TOKEN=你的token")
        sys.exit(1)

    ts.set_token(ts_token)
    global pro
    pro = ts.pro_api()

    codes_filter = None
    if args.codes:
        codes_filter = [c.strip() for c in args.codes.split(",")]

    run_daily_update(
        db_path=args.db,
        data_dir=args.data_dir,
        trade_date_arg=args.trade_date,
        codes_filter=codes_filter,
        write_csv=not args.no_csv,
        lookback_days=args.lookback,
    )


if __name__ == "__main__":
    main()