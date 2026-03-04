"""
每日/区间自动选股主流程（纯 DuckDB 版，无 CSV 中间层）

流程：
  1. 收盘时间检查（17:00 后，仅 end=今天时生效）
  2. Tushare 按 [start, end] 区间拉取 OHLCV → 直接 UPSERT 进 DuckDB indicators 表
  3. 逐只股票：从 DuckDB 读 lookback+区间 历史 → Python 计算全量指标 → UPSERT 区间行
  4. 获取区间内所有交易日列表
  5. 逐日运行 Selector → 保存信号到本地
  6. 仅对 end 日期推送飞书（汇总）

用法：
    python daily_selector.py                              # 今天
    python daily_selector.py --end 2025-09-10             # 指定结束日（start 同 end）
    python daily_selector.py --start 2025-01-01 --end 2025-09-10   # 补跑整个区间
    python daily_selector.py --skip-after-close           # 跳过收盘检查（测试）
    python daily_selector.py --dry-run                    # 不发飞书，仅打印
    python daily_selector.py --skip-fetch                 # 跳过 Tushare 拉取
    python daily_selector.py --skip-indicators            # 跳过指标计算
    python daily_selector.py --push-each-date             # 每个交易日都推飞书（默认只推 end）

环境变量：
    TUSHARE_TOKEN       Tushare API Token
    FEISHU_WEBHOOK_URL  飞书机器人 Webhook URL
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import logging
import os
import random
import sys
import threading
import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
import tushare as ts
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ── 路径配置 ─────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
SIGNAL_DIR = DATA_DIR / "signals"
STOCKLIST  = ROOT / "stocklist.csv"
BUY_CONFIG = ROOT / "configs" / "buy_selectors.json"
DB_PATH    = ROOT / "data" / "indicators.duckdb"

sys.path.insert(0, str(ROOT))

# ── 日志 ──────────────────────────────────────────────────────────────────────
(ROOT / "logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "logs" / "daily_selector.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("daily_selector")

# ── Tushare 限流配置 ───────────────────────────────────────────────────────────
COOLDOWN_SECS = 600
BAN_PATTERNS  = ("访问频繁", "请稍后", "超过频率", "too many requests", "429", "403")

# ── DuckDB 写入串行锁（DuckDB 同一时间只允许一个写连接）─────────────────────────
_db_write_lock = threading.Lock()

pro: Optional[ts.pro_api] = None


# ══════════════════════════════════════════════════════════════════════════════
# 一、工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _looks_like_ip_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(p in msg for p in BAN_PATTERNS)


def _cool_sleep(base: int) -> None:
    secs = max(1, int(base * random.uniform(0.9, 1.2)))
    logger.warning("疑似限流/封禁，冷却 %d 秒...", secs)
    time.sleep(secs)


def _to_ts_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def load_codes_from_stocklist() -> List[str]:
    df  = pd.read_csv(STOCKLIST)
    col = "symbol" if "symbol" in df.columns else "ts_code"
    codes = (
        df[col].astype(str)
        .str.replace(r"\.(SH|SZ|BJ)$", "", regex=True)
        .str.zfill(6)
        .tolist()
    )
    return list(dict.fromkeys(codes))


# ══════════════════════════════════════════════════════════════════════════════
# 二、Tushare 拉取
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_trade_date() -> str:
    """返回最新交易日，格式 YYYYMMDD"""
    today    = dt.date.today().strftime("%Y%m%d")
    lookback = (dt.date.today() - dt.timedelta(days=15)).strftime("%Y%m%d")
    cal_df   = pro.trade_cal(exchange="SSE", start_date=lookback, end_date=today, is_open="1")
    if cal_df is None or cal_df.empty:
        raise ValueError("无法从 Tushare 获取交易日历，请检查 Token 或网络")
    latest = cal_df["cal_date"].max()
    logger.info("最新交易日：%s", latest)
    return latest


def get_trade_dates_in_range(start_ts: str, end_ts: str) -> List[str]:
    """
    获取 [start_ts, end_ts] 区间内所有交易日列表（格式 YYYYMMDD）。
    优先从 DuckDB 里读（快），若 DB 没数据则 fallback 到 Tushare trade_cal。
    """
    # 先尝试从已写入 DB 的数据中获取（无需 Tushare 调用）
    start_db = f"{start_ts[:4]}-{start_ts[4:6]}-{start_ts[6:]}"
    end_db   = f"{end_ts[:4]}-{end_ts[4:6]}-{end_ts[6:]}"
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        rows = conn.execute(
            "SELECT DISTINCT date FROM indicators WHERE date >= ? AND date <= ? ORDER BY date",
            [start_db, end_db],
        ).fetchall()
        conn.close()
        if rows:
            return [r[0].replace("-", "") for r in rows]
    except Exception:
        pass

    # fallback：Tushare trade_cal
    cal_df = pro.trade_cal(exchange="SSE", start_date=start_ts, end_date=end_ts, is_open="1")
    if cal_df is None or cal_df.empty:
        raise ValueError(f"无法获取 {start_ts}~{end_ts} 的交易日历")
    return sorted(cal_df["cal_date"].tolist())


def _fetch_range_bars(code: str, start_ts: str, end_ts: str) -> Optional[pd.DataFrame]:
    """
    拉取单只股票 [start_ts, end_ts] 区间的 OHLCV（最多重试 3 次）。
    start_ts / end_ts: YYYYMMDD
    返回 DataFrame(columns=[code, date, open, close, high, low, volume]) 或 None
    """
    ts_code = _to_ts_code(code)
    for attempt in range(1, 4):
        try:
            df = ts.pro_bar(
                ts_code=ts_code, adj="qfq",
                start_date=start_ts, end_date=end_ts,
                freq="D", api=pro,
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={"trade_date": "date", "vol": "volume"})
            df = df[["date", "open", "close", "high", "low", "volume"]].copy()
            df["date"]   = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df["code"]   = code
            for c in ["open", "close", "high", "low", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            if _looks_like_ip_ban(e):
                logger.error("%s 第 %d 次拉取疑似限流，冷却 %d 秒", code, attempt, COOLDOWN_SECS)
                _cool_sleep(COOLDOWN_SECS)
            else:
                time.sleep(15 * attempt)
    logger.error("%s 三次拉取均失败，跳过", code)
    return None


def _upsert_ohlcv_df(df: pd.DataFrame, db_path: str) -> None:
    """
    将 OHLCV DataFrame（多行）批量 UPSERT 进 indicators 表。
    只写 OHLCV 五列 + updated_at，其余指标列保持原值。
    """
    if df.empty:
        return
    df = df[["code", "date", "open", "close", "high", "low", "volume"]].copy()
    df["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    with _db_write_lock:
        conn = duckdb.connect(db_path)
        conn.register("_ohlcv", df)
        conn.execute("""
            INSERT INTO indicators (code, date, open, close, high, low, volume, updated_at)
            SELECT code, date, open, close, high, low, volume, updated_at FROM _ohlcv
            ON CONFLICT (code, date) DO UPDATE SET
                open       = excluded.open,
                close      = excluded.close,
                high       = excluded.high,
                low        = excluded.low,
                volume     = excluded.volume,
                updated_at = excluded.updated_at
        """)
        conn.unregister("_ohlcv")
        conn.close()


def fetch_and_upsert_ohlcv(start_ts: str, end_ts: str, codes: List[str], workers: int = 8) -> None:
    """
    并发拉取所有股票 [start_ts, end_ts] 区间 OHLCV，批量 UPSERT 进 DuckDB。
    start_ts / end_ts: YYYYMMDD
    """
    logger.info("开始拉取 %d 只股票 OHLCV（%s ~ %s）...", len(codes), start_ts, end_ts)
    db_path  = str(DB_PATH)
    BATCH    = 5000   # 每积累 5000 行写一次 DB
    buf: List[pd.DataFrame] = []
    buf_rows = 0
    success  = skip = 0

    def _flush(buf):
        if buf:
            _upsert_ohlcv_df(pd.concat(buf, ignore_index=True), db_path)
        return [], 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_range_bars, code, start_ts, end_ts): code for code in codes}
        for future in tqdm(as_completed(futures), total=len(futures), desc="拉取 OHLCV", ncols=100):
            result = future.result()
            if result is not None and not result.empty:
                buf.append(result)
                buf_rows += len(result)
                success  += 1
                if buf_rows >= BATCH:
                    buf, buf_rows = _flush(buf)
            else:
                skip += 1

    _flush(buf)
    logger.info("OHLCV 写入完成 — 写入 %d 只，停牌/无数据 %d 只", success, skip)


# ══════════════════════════════════════════════════════════════════════════════
# 三、指标计算（从 DuckDB 读取 OHLCV 历史 → Python 计算 → 写回 DuckDB）
# ══════════════════════════════════════════════════════════════════════════════

def _load_ohlcv_history(code: str, start_date: str, end_date: str, lookback_days: int, db_path: str) -> pd.DataFrame:
    """
    从 indicators 表读取某股票的 OHLCV 历史窗口（只读）。
    start_date / end_date: YYYY-MM-DD
    包含 [lookback_before_start, end_date] 范围内所有行（计算指标需要足够历史）
    """
    cutoff = (pd.to_datetime(start_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    conn = duckdb.connect(db_path, read_only=True)
    df = conn.execute("""
        SELECT date, open, high, low, close, volume
          FROM indicators
         WHERE code = ? AND date >= ? AND date <= ?
         ORDER BY date ASC
    """, [code, cutoff, end_date]).df()
    conn.close()
    return df


def _compute_indicators(code: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    在 OHLCV DataFrame 上运行全套指标计算（复用 precompute_indicators.py 的逻辑）
    返回含所有指标列的 DataFrame，date 格式为 YYYY-MM-DD 字符串
    """
    from utils.indicators import (
        compute_kdj, compute_bbi, compute_dif,
        compute_zx_lines, compute_rsv, compute_atr,
    )
    from utils.filters import passes_day_constraints_today

    if df.empty:
        return pd.DataFrame()

    result = df.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")

    kdj = compute_kdj(df, n=9)
    result["kdj_k"] = kdj["K"]
    result["kdj_d"] = kdj["D"]
    result["kdj_j"] = kdj["J"]

    for p in [3, 6, 10, 12, 14, 24, 28, 57, 60, 114]:
        result[f"ma{p}"] = df["close"].rolling(window=p, min_periods=1).mean()

    result["bbi"] = compute_bbi(df)
    result["dif"] = compute_dif(df, fast=12, slow=26)

    zxdq, zxdkx = compute_zx_lines(df)
    result["zxdq"]  = zxdq
    result["zxdkx"] = zxdkx

    for n in [9, 8, 30, 3, 5, 21]:
        result[f"rsv_{n}"] = compute_rsv(df, n=n)

    result["atr_14"] = compute_atr(df, period=14)
    result["atr_22"] = compute_atr(df, period=22)

    result["zx_close_gt_long"] = (
        result["close"].notna() & result["zxdkx"].notna() &
        (result["close"] > result["zxdkx"])
    ).astype(int)
    result["zx_short_gt_long"] = (
        result["zxdq"].notna() & result["zxdkx"].notna() &
        (result["zxdq"] > result["zxdkx"])
    ).astype(int)

    n_rows = len(df)
    constraints = np.zeros(n_rows, dtype=np.int8)
    if n_rows >= 2:
        for i in range(1, n_rows):
            constraints[i] = int(passes_day_constraints_today(df.iloc[: i + 1]))
    result["day_constraints_pass"] = constraints

    result["vol_ma20"] = df["volume"].rolling(window=20, min_periods=1).mean()
    result["code"]       = code
    result["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    return result


def _upsert_indicators_df(df: pd.DataFrame, db_path: str) -> None:
    """将计算好的指标 DataFrame UPSERT 进 indicators 表（全列覆盖）"""
    if df.empty:
        return
    cols          = df.columns.tolist()
    col_names     = ", ".join(cols)
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in ("code", "date"))

    with _db_write_lock:
        conn = duckdb.connect(db_path)
        conn.register("_ind", df)
        conn.execute(f"""
            INSERT INTO indicators ({col_names})
            SELECT {col_names} FROM _ind
            ON CONFLICT (code, date) DO UPDATE SET {update_clause}
        """)
        conn.unregister("_ind")
        conn.close()


