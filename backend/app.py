"""
Backtest API service.

Provides endpoints for configuration, backtest execution, templates, and results.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.engine import BacktestEngine
from backtest.performance import PerformanceAnalyzer

DATA_DIR = ROOT / "data"
CONFIGS_PATH = ROOT / "configs.json"
SELL_STRATEGIES_PATH = ROOT / "configs" / "sell_strategies.json"
DB_PATH = ROOT / "backend" / "backtest_results.db"
FRONTEND_DIR = ROOT / "frontend"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _json_loads(text: Optional[str]) -> Any:
    if not text:
        return None
    return json.loads(text)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtests (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                progress REAL,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                start_date TEXT,
                end_date TEXT,
                payload_json TEXT,
                result_json TEXT,
                metrics_json TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backtest_id TEXT,
                ts TEXT,
                message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at TEXT,
                payload_json TEXT
            )
            """
        )
        conn.commit()


def db_execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, params)
        conn.commit()


def db_query(query: str, params: tuple = ()) -> List[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query, params)
        return cur.fetchall()


def load_buy_config_default() -> Dict[str, Any]:
    with open(CONFIGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sell_strategies() -> Dict[str, Any]:
    with open(SELL_STRATEGIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _scale(value: float, low: float, high: float) -> float:
    if high == low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def compute_strategy_score(analysis: Dict[str, Any]) -> Dict[str, Any]:
    returns = analysis.get("returns", {})
    risk = analysis.get("risk_adjusted", {})
    drawdown = analysis.get("drawdown", {})
    trades = analysis.get("trade_stats", {})

    total_return = float(returns.get("total_return_pct", 0.0))
    sharpe = float(risk.get("sharpe_ratio", 0.0))
    max_dd = abs(float(drawdown.get("max_drawdown_pct", 0.0)))
    win_rate = float(trades.get("win_rate_pct", 0.0))

    score = (
        0.4 * _scale(total_return, 0, 50) +
        0.25 * _scale(sharpe, 0, 2.5) +
        0.2 * _scale(win_rate, 40, 80) +
        0.15 * _scale(100 - max_dd, 50, 100)
    ) * 10

    return {
        "score": round(score, 2),
        "components": {
            "total_return_pct": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "win_rate_pct": win_rate
        }
    }


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        db_execute(
            """
            INSERT INTO backtests
            (id, name, status, progress, created_at, start_date, end_date, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                payload.get("name") or "Backtest",
                "PENDING",
                0.0,
                _now_iso(),
                payload.get("start_date"),
                payload.get("end_date"),
                _json_dumps(payload),
            ),
        )
        return job_id

    def start(self, job_id: str, payload: Dict[str, Any]) -> None:
        cancel_event = threading.Event()

        def run_job():
            db_execute(
                "UPDATE backtests SET status=?, started_at=?, progress=? WHERE id=?",
                ("RUNNING", _now_iso(), 0.0, job_id),
            )

            def log_callback(message: str) -> None:
                db_execute(
                    "INSERT INTO logs (backtest_id, ts, message) VALUES (?, ?, ?)",
                    (job_id, _now_iso(), message),
                )

            def progress_callback(done: int, total: int, date: datetime) -> None:
                progress = 0.0 if total == 0 else (done / total) * 100.0
                db_execute(
                    "UPDATE backtests SET progress=? WHERE id=?",
                    (round(progress, 2), job_id),
                )

            def cancel_check() -> bool:
                return cancel_event.is_set()

            try:
                buy_config = payload.get("buy_config")
                if buy_config is None:
                    buy_config = load_buy_config_default()

                sell_strategies = load_sell_strategies()
                sell_strategy_name = payload.get("sell_strategy_name")
                sell_strategy_config = payload.get("sell_strategy_config")
                if sell_strategy_config is None:
                    if not sell_strategy_name:
                        sell_strategy_name = "conservative_trailing"
                    sell_strategy_config = sell_strategies.get("strategies", {}).get(sell_strategy_name)
                if not sell_strategy_config:
                    raise ValueError("Sell strategy configuration not found.")

                stock_pool = payload.get("stock_pool", {"type": "all"})
                stock_codes = None
                if stock_pool.get("type") == "list":
                    stock_codes = stock_pool.get("codes", [])

                engine = BacktestEngine(
                    data_dir=str(DATA_DIR),
                    buy_config_path=str(CONFIGS_PATH),
                    sell_strategy_config=sell_strategy_config,
                    start_date=payload.get("start_date"),
                    end_date=payload.get("end_date"),
                    initial_capital=float(payload.get("initial_capital", 1000000)),
                    max_positions=int(payload.get("max_positions", 10)),
                    position_sizing=payload.get("position_sizing", "equal_weight"),
                    commission_rate=float(payload.get("commission_rate", 0.0003)),
                    stamp_tax_rate=float(payload.get("stamp_tax_rate", 0.001)),
                    slippage_rate=float(payload.get("slippage_rate", 0.001)),
                    buy_config=buy_config,
                    log_callback=log_callback,
                )

                engine.load_data(
                    stock_codes=stock_codes,
                    lookback_days=int(payload.get("lookback_days", 200)),
                )
                if len(engine.market_data) == 0:
                    raise ValueError("No market data loaded.")

                engine.load_buy_selectors()
                if len(engine.buy_selectors) == 0:
                    raise ValueError("No active buy selectors.")

                engine.load_sell_strategy()
                engine.run(progress_callback=progress_callback, cancel_check=cancel_check)

                if cancel_event.is_set():
                    db_execute(
                        "UPDATE backtests SET status=?, finished_at=? WHERE id=?",
                        ("CANCELLED", _now_iso(), job_id),
                    )
                    return

                results = engine.get_results()
                equity_df = pd.DataFrame(results.get("equity_curve", []))
                trades_df = pd.DataFrame(results.get("trades", []))

                analysis = PerformanceAnalyzer(
                    equity_curve=equity_df,
                    trades=trades_df,
                    initial_capital=float(payload.get("initial_capital", 1000000)),
                ).analyze()

                score = compute_strategy_score(analysis)

                best_trade = None
                best_stock = None
                if not trades_df.empty:
                    best_trade_row = trades_df.sort_values("net_pnl_pct", ascending=False).iloc[0]
                    best_trade = best_trade_row.to_dict()
                    best_stock_series = trades_df.groupby("code")["net_pnl"].sum().sort_values(ascending=False)
                    if not best_stock_series.empty:
                        best_stock = {"code": best_stock_series.index[0], "net_pnl": best_stock_series.iloc[0]}

                results["analysis"] = analysis
                results["strategy_score"] = score
                results["best_trade"] = best_trade
                results["best_stock"] = best_stock

                metrics = {
                    "total_return_pct": analysis.get("returns", {}).get("total_return_pct", 0),
                    "max_drawdown_pct": analysis.get("drawdown", {}).get("max_drawdown_pct", 0),
                    "win_rate_pct": analysis.get("trade_stats", {}).get("win_rate_pct", 0),
                    "sharpe_ratio": analysis.get("risk_adjusted", {}).get("sharpe_ratio", 0),
                    "final_value": analysis.get("returns", {}).get("final_value", 0),
                    "score": score.get("score", 0),
                }

                db_execute(
                    """
                    UPDATE backtests
                    SET status=?, progress=?, finished_at=?, result_json=?, metrics_json=?
                    WHERE id=?
                    """,
                    (
                        "COMPLETED",
                        100.0,
                        _now_iso(),
                        _json_dumps(results),
                        _json_dumps(metrics),
                        job_id,
                    ),
                )
            except Exception as exc:
                db_execute(
                    "UPDATE backtests SET status=?, error=?, finished_at=? WHERE id=?",
                    ("FAILED", str(exc), _now_iso(), job_id),
                )

        thread = threading.Thread(target=run_job, daemon=True)
        with self._lock:
            self._jobs[job_id] = {"thread": thread, "cancel_event": cancel_event}
        thread.start()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job["cancel_event"].set()
            return True


init_db()
job_manager = JobManager()

app = FastAPI(title="Backtest API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def root():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index)


@app.get("/api/config")
def get_config():
    return {
        "selectors": load_buy_config_default().get("selectors", []),
        "sell_strategies": load_sell_strategies().get("strategies", {}),
    }


@app.post("/api/backtests")
def create_backtest(payload: Dict[str, Any]):
    required_fields = ["start_date", "end_date"]
    for field in required_fields:
        if field not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")

    job_id = job_manager.create(payload)
    job_manager.start(job_id, payload)
    return {"id": job_id, "status": "PENDING"}


@app.get("/api/backtests")
def list_backtests():
    rows = db_query(
        """
        SELECT id, name, status, progress, created_at, started_at, finished_at,
               start_date, end_date, metrics_json, error
        FROM backtests
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "progress": row["progress"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "metrics": _json_loads(row["metrics_json"]),
            "error": row["error"],
        })
    return {"items": items}


@app.get("/api/backtests/{backtest_id}")
def get_backtest(backtest_id: str):
    rows = db_query("SELECT * FROM backtests WHERE id=?", (backtest_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Backtest not found.")
    row = rows[0]

    logs = db_query(
        "SELECT ts, message FROM logs WHERE backtest_id=? ORDER BY id DESC LIMIT 200",
        (backtest_id,),
    )
    log_items = [{"ts": log["ts"], "message": log["message"]} for log in reversed(logs)]

    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "progress": row["progress"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "payload": _json_loads(row["payload_json"]),
        "result": _json_loads(row["result_json"]),
        "metrics": _json_loads(row["metrics_json"]),
        "error": row["error"],
        "logs": log_items,
    }


@app.post("/api/backtests/{backtest_id}/cancel")
def cancel_backtest(backtest_id: str):
    ok = job_manager.cancel(backtest_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Backtest not running.")
    return {"id": backtest_id, "status": "CANCELLED_REQUESTED"}


@app.get("/api/templates")
def list_templates():
    rows = db_query("SELECT * FROM templates ORDER BY created_at DESC")
    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "payload": _json_loads(row["payload_json"]),
        })
    return {"items": items}


@app.post("/api/templates")
def create_template(payload: Dict[str, Any]):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Template name required.")
    template_id = str(uuid.uuid4())
    db_execute(
        "INSERT INTO templates (id, name, created_at, payload_json) VALUES (?, ?, ?, ?)",
        (template_id, name, _now_iso(), _json_dumps(payload)),
    )
    return {"id": template_id}


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str):
    db_execute("DELETE FROM templates WHERE id=?", (template_id,))
    return {"id": template_id, "status": "DELETED"}


@app.get("/api/rankings")
def get_rankings(metric: str = "score"):
    rows = db_query(
        "SELECT id, name, created_at, metrics_json FROM backtests WHERE status='COMPLETED'"
    )
    items = []
    for row in rows:
        metrics = _json_loads(row["metrics_json"]) or {}
        items.append({
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "metrics": metrics,
            "rank_value": metrics.get(metric, 0),
        })
    items.sort(key=lambda x: x["rank_value"], reverse=True)
    return {"items": items}


@app.get("/api/benchmark")
def get_benchmark(name: str, start: str, end: str):
    bench_dir = DATA_DIR / "index"
    bench_path = bench_dir / f"{name}.csv"
    if not bench_path.exists():
        raise HTTPException(status_code=404, detail="Benchmark data not found.")
    df = pd.read_csv(bench_path)
    if "date" not in df.columns or "close" not in df.columns:
        raise HTTPException(status_code=400, detail="Invalid benchmark data format.")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
    if df.empty:
        return {"series": []}
    base = float(df["close"].iloc[0])
    df["nav"] = df["close"] / base
    series = [{"date": d.strftime("%Y-%m-%d"), "nav": float(v)} for d, v in zip(df["date"], df["nav"])]
    return {"series": series}
