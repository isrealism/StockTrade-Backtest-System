"""
飞书消息模块

功能：
  1. send_signal()        — 按策略分组推送选股信号（含股票名称，格式见下）
  2. send_error()         — 推送异常通知
  3. FeishuCallbackServer — Flask 回调服务，处理卡片交互：
       · ⚙️ 管理策略     → 显示各策略当前状态与上线/下线按钮
       · 🔄 切换上线/下线 → 修改 buy_selectors.json，立即生效
       · 🔍 查询历史信号  → 用户选择日期，返回该日选股结果

消息格式：
    选股信号 2025-06-10
    共 8 只股票

    1. 少妇战法（3 只）：
       1. - 000001  平安银行
       2. - 600036  招商银行
       3. - 600519  贵州茅台

    2. 填坑战法（2 只）：
       1. - 000858  五粮液
       2. - 601318  中国平安

环境变量：
    FEISHU_WEBHOOK_URL   推送用 Webhook（仅推送，按钮不支持回调）
    FEISHU_APP_ID        飞书应用 App ID（Bot API，支持按钮交互）
    FEISHU_APP_SECRET    飞书应用 App Secret
    FEISHU_VERIFY_TOKEN  卡片回调验证 Token（开放平台「事件订阅」页获取）
    FEISHU_CHAT_ID       机器人所在群的 chat_id
    FEISHU_CALLBACK_PORT 回调服务监听端口（默认 8765）

回调服务启动：
    python feishu.py serve            # 阻塞启动
    python feishu.py manage           # 推送策略管理卡片
    python feishu.py query 2025-06-10 # 推送指定日期选股结果
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# 自动加载项目根目录的 .env 文件
# feishu.py 在 scripts/ 下，.env 在上一级项目根目录
try:
    from dotenv import load_dotenv
    _ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_ROOT_ENV, override=False)
except ImportError:
    pass  # python-dotenv 未安装时跳过，依赖系统环境变量

logger = logging.getLogger("feishu")

# ── 路径（feishu.py 在 scripts/ 下，项目根在上一级）────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
BUY_CONFIG = Path(os.environ.get("BUY_CONFIG", str(ROOT / "configs" / "buy_selectors.json")))
SIGNAL_DIR = Path(os.environ.get("SIGNAL_DIR", str(ROOT / "data" / "signals")))
STOCKLIST  = Path(os.environ.get("STOCKLIST",  str(ROOT / "stocklist.csv")))

# ── 环境变量 ──────────────────────────────────────────────────────────────────
WEBHOOK_URL   = os.environ.get("FEISHU_WEBHOOK_URL", "")
APP_ID        = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET    = os.environ.get("FEISHU_APP_SECRET", "")
VERIFY_TOKEN  = os.environ.get("FEISHU_VERIFY_TOKEN", "")
CHAT_ID       = os.environ.get("FEISHU_CHAT_ID", "")
CALLBACK_PORT = int(os.environ.get("FEISHU_CALLBACK_PORT", "8765"))

# ── 写锁：保护 buy_selectors.json 并发修改 ────────────────────────────────────
_config_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# 一、数据工具
# ══════════════════════════════════════════════════════════════════════════════

def load_name_map() -> Dict[str, str]:
    """从 stocklist.csv 读取 {6位code: 股票名称} 映射。"""
    if not STOCKLIST.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(STOCKLIST, dtype=str)
        code_col = "symbol" if "symbol" in df.columns else "ts_code"
        if "name" not in df.columns:
            return {}
        df["_code"] = (
            df[code_col]
            .str.replace(r"\.(SH|SZ|BJ)$", "", regex=True)
            .str.zfill(6)
        )
        return dict(zip(df["_code"], df["name"].fillna("")))
    except Exception as e:
        logger.warning("load_name_map 失败：%s", e)
        return {}


def load_signal_for_date(query_date: str) -> Dict[str, List[str]]:
    """
    读取 data/signals/{query_date}-{alias}.txt，
    返回 {alias: [code, ...], "__all__": [...]}。
    query_date: YYYY-MM-DD
    """
    results: Dict[str, List[str]] = {}
    if not SIGNAL_DIR.exists():
        return results
    for fp in sorted(SIGNAL_DIR.glob(f"{query_date}-*.txt")):
        alias = fp.stem[len(query_date) + 1:]   # "2025-06-10-少妇战法" → "少妇战法"
        codes = [c.strip() for c in fp.read_text(encoding="utf-8").splitlines() if c.strip()]
        if alias == "all":
            results["__all__"] = codes
        else:
            results[alias] = codes
    return results


def read_selector_configs() -> List[Dict[str, Any]]:
    """读取 buy_selectors.json，返回 selectors 列表。"""
    if not BUY_CONFIG.exists():
        return []
    with BUY_CONFIG.open(encoding="utf-8") as f:
        raw = json.load(f)
    return raw if isinstance(raw, list) else raw.get("selectors", [])


def toggle_selector(alias: str) -> Tuple[Optional[bool], str]:
    """
    切换指定策略的 activate 状态并写回 buy_selectors.json。
    Returns: (new_activate_state, 提示文字)  — 找不到时返回 (None, msg)
    """
    with _config_lock:
        if not BUY_CONFIG.exists():
            return None, f"配置文件不存在：{BUY_CONFIG}"

        with BUY_CONFIG.open(encoding="utf-8") as f:
            raw = json.load(f)

        is_list   = isinstance(raw, list)
        selectors = raw if is_list else raw.get("selectors", [])

        for sel in selectors:
            if sel.get("alias") == alias or sel.get("class") == alias:
                new_state       = not sel.get("activate", True)
                sel["activate"] = new_state
                break
        else:
            return None, f"未找到策略：{alias}"

        if not is_list:
            raw["selectors"] = selectors

        with BUY_CONFIG.open("w", encoding="utf-8") as f:
            json.dump(raw if not is_list else selectors, f, ensure_ascii=False, indent=2)

    state_str = "🟢 已上线" if new_state else "⭕ 已下线"
    logger.info("策略 [%s] → %s", alias, state_str)
    return new_state, f"策略「{alias}」{state_str}"


def _normalize_date(s: str) -> str:
    """将各种日期格式统一为 YYYY-MM-DD。"""
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        import pandas as pd
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return s


# ══════════════════════════════════════════════════════════════════════════════
# 二、消息正文构建
# ══════════════════════════════════════════════════════════════════════════════

def _build_signal_text(
    results: Dict[str, List[str]],
    trade_date: str,
    name_map: Dict[str, str],
) -> str:
    """
    构建选股信号正文，精确格式：

        选股信号 2025-06-10
        共 8 只股票

        1. 少妇战法（3 只）：
           1. - 000001  平安银行
           2. - 600036  招商银行
           3. - 600519  贵州茅台

        2. 填坑战法（2 只）：
           1. - 000858  五粮液
           2. - 601318  中国平安
    """
    all_codes = results.get("__all__", [])
    count     = len(all_codes)

    lines = [
        f"选股信号 {trade_date}",
        f"共 {count} 只股票",
    ]

    selector_idx = 1
    for alias, codes in results.items():
        if alias == "__all__" or not codes:
            continue
        lines.append("")
        lines.append(f"{selector_idx}. {alias}（{len(codes)} 只）：")
        for stock_idx, code in enumerate(codes, start=1):
            name     = name_map.get(code, "")
            name_str = f"  {name}" if name else ""
            lines.append(f"   {stock_idx}. - {code}{name_str}")
        selector_idx += 1

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 三、飞书卡片构建
# ══════════════════════════════════════════════════════════════════════════════

def _signal_card(
    results: Dict[str, List[str]],
    trade_date: str,
    name_map: Dict[str, str],
) -> dict:
    """构建选股信号交互卡片（底部带「管理策略」和「查询历史」按钮）。"""
    body  = _build_signal_text(results, trade_date, name_map)
    color = "green" if results.get("__all__") else "grey"

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title":    {"tag": "plain_text", "content": f"📊 选股信号 · {trade_date}"},
                "template": color,
            },
            "elements": [
                {
                    "tag":  "div",
                    "text": {"tag": "lark_md", "content": body},
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "⚙️ 管理策略"},
                            "type":  "primary",
                            "value": {"action": "show_management"},
                        },
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "🔍 查询历史"},
                            "type":  "default",
                            "value": {"action": "show_query_input"},
                        },
                    ],
                },
            ],
        },
    }


def _management_card() -> dict:
    """
    构建策略管理卡片。
    每个策略显示名称、当前状态，以及一个切换按钮。
    """
    selectors = read_selector_configs()
    elements: List[dict] = [
        {
            "tag":  "div",
            "text": {"tag": "lark_md", "content": "**⚙️ 策略管理**\n点击按钮切换上线 / 下线状态"},
        },
        {"tag": "hr"},
    ]

    for sel in selectors:
        alias    = sel.get("alias") or sel.get("class", "未知")
        active   = sel.get("activate", True)
        status   = "🟢 上线中" if active else "⭕ 已下线"
        btn_text = "🔴 下线" if active else "🟢 上线"
        btn_type = "danger"  if active else "primary"

        elements.append({
            "tag":  "div",
            "text": {"tag": "lark_md", "content": f"**{alias}**　　{status}"},
        })
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag":   "button",
                    "text":  {"tag": "plain_text", "content": f"{btn_text} {alias}"},
                    "type":  btn_type,
                    "value": {"action": "toggle_selector", "alias": alias},
                }
            ],
        })
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag":   "button",
                "text":  {"tag": "plain_text", "content": "← 返回信号"},
                "type":  "default",
                "value": {"action": "back_to_signal"},
            }
        ],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title":    {"tag": "plain_text", "content": "⚙️ 策略管理"},
                "template": "indigo",
            },
            "elements": elements,
        },
    }


def _query_input_card() -> dict:
    """构建日期查询输入卡片。用 date_picker 选日期后点「查询」提交。"""
    today = date.today().isoformat()
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title":    {"tag": "plain_text", "content": "🔍 查询历史选股"},
                "template": "wathet",
            },
            "elements": [
                {
                    "tag":  "div",
                    "text": {"tag": "lark_md", "content": "请选择要查询的交易日期："},
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag":          "date_picker",
                            "placeholder":  {"tag": "plain_text", "content": "选择日期"},
                            "initial_date": today,
                            "value":        {"action": "pick_date"},
                        },
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "查询"},
                            "type":  "primary",
                            "value": {"action": "submit_query"},
                        },
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "← 返回"},
                            "type":  "default",
                            "value": {"action": "back_to_signal"},
                        },
                    ],
                },
            ],
        },
    }


def _query_result_card(
    query_date: str,
    results: Dict[str, List[str]],
    name_map: Dict[str, str],
) -> dict:
    """构建历史查询结果卡片。"""
    if not results:
        body  = f"❌ 未找到 **{query_date}** 的选股记录\n\n（该日可能非交易日，或当日未运行选股）"
        color = "red"
        title = f"🔍 无记录 · {query_date}"
    else:
        body  = _build_signal_text(results, query_date, name_map)
        color = "green"
        title = f"🔍 查询结果 · {query_date}"

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title":    {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "🔍 再次查询"},
                            "type":  "default",
                            "value": {"action": "show_query_input"},
                        },
                        {
                            "tag":   "button",
                            "text":  {"tag": "plain_text", "content": "← 返回信号"},
                            "type":  "default",
                            "value": {"action": "back_to_signal"},
                        },
                    ],
                },
            ],
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 四、飞书 API 发送
# ══════════════════════════════════════════════════════════════════════════════

def _post_webhook(card: dict) -> None:
    """通过 Webhook 推送卡片（单向，按钮点击不会触发回调）。"""
    if not WEBHOOK_URL:
        raise EnvironmentError("FEISHU_WEBHOOK_URL 未设置")
    resp = requests.post(
        WEBHOOK_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps(card, ensure_ascii=False),
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"Webhook 发送失败：{result}")
    logger.info("飞书 Webhook 发送成功")


_token_cache: Dict[str, Any] = {"token": "", "expire": 0.0}


def _get_tenant_token() -> str:
    """获取飞书租户 access_token（本地缓存，2 小时内复用）。"""
    if _token_cache["token"] and time.time() < _token_cache["expire"]:
        return _token_cache["token"]
    if not APP_ID or not APP_SECRET:
        raise EnvironmentError("FEISHU_APP_ID / FEISHU_APP_SECRET 未设置")
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", -1) != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
    _token_cache["token"]  = data["tenant_access_token"]
    _token_cache["expire"] = time.time() + data.get("expire", 7200) - 60
    return _token_cache["token"]


def _post_bot(card: dict, chat_id: Optional[str] = None) -> None:
    """通过 Bot API 向群发送交互卡片（支持按钮回调）。"""
    cid = chat_id or CHAT_ID
    if not cid:
        raise EnvironmentError("FEISHU_CHAT_ID 未设置")
    token = _get_tenant_token()
    resp  = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
        json={
            "receive_id": cid,
            "msg_type":   "interactive",
            "content":    json.dumps(card.get("card", card), ensure_ascii=False),
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Bot API 发送失败：{data}")
    logger.info("飞书 Bot API 发送成功")


def _send(card: dict, prefer_bot: bool = True) -> None:
    """
    智能发送：
      prefer_bot=True 且配置了 App 凭据 → Bot API（按钮可交互）
      否则 → Webhook（无需额外配置）
    """
    if prefer_bot and APP_ID and APP_SECRET and CHAT_ID:
        try:
            _post_bot(card)
            return
        except Exception as e:
            logger.warning("Bot API 失败，降级 Webhook：%s", e)
    _post_webhook(card)


# ══════════════════════════════════════════════════════════════════════════════
# 五、公开 API
# ══════════════════════════════════════════════════════════════════════════════

def send_signal(
    results: Dict[str, List[str]],
    trade_date: Optional[str] = None,
    name_map: Optional[Dict[str, str]] = None,
) -> None:
    """
    推送选股信号卡片。

    Args:
        results:    来自 run_selectors_for_date() 的
                    {alias: [code, ...], "__all__": [...]}
        trade_date: 选股日期 YYYY-MM-DD（默认今天）
        name_map:   {code: name}，None 时自动从 stocklist.csv 加载
    """
    if trade_date is None:
        trade_date = date.today().isoformat()
    if name_map is None:
        name_map = load_name_map()

    card = _signal_card(results, trade_date, name_map)

    # 缓存到全局回调服务器，供 back_to_signal 使用
    if _callback_server is not None:
        _callback_server.cache_last_signal(card["card"])

    _send(card, prefer_bot=True)


def send_error(error_msg: str) -> None:
    """推送异常通知。"""
    today = date.today().isoformat()
    card  = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title":    {"tag": "plain_text", "content": f"❌ 选股任务异常 · {today}"},
                "template": "red",
            },
            "elements": [
                {
                    "tag":  "div",
                    "text": {
                        "tag":     "lark_md",
                        "content": f"**错误信息：**\n```\n{error_msg}\n```",
                    },
                }
            ],
        },
    }
    _send(card, prefer_bot=False)


def send_management_card() -> None:
    """主动推送策略管理卡片（需 Bot 配置）。"""
    _post_bot(_management_card())


# ══════════════════════════════════════════════════════════════════════════════
# 六、回调服务器（lark-oapi 长连接模式，无需公网地址）
# ══════════════════════════════════════════════════════════════════════════════

class FeishuCallbackServer:
    """
    飞书卡片交互回调服务器（长连接模式）。

    使用 lark-oapi SDK 建立 WebSocket 长连接，服务器主动连接飞书，
    无需公网地址、无需开放端口。

    动作路由：
      show_management  → 策略管理卡片
      toggle_selector  → 切换策略激活状态 → 刷新管理卡片
      show_query_input → 日期选择卡片
      pick_date        → date_picker 选中日期（暂存，等待 submit_query）
      submit_query     → 读取信号文件 → 结果卡片
      back_to_signal   → 返回最近一次信号卡片

    配置步骤：
      1. 飞书开放平台 → 事件与回调 → 回调配置
      2. 订阅方式选择「使用长连接接收回调」
      3. 添加回调：卡片回调（card.action.trigger）
      4. 确保 FEISHU_APP_ID 和 FEISHU_APP_SECRET 已在 .env 中配置
    """

    def __init__(self):
        # open_id → 上次 date_picker 选中的日期
        self._pending_dates: Dict[str, str] = {}
        # 最新信号卡片（供 back_to_signal 使用）
        self._last_signal_card: Optional[dict] = None

    def cache_last_signal(self, card_body: dict) -> None:
        self._last_signal_card = card_body

    def _extract_body(self, data: Any) -> dict:
        """
        将 lark-oapi P2CardActionTrigger 对象转换为 _dispatch 所需的 dict 格式。

        P2CardActionTrigger 结构：
          data.event.action.value   → 按钮定义的 value dict
          data.event.action.option  → date_picker / select 选中的值
          data.event.operator.open_id → 点击者 open_id
        """
        try:
            import lark_oapi as lark

            # 先序列化为 JSON，再解析，兼容所有版本的 SDK 对象结构
            raw = json.loads(lark.JSON.marshal(data))

            event    = raw.get("event", {})
            action   = event.get("action", {})
            operator = event.get("operator", {})

            action_value = action.get("value", {})
            if isinstance(action_value, str):
                try:
                    action_value = json.loads(action_value)
                except Exception:
                    action_value = {}

            return {
                "action": {
                    "value":  action_value,
                    "option": action.get("option", ""),
                    "tag":    action.get("tag", ""),
                },
                "open_id": operator.get("open_id", "anon"),
            }
        except Exception as e:
            logger.warning("事件格式转换失败：%s，使用空 body", e)
            return {"action": {"value": {}, "option": "", "tag": ""}, "open_id": "anon"}

    def _dispatch(self, body: dict) -> dict:
        """处理一次卡片回调，返回 {"card": ...} 或 {"toast": ...}。"""
        action     = body.get("action", {})
        value      = action.get("value", {})
        action_tag = value.get("action", "")
        open_id    = body.get("open_id", "anon")

        logger.info("卡片回调 open_id=%s action=%s", open_id, action_tag)

        # ── 显示策略管理卡片 ──────────────────────────────────────────────
        if action_tag == "show_management":
            return {
                "toast": {"type": "info", "content": "策略管理"},
                "card":  _management_card()["card"],
            }

        # ── 切换策略上线/下线 ─────────────────────────────────────────────
        elif action_tag == "toggle_selector":
            alias          = value.get("alias", "")
            new_state, msg = toggle_selector(alias)
            toast_type     = "success" if new_state is not None else "error"
            return {
                "toast": {"type": toast_type, "content": msg},
                "card":  _management_card()["card"],
            }

        # ── 显示日期输入卡片 ──────────────────────────────────────────────
        elif action_tag == "show_query_input":
            return {
                "toast": {"type": "info", "content": "请选择查询日期"},
                "card":  _query_input_card()["card"],
            }

        # ── date_picker 选中日期（暂存，不刷新卡片）──────────────────────
        elif action_tag == "pick_date":
            selected = action.get("option", "") or value.get("date", "")
            if selected:
                self._pending_dates[open_id] = _normalize_date(selected)
            return {}

        # ── 提交查询 ──────────────────────────────────────────────────────
        elif action_tag == "submit_query":
            query_date = (
                _normalize_date(action.get("option", ""))
                or self._pending_dates.get(open_id, "")
            )
            if not query_date:
                return {"toast": {"type": "error", "content": "请先选择日期"}}
            name_map = load_name_map()
            results  = load_signal_for_date(query_date)
            return {
                "toast": {
                    "type":    "success" if results else "warning",
                    "content": f"查询完成：{query_date}",
                },
                "card": _query_result_card(query_date, results, name_map)["card"],
            }

        # ── 返回最新信号卡片 ──────────────────────────────────────────────
        elif action_tag == "back_to_signal":
            if self._last_signal_card:
                return {"card": self._last_signal_card}
            return {"toast": {"type": "info", "content": "暂无缓存信号，请等待下次推送"}}

        else:
            logger.warning("未知 action_tag：%s", action_tag)
            return {"toast": {"type": "error", "content": f"未知操作：{action_tag}"}}

    # ── 长连接服务 ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        阻塞启动飞书长连接回调服务。
        服务器主动连接飞书 WebSocket，无需公网地址，无需开放端口。
        """
        try:
            import lark_oapi as lark
            from lark_oapi.event.callback.model.p2_card_action_trigger import (
                P2CardActionTrigger,
                P2CardActionTriggerResponse,
            )
        except ImportError:
            raise ImportError("请先安装：pip install lark-oapi")

        if not APP_ID or not APP_SECRET:
            raise EnvironmentError("FEISHU_APP_ID / FEISHU_APP_SECRET 未设置")

        server = self

        def do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            """处理卡片按钮点击回调。"""
            try:
                body   = server._extract_body(data)
                result = server._dispatch(body)
                logger.debug("回调响应：%s", result)
                return P2CardActionTriggerResponse(result)
            except Exception as e:
                logger.error("卡片回调异常：%s", e, exc_info=True)
                return P2CardActionTriggerResponse(
                    {"toast": {"type": "error", "content": str(e)}}
                )

        # 注册卡片回调处理器
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_card_action_trigger(do_card_action_trigger)
            .build()
        )

        logger.info("飞书长连接服务启动（App ID: %s）", APP_ID)
        logger.info("无需公网地址，服务器主动连接飞书 WebSocket")

        # 构建 WebSocket 长连接客户端
        cli = lark.ws.Client(
            APP_ID,
            APP_SECRET,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        cli.start()   # 阻塞，内部自动重连

    def run_background(self) -> threading.Thread:
        """在守护线程中启动（非阻塞）。"""
        t = threading.Thread(target=self.run, daemon=True, name="feishu-ws")
        t.start()
        return t


# ── 全局单例（send_signal 会自动更新缓存）────────────────────────────────────
_callback_server: Optional[FeishuCallbackServer] = None


def start_callback_server(background: bool = True) -> FeishuCallbackServer:
    """启动全局回调服务器。background=True 时非阻塞。"""
    global _callback_server
    _callback_server = FeishuCallbackServer()
    if background:
        _callback_server.run_background()
    else:
        _callback_server.run()
    return _callback_server


# ══════════════════════════════════════════════════════════════════════════════
# 七、CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    ap  = argparse.ArgumentParser(description="飞书消息工具")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("serve",  help="启动回调服务器（阻塞）")
    sub.add_parser("manage", help="推送策略管理卡片")

    qp = sub.add_parser("query", help="查询并推送指定日期的选股信号")
    qp.add_argument("date", help="日期 YYYY-MM-DD 或 YYYYMMDD")

    args = ap.parse_args()

    if args.cmd == "serve":
        FeishuCallbackServer().run()

    elif args.cmd == "manage":
        send_management_card()
        print("✅ 策略管理卡片已发送")

    elif args.cmd == "query":
        qdate    = _normalize_date(args.date)
        name_map = load_name_map()
        results  = load_signal_for_date(qdate)
        card     = _query_result_card(qdate, results, name_map)
        _send(card, prefer_bot=True)
        print(f"✅ 已推送 {qdate} 的选股信号")

    else:
        ap.print_help()