def _process_one_stock_indicators(
    code: str,
    start_date: str,
    end_date: str,
    lookback_days: int,
    db_path: str,
) -> str:
    """
    单只股票的指标更新流程：
    1. 从 DuckDB 读取 [lookback_before_start, end_date] 的 OHLCV
    2. 计算全量指标
    3. 只保留 [start_date, end_date] 区间的行 → UPSERT 回 DuckDB

    这样每只股票只调用一次计算、一次写入，无论区间多长。
    """
    try:
        history = _load_ohlcv_history(code, start_date, end_date, lookback_days, db_path)
        if history.empty:
            return "skip:no_data"

        indicators = _compute_indicators(code, history)
        if indicators.empty:
            return "error:compute_failed"

        # 只写 [start_date, end_date] 区间的行
        mask = (indicators["date"] >= start_date) & (indicators["date"] <= end_date)
        target_rows = indicators[mask]
        if target_rows.empty:
            return "skip:no_range_rows"

        _upsert_indicators_df(target_rows, db_path)
        return "ok"

    except Exception as e:
        logger.debug("%s 指标计算出错：%s", code, e)
        return f"error:{e}"


def compute_and_upsert_indicators(
    start_date: str,
    end_date: str,
    codes: List[str],
    lookback_days: int = 250,
    workers: int = 6,
) -> None:
    """
    并发为所有股票计算 [start_date, end_date] 区间的指标并写回 DuckDB。
    start_date / end_date: YYYY-MM-DD

    每只股票：一次读取（lookback+区间）→ 一次计算 → 一次写入（仅区间行）
    """
    logger.info(
        "开始计算 %d 只股票的技术指标（%s ~ %s）...", len(codes), start_date, end_date
    )
    db_path = str(DB_PATH)
    ok = skip = error = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_one_stock_indicators,
                code, start_date, end_date, lookback_days, db_path
            ): code
            for code in codes
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="计算指标", ncols=100):
            status = future.result()
            if status == "ok":
                ok += 1
            elif status.startswith("skip"):
                skip += 1
            else:
                error += 1

    logger.info("指标计算完成 — 成功 %d，跳过 %d，失败 %d", ok, skip, error)


