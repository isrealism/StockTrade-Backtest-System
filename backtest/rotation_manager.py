"""
RotationManager: 换仓决策模块

职责：
- 在每日卖出信号之后、正常买入之前运行
- 找出持仓中亏损最重且入场信号质量弱于当日强信号的仓位
- 配对换仓：生成对应的卖出订单和买入订单
- 记录换仓日志，方便后续绩效归因分析
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

try:
    from .data_structures import BuySignal, Position, Order, OrderAction, OrderStatus
except ImportError:
    from data_structures import BuySignal, Position, Order, OrderAction, OrderStatus  # type: ignore


# ─────────────────────────────────────────
#  换仓配对结果
# ─────────────────────────────────────────

@dataclass
class RotationPair:
    """一对换仓组合：退出仓位 + 进入信号"""
    exit_position: Position          # 要换出的持仓
    entry_signal: BuySignal          # 要换入的新信号

    # 决策依据（方便日志/分析）
    exit_pnl_pct: float              # 换出时的浮亏百分比（负数，如 -0.05 = -5%）
    exit_entry_score: float          # 换出仓位当初的入场 score
    entry_score: float               # 换入信号的当日 score
    score_improvement: float         # entry_score - exit_entry_score（绝对提升）
    score_ratio: float               # entry_score / exit_entry_score（相对倍数）


# ─────────────────────────────────────────
#  RotationManager
# ─────────────────────────────────────────

class RotationManager:
    """
    换仓决策引擎。

    参数
    ----
    min_stop_threshold : float
        触发换仓考察的最低浮亏幅度，默认 -0.05（即亏损超过 5% 才考虑换仓）。
        使用正数表示亏损百分比，内部比较时取负值。

    max_rotations_per_day : int
        每日最多完成的换仓对数，默认 2。

    score_ratio_threshold : float
        新信号 score 必须是旧入场 score 的多少倍（相对门槛），默认 1.2。
        即新信号至少比当时强 20%。

    min_score_improvement : float
        新信号 score 必须比旧入场 score 高多少分（绝对门槛），默认 10。
        防止低分区的微小差距触发不必要的换仓（同时覆盖双边摩擦成本）。

    no_score_position_policy : str
        对于入场时没有记录 score（entry_score = 0）的老仓位如何处理：
        - "skip"   : 跳过，不参与换仓比较（保守，默认）
        - "allow"  : 视为 entry_score = 0，几乎总会触发换仓（激进）
        - "mean"   : 用历史 score 均值填充，较为中性

    score_history_ref : list[float] | None
        传入 engine 的 score_history，仅在 no_score_position_policy="mean" 时使用。
    """

    SELL_REASON_PREFIX = "rotation_replace"   # 卖出原因前缀，方便性能分析筛选

    def __init__(
        self,
        min_stop_threshold: float = 0.05,
        max_rotations_per_day: int = 2,
        score_ratio_threshold: float = 1.2,
        min_score_improvement: float = 10.0,
        no_score_position_policy: str = "skip",
        score_history_ref: Optional[List[float]] = None,
    ):
        # 参数合法性检查
        if min_stop_threshold <= 0:
            raise ValueError(f"min_stop_threshold must be > 0, got {min_stop_threshold}")
        if max_rotations_per_day < 1:
            raise ValueError(f"max_rotations_per_day must be >= 1, got {max_rotations_per_day}")
        if score_ratio_threshold < 1.0:
            raise ValueError(f"score_ratio_threshold must be >= 1.0, got {score_ratio_threshold}")
        if min_score_improvement < 0:
            raise ValueError(f"min_score_improvement must be >= 0, got {min_score_improvement}")
        if no_score_position_policy not in ("skip", "allow", "mean"):
            raise ValueError(f"no_score_position_policy must be 'skip'/'allow'/'mean'")

        self.min_stop_threshold = min_stop_threshold
        self.max_rotations_per_day = max_rotations_per_day
        self.score_ratio_threshold = score_ratio_threshold
        self.min_score_improvement = min_score_improvement
        self.no_score_position_policy = no_score_position_policy
        self.score_history_ref = score_history_ref

        # 换仓历史记录（用于事后分析）
        self.rotation_log: List[Dict[str, Any]] = []

    # ─────────────────────────────────────
    #  核心：寻找换仓配对
    # ─────────────────────────────────────

    def find_rotation_pairs(
        self,
        positions: Dict[str, Position],
        good_signals: List[BuySignal],
        current_prices: Dict[str, float],
        date: datetime,
        sell_triggered_codes: set,
    ) -> List[RotationPair]:
        """
        寻找当日可执行的换仓配对。

        Parameters
        ----------
        positions : dict
            当前持仓字典 {code: Position}
        good_signals : list[BuySignal]
            已通过 score 百分位过滤的当日信号，按 score 从高到低排列
        current_prices : dict
            {code: 当日收盘价}，用于计算浮亏
        date : datetime
            当日日期
        sell_triggered_codes : set
            已被正常卖出逻辑触发的股票代码集合，这些仓位已在卖出队列中，
            不再参与换仓比较

        Returns
        -------
        list[RotationPair]
            按"亏损从大到小"排列的换仓配对，长度 <= max_rotations_per_day
        """
        if not good_signals or not positions:
            return []

        # Step 1: 找出亏损候选仓位，过滤掉已触发正常卖出的
        losers = self._find_loser_positions(
            positions=positions,
            current_prices=current_prices,
            sell_triggered_codes=sell_triggered_codes,
        )

        if not losers:
            return []

        # Step 2: 过滤掉当前持仓已有的信号（不重复买入）
        existing_codes = set(positions.keys())
        candidate_signals = [s for s in good_signals if s.code not in existing_codes]

        if not candidate_signals:
            return []

        # Step 3: 贪心配对：从亏损最重的开始，逐一与当日最强可用信号配对
        pairs: List[RotationPair] = []
        used_signal_codes: set = set()

        for loser_pos, pnl_pct in losers:
            if len(pairs) >= self.max_rotations_per_day:
                break

            # 解析此仓位的入场 score
            exit_entry_score = self._resolve_entry_score(loser_pos)
            if exit_entry_score is None:
                # policy = "skip"，跳过此仓位
                continue

            # 从当日信号中找第一个满足条件且尚未被配对的信号
            best_match = self._find_best_replacement(
                exit_entry_score=exit_entry_score,
                candidate_signals=candidate_signals,
                used_signal_codes=used_signal_codes,
            )

            if best_match is None:
                # 没有足够好的信号可以替换此仓位，继续下一个亏损仓位
                continue

            pair = RotationPair(
                exit_position=loser_pos,
                entry_signal=best_match,
                exit_pnl_pct=pnl_pct,
                exit_entry_score=exit_entry_score,
                entry_score=best_match.score,
                score_improvement=best_match.score - exit_entry_score,
                score_ratio=best_match.score / exit_entry_score if exit_entry_score > 0 else float("inf"),
            )
            pairs.append(pair)
            used_signal_codes.add(best_match.code)

        return pairs

    # ─────────────────────────────────────
    #  执行换仓：生成订单
    # ─────────────────────────────────────

    def execute_rotations(
        self,
        pairs: List[RotationPair],
        portfolio,           # PortfolioManager，避免循环 import 用 Any
        date: datetime,
        current_prices: Dict[str, float],
        market_data_cache: Dict[str, Any],
        log_fn: Optional[Any] = None,
    ) -> Tuple[List[Order], List[Order]]:
        """
        对配对结果生成卖出订单和买入订单。

        Parameters
        ----------
        pairs : list[RotationPair]
        portfolio : PortfolioManager
        date : datetime
        current_prices : dict
        market_data_cache : dict
            {code: pd.DataFrame}，用于仓位计算（risk-based sizing）
        log_fn : callable | None
            传入 engine.log 方便日志统一格式

        Returns
        -------
        (sell_orders, buy_orders) : tuple[list[Order], list[Order]]
            成功生成的卖出订单列表和买入订单列表
        """
        def _log(msg: str):
            if log_fn:
                log_fn(msg)

        sell_orders: List[Order] = []
        buy_orders: List[Order] = []

        for pair in pairs:
            exit_code = pair.exit_position.code
            entry_code = pair.entry_signal.code

            _log(
                f"  [ROTATION] {exit_code} (pnl={pair.exit_pnl_pct*100:+.1f}%, "
                f"entry_score={pair.exit_entry_score:.1f}) "
                f"→ {entry_code} (score={pair.entry_score:.1f}, "
                f"+{pair.score_improvement:.1f}pts, x{pair.score_ratio:.2f})"
            )

            # 1. 生成卖出订单
            sell_reason = (
                f"{self.SELL_REASON_PREFIX}:{entry_code}"
                f"|score_gain={pair.score_improvement:.1f}"
            )
            sell_order = portfolio.generate_sell_order(
                code=exit_code,
                signal_date=date,
                reason=sell_reason,
            )

            if sell_order is None:
                _log(f"    ✗ Sell order for {exit_code} failed (locked or no position)")
                continue

            sell_orders.append(sell_order)
            _log(f"    ✓ Sell order: {exit_code} x {sell_order.shares}")

            # 2. 生成买入订单（绕过持仓上限检查，因为对应的卖出已生成）
            entry_price = current_prices.get(entry_code)
            if entry_price is None:
                _log(f"    ✗ No price data for {entry_code}, rotation buy skipped")
                continue

            df_entry = market_data_cache.get(entry_code)
            buy_order = self._generate_rotation_buy_order(
                portfolio=portfolio,
                code=entry_code,
                signal_date=date,
                price=entry_price,
                strategy_alias=pair.entry_signal.strategy_alias,
                entry_score=pair.entry_score,
                signal_data=pair.entry_signal.signal_data,
                market_data=df_entry,
            )

            if buy_order is None:
                # 买入失败（资金不足等），把之前的卖出撤销（从 pending_orders 移除）
                _log(f"    ✗ Buy order for {entry_code} failed — rolling back sell order for {exit_code}")
                portfolio.pending_orders.remove(sell_order)
                sell_orders.remove(sell_order)
                continue

            buy_orders.append(buy_order)
            _log(
                f"    ✓ Buy order: {entry_code} x {buy_order.shares} "
                f"@ ~{entry_price:.2f} | strategy={pair.entry_signal.strategy_alias}"
            )

            # 3. 记录换仓日志
            self._record_rotation(pair, date, sell_order, buy_order)

        _log(
            f"  [ROTATION] Summary: {len(sell_orders)} pairs executed "
            f"(of {len(pairs)} candidates)"
        )

        return sell_orders, buy_orders

    # ─────────────────────────────────────
    #  私有辅助方法
    # ─────────────────────────────────────

    def _find_loser_positions(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float],
        sell_triggered_codes: set,
    ) -> List[Tuple[Position, float]]:
        """
        找出亏损超过 min_stop_threshold 的持仓，按亏损从大到小排列。

        Returns list of (Position, pnl_pct) tuples，pnl_pct 为负数。
        """
        losers: List[Tuple[Position, float]] = []

        for code, position in positions.items():
            # 跳过已触发正常卖出信号的仓位
            if code in sell_triggered_codes:
                continue

            price = current_prices.get(code)
            if price is None:
                continue

            pnl_pct = position.unrealized_pnl_pct(price)

            # 只考虑亏损超过阈值的仓位（pnl_pct < 0 且 abs > threshold）
            if pnl_pct < -self.min_stop_threshold:
                losers.append((position, pnl_pct))

        # 亏损最重的排在最前（pnl_pct 最小的排最前）
        losers.sort(key=lambda x: x[1])
        return losers

    def _resolve_entry_score(self, position: Position) -> Optional[float]:
        """
        从 position.buy_signal_data 中读取入场 score。

        根据 no_score_position_policy 处理 score 缺失或为 0 的情况：
        - "skip" : 返回 None（调用方跳过此仓位）
        - "allow": 返回 0.0（几乎必然触发换仓）
        - "mean" : 返回历史 score 均值

        Returns
        -------
        float | None
            None 表示跳过此仓位
        """
        raw_score = None

        if position.buy_signal_data and "entry_score" in position.buy_signal_data:
            raw_score = float(position.buy_signal_data["entry_score"])

        # score 有效（> 0）：直接返回
        if raw_score is not None and raw_score > 0:
            return raw_score

        # score 缺失或为 0，按 policy 处理
        if self.no_score_position_policy == "skip":
            return None

        elif self.no_score_position_policy == "allow":
            return 0.0

        else:  # "mean"
            if self.score_history_ref and len(self.score_history_ref) > 0:
                return float(np.mean(self.score_history_ref))
            else:
                # 历史也没有，退化为 skip
                return None

    def _find_best_replacement(
        self,
        exit_entry_score: float,
        candidate_signals: List[BuySignal],
        used_signal_codes: set,
    ) -> Optional[BuySignal]:
        """
        从 candidate_signals（已按 score 降序）中找第一个同时满足：
        1. 尚未被当日其他换仓配对使用
        2. score > exit_entry_score * score_ratio_threshold（相对门槛）
        3. score - exit_entry_score > min_score_improvement（绝对门槛）

        由于 candidate_signals 已降序，第一个满足的就是最强的。
        """
        for signal in candidate_signals:
            if signal.code in used_signal_codes:
                continue

            # 相对门槛
            if exit_entry_score > 0:
                ratio_ok = signal.score >= exit_entry_score * self.score_ratio_threshold
            else:
                # exit_entry_score = 0（policy = "allow"），只检查绝对门槛
                ratio_ok = True

            # 绝对门槛
            improvement_ok = (signal.score - exit_entry_score) >= self.min_score_improvement

            if ratio_ok and improvement_ok:
                return signal

        return None

    def _generate_rotation_buy_order(
        self,
        portfolio,
        code: str,
        signal_date: datetime,
        price: float,
        strategy_alias: str,
        entry_score: float,
        signal_data: Optional[Dict],
        market_data,
    ) -> Optional[Order]:
        """
        生成换仓专用买入订单。

        与 portfolio.generate_buy_order() 的区别：
        跳过 can_open_new_position() 检查——换仓场景下对应的卖出订单已生成，
        T+1 执行时持仓槽会释放，不能因为今日统计满仓而拒绝换仓买入。

        同时把 entry_score 写入订单的 buy_signal_data（通过 buy_strategy 字段无法携带，
        因此换仓买入创建的 Position 在 _execute_buy 时会缺少 entry_score，
        需要在 engine 层或 portfolio._execute_buy 中补充写入——见集成说明）。
        """
        # 检查是否已经持有（不允许重复买同一只）
        if portfolio.has_position(code):
            return None

        # 检查是否已有待执行买单
        for o in portfolio.pending_orders:
            if o.code == code and o.action == OrderAction.BUY and o.status == OrderStatus.PENDING:
                return None

        # 计算仓位（复用 portfolio 的仓位计算逻辑，使用当日投影现金）
        execution_date = portfolio._next_trading_date(signal_date)
        projected_cash = portfolio.get_projected_cash(execution_date)
        shares = portfolio.calculate_position_size(
            code=code,
            price=price,
            market_data=market_data,
            projected_cash=projected_cash,
        )

        if shares == 0:
            return None

        # 构建订单，strategy_alias 中附加 entry_score 便于 _execute_buy 解析
        order = Order(
            code=code,
            action=OrderAction.BUY,
            shares=shares,
            signal_date=signal_date,
            execution_date=execution_date,
            buy_strategy=strategy_alias,
            reason=f"rotation_entry|entry_score={entry_score:.2f}",
        )

        # 预估成本（供 get_projected_cash 后续使用）
        estimated_cost = portfolio.execution_engine.estimate_buy_cost(shares, price)
        order.total_cost = estimated_cost

        portfolio.pending_orders.append(order)
        return order

    def _record_rotation(
        self,
        pair: RotationPair,
        date: datetime,
        sell_order: Order,
        buy_order: Order,
    ):
        """记录换仓日志，供事后绩效归因分析。"""
        self.rotation_log.append({
            "date": date.strftime("%Y-%m-%d"),
            "exit_code": pair.exit_position.code,
            "exit_entry_date": pair.exit_position.entry_date.strftime("%Y-%m-%d"),
            "exit_pnl_pct": round(pair.exit_pnl_pct * 100, 2),
            "exit_entry_score": round(pair.exit_entry_score, 2),
            "entry_code": pair.entry_signal.code,
            "entry_score": round(pair.entry_score, 2),
            "score_improvement": round(pair.score_improvement, 2),
            "score_ratio": round(pair.score_ratio, 3),
            "sell_shares": sell_order.shares,
            "buy_shares": buy_order.shares,
        })

    # ─────────────────────────────────────
    #  分析接口
    # ─────────────────────────────────────

    def get_rotation_summary(self) -> Dict[str, Any]:
        """返回换仓统计摘要，方便在回测结果中呈现。"""
        if not self.rotation_log:
            return {"total_rotations": 0}

        pnl_list = [r["exit_pnl_pct"] for r in self.rotation_log]
        improvement_list = [r["score_improvement"] for r in self.rotation_log]

        return {
            "total_rotations": len(self.rotation_log),
            "avg_exit_pnl_pct": round(float(np.mean(pnl_list)), 2),
            "avg_score_improvement": round(float(np.mean(improvement_list)), 2),
            "rotation_log": self.rotation_log,
        }