from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import sys
import time
import warnings
from pathlib import Path
from typing import Optional
import os

import pandas as pd
import tushare as ts

warnings.filterwarnings("ignore")

# --------------------------- 全局日志配置 --------------------------- #
LOG_FILE = Path("fetch_index.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fetch_index")

# --------------------------- 限流/封禁处理配置 --------------------------- #
COOLDOWN_SECS = 600
BAN_PATTERNS = (
    "访问频繁", "请稍后", "超过频率", "频繁访问",
    "too many requests", "429",
    "forbidden", "403",
    "max retries exceeded"
)

def _looks_like_ip_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(pat in msg for pat in BAN_PATTERNS)

class RateLimitError(RuntimeError):
    """表示命中限流/封禁，需要长时间冷却后重试。"""
    pass

def _cool_sleep(base_seconds: int) -> None:
    jitter = random.uniform(0.9, 1.2)
    sleep_s = max(1, int(base_seconds * jitter))
    logger.warning("疑似被限流/封禁，进入冷却期 %d 秒...", sleep_s)
    time.sleep(sleep_s)

# --------------------------- 指数K线数据抓取 --------------------------- #
pro: Optional[ts.pro_api] = None  # 模块级会话

def set_api(session) -> None:
    """由外部注入已创建好的 ts.pro_api() 会话"""
    global pro
    pro = session

def _get_index_kline(ts_code: str, start: str, end: str) -> pd.DataFrame:
    """
    抓取指数日K线数据
    
    参数:
        ts_code: Tushare指数代码，如 '000300.SH'
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD
    
    返回:
        包含 date, open, close, high, low, volume 列的DataFrame
    """
    try:
        # 使用 index_daily 接口获取指数日线数据
        df = pro.index_daily(
            ts_code=ts_code,
            start_date=start,
            end_date=end
        )
    except Exception as e:
        if _looks_like_ip_ban(e):
            raise RateLimitError(str(e)) from e
        raise

    if df is None or df.empty:
        return pd.DataFrame()

    # 重命名列，保持与股票数据一致
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    
    return df.sort_values("date").reset_index(drop=True)

def validate(df: pd.DataFrame) -> pd.DataFrame:
    """验证数据质量"""
    if df is None or df.empty:
        return df
    
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    
    if df["date"].isna().any():
        raise ValueError("存在缺失日期！")
    
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("数据包含未来日期，可能抓取错误！")
    
    return df

# --------------------------- 单个指数抓取 --------------------------- #
def fetch_index(
    ts_code: str,
    start: str,
    end: str,
    out_dir: Path,
):
    """
    抓取单个指数的K线数据并保存
    
    参数:
        ts_code: 指数代码，如 '000300.SH'
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD
        out_dir: 输出目录
    """
    csv_path = out_dir / f"{ts_code.replace('.', '_')}.csv"

    for attempt in range(1, 4):
        try:
            new_df = _get_index_kline(ts_code, start, end)
            if new_df.empty:
                logger.warning("%s 无数据，生成空表。", ts_code)
                new_df = pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
            
            new_df = validate(new_df)
            new_df.to_csv(csv_path, index=False)
            logger.info("%s 数据已保存: %d 条记录", ts_code, len(new_df))
            break
            
        except Exception as e:
            if _looks_like_ip_ban(e):
                logger.error(f"{ts_code} 第 {attempt} 次抓取疑似被封禁，沉睡 {COOLDOWN_SECS} 秒")
                _cool_sleep(COOLDOWN_SECS)
            else:
                silent_seconds = 15 * attempt
                logger.info(f"{ts_code} 第 {attempt} 次抓取失败，{silent_seconds} 秒后重试：{e}")
                time.sleep(silent_seconds)
    else:
        logger.error("%s 三次抓取均失败，已跳过！", ts_code)

# --------------------------- 主入口 --------------------------- #
def main():
    parser = argparse.ArgumentParser(description="从Tushare抓取指数日线K线数据")
    
    # 抓取范围
    parser.add_argument("--start", default="20190101", help="起始日期 YYYYMMDD 或 'today'")
    parser.add_argument("--end", default="today", help="结束日期 YYYYMMDD 或 'today'")
    
    # 指数代码
    parser.add_argument(
        "--index-codes",
        nargs="*",
        default=["000300.SH"],
        help="指数代码列表，如 000300.SH 000905.SH 000852.SH"
    )
    
    # 其它
    parser.add_argument("--out", default="./index_data", help="输出目录")
    
    args = parser.parse_args()

    # ---------- Tushare Token ---------- #
    os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        raise ValueError("请先设置环境变量 TUSHARE_TOKEN，例如：export TUSHARE_TOKEN=你的token")
    
    ts.set_token(ts_token)
    global pro
    pro = ts.pro_api()

    # ---------- 日期解析 ---------- #
    start = dt.date.today().strftime("%Y%m%d") if str(args.start).lower() == "today" else args.start
    end = dt.date.today().strftime("%Y%m%d") if str(args.end).lower() == "today" else args.end

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "开始抓取 %d 个指数 | 数据源:Tushare(日线) | 日期:%s → %s",
        len(args.index_codes), start, end,
    )

    # ---------- 抓取各个指数 ---------- #
    for ts_code in args.index_codes:
        logger.info("正在抓取指数: %s", ts_code)
        fetch_index(ts_code, start, end, out_dir)
        # 礼貌性暂停，避免频繁请求
        time.sleep(1)

    logger.info("全部任务完成，数据已保存至 %s", out_dir.resolve())

if __name__ == "__main__":
    main()