# ══════════════════════════════════════════════════════════════════════════════
# 四、从 DuckDB 加载数据供 Selector 使用
# ══════════════════════════════════════════════════════════════════════════════

def load_data_from_db(start_date: str, end_date: str, lookback_days: int = 250) -> Dict[str, pd.DataFrame]:
    """
    通过 IndicatorStore 从 DuckDB 加载所有股票的指标数据。
    start_date / end_date: YYYY-MM-DD
    实际读取 [start_date - lookback_days, end_date]，保证最早一天也有足够历史供 Selector 使用。
    """
    from backtest.indicator_store import IndicatorStore

    store    = IndicatorStore(str(DB_PATH))
    load_from = (pd.to_datetime(start_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    logger.info("从 DuckDB 读取指标数据（%s ~ %s）...", load_from, end_date)

    df_all = store.load_all(start_date=load_from, end_date=end_date)

    if df_all.empty:
        raise RuntimeError(
            "DuckDB 中查不到任何数据，请先运行 precompute_indicators.py 完成全量初始化"
        )

    data: Dict[str, pd.DataFrame] = {
        str(code).zfill(6): grp.sort_values("date").reset_index(drop=True)
        for code, grp in df_all.groupby("code")
    }
    logger.info("加载完成：%d 只股票", len(data))
    return data


# ══════════════════════════════════════════════════════════════════════════════
# 五、选股器
# ══════════════════════════════════════════════════════════════════════════════

def _load_selector_config() -> List[Dict[str, Any]]:
    with BUY_CONFIG.open(encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    return raw.get("selectors", [raw])


def _instantiate_selector(cfg: Dict[str, Any]):
    cls_name = cfg.get("class", "")
    if not cls_name:
        raise ValueError("缺少 class 字段")
    module = importlib.import_module("backtest.Selector")
    cls    = getattr(module, cls_name)
    return cfg.get("alias", cls_name), cls(**cfg.get("params", {}))


def run_selectors_for_date(
    data: Dict[str, pd.DataFrame],
    trade_date: pd.Timestamp,
) -> Dict[str, List[str]]:
    """在给定的数据集上运行所有激活 Selector，返回 {alias: codes, "__all__": merged}"""
    results:   Dict[str, List[str]] = {}
    all_codes: set = set()

    for cfg in _load_selector_config():
        if not cfg.get("activate", True):
            continue
        try:
            alias, selector = _instantiate_selector(cfg)
        except Exception as e:
            logger.error("跳过 %s：%s", cfg.get("class"), e)
            continue

        try:
            picks = sorted({str(c).zfill(6) for c in selector.select(trade_date, data)})
            results[alias] = picks
            all_codes.update(picks)
            logger.info("  【%s】%d 只：%s", alias, len(picks), " ".join(picks) or "无")
        except Exception:
            logger.error("  【%s】运行出错：\n%s", alias, traceback.format_exc())
            results[alias] = []

    results["__all__"] = sorted(all_codes)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 六、保存信号 & 飞书推送
# ══════════════════════════════════════════════════════════════════════════════

def save_signal(results: Dict[str, List[str]], trade_date: str) -> None:
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    for alias, codes in results.items():
        if alias == "__all__":
            continue
        (SIGNAL_DIR / f"{trade_date}-{alias.replace('/', '_').replace(' ', '_')}.txt").write_text(
            "\n".join(codes), encoding="utf-8"
        )
    (SIGNAL_DIR / f"{trade_date}-all.txt").write_text("\n".join(results["__all__"]), encoding="utf-8")
    logger.info("信号已保存至 %s", SIGNAL_DIR)


def _build_feishu_extra(results: Dict[str, List[str]]) -> str:
    return "\n".join(
        f"**{alias}**（{len(codes)} 只）：" + ("  ".join(codes) if codes else "无")
        for alias, codes in results.items()
        if alias != "__all__"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="区间选股 + 飞书推送（纯 DuckDB 版）")
    # ── 日期参数 ──────────────────────────────────────────────────────────
    parser.add_argument("--start",            help="开始日期 YYYY-MM-DD（默认同 --end）")
    parser.add_argument("--end",              help="结束日期 YYYY-MM-DD（默认今天最新交易日）")
    # ── 性能参数 ──────────────────────────────────────────────────────────
    parser.add_argument("--lookback-days",    type=int, default=250,
                                              help="指标计算历史窗口，天数（默认 250，覆盖 MA114）")
    parser.add_argument("--workers",          type=int, default=2,
                                              help="Tushare 拉取并发线程数（默认 8）")
    parser.add_argument("--ind-workers",      type=int, default=6,
                                              help="指标计算并发线程数（默认 6）")
    # ── 控制参数 ──────────────────────────────────────────────────────────
    parser.add_argument("--skip-after-close", action="store_true",
                                              help="跳过收盘时间检查（测试 / 补跑历史时使用）")
    parser.add_argument("--skip-fetch",       action="store_true", help="跳过 Tushare 拉取")
    parser.add_argument("--skip-indicators",  action="store_true", help="跳过指标计算")
    parser.add_argument("--push-each-date",   action="store_true",
                                              help="每个交易日都推飞书（默认只推 end 日期）")
    parser.add_argument("--dry-run",          action="store_true", help="不实际发送飞书消息，仅打印")
    args = parser.parse_args()

    from feishu import send_signal, send_error

    now = dt.datetime.now()

    try:
        # ── 0. 初始化 Tushare ─────────────────────────────────────────────
        global pro
        if not args.skip_fetch:
            ts_token = os.environ.get("TUSHARE_TOKEN")
            if not ts_token:
                raise EnvironmentError("请设置环境变量 TUSHARE_TOKEN")
            ts.set_token(ts_token)
            os.environ.setdefault("NO_PROXY", "api.waditu.com,.waditu.com")
            pro = ts.pro_api()

        # ── 1. 解析日期范围 ────────────────────────────────────────────────
        if args.end:
            end_ts = args.end.replace("-", "")            # YYYYMMDD
        else:
            end_ts = get_latest_trade_date()              # 自动取最新交易日

        start_ts = args.start.replace("-", "") if args.start else end_ts   # 默认 start=end

        end_date   = f"{end_ts[:4]}-{end_ts[4:6]}-{end_ts[6:]}"    # YYYY-MM-DD
        start_date = f"{start_ts[:4]}-{start_ts[4:6]}-{start_ts[6:]}"

        # 收盘检查：仅当 end 是今天且未跳过时生效
        today_ts = now.date().strftime("%Y%m%d")
        if not args.skip_after_close and end_ts == today_ts:
            cutoff = now.replace(hour=17, minute=00, second=0, microsecond=0)
            if now < cutoff:
                raise RuntimeError(f"当前时间 {now.strftime('%H:%M')}，未到 A 股收盘 17:00，终止。")

        codes = load_codes_from_stocklist()
        logger.info("日期范围：%s ~ %s，股票池：%d 只", start_date, end_date, len(codes))

        # ── 2. Tushare 拉取整个区间 OHLCV → DuckDB ───────────────────────
        if not args.skip_fetch:
            fetch_and_upsert_ohlcv(start_ts, end_ts, codes, workers=args.workers)

        # ── 3. 计算整个区间指标 → DuckDB ─────────────────────────────────
        if not args.skip_indicators:
            compute_and_upsert_indicators(
                start_date, end_date, codes,
                lookback_days=args.lookback_days,
                workers=args.ind_workers,
            )

        # ── 4. 从 DuckDB 一次性加载所有数据（含 lookback）────────────────
        data = load_data_from_db(start_date, end_date, lookback_days=args.lookback_days)

        # ── 5. 获取区间内实际交易日列表 ───────────────────────────────────
        trade_dates_ts = get_trade_dates_in_range(start_ts, end_ts)   # YYYYMMDD list
        trade_dates    = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in trade_dates_ts]  # YYYY-MM-DD
        logger.info("区间内共 %d 个交易日", len(trade_dates))

        # ── 6. 逐日运行 Selector ──────────────────────────────────────────
        all_results: Dict[str, Dict[str, List[str]]] = {}   # {date: {alias: codes}}

        for date in trade_dates:
            logger.info("── 选股日期：%s ──", date)
            results = run_selectors_for_date(data, pd.to_datetime(date))
            all_results[date] = results
            save_signal(results, date)
            logger.info(
                "  合并共 %d 只：%s",
                len(results["__all__"]),
                " ".join(results["__all__"]) or "无",
            )

            # 若 --push-each-date，逐日推送（补跑历史时通常不需要）
            if args.push_each_date and date != end_date:
                extra = _build_feishu_extra(results)
                if args.dry_run:
                    logger.info("[dry-run] %s 飞书内容：\n%s", date, extra)
                else:
                    send_signal(results["__all__"], extra_info=f"📅 {date}\n{extra}")

        # ── 7. 只对 end_date 推送汇总飞书 ───────────────────────────────
        end_results = all_results.get(end_date, {})
        if not end_results:
            logger.warning("end_date %s 没有选股结果（非交易日？）", end_date)
        else:
            # 若区间 > 1 天，在飞书消息里附上每日摘要
            if len(trade_dates) > 1:
                summary_lines = [f"📅 区间：{start_date} ~ {end_date}，共 {len(trade_dates)} 个交易日\n"]
                for d in trade_dates:
                    r = all_results.get(d, {})
                    n = len(r.get("__all__", []))
                    summary_lines.append(f"  {d}：{n} 只")
                summary_lines.append("")
                summary = "\n".join(summary_lines)
                extra = summary + _build_feishu_extra(end_results)
            else:
                extra = _build_feishu_extra(end_results)

            if args.dry_run:
                logger.info("[dry-run] 飞书推送（%s）：\n%s", end_date, extra)
            else:
                send_signal(end_results["__all__"], extra_info=extra)
                logger.info("飞书推送完成 ✅（%s）", end_date)

    except Exception as e:
        logger.error("任务异常：\n%s", traceback.format_exc())
        if not args.dry_run:
            try:
                send_error(str(e))
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()