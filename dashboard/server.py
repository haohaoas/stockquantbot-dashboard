#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import math
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, time as dt_time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = Path(__file__).resolve().parent
STATIC = DASHBOARD / "static"
STATE_FILE = DASHBOARD / "ai_paper_state.json"
DB_FILE = DASHBOARD / "ai_paper_history.sqlite3"
PYTHON = Path(os.environ.get("NAUTILUS_DASHBOARD_PYTHON", "/Users/haohao/nautilus_venv/bin/python"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not os.environ.get(key):
            os.environ[key] = value


load_env_file(ROOT / ".env")
load_env_file(DASHBOARD / ".env")

DEFAULT_WATCHLIST = ["600519", "000001", "002415", "002001", "605488", "603358", "603409", "002899"]
DEFAULT_CASH = 100_000.0
QUOTE_INTERVAL_SEC = float(os.environ.get("NAUTILUS_AI_QUOTE_INTERVAL", "3"))
AI_INTERVAL_SEC = float(os.environ.get("NAUTILUS_AI_INTERVAL", "15"))
MAX_POSITIONS = 5
PER_POSITION_CASH = 20_000.0
MORNING_REBOUND_ENABLED = os.environ.get("NAUTILUS_MORNING_REBOUND", "1").strip() != "0"
MORNING_REBOUND_END = dt_time(10, 0)
EARLY_SELL_OBSERVE_END = dt_time(9, 45)
EARLY_SELL_DEEP_LOSS_PCT = float(os.environ.get("NAUTILUS_EARLY_SELL_DEEP_LOSS_PCT", "-0.07"))
EARLY_SELL_WEAK_DAY_PCT = float(os.environ.get("NAUTILUS_EARLY_SELL_WEAK_DAY_PCT", "-3.0"))
EARLY_SELL_WEAK_OPEN_EXT = float(os.environ.get("NAUTILUS_EARLY_SELL_WEAK_OPEN_EXT", "-0.02"))
EARLY_SELL_WEAK_VWAP_EXT = float(os.environ.get("NAUTILUS_EARLY_SELL_WEAK_VWAP_EXT", "-0.018"))
EARLY_SELL_EMERGENCY_LOSS_PCT = float(os.environ.get("NAUTILUS_EARLY_SELL_EMERGENCY_LOSS_PCT", "-0.15"))
EARLY_SELL_EMERGENCY_DAY_PCT = float(os.environ.get("NAUTILUS_EARLY_SELL_EMERGENCY_DAY_PCT", "-9.8"))
EARLY_SELL_EMERGENCY_OPEN_EXT = float(os.environ.get("NAUTILUS_EARLY_SELL_EMERGENCY_OPEN_EXT", "-0.045"))
EARLY_SELL_EMERGENCY_VWAP_EXT = float(os.environ.get("NAUTILUS_EARLY_SELL_EMERGENCY_VWAP_EXT", "-0.035"))
MORNING_REBOUND_MAX_BUYS = int(os.environ.get("NAUTILUS_MORNING_REBOUND_MAX_BUYS", "1"))
MORNING_REBOUND_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_MORNING_REBOUND_MAX_PCT_CHG", "4.8"))
MORNING_REBOUND_MAX_OPEN_EXT = float(os.environ.get("NAUTILUS_MORNING_REBOUND_MAX_OPEN_EXT", "0.035"))
MORNING_REBOUND_MAX_PREV_EXT = float(os.environ.get("NAUTILUS_MORNING_REBOUND_MAX_PREV_EXT", "0.045"))
MORNING_REBOUND_MAX_PLATFORM_EXT = float(os.environ.get("NAUTILUS_MORNING_REBOUND_MAX_PLATFORM_EXT", "0.035"))
T_MODULE_ENABLED = os.environ.get("NAUTILUS_T_MODULE_ENABLED", "1").strip() != "0"
T_OUT_MIN_DAY_PCT = float(os.environ.get("NAUTILUS_T_OUT_MIN_DAY_PCT", "5.0"))
T_OUT_MIN_MA20_EXT = float(os.environ.get("NAUTILUS_T_OUT_MIN_MA20_EXT", "0.08"))
T_OUT_MAX_POSITION_PCT = float(os.environ.get("NAUTILUS_T_OUT_MAX_POSITION_PCT", "0.30"))
T_INTRADAY_DROP_PCT = float(os.environ.get("NAUTILUS_T_INTRADAY_DROP_PCT", "-0.03"))
T_INTRADAY_BUY_PCT = float(os.environ.get("NAUTILUS_T_INTRADAY_BUY_PCT", "0.12"))
T_STOP_LOSS_PCT = float(os.environ.get("NAUTILUS_T_STOP_LOSS_PCT", "-0.02"))
N_SHAPE_TRIGGER_PCT = float(os.environ.get("NAUTILUS_N_SHAPE_TRIGGER_PCT", "0.02"))
N_SHAPE_Y_RET_MIN = float(os.environ.get("NAUTILUS_N_SHAPE_Y_RET_MIN", "-0.095"))
N_SHAPE_Y_RET_MAX = float(os.environ.get("NAUTILUS_N_SHAPE_Y_RET_MAX", "-0.01"))
N_SHAPE_OPEN_CHG_MIN = float(os.environ.get("NAUTILUS_N_SHAPE_OPEN_CHG_MIN", "-0.03"))
N_SHAPE_OPEN_CHG_MAX = float(os.environ.get("NAUTILUS_N_SHAPE_OPEN_CHG_MAX", "0.017"))
N_SHAPE_MIN_AMOUNT = float(os.environ.get("NAUTILUS_N_SHAPE_MIN_AMOUNT", "30000000"))
N_SHAPE_MAX_SPREAD_PCT = float(os.environ.get("NAUTILUS_N_SHAPE_MAX_SPREAD_PCT", "0.25"))
N_SHAPE_WATCH_SCORE_CAP = float(os.environ.get("NAUTILUS_N_SHAPE_WATCH_SCORE_CAP", "74"))
N_SHAPE_WATCH_MIN_OPEN_GAIN = float(os.environ.get("NAUTILUS_N_SHAPE_WATCH_MIN_OPEN_GAIN", "-0.005"))
N_SHAPE_WATCH_MAX_OPEN_GAIN = float(os.environ.get("NAUTILUS_N_SHAPE_WATCH_MAX_OPEN_GAIN", "0.045"))
N_SHAPE_WATCH_OPEN_CHG_MIN = float(os.environ.get("NAUTILUS_N_SHAPE_WATCH_OPEN_CHG_MIN", "-0.04"))
N_SHAPE_WATCH_OPEN_CHG_MAX = float(os.environ.get("NAUTILUS_N_SHAPE_WATCH_OPEN_CHG_MAX", "0.03"))
N_SHAPE_AI_MIN_SCORE = float(os.environ.get("NAUTILUS_N_SHAPE_AI_MIN_SCORE", "68"))
N_SHAPE_ROTATION_MIN_SCORE_ADVANTAGE = float(os.environ.get("NAUTILUS_N_SHAPE_ROTATION_MIN_SCORE_ADVANTAGE", "8"))
N_SHAPE_SOURCE_SCAN_LIMIT = int(os.environ.get("NAUTILUS_N_SHAPE_SOURCE_SCAN_LIMIT", "220"))
RIGHT_SIDE_ENABLED = os.environ.get("NAUTILUS_RIGHT_SIDE_ENABLED", "1").strip() != "0"
RIGHT_SIDE_SOURCE_SCAN_LIMIT = int(os.environ.get("NAUTILUS_RIGHT_SIDE_SOURCE_SCAN_LIMIT", "180"))
RIGHT_SIDE_AI_ENABLED = os.environ.get("NAUTILUS_RIGHT_SIDE_AI_ENABLED", "1").strip() != "0"
RIGHT_SIDE_AI_MIN_SCORE = float(os.environ.get("NAUTILUS_RIGHT_SIDE_AI_MIN_SCORE", "72"))
RIGHT_SIDE_MIN_PCT_CHG = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MIN_PCT_CHG", "0.3"))
RIGHT_SIDE_MAX_OPEN_GAIN = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MAX_OPEN_GAIN", "0.028"))
RIGHT_SIDE_MAX_MA5_EXT = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MAX_MA5_EXT", "0.045"))
RIGHT_SIDE_MAX_VWAP_EXT = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MAX_VWAP_EXT", "0.035"))
RIGHT_SIDE_BUY_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_RIGHT_SIDE_BUY_MAX_PCT_CHG", "5.0"))
RIGHT_SIDE_BUY_MAX_OPEN_GAIN = float(os.environ.get("NAUTILUS_RIGHT_SIDE_BUY_MAX_OPEN_GAIN", "0.03"))
RIGHT_SIDE_BUY_MAX_VWAP_EXT = float(os.environ.get("NAUTILUS_RIGHT_SIDE_BUY_MAX_VWAP_EXT", "0.022"))
RIGHT_SIDE_MIN_AMOUNT = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MIN_AMOUNT", "30000000"))
RIGHT_SIDE_MIN_20D_RETURN = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MIN_20D_RETURN", "0.08"))
RIGHT_SIDE_MIN_60D_RETURN = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MIN_60D_RETURN", "0.12"))
RIGHT_SIDE_MAX_20D_HIGH_GAP = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MAX_20D_HIGH_GAP", "0.035"))
RIGHT_SIDE_MIN_MA20_SLOPE = float(os.environ.get("NAUTILUS_RIGHT_SIDE_MIN_MA20_SLOPE", "0.015"))
HOT_LEADER_ENABLED = os.environ.get("NAUTILUS_HOT_LEADER_ENABLED", "1").strip() != "0"
HOT_LEADER_AMOUNT_TOP_PCT = float(os.environ.get("NAUTILUS_HOT_LEADER_AMOUNT_TOP_PCT", "0.10"))
HOT_LEADER_5D_TOP_PCT = float(os.environ.get("NAUTILUS_HOT_LEADER_5D_TOP_PCT", "0.15"))
HOT_LEADER_MAIN_NET_TOP_PCT = float(os.environ.get("NAUTILUS_HOT_LEADER_MAIN_NET_TOP_PCT", "0.20"))
HOT_LEADER_MIN_LISTING_DAYS = int(os.environ.get("NAUTILUS_HOT_LEADER_MIN_LISTING_DAYS", "60"))
HOT_LEADER_FLOW_TTL_SEC = max(20.0, float(os.environ.get("NAUTILUS_HOT_LEADER_FLOW_TTL", "60")))
HOT_LEADER_MAX_HISTORY_CHECKS = int(os.environ.get("NAUTILUS_HOT_LEADER_MAX_HISTORY_CHECKS", "80"))
HOT_LEADER_FLOW_MAX_PAGES = int(os.environ.get("NAUTILUS_HOT_LEADER_FLOW_MAX_PAGES", "60"))
HOT_LEADER_FLEXIBLE_FALLBACK = os.environ.get("NAUTILUS_HOT_LEADER_FLEXIBLE_FALLBACK", "1").strip() != "0"
HOT_LEADER_FLEXIBLE_LIMIT = int(os.environ.get("NAUTILUS_HOT_LEADER_FLEXIBLE_LIMIT", "10"))
LEADER_MIN_AMOUNT = float(os.environ.get("NAUTILUS_LEADER_MIN_AMOUNT", "150000000"))
LEADER_TOP_AMOUNT_RANK = int(os.environ.get("NAUTILUS_LEADER_TOP_AMOUNT_RANK", "80"))
LEADER_TOP_PCT_RANK = int(os.environ.get("NAUTILUS_LEADER_TOP_PCT_RANK", "120"))
LEADER_MIN_HEAT_SCORE = float(os.environ.get("NAUTILUS_LEADER_MIN_HEAT_SCORE", "58"))
LEADER_LIVE_MIN_HEAT_SCORE = float(os.environ.get("NAUTILUS_LEADER_LIVE_MIN_HEAT_SCORE", "42"))
LEADER_AVOID_KEYWORDS = tuple(
    item.strip()
    for item in os.environ.get(
        "NAUTILUS_LEADER_AVOID_KEYWORDS",
        "银行,保险,石油,茅台,格力,电信,移动,联通,中国建筑,中国中铁,中国铁建,中国交建,交通银行,农业银行,工商银行,邮储银行",
    ).split(",")
    if item.strip()
)
AI_BUY_MODE = os.environ.get("NAUTILUS_AI_BUY_MODE", "ai_guided").strip().lower()
AI_BUY_ENABLED = AI_BUY_MODE != "off"
AI_GUARD_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_AI_GUARD_MAX_PCT_CHG", "4.8"))
AI_GUARD_AFTERNOON_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_AI_GUARD_AFTERNOON_MAX_PCT_CHG", "3.8"))
AI_GUARD_MIN_AMOUNT = float(os.environ.get("NAUTILUS_AI_GUARD_MIN_AMOUNT", "30000000"))
AI_GUARD_MAX_SPREAD_PCT = float(os.environ.get("NAUTILUS_AI_GUARD_MAX_SPREAD_PCT", "0.35"))
PUBLIC_RISK_SYMBOLS = {
    re.sub(r"\D", "", item.split(":", 1)[0])[-6:]: (item.split(":", 1)[1].strip() if ":" in item else "手动公共风险拦截")
    for item in os.environ.get(
        "NAUTILUS_PUBLIC_RISK_SYMBOLS",
        "002600:领益智造近期H股上市首日破发，属于买前公共风险，暂停AI新买",
    ).split("|")
    if re.sub(r"\D", "", item.split(":", 1)[0])[-6:]
}
ANNOUNCEMENT_GUARD_ENABLED = os.environ.get("NAUTILUS_ANNOUNCEMENT_GUARD_ENABLED", "1").strip() != "0"
ANNOUNCEMENT_LOOKBACK_DAYS = max(1, int(os.environ.get("NAUTILUS_ANNOUNCEMENT_LOOKBACK_DAYS", "7")))
ANNOUNCEMENT_REDUCTION_LOOKBACK_DAYS = max(1, int(os.environ.get("NAUTILUS_ANNOUNCEMENT_REDUCTION_LOOKBACK_DAYS", "7")))
ANNOUNCEMENT_CACHE_TTL_SEC = max(60.0, float(os.environ.get("NAUTILUS_ANNOUNCEMENT_CACHE_TTL", "1800")))
ANNOUNCEMENT_BLOCK_KEYWORDS = tuple(
    item.strip()
    for item in os.environ.get(
        "NAUTILUS_ANNOUNCEMENT_BLOCK_KEYWORDS",
        "减持,拟减持,股份减持,减持计划,减持股份,解禁,限售股上市流通,立案,监管函,问询函,关注函,业绩预亏,业绩亏损,重大诉讼,H股,港股,境外上市,上市首日,首日破发,破发",
    ).split(",")
    if item.strip()
)
ANNOUNCEMENT_REDUCTION_KEYWORDS = ("减持", "拟减持", "股份减持", "减持计划", "减持股份")
ANNOUNCEMENT_REDUCTION_RELIEF_KEYWORDS = ("提前终止", "终止减持", "减持完成", "实施完毕", "结果公告", "时间届满", "期限届满")
RULE_BUY_SOURCES = {"n_shape"}
MARKET_SCAN_BATCH_SIZE = int(os.environ.get("NAUTILUS_MARKET_SCAN_BATCH_SIZE", "320"))
MARKET_SCAN_WORKERS = max(1, int(os.environ.get("NAUTILUS_MARKET_SCAN_WORKERS", "4")))
MARKET_OPEN_START = dt_time(9, 15)
MARKET_MORNING_END = dt_time(11, 30)
MARKET_AFTERNOON_START = dt_time(13, 0)
MARKET_OPEN_END = dt_time(15, 0)
REVIEW_START = dt_time(17, 0)
MAX_REVIEW_ITEMS = 60
MAX_REVIEW_TRADES = 24
REVIEW_MEMORY_DAYS = max(1, int(os.environ.get("NAUTILUS_REVIEW_MEMORY_DAYS", "5")))
POSITION_QUOTE_TTL_OPEN_SEC = max(1.0, float(os.environ.get("NAUTILUS_POSITION_QUOTE_TTL_OPEN", "5")))
POSITION_QUOTE_TTL_CLOSED_SEC = max(30.0, float(os.environ.get("NAUTILUS_POSITION_QUOTE_TTL_CLOSED", "300")))
DEEPSEEK_REVIEW_TIMEOUT_SEC = max(20.0, float(os.environ.get("DEEPSEEK_REVIEW_TIMEOUT", "75")))
DEEPSEEK_REVIEW_RETRIES = max(1, int(os.environ.get("DEEPSEEK_REVIEW_RETRIES", "2")))
TRADING_COACH_ENABLED = os.environ.get("NAUTILUS_TRADING_COACH_ENABLED", "1").strip() != "0"
TRADING_COACH_ALLOW_OVERRIDE = os.environ.get("NAUTILUS_TRADING_COACH_ALLOW_OVERRIDE", "1").strip() != "0"
TRADING_COACH_STRICT_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_TRADING_COACH_STRICT_MAX_PCT_CHG", "3.2"))
TRADING_COACH_CAUTION_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_TRADING_COACH_CAUTION_MAX_PCT_CHG", "3.8"))
TRADING_COACH_MARKET_MAX_PCT_CHG = float(os.environ.get("NAUTILUS_TRADING_COACH_MARKET_MAX_PCT_CHG", "2.5"))
TRADING_COACH_MAX_PULLBACK_DEPTH = float(os.environ.get("NAUTILUS_TRADING_COACH_MAX_PULLBACK_DEPTH", "0.15"))
TRADING_COACH_RELATIVE_STRENGTH_BUFFER = float(os.environ.get("NAUTILUS_TRADING_COACH_RELATIVE_STRENGTH_BUFFER", "0.35"))
YESTERDAY_LIMIT_MAX_DAILY_BUYS = int(os.environ.get("NAUTILUS_YESTERDAY_LIMIT_MAX_DAILY_BUYS", "0"))
THS_BLOGGER_ENABLED = os.environ.get("NAUTILUS_THS_BLOGGER_ENABLED", "1").strip() != "0"
THS_BLOGGER_USER_ID = os.environ.get("NAUTILUS_THS_BLOGGER_USER_ID", "827122963").strip()
THS_BLOGGER_INTERVAL_SEC = max(15.0, float(os.environ.get("NAUTILUS_THS_BLOGGER_INTERVAL", "60")))
THS_BLOGGER_COOKIE = os.environ.get("NAUTILUS_THS_COOKIE", "").strip()
THS_BLOGGER_HOME = f"https://t.10jqka.com.cn/lgt/community/home-page.html?userid={THS_BLOGGER_USER_ID}"
THS_BLOGGER_SEED_CONTENT_IDS = [
    item.strip()
    for item in os.environ.get("NAUTILUS_THS_SEED_CONTENT_IDS", "1dql92bnxi85qr4ec06bc2").split(",")
    if item.strip()
]
THS_HOLDINGS_ENABLED = False
THS_HOLDINGS_SHARE_ID = os.environ.get("NAUTILUS_THS_HOLDINGS_SHARE_ID", "3T4M8JXA000SR8K").strip()
THS_HOLDINGS_BIZ_KEY = os.environ.get("NAUTILUS_THS_HOLDINGS_BIZ_KEY", "827122963_331").strip()
THS_HOLDINGS_INTERVAL_SEC = max(30.0, float(os.environ.get("NAUTILUS_THS_HOLDINGS_INTERVAL", "60")))
THS_HOLDINGS_SHARE_URL = (
    "https://eq.10jqka.com.cn/operation/function/selfstock-share/webpage/index.html"
    f"#/?id={THS_HOLDINGS_SHARE_ID}&st=2&bk={THS_HOLDINGS_BIZ_KEY}"
)


def build_code_range(start: int, end: int) -> list[str]:
    return [f"{code:06d}" for code in range(start, end + 1)]


MARKET_UNIVERSE = (
    build_code_range(1, 4999)
    + build_code_range(600000, 603999)
    + build_code_range(605000, 605999)
)
MARKET_UNIVERSE = tuple(dict.fromkeys(MARKET_UNIVERSE))

MARKET_QUOTE_CACHE: dict[str, dict[str, Any]] = {}
DAILY_BAR_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
MARKET_REGIME_CACHE: dict[str, dict[str, Any]] = {}
MARKET_INDEX_CACHE: dict[str, Any] = {"expires_at": 0.0, "rows": []}
ANNOUNCEMENT_RISK_CACHE: dict[str, dict[str, Any]] = {}
FUND_FLOW_CACHE: dict[str, Any] = {"expires_at": 0.0, "rows": {}}
FUND_FLOW_HISTORY_CACHE: dict[str, dict[str, Any]] = {}


def akshare_market_from_symbol(sym: str) -> str:
    code = normalize_symbol(sym)
    return "sh" if code.startswith(("5", "6", "9")) else "sz"

LOCK = threading.Lock()
CYCLE_LOCK = threading.Lock()
WATCH_THREAD_STARTED = False
BLOGGER_THREAD_STARTED = False
HOLDINGS_THREAD_STARTED = False
STOP_EVENT = threading.Event()
AI_PROVIDER_LABEL = os.environ.get("AI_PROVIDER_LABEL", "deepseek").strip() or "deepseek"
LLM_JSON_RESPONSE_FORMAT = os.environ.get("LLM_JSON_RESPONSE_FORMAT", "1").strip() != "0"
LLM_THINKING_PARAM = os.environ.get("LLM_THINKING_PARAM", "1").strip() != "0"
LLM_RETRIES = max(1, int(os.environ.get("LLM_RETRIES", "3")))
LLM_RETRY_BACKOFF_SEC = max(0.0, float(os.environ.get("LLM_RETRY_BACKOFF_SEC", "1.2")))


def llm_chat_body(model: str, prompt: str, *, temperature: float = 0.2, max_tokens: int = 800) -> bytes:
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if LLM_JSON_RESPONSE_FORMAT:
        body["response_format"] = {"type": "json_object"}
    if LLM_THINKING_PARAM:
        body["thinking"] = {"type": "disabled"}
    return json.dumps(body).encode("utf-8")


def llm_error_summary(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if "UNEXPECTED_EOF_WHILE_READING" in text or "EOF occurred in violation of protocol" in text:
        return f"网关SSL连接被提前断开：{text}"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return f"网关响应超时：{text}"
    return text


def llm_post_json(body: bytes, key: str, *, timeout: float, retries: int | None = None) -> dict[str, Any]:
    url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
    attempts = max(1, int(retries or LLM_RETRIES))
    errors: list[str] = []
    last_exc: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "nautilus-ai-paper/1.0",
                "Connection": "close",
            },
        )
        try:
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            if not raw:
                raise RuntimeError("空响应")
            payload = json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(payload, dict) and payload.get("code") and not payload.get("choices"):
                raise RuntimeError(str(payload)[:500])
            return payload
        except Exception as exc:
            last_exc = exc
            errors.append(f"try{attempt + 1}/{attempts} {llm_error_summary(exc)}")
            if attempt + 1 < attempts:
                time.sleep(LLM_RETRY_BACKOFF_SEC * (attempt + 1))
    raise RuntimeError("；".join(errors[-attempts:])) from last_exc

RUNTIME: dict[str, Any] = {
    "watching": False,
    "running": False,
    "last_quote_at": "",
    "last_decision_at": "",
    "last_error": "",
    "deepseek_enabled": False,
    "nautilus_ok": False,
    "nautilus_version": "",
    "market_scan_total": len(MARKET_UNIVERSE),
    "market_scan_cursor": 0,
    "market_scan_batch_size": MARKET_SCAN_BATCH_SIZE,
    "market_open": False,
    "market_session": "closed",
    "market_next_open_at": "",
    "next_review_at": "",
    "sellable_position_count": 0,
    "ai_buy_blocked_no_sellable": False,
    "deepseek_last_error": "",
    "ai_buy_enabled": AI_BUY_ENABLED,
    "ai_buy_mode": AI_BUY_MODE,
    "blogger_enabled": THS_BLOGGER_ENABLED,
    "blogger_user_id": THS_BLOGGER_USER_ID,
    "blogger_interval_sec": THS_BLOGGER_INTERVAL_SEC,
    "blogger_last_check_at": "",
    "blogger_last_post_at": "",
    "blogger_last_error": "",
    "blogger_need_cookie": False,
    "holdings_enabled": THS_HOLDINGS_ENABLED,
    "holdings_share_id": THS_HOLDINGS_SHARE_ID,
    "holdings_interval_sec": THS_HOLDINGS_INTERVAL_SEC,
    "holdings_last_check_at": "",
    "holdings_last_change_at": "",
    "holdings_last_error": "",
}
RUNTIME["deepseek_enabled"] = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
DB_LAST_SYNC_SIGNATURE = ""


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_history_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                label TEXT NOT NULL,
                state_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                key TEXT PRIMARY KEY,
                time TEXT,
                symbol TEXT,
                side TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                key TEXT PRIMARY KEY,
                time TEXT,
                symbol TEXT,
                side TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                key TEXT PRIMARY KEY,
                time TEXT,
                source TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                key TEXT PRIMARY KEY,
                review_date TEXT,
                generated_at TEXT,
                source TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_time ON orders(time);
            CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(time);
            CREATE INDEX IF NOT EXISTS idx_decisions_time ON decisions(time);
            CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date);
            """
        )


def history_row_key(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    raw = "|".join(str(row.get(field) or "") for field in fields)
    if not raw.strip("|"):
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def history_sync_signature(state: dict[str, Any]) -> str:
    parts = []
    for key in ("orders", "trades", "decisions", "reviews"):
        rows = state.get(key) or []
        tail = rows[-1] if rows else {}
        parts.append(f"{key}:{len(rows)}:{json.dumps(tail, ensure_ascii=False, sort_keys=True)[:240]}")
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def sync_history_to_db(state: dict[str, Any]) -> None:
    global DB_LAST_SYNC_SIGNATURE
    signature = history_sync_signature(state)
    if signature == DB_LAST_SYNC_SIGNATURE:
        return
    try:
        init_history_db()
        with db_connect() as conn:
            for row in state.get("orders") or []:
                key = history_row_key(row, ("time", "symbol", "side", "qty", "price"))
                conn.execute(
                    "INSERT OR REPLACE INTO orders(key,time,symbol,side,payload_json) VALUES(?,?,?,?,?)",
                    (key, row.get("time", ""), normalize_symbol(row.get("symbol")), row.get("side", ""), json.dumps(row, ensure_ascii=False)),
                )
            for row in state.get("trades") or []:
                key = history_row_key(row, ("time", "symbol", "side", "qty", "price"))
                conn.execute(
                    "INSERT OR REPLACE INTO trades(key,time,symbol,side,payload_json) VALUES(?,?,?,?,?)",
                    (key, row.get("time", ""), normalize_symbol(row.get("symbol")), row.get("side", ""), json.dumps(row, ensure_ascii=False)),
                )
            for row in state.get("decisions") or []:
                key = history_row_key(row, ("time", "source", "summary"))
                conn.execute(
                    "INSERT OR REPLACE INTO decisions(key,time,source,payload_json) VALUES(?,?,?,?)",
                    (key, row.get("time", ""), row.get("source", ""), json.dumps(row, ensure_ascii=False)),
                )
            for row in state.get("reviews") or []:
                key = history_row_key(row, ("review_date", "generated_at", "review_source"))
                conn.execute(
                    "INSERT OR REPLACE INTO reviews(key,review_date,generated_at,source,payload_json) VALUES(?,?,?,?,?)",
                    (key, row.get("review_date", ""), row.get("generated_at", ""), row.get("review_source", ""), json.dumps(row, ensure_ascii=False)),
                )
        DB_LAST_SYNC_SIGNATURE = signature
    except Exception as exc:
        RUNTIME["last_error"] = f"历史数据库同步失败：{type(exc).__name__}: {exc}"


def save_state_snapshot_to_db(state: dict[str, Any], label: str) -> None:
    try:
        init_history_db()
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO state_snapshots(created_at,label,state_json) VALUES(?,?,?)",
                (now_iso(), str(label or "snapshot"), json.dumps(state, ensure_ascii=False)),
            )
    except Exception as exc:
        RUNTIME["last_error"] = f"历史数据库快照失败：{type(exc).__name__}: {exc}"


def load_history_table_from_db(table: str, order_col: str) -> list[dict[str, Any]]:
    if not DB_FILE.exists():
        return []
    try:
        init_history_db()
        with db_connect() as conn:
            rows = conn.execute(
                f"SELECT payload_json FROM {table} ORDER BY {order_col}, key"
            ).fetchall()
        return [json.loads(row[0]) for row in rows if row and row[0]]
    except Exception as exc:
        RUNTIME["last_error"] = f"历史数据库读取失败：{type(exc).__name__}: {exc}"
        return []


def merge_history_rows(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in primary + secondary:
        if not isinstance(row, dict):
            continue
        key = history_row_key(row, fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def hydrate_history_from_db(data: dict[str, Any]) -> None:
    table_specs = {
        "orders": ("orders", "time", ("time", "symbol", "side", "qty", "price")),
        "trades": ("trades", "time", ("time", "symbol", "side", "qty", "price")),
        "decisions": ("decisions", "time", ("time", "source", "summary")),
        "reviews": ("reviews", "review_date", ("review_date", "generated_at", "review_source")),
    }
    for key, (table, order_col, fields) in table_specs.items():
        db_rows = load_history_table_from_db(table, order_col)
        if db_rows:
            data[key] = merge_history_rows(db_rows, data.get(key) or [], fields)


def latest_state_snapshot_from_db() -> dict[str, Any] | None:
    if not DB_FILE.exists():
        return None
    try:
        init_history_db()
        with db_connect() as conn:
            row = conn.execute(
                "SELECT created_at,label,state_json FROM state_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        state = json.loads(row[2])
        if not isinstance(state, dict):
            return None
        return {"created_at": row[0], "label": row[1], "state": state}
    except Exception as exc:
        RUNTIME["last_error"] = f"历史数据库快照读取失败：{type(exc).__name__}: {exc}"
        return None


def replay_account_from_trades(state: dict[str, Any]) -> tuple[float, dict[str, dict[str, Any]], str]:
    baseline_state: dict[str, Any] = {}
    baseline_trade_keys: set[str] = set()
    baseline_label = "initial"
    snapshot = latest_state_snapshot_from_db()
    if snapshot:
        baseline_state = snapshot.get("state") or {}
        baseline_label = str(snapshot.get("label") or "snapshot")
    cash = float(baseline_state.get("cash") or state.get("initial_cash") or DEFAULT_CASH)
    positions = json.loads(json.dumps(baseline_state.get("positions") or {}, ensure_ascii=False))
    baseline_trade_keys = {
        history_row_key(row, ("time", "symbol", "side", "qty", "price"))
        for row in (baseline_state.get("trades") or [])
        if isinstance(row, dict)
    }

    for trade in sorted(state.get("trades") or [], key=lambda row: str((row or {}).get("time") or "")):
        if not isinstance(trade, dict):
            continue
        if baseline_trade_keys and history_row_key(trade, ("time", "symbol", "side", "qty", "price")) in baseline_trade_keys:
            continue
        side = str(trade.get("side") or "").upper()
        sym = normalize_symbol(trade.get("symbol"))
        try:
            qty = int(float(trade.get("qty") or 0))
            price = float(trade.get("price") or 0)
        except Exception:
            continue
        if not sym or qty <= 0 or price <= 0:
            continue
        amount = qty * price
        pos = positions.get(sym)
        if side == "BUY":
            cash -= amount
            if pos:
                old_qty = int(pos.get("qty") or 0)
                old_cost = float(pos.get("avg_cost") or 0)
                new_qty = old_qty + qty
                pos["qty"] = new_qty
                pos["avg_cost"] = round((old_qty * old_cost + amount) / new_qty, 4) if new_qty > 0 else price
                pos["last_price"] = price
            else:
                positions[sym] = {
                    "symbol": sym,
                    "name": trade.get("name", ""),
                    "qty": qty,
                    "avg_cost": price,
                    "last_price": price,
                    "opened_at": trade.get("time", ""),
                    "trade_date": str(trade.get("time") or "")[:10],
                    "source": trade.get("ai_source") or trade.get("source") or "",
                }
        elif side == "SELL":
            cash += amount
            if not pos:
                continue
            old_qty = int(pos.get("qty") or 0)
            remain = old_qty - qty
            if remain <= 0:
                positions.pop(sym, None)
            else:
                pos["qty"] = remain
                pos["last_price"] = price
    return round(cash, 2), positions, baseline_label


def account_signature(cash: Any, positions: dict[str, Any]) -> str:
    compact = {
        normalize_symbol(sym): {
            "qty": int((pos or {}).get("qty") or 0),
            "avg_cost": round(float((pos or {}).get("avg_cost") or 0), 2),
        }
        for sym, pos in sorted((positions or {}).items())
        if int((pos or {}).get("qty") or 0) > 0
    }
    return json.dumps({"cash": round(float(cash or 0), 2), "positions": compact}, ensure_ascii=False, sort_keys=True)


def repair_account_from_history_if_needed(data: dict[str, Any]) -> None:
    if not data.get("trades"):
        return
    replay_cash, replay_positions, baseline_label = replay_account_from_trades(data)
    current_sig = account_signature(data.get("cash"), data.get("positions") or {})
    replay_sig = account_signature(replay_cash, replay_positions)
    if current_sig == replay_sig:
        return
    old_cash = round(float(data.get("cash") or 0), 2)
    old_count = len(data.get("positions") or {})
    data["cash"] = replay_cash
    data["positions"] = replay_positions
    logs = list(data.get("logs") or [])
    logs.append({
        "time": now_iso(),
        "msg": f"检测到账户运行态与成交历史不一致，已按{baseline_label}快照和后续成交恢复：现金 {old_cash:.2f}->{replay_cash:.2f}，持仓 {old_count}->{len(replay_positions)}。",
    })
    data["logs"] = logs[-300:]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def market_clock(now: datetime | None = None) -> datetime:
    return now or datetime.now()


def is_market_day(now: datetime | None = None) -> bool:
    return market_clock(now).weekday() < 5


def get_next_market_open(now: datetime | None = None) -> datetime:
    current = market_clock(now)
    open_today = current.replace(hour=MARKET_OPEN_START.hour, minute=MARKET_OPEN_START.minute, second=0, microsecond=0)
    lunch_resume = current.replace(hour=MARKET_AFTERNOON_START.hour, minute=MARKET_AFTERNOON_START.minute, second=0, microsecond=0)
    if current.weekday() < 5:
        if current < open_today:
            return open_today
        if current < lunch_resume and current >= current.replace(hour=MARKET_MORNING_END.hour, minute=MARKET_MORNING_END.minute, second=0, microsecond=0):
            return lunch_resume
    candidate = (current + timedelta(days=1)).replace(hour=MARKET_OPEN_START.hour, minute=MARKET_OPEN_START.minute, second=0, microsecond=0)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def market_status(now: datetime | None = None) -> tuple[bool, datetime, str]:
    current = market_clock(now)
    open_today = current.replace(hour=MARKET_OPEN_START.hour, minute=MARKET_OPEN_START.minute, second=0, microsecond=0)
    morning_end = current.replace(hour=MARKET_MORNING_END.hour, minute=MARKET_MORNING_END.minute, second=0, microsecond=0)
    afternoon_start = current.replace(hour=MARKET_AFTERNOON_START.hour, minute=MARKET_AFTERNOON_START.minute, second=0, microsecond=0)
    close_today = current.replace(hour=MARKET_OPEN_END.hour, minute=MARKET_OPEN_END.minute, second=0, microsecond=0)
    if current.weekday() >= 5:
        return False, get_next_market_open(current), "closed"
    if open_today <= current < morning_end:
        return True, get_next_market_open(current), "open"
    if morning_end <= current < afternoon_start:
        return False, afternoon_start, "lunch"
    if afternoon_start <= current < close_today:
        return True, get_next_market_open(current), "open"
    return False, get_next_market_open(current), "closed"


def normalize_symbol(sym: str) -> str:
    s = "".join(ch for ch in str(sym or "") if ch.isdigit())
    return s[-6:].zfill(6) if s else ""


def market_code(sym: str) -> str:
    s = normalize_symbol(sym)
    return ("sh" if s.startswith(("5", "6", "9")) else "sz") + s


def sina_symbol(sym: str) -> str:
    return market_code(sym)


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("initial_cash", DEFAULT_CASH)
    data.setdefault("cash", DEFAULT_CASH)
    data.setdefault("watchlist", DEFAULT_WATCHLIST[:])
    data.setdefault("positions", {})
    data.setdefault("orders", [])
    data.setdefault("trades", [])
    data.setdefault("decisions", [])
    data.setdefault("reviews", [])
    data.setdefault("quotes", {})
    data.setdefault("candidates", [])
    data.setdefault("strategy_signals", [])
    data.setdefault("strategy_watchlist", [])
    data.setdefault("right_side_watchlist", [])
    data.setdefault("ai_buy_candidates", [])
    data.setdefault("t_signals", [])
    data.setdefault("t_ledger", [])
    data.setdefault("fund_flow_snapshot", {})
    data.setdefault("ai_ask_history", [])
    data.setdefault("announcement_risks", {})
    data.setdefault("strategy_diagnostics", {})
    data.setdefault("blogger_posts", [])
    data.setdefault("blogger_seen_ids", [])
    data.setdefault("blogger_alerts", [])
    data.setdefault("influencer_holdings", {})
    data.setdefault("influencer_holding_alerts", [])
    data.setdefault("logs", [])
    data.setdefault("market_scan_cursor", 0)
    data.setdefault("watching_enabled", False)
    hydrate_history_from_db(data)
    repair_account_from_history_if_needed(data)
    return data


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_history_to_db(state)


def backup_state_file(label: str) -> Path | None:
    if not STATE_FILE.exists():
        return None
    backup_dir = DASHBOARD / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(label or "manual"))
    target = backup_dir / f"ai_paper_state_{safe_label}.json"
    target.write_text(STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        save_state_snapshot_to_db(json.loads(target.read_text(encoding="utf-8")), safe_label)
    except Exception as exc:
        RUNTIME["last_error"] = f"历史数据库快照失败：{type(exc).__name__}: {exc}"
    return target


def append_log(state: dict[str, Any], msg: str) -> None:
    logs = list(state.get("logs") or [])
    logs.append({"time": now_iso(), "msg": msg})
    state["logs"] = logs[-300:]


def clean_post_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<hx_stock>stockName:([^,]+),stockCode:([^,]+),market:[^<]+</hx_stock>", r"$$\1(\2)$$", text)
    text = re.sub(r"<hx_topic>topicName:(.*?),topicCode:.*?</hx_topic>", r"#\1#", text)
    text = re.sub(r"<hx_at>userId:[^:]+,userName:([^:]+)</hx_at>", r"@\1", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_announcement_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(str(value or "")))).strip()


def extract_json_object_text(text: str) -> str:
    raw = str(text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("返回内容不是JSON")
    return raw[start:end + 1]


def repair_model_json_text(text: str) -> str:
    repaired = text.strip()
    repaired = repaired.replace("，", ",").replace("：", ":")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"(?<=[\]}\"0-9])\s*\n\s*(?=\"[^\"\n]+\"\s*:)", ",\n", repaired)
    repaired = re.sub(r"(?<=[\]}\"])\s+(?=\"[^\"\n]+\"\s*:)", ", ", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    return repaired


def parse_model_json_object(text: str) -> dict[str, Any]:
    obj_text = extract_json_object_text(text)
    try:
        result = json.loads(obj_text)
    except json.JSONDecodeError as first_exc:
        repaired = repair_model_json_text(obj_text)
        try:
            result = json.loads(repaired)
        except json.JSONDecodeError:
            raise first_exc
    if not isinstance(result, dict):
        raise ValueError("返回JSON不是对象")
    return result


def parse_announcement_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000).date().isoformat()
        except Exception:
            return ""
    text = str(value)
    match = re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", text)
    if not match:
        return ""
    try:
        return datetime.fromisoformat(match.group(0).replace("/", "-")).date().isoformat()
    except Exception:
        return match.group(0).replace("/", "-")


def announcement_cutoff_date(now: datetime | None = None) -> str:
    return (market_clock(now).date() - timedelta(days=ANNOUNCEMENT_LOOKBACK_DAYS)).isoformat()


def announcement_hit_keywords(text: str) -> list[str]:
    return [kw for kw in ANNOUNCEMENT_BLOCK_KEYWORDS if kw and kw in text]


def announcement_item_date(item: dict[str, Any]) -> date | None:
    text = str(item.get("date") or "")
    try:
        return datetime.fromisoformat(text[:10]).date()
    except Exception:
        return None


def announcement_is_reduction_item(item: dict[str, Any]) -> bool:
    text = f"{item.get('title') or ''} {item.get('columns') or ''}"
    keywords = item.get("keywords") or []
    return any(kw in text or kw in keywords for kw in ANNOUNCEMENT_REDUCTION_KEYWORDS)


def announcement_is_reduction_relief(item: dict[str, Any]) -> bool:
    text = f"{item.get('title') or ''} {item.get('columns') or ''}"
    return announcement_is_reduction_item(item) and any(kw in text for kw in ANNOUNCEMENT_REDUCTION_RELIEF_KEYWORDS)


def announcement_item_is_active_risk(item: dict[str, Any], now: datetime | None = None) -> bool:
    if announcement_is_reduction_relief(item):
        return False
    item_day = announcement_item_date(item)
    if item_day is None:
        return True
    current_day = market_clock(now).date()
    lookback_days = ANNOUNCEMENT_REDUCTION_LOOKBACK_DAYS if announcement_is_reduction_item(item) else ANNOUNCEMENT_LOOKBACK_DAYS
    return item_day >= current_day - timedelta(days=lookback_days)


def announcement_risk_is_active(risk: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not risk or not risk.get("blocked"):
        return False
    return any(announcement_item_is_active_risk(item, now) for item in (risk.get("items") or []))


def cninfo_stock_param(sym: str) -> tuple[str, str, str] | None:
    code = normalize_symbol(sym)
    if not code:
        return None
    if code.startswith(("000", "001", "002", "003")):
        return f"{code},gssz0{code}", "szse", "sz"
    if code.startswith(("600", "601", "603", "605")):
        return f"{code},gssh0{code}", "sse", "sh"
    return None


def fetch_eastmoney_announcements(sym: str) -> list[dict[str, Any]]:
    code = normalize_symbol(sym)
    if not code:
        return []
    params = urllib.parse.urlencode({
        "sr": "-1",
        "page_size": "20",
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": code,
    })
    url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    raw = opener.open(req, timeout=8).read()
    payload = json.loads(raw.decode("utf-8"))
    rows = []
    for item in ((payload.get("data") or {}).get("list") or []):
        title = clean_announcement_text(item.get("title") or item.get("title_ch"))
        columns = "、".join(clean_announcement_text(col.get("column_name")) for col in (item.get("columns") or []) if isinstance(col, dict))
        text = f"{title} {columns}"
        hits = announcement_hit_keywords(text)
        if not hits:
            continue
        rows.append({
            "source": "eastmoney",
            "symbol": code,
            "title": title,
            "columns": columns,
            "date": parse_announcement_date(item.get("notice_date") or item.get("display_time")),
            "keywords": hits,
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{item.get('art_code', '')}.html" if item.get("art_code") else "",
        })
    return rows


def fetch_cninfo_announcements(sym: str) -> list[dict[str, Any]]:
    code = normalize_symbol(sym)
    params = cninfo_stock_param(code)
    if not params:
        return []
    stock_param, column, plate = params
    start = (market_clock().date() - timedelta(days=ANNOUNCEMENT_LOOKBACK_DAYS)).isoformat()
    end = market_clock().date().isoformat()
    rows = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for keyword in ANNOUNCEMENT_BLOCK_KEYWORDS:
        body = urllib.parse.urlencode({
            "stock": stock_param,
            "pageNum": "1",
            "pageSize": "10",
            "column": column,
            "tabName": "fulltext",
            "plate": plate,
            "searchkey": keyword,
            "seDate": f"{start}~{end}",
            "isHLtitle": "true",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
            },
        )
        try:
            payload = json.loads(opener.open(req, timeout=8).read().decode("utf-8"))
        except Exception:
            continue
        for item in payload.get("announcements") or []:
            title = clean_announcement_text(item.get("announcementTitle") or item.get("shortTitle"))
            text = f"{title} {keyword}"
            hits = announcement_hit_keywords(text)
            if not hits:
                continue
            adjunct = str(item.get("adjunctUrl") or "")
            rows.append({
                "source": "cninfo",
                "symbol": code,
                "title": title,
                "columns": "",
                "date": parse_announcement_date(item.get("announcementTime")),
                "keywords": hits,
                "url": f"https://static.cninfo.com.cn/{adjunct}" if adjunct else "",
            })
        if rows:
            break
    return rows


def announcement_risk_for_symbol(sym: str, force: bool = False) -> dict[str, Any]:
    code = normalize_symbol(sym)
    if not code or not ANNOUNCEMENT_GUARD_ENABLED:
        return {"blocked": False, "symbol": code, "items": [], "reason": ""}
    manual_reason = PUBLIC_RISK_SYMBOLS.get(code)
    if manual_reason:
        return {
            "blocked": True,
            "symbol": code,
            "reason": f"公共风险：{manual_reason}",
            "items": [{
                "source": "manual_public_risk",
                "symbol": code,
                "title": manual_reason,
                "date": market_clock().date().isoformat(),
                "keywords": ["公共风险", "H股", "破发"],
                "url": "",
            }],
            "checked_at": now_iso(),
            "errors": [],
        }
    cached = ANNOUNCEMENT_RISK_CACHE.get(code)
    if cached and not force and time.time() < float(cached.get("expires_at") or 0):
        cached_risk = cached.get("risk") or {"blocked": False, "symbol": code, "items": [], "reason": ""}
        if announcement_risk_is_active(cached_risk):
            return cached_risk
        return {"blocked": False, "symbol": code, "items": [], "reason": ""}
    cutoff = announcement_cutoff_date()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for fetcher in (fetch_eastmoney_announcements, fetch_cninfo_announcements):
        try:
            items.extend(fetcher(code))
        except Exception as exc:
            errors.append(f"{fetcher.__name__}:{type(exc).__name__}")
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        item_date = str(item.get("date") or "")
        if item_date and item_date < cutoff:
            continue
        if not announcement_item_is_active_risk(item):
            continue
        key = f"{item.get('source')}:{item.get('title')}:{item_date}"
        deduped[key] = item
    final_items = sorted(deduped.values(), key=lambda row: row.get("date") or "", reverse=True)[:5]
    reason = ""
    if final_items:
        first = final_items[0]
        reason = f"公告风险：{first.get('date') or '近期'} {first.get('title') or ''}"
    risk = {
        "blocked": bool(final_items),
        "symbol": code,
        "reason": reason,
        "items": final_items,
        "checked_at": now_iso(),
        "errors": errors[-3:],
    }
    ANNOUNCEMENT_RISK_CACHE[code] = {"expires_at": time.time() + ANNOUNCEMENT_CACHE_TTL_SEC, "risk": risk}
    return risk


def collect_announcement_risks(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not ANNOUNCEMENT_GUARD_ENABLED:
        return {}
    risks: dict[str, dict[str, Any]] = {}
    for sym in dedupe_symbols(symbols)[:80]:
        risk = announcement_risk_for_symbol(sym)
        if announcement_risk_is_active(risk):
            risks[normalize_symbol(sym)] = risk
    return risks


def post_id_from_item(item: dict[str, Any]) -> str:
    for key in ("pid", "post_id", "postId", "biz_id", "bizId", "item_id", "itemId", "id", "hot_key", "hotKey"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def blogger_fallback_id(text: str, url: str = "") -> str:
    base = f"{url}\n{text}".strip()
    return "browser:" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def stable_blogger_post_key(post: dict[str, Any]) -> str:
    text = clean_post_text(post.get("text") or post.get("title") or "")[:220]
    stocks = ",".join(dedupe_symbols(post.get("stocks") or []))
    raw_time = str(post.get("time") or "")
    minute = raw_time[:16] if len(raw_time) >= 16 else raw_time
    base = f"{stocks}\n{minute}\n{text}".strip()
    if not base:
        base = str(post.get("id") or "")
    return "post:" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def post_time_from_item(item: dict[str, Any]) -> str:
    for key in ("ctime", "create_time", "createTime", "publish_time", "publishTime", "time"):
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            num = float(value)
            if num > 10_000_000_000:
                num /= 1000.0
            if num > 1_000_000_000:
                return datetime.fromtimestamp(num).isoformat(timespec="seconds")
        except Exception:
            pass
        return str(value)
    return ""


def stock_codes_from_post(item: dict[str, Any], text: str) -> list[str]:
    codes: list[str] = []
    forum = item.get("forum")
    if isinstance(forum, dict):
        code = normalize_symbol(forum.get("code"))
        if code:
            codes.append(code)
    for forum_key in ("forumList", "forum_list"):
        forums = item.get(forum_key) or []
        if isinstance(forums, list):
            for forum in forums:
                if isinstance(forum, dict):
                    code = normalize_symbol(forum.get("code"))
                    if code:
                        codes.append(code)
    codes.extend(normalize_symbol(code) for code in re.findall(r"(?<!\d)(?:[036]\d{5})(?!\d)", text))
    return dedupe_symbols([code for code in codes if code])


def compact_blogger_post(item: dict[str, Any]) -> dict[str, Any]:
    text = clean_post_text(item.get("summary") or item.get("content") or item.get("title") or "")
    title = clean_post_text(item.get("title") or "")
    if title and title not in text:
        text = f"{title} {text}".strip()
    return {
        "id": post_id_from_item(item),
        "time": post_time_from_item(item),
        "title": title,
        "text": text[:500],
        "stocks": stock_codes_from_post(item, text),
        "url": item.get("jumpUrl") or item.get("jump_url") or item.get("url") or THS_BLOGGER_HOME,
        "raw_type": item.get("bizType") or item.get("biz_type") or item.get("type") or "",
    }


def walk_json_for_posts(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("contentList", "content_list", "postList", "post_list", "list", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        if any(k in item for k in ("summary", "content", "title", "bizId", "pid", "jumpUrl")):
                            found.append(item)
                        else:
                            found.extend(walk_json_for_posts(item))
            elif isinstance(value, dict):
                found.extend(walk_json_for_posts(value))
    return found


def ths_headers() -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Accept": "application/json,text/plain,*/*",
        "Referer": THS_BLOGGER_HOME,
    }
    if THS_BLOGGER_COOKIE:
        headers["Cookie"] = THS_BLOGGER_COOKIE
    return headers


def fetch_ths_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"https://t.10jqka.com.cn{path}?{query}"
    req = urllib.request.Request(url, headers=ths_headers())
    raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def fetch_ths_public_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"https://c.10jqka.com.cn{path}?{query}"
    headers = ths_headers()
    headers["Referer"] = "https://c.10jqka.com.cn/m/post/discussDetail/"
    req = urllib.request.Request(url, headers=headers)
    raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def fetch_public_blogger_post(content_id: str) -> dict[str, Any] | None:
    if not content_id:
        return None
    payload = fetch_ths_public_json("/lgt/post/open/api/post/info/get", {"content_id": content_id})
    status_code = payload.get("status_code", payload.get("statusCode"))
    if status_code != 0:
        return None
    post = ((payload.get("data") or {}).get("post") or {})
    if str(post.get("uid") or "") != str(THS_BLOGGER_USER_ID):
        return None
    return compact_blogger_post(post)


def fetch_seed_blogger_posts() -> list[dict[str, Any]]:
    posts = []
    for content_id in THS_BLOGGER_SEED_CONTENT_IDS[:20]:
        try:
            post = fetch_public_blogger_post(content_id)
        except Exception:
            post = None
        if post:
            posts.append(post)
    return posts


def fetch_blogger_posts() -> tuple[list[dict[str, Any]], str]:
    if not (THS_BLOGGER_ENABLED and THS_BLOGGER_USER_ID):
        return [], "disabled"
    attempts = [
        ("/lgt/post/open/api/user/post", {"uid": THS_BLOGGER_USER_ID, "page": 1, "page_size": 15, "pid": 0}),
        ("/user_center/open/api/content/v1/get_by_uid", {"uid": THS_BLOGGER_USER_ID, "limit": 20}),
        ("/user_center/open/api/content/v1/get_by_uid", {"user_id": THS_BLOGGER_USER_ID, "limit": 20}),
    ]
    errors: list[str] = []
    for path, params in attempts:
        try:
            payload = fetch_ths_json(path, params)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        status_code = payload.get("status_code", payload.get("statusCode", payload.get("errorCode")))
        status_msg = payload.get("status_msg", payload.get("statusMsg", payload.get("errorMsg", "")))
        posts = [compact_blogger_post(item) for item in walk_json_for_posts(payload)]
        posts = [post for post in posts if post.get("text") or post.get("title")]
        if posts:
            return posts, ""
        if status_code not in (0, 100, None):
            errors.append(f"{path}: {status_code} {status_msg}".strip())
    seed_posts = fetch_seed_blogger_posts()
    if seed_posts:
        return seed_posts, "公开列表接口暂未命中；已读取详情页种子帖。保持浏览器主页推送可收到新帖。"
    return [], "；".join(errors[-3:]) or "未返回帖子"


def import_blogger_posts(posts: list[dict[str, Any]], source: str = "browser") -> list[dict[str, Any]]:
    normalized = []
    for item in posts:
        if not isinstance(item, dict):
            continue
        content_id = str(item.get("content_id") or item.get("contentId") or "").strip()
        url = str(item.get("url") or item.get("jump_url") or item.get("jumpUrl") or "")
        if not content_id:
            match = re.search(r"contentId=([0-9a-z]+)", url)
            if match:
                content_id = match.group(1)
        post = None
        if content_id:
            try:
                post = fetch_public_blogger_post(content_id)
            except Exception:
                post = None
        if post is None:
            text = clean_post_text(item.get("text") or item.get("content") or item.get("title") or "")
            if not text:
                continue
            post = {
                "id": content_id or blogger_fallback_id(text, url),
                "time": str(item.get("time") or item.get("ctime") or now_iso()),
                "title": clean_post_text(item.get("title") or ""),
                "text": text[:500],
                "stocks": stock_codes_from_post(item, text),
                "url": url or THS_BLOGGER_HOME,
                "raw_type": source,
            }
        normalized.append(post)
    new_posts: list[dict[str, Any]] = []
    with LOCK:
        state = load_state()
        old_posts = list(state.get("blogger_posts") or [])
        seen = set(str(x) for x in (state.get("blogger_seen_ids") or []))
        merged: dict[str, dict[str, Any]] = {stable_blogger_post_key(post): post for post in old_posts if post.get("id")}
        for post in normalized:
            pid = stable_blogger_post_key(post)
            if not pid:
                continue
            post["stable_id"] = pid
            merged[pid] = post
            if pid not in seen:
                seen.add(pid)
                new_posts.append(post)
        if new_posts:
            alerts = list(state.get("blogger_alerts") or [])
            for post in new_posts:
                alerts.append({"time": now_iso(), "post": post})
                append_log(state, f"浏览器推送博主新帖：{post.get('text') or post.get('title')}")
            state["blogger_alerts"] = alerts[-80:]
        state["blogger_posts"] = list(merged.values())[-80:]
        state["blogger_seen_ids"] = list(seen)[-300:]
        RUNTIME["blogger_last_check_at"] = now_iso()
        RUNTIME["blogger_last_error"] = ""
        RUNTIME["blogger_need_cookie"] = False
        if normalized:
            RUNTIME["blogger_last_post_at"] = normalized[0].get("time") or now_iso()
        save_state(state)
    return new_posts


def poll_blogger_posts(force: bool = False) -> list[dict[str, Any]]:
    if not THS_BLOGGER_ENABLED:
        return []
    posts, error = fetch_blogger_posts()
    with LOCK:
        state = load_state()
        old_posts = list(state.get("blogger_posts") or [])
        seen = set(str(x) for x in (state.get("blogger_seen_ids") or []))
        first_run = not seen and not old_posts
        new_posts = []
        for post in posts:
            pid = stable_blogger_post_key(post)
            post["stable_id"] = pid
            if pid and pid not in seen:
                new_posts.append(post)
                seen.add(pid)
        if posts:
            merged: dict[str, dict[str, Any]] = {stable_blogger_post_key(post): post for post in old_posts if post.get("id")}
            for post in posts:
                post["stable_id"] = stable_blogger_post_key(post)
                merged[str(post.get("stable_id"))] = post
            state["blogger_posts"] = list(merged.values())[-80:]
            state["blogger_seen_ids"] = list(seen)[-300:]
            RUNTIME["blogger_last_post_at"] = posts[0].get("time") or now_iso()
            RUNTIME["blogger_need_cookie"] = False
        RUNTIME["blogger_last_check_at"] = now_iso()
        RUNTIME["blogger_last_error"] = error
        if error:
            RUNTIME["blogger_need_cookie"] = any(token in error for token in ("unauthorized", "3000", "404", "param error"))
            if force:
                append_log(state, f"博主新帖检查失败：{error}")
        elif new_posts and not first_run:
            alerts = list(state.get("blogger_alerts") or [])
            for post in new_posts:
                alerts.append({"time": now_iso(), "post": post})
                append_log(state, f"博主发新帖：{post.get('text') or post.get('title')}")
            state["blogger_alerts"] = alerts[-80:]
        elif force and posts:
            append_log(state, f"博主新帖检查完成：当前可读取 {len(posts)} 条。")
        save_state(state)
    return [] if first_run else new_posts


def ths_holdings_headers() -> dict[str, str]:
    headers = ths_headers()
    headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Referer": THS_HOLDINGS_SHARE_URL,
        "Origin": "https://eq.10jqka.com.cn",
    })
    return headers


def fetch_ths_holdings_json() -> dict[str, Any]:
    params = {
        "id_type": "share",
        "id": THS_HOLDINGS_SHARE_ID,
        "support_all": 1,
        "from": "sjcg_web",
    }
    query = urllib.parse.urlencode(params)
    url = f"https://ugc.10jqka.com.cn/optdata/selfgroup/noauth/api/share/v1/query?{query}"
    req = urllib.request.Request(url, headers=ths_holdings_headers())
    raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def compact_holding_stock(item: dict[str, Any], quote: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = normalize_symbol(item.get("code") or item.get("stock_code") or item.get("symbol"))
    quote = quote or {}
    return {
        "symbol": symbol,
        "market": item.get("market") or item.get("market_id") or "",
        "name": quote.get("name") or item.get("name") or item.get("stock_name") or "",
        "price": to_float(quote.get("price"), 0.0),
        "pct_chg": to_float(quote.get("pct_chg"), 0.0),
    }


def fetch_influencer_holdings() -> tuple[dict[str, Any], str]:
    if not (THS_HOLDINGS_ENABLED and THS_HOLDINGS_SHARE_ID):
        return {}, "disabled"
    payload = fetch_ths_holdings_json()
    status_code = payload.get("status_code", payload.get("statusCode", payload.get("errorCode")))
    status_msg = payload.get("status_msg", payload.get("statusMsg", payload.get("errorMsg", "")))
    if status_code not in (0, "0", None):
        return {}, f"{status_code} {status_msg}".strip()
    data = payload.get("data") or {}
    raw_stocks = data.get("selfstock") or data.get("selfStock") or data.get("stocks") or []
    if not isinstance(raw_stocks, list):
        raw_stocks = []
    symbols = dedupe_symbols([
        normalize_symbol(item.get("code") or item.get("stock_code") or item.get("symbol"))
        for item in raw_stocks
        if isinstance(item, dict)
    ])
    quotes: dict[str, dict[str, Any]] = {}
    try:
        quotes = fetch_sina_quotes(symbols)
    except Exception:
        quotes = {}
    stocks = [
        compact_holding_stock(item, quotes.get(normalize_symbol(item.get("code") or item.get("stock_code") or item.get("symbol"))))
        for item in raw_stocks
        if isinstance(item, dict) and normalize_symbol(item.get("code") or item.get("stock_code") or item.get("symbol"))
    ]
    stocks = [stock for stock in stocks if stock.get("symbol")]
    snapshot = {
        "group_name": data.get("group_name") or data.get("groupName") or "游神持仓",
        "share_name": data.get("share_name") or data.get("shareName") or "游神所有持仓",
        "nickname": data.get("nickname") or "顶级游神大号10w粉",
        "followed_num": data.get("followed_num") or data.get("followedNum") or 0,
        "share_userid": str(data.get("share_userid") or data.get("shareUserId") or THS_BLOGGER_USER_ID),
        "source_url": THS_HOLDINGS_SHARE_URL,
        "updated_at": now_iso(),
        "stocks": stocks,
    }
    return snapshot, ""


def holding_symbols(snapshot: dict[str, Any]) -> list[str]:
    return [normalize_symbol(stock.get("symbol")) for stock in (snapshot.get("stocks") or []) if normalize_symbol(stock.get("symbol"))]


def build_holding_alert(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    old_stocks = {normalize_symbol(stock.get("symbol")): stock for stock in (previous.get("stocks") or []) if normalize_symbol(stock.get("symbol"))}
    new_stocks = {normalize_symbol(stock.get("symbol")): stock for stock in (current.get("stocks") or []) if normalize_symbol(stock.get("symbol"))}
    added_symbols = [symbol for symbol in new_stocks if symbol not in old_stocks]
    removed_symbols = [symbol for symbol in old_stocks if symbol not in new_stocks]
    if not added_symbols and not removed_symbols:
        return None
    fingerprint = "|".join([
        ",".join(sorted(new_stocks)),
        "+".join(sorted(added_symbols)),
        "-".join(sorted(removed_symbols)),
    ])
    return {
        "id": "holdings:" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16],
        "time": now_iso(),
        "group_name": current.get("group_name") or "游神持仓",
        "share_name": current.get("share_name") or "",
        "nickname": current.get("nickname") or "",
        "added": [new_stocks[symbol] for symbol in added_symbols],
        "removed": [old_stocks[symbol] for symbol in removed_symbols],
        "stocks": current.get("stocks") or [],
        "source_url": current.get("source_url") or THS_HOLDINGS_SHARE_URL,
    }


def poll_influencer_holdings(force: bool = False) -> list[dict[str, Any]]:
    if not THS_HOLDINGS_ENABLED:
        return []
    try:
        snapshot, error = fetch_influencer_holdings()
    except Exception as exc:
        snapshot, error = {}, str(exc)
    with LOCK:
        state = load_state()
        RUNTIME["holdings_last_check_at"] = now_iso()
        RUNTIME["holdings_last_error"] = error
        alerts: list[dict[str, Any]] = []
        if error:
            if force:
                append_log(state, f"游神持仓检查失败：{error}")
            save_state(state)
            return []
        previous = state.get("influencer_holdings") or {}
        first_run = not holding_symbols(previous)
        alert = build_holding_alert(previous, snapshot) if snapshot else None
        state["influencer_holdings"] = snapshot
        if alert and not first_run:
            old_alerts = list(state.get("influencer_holding_alerts") or [])
            old_alerts.append(alert)
            state["influencer_holding_alerts"] = old_alerts[-80:]
            RUNTIME["holdings_last_change_at"] = alert["time"]
            added = "、".join(stock.get("symbol", "") for stock in alert.get("added", [])) or "无"
            removed = "、".join(stock.get("symbol", "") for stock in alert.get("removed", [])) or "无"
            append_log(state, f"游神持仓更新：新增 {added}；移除 {removed}")
            alerts = [alert]
        elif force and snapshot:
            append_log(state, f"游神持仓检查完成：当前 {len(snapshot.get('stocks') or [])} 只。")
        save_state(state)
    return alerts


def append_review(state: dict[str, Any], review: dict[str, Any]) -> None:
    reviews = list(state.get("reviews") or [])
    reviews.append(review)
    state["reviews"] = reviews[-MAX_REVIEW_ITEMS:]


def latest_review(state: dict[str, Any]) -> dict[str, Any] | None:
    reviews = state.get("reviews") or []
    return reviews[-1] if reviews else None


def compact_review(review: dict[str, Any] | None) -> dict[str, Any] | None:
    if not review:
        return None
    review = sanitize_review_t1_language(review)
    return {
        "review_date": review.get("review_date", ""),
        "review_source": review.get("review_source", ""),
        "summary": review.get("summary", ""),
        "wins": (review.get("wins") or [])[:3],
        "losses": (review.get("losses") or [])[:3],
        "next_rules": (review.get("next_rules") or [])[:5],
        "total_pnl": review.get("total_pnl", 0.0),
        "total_pnl_pct": review.get("total_pnl_pct", 0.0),
        "realized_pnl": review.get("realized_pnl", 0.0),
        "realized_pnl_pct": review.get("realized_pnl_pct", 0.0),
        "unrealized_pnl": review.get("unrealized_pnl", 0.0),
        "day_pnl": review.get("day_pnl", review.get("realized_pnl", 0.0)),
        "previous_total_pnl": review.get("previous_total_pnl", 0.0),
        "trade_mark_pnl": review.get("trade_mark_pnl", 0.0),
        "trade_count": review.get("trade_count", 0),
        "confidence": review.get("confidence", 0.0),
    }


def review_has_t1_intraday_only(review: dict[str, Any] | None) -> bool:
    if not review:
        return False
    rows = review.get("intraday_rows") or []
    if not rows:
        return False
    if any(row.get("can_sell_today") is True for row in rows):
        return False
    return True


def sanitize_t1_review_text(text: str) -> str:
    text = str(text or "")
    replacements = {
        "弱市环境下冲高未及时移动止盈导致利润回吐": "今日新仓受T+1限制无法盘中卖出，弱市冲高回落导致浮盈回吐，需明日可卖后按移动止盈/止损处理",
        "没有把盘中浮盈转化为移动止盈/分批止盈": "今日新仓T+1不可卖，盘中浮盈只能作为明日可卖后的风险处理依据",
        "未能把盘中浮盈转化为移动止盈/分批止盈": "今日新仓T+1不可卖，盘中浮盈只能作为明日可卖后的风险处理依据",
        "未在高点部分止盈": "今日新仓T+1不可卖，不能要求当日高点止盈",
        "未及时移动止盈": "今日新仓T+1不可卖，不能归责为当日未移动止盈；明日可卖后再执行移动止盈",
        "未及时止盈": "今日新仓T+1不可卖，不能归责为当日未止盈；明日可卖后再执行止盈",
        "应执行移动止盈规则": "明日可卖后应执行移动止盈规则",
        "必须移动止盈或分批止盈": "若为可卖持仓才移动止盈或分批止盈；今日新仓只能记录冲高回落风险",
        "启动移动止盈或分批止盈": "明日可卖后启动移动止盈或分批止盈",
        "至少锁定一部分利润": "可卖后至少锁定一部分利润",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace(
        "不能归责为当日未止盈；明日可卖后再执行止盈，明日可卖后应执行移动止盈规则",
        "不能归责为当日未止盈；明日可卖后再执行移动止盈规则",
    )
    return text


def sanitize_review_t1_language(review: dict[str, Any]) -> dict[str, Any]:
    if not review_has_t1_intraday_only(review):
        return review
    cleaned = dict(review)
    cleaned["summary"] = sanitize_t1_review_text(str(cleaned.get("summary") or ""))
    cleaned["wins"] = [sanitize_t1_review_text(item) for item in (cleaned.get("wins") or [])]
    cleaned["losses"] = [sanitize_t1_review_text(item) for item in (cleaned.get("losses") or [])]
    cleaned["next_rules"] = [sanitize_t1_review_text(item) for item in (cleaned.get("next_rules") or [])]
    return cleaned


def build_review_memory(state: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    reviews = [compact_review(item) for item in (state.get("reviews") or []) if item]
    reviews = [item for item in reviews if item]
    window_size = limit or REVIEW_MEMORY_DAYS
    window = reviews[-window_size:]
    if not window:
        return {"window_days": window_size, "reviews": [], "habit_rules": [], "avoid_patterns": [], "recent_pnl": 0.0}
    rule_counts: dict[str, int] = {}
    avoid_counts: dict[str, int] = {}
    for review in window:
        for rule in review.get("next_rules") or []:
            text = str(rule or "").strip()
            if text:
                rule_counts[text] = rule_counts.get(text, 0) + 1
        for loss in review.get("losses") or []:
            text = str(loss or "").strip()
            if text:
                avoid_counts[text] = avoid_counts.get(text, 0) + 1
    habit_rules = sorted(rule_counts, key=lambda key: (rule_counts[key], len(key)), reverse=True)[:8]
    avoid_patterns = sorted(avoid_counts, key=lambda key: (avoid_counts[key], len(key)), reverse=True)[:8]
    recent_pnl = sum(to_float(review.get("day_pnl"), 0.0) for review in window)
    recent_trades = sum(int(to_float(review.get("trade_count"), 0.0)) for review in window)
    return {
        "window_days": window_size,
        "actual_count": len(window),
        "date_range": [window[0].get("review_date"), window[-1].get("review_date")],
        "recent_pnl": recent_pnl,
        "recent_trade_count": recent_trades,
        "habit_rules": habit_rules,
        "avoid_patterns": avoid_patterns,
        "reviews": window,
    }


def build_buy_timing_memory(review_memory: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    for review in review_memory.get("reviews") or []:
        texts.append(str(review.get("summary") or ""))
        texts.extend(str(item or "") for item in review.get("wins") or [])
        texts.extend(str(item or "") for item in review.get("losses") or [])
        texts.extend(str(item or "") for item in review.get("next_rules") or [])
    corpus = "\n".join(texts)
    chase_hits = keyword_score(corpus, ("追高", "涨幅", "相对开盘", "偏离", "离VWAP", "离平台", "高位", "冲高回落"))
    weak_market_hits = keyword_score(corpus, ("弱市", "指数", "市场转弱", "大跌", "普跌", "系统性"))
    realtime_flow_hits = keyword_score(corpus, ("实时资金流", "历史兜底", "主力净额", "近3日持续"))
    t1_hits = keyword_score(corpus, ("T+1", "无法当日止盈", "次日", "移动止盈", "浮盈回吐"))
    preferences: list[str] = []
    avoid_patterns: list[str] = []
    if chase_hits:
        preferences.append("强票优先等靠近开盘/VWAP的买点，避免日内涨幅和相对开盘偏离过大的位置。")
        avoid_patterns.append("热门强票已经明显冲高时，不把热度本身当作立即买入理由。")
    if weak_market_hits:
        preferences.append("弱市或指数转弱时，买入需要更高安全垫；宁可少买，也不要满仓追强。")
    if realtime_flow_hits:
        preferences.append("优先选择实时资金流确认的强票；历史兜底资金流只能降低确信度，不能单独支撑追买。")
    if t1_hits:
        avoid_patterns.append("今日买入会被T+1锁定，盘中浮盈不能当天兑现，因此买点要给次日波动留余地。")
    sensitivity = min(1.0, (chase_hits + weak_market_hits + t1_hits) / 10.0)
    return {
        "mode": "soft_learning",
        "source": "rolling_review_window",
        "window_days": review_memory.get("window_days"),
        "actual_review_count": review_memory.get("actual_count", 0),
        "recent_pnl": review_memory.get("recent_pnl", 0.0),
        "signals": {
            "chasing_risk_mentions": chase_hits,
            "weak_market_mentions": weak_market_hits,
            "fund_flow_quality_mentions": realtime_flow_hits,
            "t_plus_1_mentions": t1_hits,
            "timing_sensitivity": round(sensitivity, 3),
        },
        "soft_reference": {
            "right_side_prefer_pct_chg_lte": RIGHT_SIDE_BUY_MAX_PCT_CHG,
            "right_side_prefer_open_gain_lte": RIGHT_SIDE_BUY_MAX_OPEN_GAIN,
            "right_side_prefer_vwap_deviation_lte": RIGHT_SIDE_BUY_MAX_VWAP_EXT,
            "note": "这些来自复盘学习，只用于排序和AI判断，不是一票否决。",
        },
        "preferences": preferences[:6],
        "avoid_patterns": avoid_patterns[:6],
    }


def truncate_text(value: Any, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def compact_number(value: Any, digits: int = 2) -> float | None:
    number = to_float(value, float("nan"))
    if not math.isfinite(number):
        return None
    return round(number, digits)


def compact_money_yi(value: Any) -> float | None:
    number = to_float(value, float("nan"))
    if not math.isfinite(number):
        return None
    return round(number / 100000000.0, 3)


def compact_reason_items(row: dict[str, Any], limit: int = 5) -> list[str]:
    items: list[str] = []
    for key in ("risk_tags", "buy_timing_notes"):
        for item in row.get(key) or []:
            text = truncate_text(item, 60)
            if text and text not in items:
                items.append(text)
    for key in ("guardrail_reason", "trading_coach_reason", "blocked_reason"):
        text = truncate_text(row.get(key), 70)
        if text and text not in items:
            items.append(text)
    return items[:limit]


def prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            pruned = prune_empty(item)
            if pruned is None or pruned == "" or pruned == [] or pruned == {}:
                continue
            out[key] = pruned
        return out
    if isinstance(value, list):
        return [item for item in (prune_empty(item) for item in value) if item is not None and item != "" and item != [] and item != {}]
    return value


def compact_candidate_for_ai(row: dict[str, Any]) -> dict[str, Any]:
    sym = normalize_symbol(row.get("symbol"))
    core = {
        "symbol": sym,
        "name": row.get("name", ""),
        "score": compact_number(row.get("score")),
        "timing": compact_number(row.get("buy_timing_score")),
        "penalty": compact_number(row.get("buy_timing_penalty")),
        "source": row.get("ai_pool_source") or row.get("score_basis") or row.get("source") or "",
        "price": compact_number(row.get("price")),
        "pct": compact_number(row.get("pct_chg")),
        "open_ext": compact_number(row.get("relative_open_gain"), 4),
        "vwap_ext": compact_number(row.get("vwap_deviation"), 4) if row.get("vwap_deviation") is not None else compact_number(row.get("vwap_ext"), 4),
        "amount_yi": compact_money_yi(row.get("amount")),
        "amount_rank": row.get("amount_rank"),
        "pct_rank": row.get("pct_rank"),
        "main_net_yi": compact_money_yi(row.get("main_net")),
        "main_net_change_1d_yi": compact_money_yi(row.get("main_net_change_1d")),
        "recent_3d_main_net_yi": [compact_money_yi(item) for item in (row.get("recent_3d_main_net") or [])[:3] if compact_money_yi(item) is not None],
        "fund_flow_source": row.get("fund_flow_source", ""),
        "trend": {
            "ma5_gt_ma20_gt_ma60": row.get("ma5_gt_ma20_gt_ma60"),
            "above_ma20": row.get("above_ma20"),
            "ma20_slope": compact_number(row.get("ma20_slope"), 4),
            "ret_5d": compact_number(row.get("return_5d"), 4),
            "ret_10d": compact_number(row.get("return_10d"), 4),
            "ret_20d": compact_number(row.get("return_20d"), 4),
        },
        "style": {
            "yesterday_limit_up": bool(row.get("yesterday_limit_up")),
            "real_pullback": row.get("real_pullback"),
            "strict_pass": row.get("strict_pass"),
            "score_basis": row.get("score_basis", ""),
        },
        "key_flags": compact_reason_items(row, 3),
    }
    parts = [
        f"{sym} {row.get('name', '')}".strip(),
        f"score={core['score']}" if core["score"] is not None else "",
        f"timing={core['timing']}" if core["timing"] is not None else "",
        f"pct={core['pct']:+.2f}%" if core["pct"] is not None else "",
        f"open={core['open_ext']:+.2%}" if core["open_ext"] is not None else "",
        f"vwap={core['vwap_ext']:+.2%}" if core["vwap_ext"] is not None else "",
        f"main={core['main_net_yi']:+.2f}亿" if core["main_net_yi"] is not None else "",
        f"flow={core['fund_flow_source']}" if core["fund_flow_source"] else "",
    ]
    core["one_line"] = " | ".join(part for part in parts if part)
    return prune_empty(core)


def compact_candidates_for_ai(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [compact_candidate_for_ai(row) for row in (rows or []) if isinstance(row, dict)]


def market_state_instruction(market_intraday: dict[str, Any], market_regime: dict[str, Any]) -> str:
    avg_pct = to_float(market_intraday.get("avg_pct_chg"), 0.0)
    if market_intraday.get("is_intraday_strong"):
        return f"当前市场偏强，指数均涨跌{avg_pct:+.2f}%，允许强者恒强，但仍需检查买点、VWAP偏离和公告风险。"
    if market_intraday.get("is_intraday_weak") or not market_regime.get("is_bullish"):
        return f"当前市场偏弱/非多头，指数均涨跌{avg_pct:+.2f}%，少追高，优先近VWAP安全垫；09:45前旧仓急杀先等修复确认。"
    return f"当前市场震荡，指数均涨跌{avg_pct:+.2f}%，优先低偏离买点，避免仅凭热度补仓。"


def compact_review_memory_for_ai(review_memory: dict[str, Any], market_instruction: str) -> dict[str, Any]:
    habit_rules = [truncate_text(item, 120) for item in (review_memory.get("habit_rules") or []) if item][:5]
    avoid_patterns = [truncate_text(item, 120) for item in (review_memory.get("avoid_patterns") or []) if item][:5]
    return {
        "window_days": review_memory.get("window_days"),
        "actual_count": review_memory.get("actual_count", 0),
        "date_range": review_memory.get("date_range", []),
        "recent_pnl": compact_number(review_memory.get("recent_pnl")),
        "recent_trade_count": review_memory.get("recent_trade_count", 0),
        "market_state_instruction": market_instruction,
        "core_rules": habit_rules,
        "avoid_patterns": avoid_patterns,
    }


def compact_latest_review_for_ai(review: dict[str, Any] | None) -> dict[str, Any] | None:
    if not review:
        return None
    return {
        "review_date": review.get("review_date", ""),
        "summary": truncate_text(review.get("summary"), 220),
        "wins": [truncate_text(item, 100) for item in (review.get("wins") or [])[:2]],
        "losses": [truncate_text(item, 100) for item in (review.get("losses") or [])[:2]],
        "next_rules": [truncate_text(item, 120) for item in (review.get("next_rules") or [])[:5]],
        "day_pnl": review.get("day_pnl", 0.0),
        "total_pnl": review.get("total_pnl", 0.0),
    }


def candidate_buy_timing_profile(row: dict[str, Any], timing_memory: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("ai_pool_source") or "")
    score = to_float(row.get("score"), 0.0)
    penalty = 0.0
    notes: list[str] = []
    if source == "right_side_watch":
        pct_chg = to_float(row.get("pct_chg"), 0.0)
        price = to_float(row.get("price"), 0.0)
        day_open = to_float(row.get("open"), 0.0)
        amount = to_float(row.get("amount"), 0.0)
        volume = to_float(row.get("volume"), 0.0)
        relative_open_gain = to_float(row.get("relative_open_gain"), float("nan"))
        if not math.isfinite(relative_open_gain) and price > 0 and day_open > 0:
            relative_open_gain = price / day_open - 1.0
        vwap_deviation = to_float(row.get("vwap_deviation"), float("nan"))
        if not math.isfinite(vwap_deviation) and price > 0 and amount > 0 and volume > 0:
            vwap = amount / volume
            vwap_deviation = price / vwap - 1.0 if vwap > 0 else float("nan")
        sensitivity = to_float((timing_memory.get("signals") or {}).get("timing_sensitivity"), 0.0)
        multiplier = 0.75 + sensitivity
        if pct_chg > RIGHT_SIDE_BUY_MAX_PCT_CHG:
            excess = pct_chg - RIGHT_SIDE_BUY_MAX_PCT_CHG
            penalty += min(18.0, excess * 2.4 * multiplier)
            notes.append(f"复盘学习：涨幅{pct_chg:.2f}%偏高，容易变成追强。")
        if math.isfinite(relative_open_gain) and relative_open_gain > RIGHT_SIDE_BUY_MAX_OPEN_GAIN:
            excess = relative_open_gain - RIGHT_SIDE_BUY_MAX_OPEN_GAIN
            penalty += min(18.0, excess * 320.0 * multiplier)
            notes.append(f"复盘学习：相对开盘{relative_open_gain:+.2%}偏高，买点缺安全垫。")
        if math.isfinite(vwap_deviation) and vwap_deviation > RIGHT_SIDE_BUY_MAX_VWAP_EXT:
            excess = vwap_deviation - RIGHT_SIDE_BUY_MAX_VWAP_EXT
            penalty += min(14.0, excess * 260.0 * multiplier)
            notes.append(f"复盘学习：离VWAP{vwap_deviation:+.2%}偏远，容易冲高回落。")
        flow_source = str(row.get("fund_flow_source") or "")
        positive_days = sum(1 for value in row.get("recent_3d_main_net") or [] if to_float(value, 0.0) > 0)
        if flow_source.startswith("eastmoney_history_"):
            penalty += 4.0
            notes.append("复盘学习：资金流为历史兜底，不能支撑高位追买。")
        if positive_days and positive_days < 3:
            penalty += 2.0
            notes.append(f"复盘学习：近3日主力仅{positive_days}日为正，买入确信度下降。")
    adjusted = max(0.0, score - penalty)
    return {
        "buy_timing_score": round(adjusted, 2),
        "buy_timing_penalty": round(penalty, 2),
        "buy_timing_notes": notes[:5],
        "buy_timing_learning": {
            "mode": timing_memory.get("mode", "soft_learning"),
            "not_hard_block": True,
        },
    }


def count_today_buys(state: dict[str, Any], now: datetime | None = None) -> int:
    today = market_clock(now).date().isoformat()
    total = 0
    for trade in state.get("trades") or []:
        if str(trade.get("side") or "").upper() == "BUY" and parse_trade_date(trade) == today:
            total += 1
    return total


def was_latest_bar_limit_up(sym: str) -> bool:
    bars = fetch_sina_daily_bars(sym, 3)
    if len(bars) < 2:
        return False
    return approx_limit_up(bars[-2]["close"], bars[-1]["close"])


def count_today_yesterday_limit_buys(state: dict[str, Any], now: datetime | None = None) -> int:
    today = market_clock(now).date().isoformat()
    total = 0
    for trade in state.get("trades") or []:
        if str(trade.get("side") or "").upper() != "BUY" or parse_trade_date(trade) != today:
            continue
        if bool(trade.get("yesterday_limit_up")) or was_latest_bar_limit_up(str(trade.get("symbol") or "")):
            total += 1
    return total


def is_yesterday_limit_candidate(row: dict[str, Any]) -> bool:
    if bool(row.get("yesterday_limit_up")):
        return True
    haystack = " ".join(
        str(item or "")
        for item in [
            row.get("reason"),
            row.get("guardrail_reason"),
            row.get("trading_coach_reason"),
            *(row.get("risk_tags") or []),
        ]
    )
    return bool(re.search(r"昨日跌幅不符\+(?:9|10)\.", haystack)) or "昨日涨停" in haystack


def annotate_candidate_style(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    had_yesterday_limit_field = "yesterday_limit_up" in enriched
    had_real_pullback_field = "real_pullback" in enriched
    if "yesterday_limit_up" not in enriched:
        inferred = is_yesterday_limit_candidate(enriched)
        if not inferred:
            inferred = was_latest_bar_limit_up(str(enriched.get("symbol") or ""))
        enriched["yesterday_limit_up"] = inferred
    if "real_pullback" not in enriched:
        depth = to_float(enriched.get("pullback_depth"), float("nan"))
        if math.isfinite(depth):
            enriched["real_pullback"] = bool(depth <= -0.01)
    if enriched.get("yesterday_limit_up") and not had_yesterday_limit_field:
        enriched["score"] = round(to_float(enriched.get("score"), 0.0) - 14.0, 2)
    if enriched.get("real_pullback") is False and not had_real_pullback_field:
        enriched["score"] = round(to_float(enriched.get("score"), 0.0) - 10.0, 2)
    return enriched


def keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(text.count(keyword) for keyword in keywords if keyword)


def build_trading_coach(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    review_memory = build_review_memory(state)
    base_max_pct = current_ai_guard_max_pct_chg(now)
    position_count = len(state.get("positions") or {})
    available_slots = max(0, MAX_POSITIONS - position_count)
    yesterday_limit_buys = count_today_yesterday_limit_buys(state, now)
    market_intraday = build_market_intraday_snapshot()
    if not TRADING_COACH_ENABLED:
        return {
            "enabled": False,
            "risk_mode": "off",
            "max_pct_chg": base_max_pct,
            "market_candidate_max_pct_chg": base_max_pct,
            "allow_market_candidate": True,
            "allow_right_side_watch": RIGHT_SIDE_AI_ENABLED,
            "allow_n_shape_watch": True,
            "allow_override": TRADING_COACH_ALLOW_OVERRIDE,
            "require_strict_n_shape": False,
            "available_position_slots": available_slots,
            "today_buy_count": count_today_buys(state, now),
            "yesterday_limit_buy_count": yesterday_limit_buys,
            "yesterday_limit_max_daily_buys": YESTERDAY_LIMIT_MAX_DAILY_BUYS,
            "market_intraday": market_intraday,
            "constraints": [],
            "reasons": ["交易教练已关闭"],
        }

    memory_text = "\n".join(
        str(item or "")
        for item in (review_memory.get("habit_rules") or []) + (review_memory.get("avoid_patterns") or [])
    )
    chasing_score = keyword_score(memory_text, ("追高", "涨超", "涨幅", "偏离", "离平台", "开盘涨", "高位"))
    loosen_score = keyword_score(memory_text, ("未通过严格", "非N字", "非 N 字", "放宽", "主观", "评分高"))
    loss_score = keyword_score(memory_text, ("亏", "回撤", "失败", "止损", "风险"))
    recent_pnl = to_float(review_memory.get("recent_pnl"), 0.0)
    today_buys = count_today_buys(state, now)

    risk_mode = "normal"
    reasons: list[str] = []
    if chasing_score >= 2:
        risk_mode = "cautious"
        reasons.append("近5条复盘多次提到追高/涨幅/平台偏离，降低买入涨幅上限")
    if loosen_score >= 2:
        risk_mode = "strict"
        reasons.append("近5条复盘反复提到非N字或放宽规则，禁止市场候选绕过N字池")
    if recent_pnl < 0:
        risk_mode = "strict"
        reasons.append("近5条复盘合计收益为负，收紧候选质量但不限制补满仓位")
    elif not reasons:
        reasons.append("近5条复盘未触发额外收紧项，保留基础风控")

    if risk_mode == "strict":
        max_pct_chg = min(base_max_pct, TRADING_COACH_STRICT_MAX_PCT_CHG)
        market_max_pct_chg = min(max_pct_chg, TRADING_COACH_MARKET_MAX_PCT_CHG)
        allow_market_candidate = False
    elif risk_mode == "cautious":
        max_pct_chg = min(base_max_pct, TRADING_COACH_CAUTION_MAX_PCT_CHG)
        market_max_pct_chg = min(max_pct_chg, TRADING_COACH_MARKET_MAX_PCT_CHG)
        allow_market_candidate = False if loosen_score > 0 else True
    else:
        max_pct_chg = base_max_pct
        market_max_pct_chg = min(base_max_pct, TRADING_COACH_MARKET_MAX_PCT_CHG)
        allow_market_candidate = True

    constraints = [
        f"买入候选涨幅不得超过{max_pct_chg:.2f}%",
        f"市场候选涨幅不得超过{market_max_pct_chg:.2f}%",
        f"N字观察池回踩深度不得超过{TRADING_COACH_MAX_PULLBACK_DEPTH:.0%}",
        "昨日涨停票不符合原N字策略，禁止作为N字买入",
        f"右侧交易升级为热门龙头池：热度池可观察强票，但实际买入必须控制买点；涨幅≤{RIGHT_SIDE_BUY_MAX_PCT_CHG:.1f}%、相对开盘≤{RIGHT_SIDE_BUY_MAX_OPEN_GAIN:.1%}、离VWAP≤{RIGHT_SIDE_BUY_MAX_VWAP_EXT:.1%}，超出则只观察不追。",
        f"总持仓未满即可开仓：当前{position_count}/{MAX_POSITIONS}，可开{available_slots}只；今日已买{today_buys}只不作为拦截条件",
        "strict_n_shape优先；n_shape_watch允许AI排序，但必须说明回踩/平台/开盘位置",
    ]
    if market_intraday.get("is_intraday_strong"):
        constraints.append(f"盘中指数走强时，买入候选涨幅不得明显跑输指数均值{market_intraday.get('avg_pct_chg'):+.2f}%")
    if not allow_market_candidate:
        constraints.append("禁止买入market_candidate，必须来自strict_n_shape或n_shape_watch")

    return {
        "enabled": True,
        "window_days": review_memory.get("window_days"),
        "actual_review_count": review_memory.get("actual_count", 0),
        "recent_pnl": recent_pnl,
        "recent_trade_count": review_memory.get("recent_trade_count", 0),
        "risk_mode": risk_mode,
        "max_pct_chg": max_pct_chg,
        "market_candidate_max_pct_chg": market_max_pct_chg,
        "allow_market_candidate": allow_market_candidate,
        "allow_right_side_watch": RIGHT_SIDE_AI_ENABLED,
        "allow_n_shape_watch": True,
        "allow_override": TRADING_COACH_ALLOW_OVERRIDE,
        "require_strict_n_shape": False,
        "available_position_slots": available_slots,
        "position_count": position_count,
        "today_buy_count": today_buys,
        "yesterday_limit_buy_count": yesterday_limit_buys,
        "yesterday_limit_max_daily_buys": YESTERDAY_LIMIT_MAX_DAILY_BUYS,
        "max_pullback_depth": TRADING_COACH_MAX_PULLBACK_DEPTH,
        "relative_strength_buffer": TRADING_COACH_RELATIVE_STRENGTH_BUFFER,
        "market_intraday": market_intraday,
        "constraints": constraints,
        "reasons": reasons,
    }


def trading_coach_allows_candidate(row: dict[str, Any], coach: dict[str, Any]) -> tuple[bool, str]:
    if not coach.get("enabled"):
        return True, ""
    source = str(row.get("ai_pool_source") or "")
    if source == "right_side_watch":
        return True, "热度池不走形态教练；买点由复盘学习信号排序，不做一票否决"
    pct_chg = to_float(row.get("pct_chg"), 0.0)
    pullback_depth = to_float(row.get("pullback_depth"), float("nan"))
    max_pullback_depth = to_float(coach.get("max_pullback_depth"), TRADING_COACH_MAX_PULLBACK_DEPTH)
    if math.isfinite(pullback_depth) and pullback_depth < -max_pullback_depth:
        return False, f"交易教练：回踩过深{pullback_depth:+.2%}，超过{max_pullback_depth:.0%}上限"
    market_intraday = coach.get("market_intraday") or {}
    if market_intraday.get("is_intraday_strong"):
        benchmark = to_float(market_intraday.get("avg_pct_chg"), 0.0)
        buffer = to_float(coach.get("relative_strength_buffer"), TRADING_COACH_RELATIVE_STRENGTH_BUFFER)
        if pct_chg < benchmark - buffer:
            return False, f"交易教练：盘中指数走强({benchmark:+.2f}%)，候选涨幅{pct_chg:.2f}%明显跑输市场"
    if is_yesterday_limit_candidate(row):
        limit_buys = int(coach.get("yesterday_limit_buy_count") or 0)
        limit_max = int(coach.get("yesterday_limit_max_daily_buys") or YESTERDAY_LIMIT_MAX_DAILY_BUYS)
        if limit_buys >= limit_max:
            return False, f"交易教练：昨日涨停票今日已买{limit_buys}只，达到每日上限{limit_max}只"
    if coach.get("require_strict_n_shape") and source != "strict_n_shape":
        return False, "交易教练：当前只允许严格N字候选"
    if source == "market_candidate":
        if not coach.get("allow_market_candidate", True):
            return False, "交易教练：近5条复盘禁止非N字市场候选"
        market_limit = to_float(coach.get("market_candidate_max_pct_chg"), current_ai_guard_max_pct_chg())
        if pct_chg > market_limit:
            return False, f"交易教练：市场候选涨幅{pct_chg:.2f}%>{market_limit:.2f}%"
    if source == "n_shape_watch" and not coach.get("allow_n_shape_watch", True):
        return False, "交易教练：当前禁止N字观察池"
    if source == "n_shape_watch":
        score = to_float(row.get("score"), 0.0)
        strict_pass = bool(row.get("strict_pass"))
        risk_text = "；".join(str(item or "") for item in (row.get("risk_tags") or []))
        if score < N_SHAPE_AI_MIN_SCORE:
            return False, f"交易教练：N字观察票质量分{score:.1f}<{N_SHAPE_AI_MIN_SCORE:.0f}"
        if not strict_pass and "回踩缩量不足" in risk_text:
            return False, "交易教练：未过严格且回踩缩量不足，暂不买入"
        if not strict_pass and "昨日跌幅偏离原策略+" in risk_text:
            return False, "交易教练：昨日不是回调而是上涨，非标准N字回踩"
        if not strict_pass and "未到早盘确认" in risk_text and score < N_SHAPE_AI_MIN_SCORE + 4:
            return False, "交易教练：未到早盘突破确认且分数不够"
    max_pct = to_float(coach.get("max_pct_chg"), current_ai_guard_max_pct_chg())
    if pct_chg > max_pct:
        return False, f"交易教练：涨幅{pct_chg:.2f}%>{max_pct:.2f}%"
    return True, ""


def trading_coach_allows_buy(
    state: dict[str, Any],
    order: dict[str, Any],
    quote: dict[str, Any],
    coach: dict[str, Any],
    candidate_row: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    if not coach.get("enabled"):
        return True, ""
    sym = normalize_symbol(order.get("symbol"))
    pool_row = candidate_row or next(
        (item for item in build_ai_buy_candidate_sets(state).get("raw", []) if normalize_symbol(item.get("symbol")) == sym),
        {},
    )
    row = {**quote, **pool_row}
    if "ai_pool_source" not in row:
        row["ai_pool_source"] = pool_row.get("ai_pool_source") or "unknown"
    return trading_coach_allows_candidate(row, coach)


def previous_market_day(ref: datetime | None = None) -> str:
    day = market_clock(ref).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def current_review_date(ref: datetime | None = None) -> str | None:
    current = market_clock(ref)
    if current.weekday() >= 5:
        return None
    if current.time() < REVIEW_START:
        return None
    return current.date().isoformat()


def next_review_time(ref: datetime | None = None) -> datetime:
    current = market_clock(ref)
    review_today = current.replace(hour=REVIEW_START.hour, minute=REVIEW_START.minute, second=0, microsecond=0)
    if current.weekday() < 5 and current < review_today:
        return review_today
    candidate = (current + timedelta(days=1)).replace(hour=REVIEW_START.hour, minute=REVIEW_START.minute, second=0, microsecond=0)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def parse_trade_date(item: dict[str, Any]) -> str | None:
    raw = item.get("time") or item.get("trade_date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date().isoformat()
    except Exception:
        return None


def trade_sort_key(item: dict[str, Any]) -> str:
    raw = item.get("time") or item.get("trade_date") or ""
    return str(raw)


def position_rows_from_map(positions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sym, pos in sorted(positions.items()):
        rows.append({
            "symbol": sym,
            "name": pos.get("name", ""),
            "qty": int(pos.get("qty") or 0),
            "avg_cost": round(to_float(pos.get("avg_cost"), 0.0), 2),
            "opened_at": pos.get("opened_at", ""),
            "trade_date": pos.get("trade_date", ""),
        })
    return rows


def apply_trade_to_positions(positions: dict[str, dict[str, Any]], trade: dict[str, Any]) -> float:
    action = str(trade.get("side") or "").upper()
    sym = normalize_symbol(trade.get("symbol"))
    qty = int(trade.get("qty") or 0)
    price = to_float(trade.get("price"), 0.0)
    if not sym or qty <= 0 or price <= 0:
        return 0.0
    pos = positions.get(sym)
    if action == "BUY":
        if not pos:
            positions[sym] = {
                "symbol": sym,
                "name": trade.get("name", ""),
                "qty": qty,
                "avg_cost": price,
            }
        else:
            old_qty = int(pos.get("qty") or 0)
            old_cost = to_float(pos.get("avg_cost"), 0.0)
            new_qty = old_qty + qty
            new_avg = (old_qty * old_cost + qty * price) / new_qty if new_qty > 0 else price
            pos["qty"] = new_qty
            pos["avg_cost"] = new_avg
        return 0.0
    if action == "SELL":
        if not pos:
            return 0.0
        sell_qty = min(qty, int(pos.get("qty") or 0))
        if sell_qty <= 0:
            return 0.0
        avg_cost = to_float(pos.get("avg_cost"), 0.0)
        realized = (price - avg_cost) * sell_qty
        remaining = int(pos.get("qty") or 0) - sell_qty
        if remaining <= 0:
            positions.pop(sym, None)
        else:
            pos["qty"] = remaining
        return realized
    return 0.0


def build_review_context(state: dict[str, Any], target_date: str) -> dict[str, Any]:
    account = account_snapshot(state)
    quotes = state.get("quotes") or {}
    total_pnl = round(to_float(account.get("total_pnl"), 0.0), 2)
    previous_reviews = [
        item for item in (state.get("reviews") or [])
        if str(item.get("review_date") or "") < target_date
    ]
    previous_total_pnl = to_float(previous_reviews[-1].get("total_pnl"), 0.0) if previous_reviews else 0.0
    trades = sorted(state.get("trades") or [], key=trade_sort_key)
    decisions = [d for d in (state.get("decisions") or []) if parse_trade_date(d) == target_date]
    positions: dict[str, dict[str, Any]] = {}
    day_trades: list[dict[str, Any]] = []
    realized_rows: list[dict[str, Any]] = []
    realized_pnl = 0.0
    buys = sells = 0
    start_positions: list[dict[str, Any]] = []
    for trade in trades:
        trade_date = parse_trade_date(trade)
        if not trade_date:
            continue
        if trade_date > target_date:
            break
        if trade_date < target_date:
            apply_trade_to_positions(positions, trade)
            continue
        if not start_positions:
            start_positions = position_rows_from_map(positions)
        day_trades.append(trade)
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            buys += 1
            apply_trade_to_positions(positions, trade)
            continue
        if side == "SELL":
            sells += 1
            pos = positions.get(normalize_symbol(trade.get("symbol")))
            avg_cost = to_float(pos.get("avg_cost"), 0.0) if pos else 0.0
            qty = min(int(trade.get("qty") or 0), int(pos.get("qty") or 0) if pos else int(trade.get("qty") or 0))
            pnl = apply_trade_to_positions(positions, trade)
            realized_pnl += pnl
            realized_rows.append({
                "time": trade.get("time", ""),
                "symbol": normalize_symbol(trade.get("symbol")),
                "name": trade.get("name", ""),
                "qty": qty,
                "price": round(to_float(trade.get("price"), 0.0), 2),
                "avg_cost": round(avg_cost, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / (avg_cost * qty) if avg_cost > 0 and qty > 0 else 0.0, 4),
                "reason": trade.get("reason", ""),
            })

    winners = sorted((row for row in realized_rows if row["pnl"] > 0), key=lambda row: row["pnl"], reverse=True)[:3]
    losers = sorted((row for row in realized_rows if row["pnl"] < 0), key=lambda row: row["pnl"])[:3]
    unrealized_rows = []
    intraday_rows = []
    for pos in account.get("positions") or []:
        if str(pos.get("trade_date") or "") != target_date:
            continue
        sym = normalize_symbol(pos.get("symbol"))
        q = quotes.get(sym) or {}
        pnl = to_float(pos.get("pnl"), 0.0)
        avg_cost = to_float(pos.get("avg_cost"), 0.0)
        last_price = to_float(pos.get("last_price"), 0.0)
        high_price = to_float(q.get("high"), 0.0)
        high_pnl_pct = high_price / avg_cost - 1.0 if avg_cost > 0 and high_price > 0 else 0.0
        fade_from_high_pct = last_price / high_price - 1.0 if last_price > 0 and high_price > 0 else 0.0
        unrealized_rows.append({
            "symbol": sym,
            "name": pos.get("name", ""),
            "qty": int(pos.get("qty") or 0),
            "opened_date": pos.get("trade_date", ""),
            "can_sell_today": False,
            "t_plus_1_locked": True,
            "avg_cost": round(avg_cost, 2),
            "last_price": round(last_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(to_float(pos.get("pnl_pct"), 0.0), 4),
            "high_price": round(high_price, 2),
            "high_pnl_pct": round(high_pnl_pct, 4),
            "fade_from_high_pct": round(fade_from_high_pct, 4),
        })
        intraday_rows.append({
            "symbol": sym,
            "name": pos.get("name", ""),
            "opened_date": pos.get("trade_date", ""),
            "can_sell_today": False,
            "t_plus_1_locked": True,
            "avg_cost": round(avg_cost, 2),
            "last_price": round(last_price, 2),
            "high_price": round(high_price, 2),
            "close_pnl_pct": round(to_float(pos.get("pnl_pct"), 0.0), 4),
            "high_pnl_pct": round(high_pnl_pct, 4),
            "fade_from_high_pct": round(fade_from_high_pct, 4),
            "pct_chg": to_float(q.get("pct_chg"), 0.0),
        })
    unrealized_pnl = sum(to_float(row.get("pnl"), 0.0) for row in unrealized_rows)
    trade_mark_pnl = realized_pnl + unrealized_pnl
    day_pnl = total_pnl - previous_total_pnl
    return {
        "review_date": target_date,
        "generated_at": now_iso(),
        "total_pnl": total_pnl,
        "total_pnl_pct": round(to_float(account.get("total_pnl_pct"), 0.0), 4),
        "previous_total_pnl": round(previous_total_pnl, 2),
        "total_value": round(to_float(account.get("total_value"), 0.0), 2),
        "cash": round(to_float(account.get("cash"), 0.0), 2),
        "market_value": round(to_float(account.get("market_value"), 0.0), 2),
        "trades": day_trades[-MAX_REVIEW_TRADES:],
        "decisions": decisions[-8:],
        "start_positions": start_positions,
        "end_positions": position_rows_from_map(positions),
        "realized_rows": realized_rows,
        "realized_pnl": round(realized_pnl, 2),
        "realized_pnl_pct": round(realized_pnl / DEFAULT_CASH if DEFAULT_CASH > 0 else 0.0, 4),
        "unrealized_rows": unrealized_rows,
        "intraday_rows": intraday_rows,
        "market_indices": fetch_market_index_snapshot(),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "unrealized_pnl_pct": round(unrealized_pnl / DEFAULT_CASH if DEFAULT_CASH > 0 else 0.0, 4),
        "trade_mark_pnl": round(trade_mark_pnl, 2),
        "day_pnl": round(day_pnl, 2),
        "day_pnl_pct": round(day_pnl / DEFAULT_CASH if DEFAULT_CASH > 0 else 0.0, 4),
        "buy_count": buys,
        "sell_count": sells,
        "trade_count": len(day_trades),
        "winners": winners,
        "losers": losers,
        "review_source": "local",
    }


def local_daily_review(context: dict[str, Any]) -> dict[str, Any]:
    total_pnl = to_float(context.get("total_pnl"), to_float(context.get("realized_pnl"), 0.0))
    total_pnl_pct = to_float(context.get("total_pnl_pct"), 0.0)
    realized_pnl = to_float(context.get("realized_pnl"), 0.0)
    realized_pnl_pct = to_float(context.get("realized_pnl_pct"), 0.0)
    unrealized_pnl = to_float(context.get("unrealized_pnl"), 0.0)
    unrealized_pnl_pct = to_float(context.get("unrealized_pnl_pct"), 0.0)
    day_pnl = to_float(context.get("day_pnl"), realized_pnl + unrealized_pnl)
    day_pnl_pct = to_float(context.get("day_pnl_pct"), day_pnl / DEFAULT_CASH if DEFAULT_CASH > 0 else 0.0)
    winners = context.get("winners") or []
    losers = context.get("losers") or []
    if context.get("trade_count", 0) <= 0:
        return {
            "summary": f"当日无成交；账户累计总盈亏{total_pnl:+.2f}元。",
            "wins": [],
            "losses": [],
            "next_rules": ["继续等待有价差、量能和涨幅共振的标的。"],
            "review_source": "local",
            "confidence": 0.7,
        }
    summary_parts = [
        f"当日共{context.get('trade_count', 0)}笔成交，买入{context.get('buy_count', 0)}笔，卖出{context.get('sell_count', 0)}笔。",
        f"账户当日净变化{day_pnl:+.2f}元（{day_pnl_pct:+.2%}）；已实现盈亏{realized_pnl:+.2f}元（按成本口径），当前持仓浮盈{unrealized_pnl:+.2f}元（{unrealized_pnl_pct:+.2%}）。",
        f"账户累计总盈亏{total_pnl:+.2f}元（{total_pnl_pct:+.2%}）。",
    ]
    wins = []
    losses = []
    if winners:
        top = winners[0]
        wins.append(f"{top.get('symbol')} {top.get('pnl', 0):+.2f}元，说明卖出节奏或持有过程有效。")
    if losers:
        bottom = losers[0]
        losses.append(f"{bottom.get('symbol')} {bottom.get('pnl', 0):+.2f}元，{bottom.get('reason') or '卖出原因不充分'}，说明追高/换仓/止损节奏偏急。")
    next_rules = [
        "优先保留当日强势、低价差、评分高的标的，减少情绪化换仓。",
        "出现亏损时先看是否是追高后回撤，再决定是否继续持有。",
        "复盘里有连续盈利的买点特征，就把它前置成硬规则。"
    ]
    if day_pnl < 0:
        next_rules.insert(0, "当日综合亏损，优先收紧入场条件，先解释清楚亏损来自卖出时机、买点质量还是持仓浮亏。")
    else:
        next_rules.insert(0, "当日综合赚钱，把有效的入场和持仓条件继续保留，并提高同类标的优先级。")
    return {
        "summary": " ".join(summary_parts),
        "wins": wins,
        "losses": losses,
        "next_rules": next_rules,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "previous_total_pnl": to_float(context.get("previous_total_pnl"), 0.0),
        "trade_mark_pnl": to_float(context.get("trade_mark_pnl"), realized_pnl + unrealized_pnl),
        "day_pnl": day_pnl,
        "day_pnl_pct": day_pnl_pct,
        "review_source": "local",
        "confidence": 0.66,
    }


def compact_daily_review_context(context: dict[str, Any]) -> dict[str, Any]:
    def slim_trade(trade: dict[str, Any]) -> dict[str, Any]:
        return {
            "time": trade.get("time", ""),
            "side": trade.get("side", ""),
            "symbol": trade.get("symbol", ""),
            "name": trade.get("name", ""),
            "qty": trade.get("qty", 0),
            "price": trade.get("price", 0.0),
            "amount": trade.get("amount", 0.0),
            "reason": trade.get("reason", ""),
            "ai_source": trade.get("ai_source", ""),
            "yesterday_limit_up": trade.get("yesterday_limit_up"),
            "real_pullback": trade.get("real_pullback"),
            "ai_pool_source": trade.get("ai_pool_source", ""),
        }

    def slim_decision(decision: dict[str, Any]) -> dict[str, Any]:
        return {
            "time": decision.get("time", ""),
            "source": decision.get("source", ""),
            "summary": decision.get("summary", ""),
            "actions": [
                {
                    "side": item.get("side", ""),
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "reason": item.get("reason", ""),
                }
                for item in (decision.get("actions") or [])[:5]
            ],
            "blocked_reasons": [
                str(item.get("blocked_reason") or "")
                for item in (decision.get("blocked_orders") or [])[:5]
                if item.get("blocked_reason")
            ],
        }

    return {
        "review_date": context.get("review_date", ""),
        "generated_at": context.get("generated_at", ""),
        "total_pnl": context.get("total_pnl", 0.0),
        "total_pnl_pct": context.get("total_pnl_pct", 0.0),
        "previous_total_pnl": context.get("previous_total_pnl", 0.0),
        "total_value": context.get("total_value", 0.0),
        "cash": context.get("cash", 0.0),
        "market_value": context.get("market_value", 0.0),
        "realized_pnl": context.get("realized_pnl", 0.0),
        "realized_pnl_pct": context.get("realized_pnl_pct", 0.0),
        "unrealized_pnl": context.get("unrealized_pnl", 0.0),
        "unrealized_pnl_pct": context.get("unrealized_pnl_pct", 0.0),
        "trade_mark_pnl": context.get("trade_mark_pnl", 0.0),
        "day_pnl": context.get("day_pnl", 0.0),
        "day_pnl_pct": context.get("day_pnl_pct", 0.0),
        "buy_count": context.get("buy_count", 0),
        "sell_count": context.get("sell_count", 0),
        "trade_count": context.get("trade_count", 0),
        "market_indices": context.get("market_indices", []),
        "trades": [slim_trade(item) for item in (context.get("trades") or [])],
        "realized_rows": context.get("realized_rows", []),
        "unrealized_rows": context.get("unrealized_rows", []),
        "intraday_rows": context.get("intraday_rows", []),
        "decisions": [slim_decision(item) for item in (context.get("decisions") or [])[-6:]],
    }


def deepseek_daily_review(context: dict[str, Any]) -> dict[str, Any] | None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    review_context = compact_daily_review_context(context)
    prompt = (
        "你是A股模拟盘复盘官，只输出json。请基于当天成交、当日已实现盈亏、当日持仓浮盈、当日综合盈亏、账户累计总盈亏和交易理由，复盘当天操作为什么赚钱/亏钱，并提炼次日可执行规则。"
        "判断“今天操作赚钱还是亏钱”必须优先看 day_pnl；day_pnl 是账户累计总盈亏相对上一条复盘的净变化。"
        "realized_pnl 是卖出相对持仓成本的落袋盈亏，可能包含昨天已经反映过的浮亏，不等于今天账户净变化；unrealized_pnl 是当前持仓相对成本的浮动盈亏；total_pnl 是账户从初始资金以来的累计结果。"
        "如果 day_pnl 为正，即使 realized_pnl 为负，也必须表述为“今天账户净值赚钱/修复亏损”，不能说今天亏钱。"
        "如果 day_pnl 为正，losses字段只能写“可改进点/风险暴露”，不能把realized_pnl负数表述成今天整体亏损；必须说明负的realized_pnl多为昨日已计入的浮亏落袋。"
        "必须阅读market_indices和intraday_rows：如果指数大跌或市场环境明显弱，而个股盘中high_pnl_pct曾明显为正、收盘回落，"
        "不要简单归因为买点错误或追高，应评价为弱市冲高回落；可把改进点写成弱市移动止盈/冲高分批止盈，而不是否定选股。"
        "但A股模拟盘遵循T+1：intraday_rows里can_sell_today=false或t_plus_1_locked=true的今日新仓，当天不能卖出。"
        "对这类今日新仓，复盘不能批评“没有盘中止盈/未及时止盈/未移动止盈”，只能表述为“冲高回落风险，明日可卖后按移动止盈或止损处理”。"
        "只有当天本来可卖的旧仓，才可以评价是否应该盘中止盈。"
        "如果标的盘中给过3%以上浮盈，losses里不要写成“完全买错”，除非买入时已违反硬风控或公告风险。"
        "要求具体，避免空话。格式："
        "{\"summary\":\"...\",\"wins\":[\"...\"],\"losses\":[\"...\"],\"next_rules\":[\"...\"],\"total_pnl\":0.0,\"total_pnl_pct\":0.0,\"realized_pnl\":0.0,\"realized_pnl_pct\":0.0,\"unrealized_pnl\":0.0,\"unrealized_pnl_pct\":0.0,\"day_pnl\":0.0,\"day_pnl_pct\":0.0,\"confidence\":0.0}\n"
        f"上下文：{json.dumps(review_context, ensure_ascii=False)}"
    )
    primary_model = os.environ.get("DEEPSEEK_REVIEW_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")).strip()
    fallback_model = os.environ.get("DEEPSEEK_REVIEW_FALLBACK_MODEL", "deepseek-chat").strip()
    models = list(dict.fromkeys(model for model in (primary_model, fallback_model) if model))
    errors = []
    for model in models:
        for attempt in range(DEEPSEEK_REVIEW_RETRIES):
            body = llm_chat_body(
                model,
                prompt,
                temperature=0.2,
                max_tokens=int(os.environ.get("DEEPSEEK_REVIEW_MAX_TOKENS", "650")),
            )
            try:
                started = time.time()
                payload = llm_post_json(body, key, timeout=DEEPSEEK_REVIEW_TIMEOUT_SEC, retries=DEEPSEEK_REVIEW_RETRIES)
                text = payload["choices"][0]["message"]["content"]
                review = parse_model_json_object(text)
                review["review_source"] = AI_PROVIDER_LABEL
                review["review_model"] = model
                review["review_latency_sec"] = round(time.time() - started, 2)
                RUNTIME["deepseek_last_error"] = ""
                return review
            except Exception as exc:
                errors.append(f"{model}#{attempt + 1}:{llm_error_summary(exc)}")
    RUNTIME["deepseek_last_error"] = "复盘失败：" + " | ".join(errors[-4:])
    return None


def normalize_review_summary(review: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    total_pnl = to_float(context.get("total_pnl"), 0.0)
    total_pnl_pct = to_float(context.get("total_pnl_pct"), 0.0)
    realized_pnl = to_float(context.get("realized_pnl"), 0.0)
    realized_pnl_pct = to_float(context.get("realized_pnl_pct"), 0.0)
    unrealized_pnl = to_float(context.get("unrealized_pnl"), 0.0)
    unrealized_pnl_pct = to_float(context.get("unrealized_pnl_pct"), 0.0)
    day_pnl = to_float(context.get("day_pnl"), realized_pnl + unrealized_pnl)
    day_pnl_pct = to_float(context.get("day_pnl_pct"), day_pnl / DEFAULT_CASH if DEFAULT_CASH > 0 else 0.0)
    previous_total_pnl = to_float(context.get("previous_total_pnl"), 0.0)
    trade_mark_pnl = to_float(context.get("trade_mark_pnl"), realized_pnl + unrealized_pnl)
    summary = str(review.get("summary") or "").strip()
    has_profit_word = any(token in summary for token in ("盈利", "赚钱", "赚了", "赚"))
    has_loss_word = any(token in summary for token in ("亏损", "赔", "亏了"))
    no_profit_claim = any(token in summary for token in ("没有实际盈亏", "未产生实际盈亏", "realized_pnl为0", "realized_pnl 为0"))
    if day_pnl > 0 and (has_loss_word or no_profit_claim):
        summary = f"账户当日净变化{day_pnl:+.2f}元（{day_pnl_pct:+.2%}），上一复盘累计盈亏{previous_total_pnl:+.2f}元，当前累计盈亏{total_pnl:+.2f}元；今天账户净值是赚钱/修复亏损的。已实现{realized_pnl:+.2f}元是按成本口径，包含昨日已反映过的浮亏，不能当成今日净亏；当前持仓浮盈{unrealized_pnl:+.2f}元。"
    elif day_pnl < 0 and has_profit_word and not has_loss_word:
        summary = f"账户当日净变化{day_pnl:+.2f}元（{day_pnl_pct:+.2%}），其中已实现{realized_pnl:+.2f}元、持仓浮盈{unrealized_pnl:+.2f}元；今天账户净值是亏损的。账户累计总盈亏{total_pnl:+.2f}元（{total_pnl_pct:+.2%}）。{summary}"
    elif not summary:
        summary = f"账户当日净变化{day_pnl:+.2f}元（{day_pnl_pct:+.2%}），已实现盈亏{realized_pnl:+.2f}元（{realized_pnl_pct:+.2%}），持仓浮盈{unrealized_pnl:+.2f}元（{unrealized_pnl_pct:+.2%}），账户累计总盈亏{total_pnl:+.2f}元（{total_pnl_pct:+.2%}）。"
    review["summary"] = summary
    if day_pnl > 0:
        normalized_losses = []
        for item in review.get("losses") or []:
            text = str(item or "")
            if realized_pnl < 0 and any(token in text for token in ("今日亏损", "今天亏损", "账户亏损", "整体亏损")):
                text = text.replace("今日亏损", "今日可改进点").replace("今天亏损", "今日可改进点").replace("账户亏损", "风险暴露").replace("整体亏损", "风险暴露")
            normalized_losses.append(text)
        if normalized_losses:
            review["losses"] = normalized_losses
    review = sanitize_review_t1_language(review)
    review["total_pnl"] = total_pnl
    review["total_pnl_pct"] = total_pnl_pct
    review["previous_total_pnl"] = previous_total_pnl
    review["realized_pnl"] = realized_pnl
    review["realized_pnl_pct"] = realized_pnl_pct
    review["unrealized_pnl"] = unrealized_pnl
    review["unrealized_pnl_pct"] = unrealized_pnl_pct
    review["trade_mark_pnl"] = trade_mark_pnl
    review["day_pnl"] = day_pnl
    review["day_pnl_pct"] = day_pnl_pct
    return review


def generate_daily_review(state: dict[str, Any], ref: datetime | None = None) -> dict[str, Any] | None:
    review_date = current_review_date(ref)
    if not review_date:
        return None
    reviews = state.get("reviews") or []
    if any((review.get("review_date") == review_date for review in reviews)):
        return None
    context = build_review_context(state, review_date)
    review = deepseek_daily_review(context) or local_daily_review(context)
    review = normalize_review_summary(review, context)
    review.update({
        "review_date": review_date,
        "generated_at": now_iso(),
        "total_pnl": context.get("total_pnl", 0.0),
        "total_pnl_pct": context.get("total_pnl_pct", 0.0),
        "trade_count": context.get("trade_count", 0),
        "realized_pnl": context.get("realized_pnl", 0.0),
        "realized_pnl_pct": context.get("realized_pnl_pct", 0.0),
        "unrealized_pnl": context.get("unrealized_pnl", 0.0),
        "unrealized_pnl_pct": context.get("unrealized_pnl_pct", 0.0),
        "intraday_rows": context.get("intraday_rows", []),
        "market_indices": context.get("market_indices", []),
        "trade_mark_pnl": context.get("trade_mark_pnl", 0.0),
        "day_pnl": context.get("day_pnl", 0.0),
        "day_pnl_pct": context.get("day_pnl_pct", 0.0),
        "buy_count": context.get("buy_count", 0),
        "sell_count": context.get("sell_count", 0),
    })
    return review


def persist_daily_review(ref: datetime | None = None) -> dict[str, Any] | None:
    with LOCK:
        state = load_state()
        review = generate_daily_review(state, ref)
        if review is None:
            return None
        append_review(state, review)
        RUNTIME["last_review_date"] = review.get("review_date", "")
        RUNTIME["last_review_at"] = review.get("generated_at", "")
        RUNTIME["last_review_summary"] = review.get("summary", "")
        append_log(state, f"今日复盘({review.get('review_date', '')})已生成：{review.get('summary', '')}")
        save_state(state)
    return review


def maybe_run_daily_review(now: datetime | None = None) -> dict[str, Any] | None:
    current = market_clock(now)
    review_key = current_review_date(current)
    if not review_key:
        RUNTIME["next_review_at"] = next_review_time(current).isoformat(timespec="minutes")
        return None
    with LOCK:
        state = load_state()
        already_done = any((item.get("review_date") == review_key for item in (state.get("reviews") or [])))
    if already_done:
        RUNTIME["next_review_at"] = next_review_time(current).isoformat(timespec="minutes")
        return None
    review = persist_daily_review(current)
    RUNTIME["next_review_at"] = next_review_time(current).isoformat(timespec="minutes")
    return review


def update_market_runtime() -> bool:
    open_now, next_open, session = market_status()
    RUNTIME["market_open"] = open_now
    RUNTIME["market_session"] = session
    RUNTIME["market_next_open_at"] = next_open.isoformat(timespec="minutes")
    RUNTIME["next_review_at"] = next_review_time().isoformat(timespec="minutes")
    return open_now


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


def lot_qty(cash: float, price: float) -> int:
    if not (price > 0 and cash >= price * 100):
        return 0
    return int(math.floor(cash / price / 100) * 100)


def fetch_market_index_snapshot() -> list[dict[str, Any]]:
    cached_rows = MARKET_INDEX_CACHE.get("rows") or []
    if cached_rows and time.time() < float(MARKET_INDEX_CACHE.get("expires_at") or 0.0):
        return list(cached_rows)

    def eastmoney_fallback() -> list[dict[str, Any]]:
        secids = {
            "1.000001": ("s_sh000001", "上证指数"),
            "0.399001": ("s_sz399001", "深证成指"),
            "0.399006": ("s_sz399006", "创业板指"),
            "1.000300": ("s_sh000300", "沪深300"),
        }
        params = urllib.parse.urlencode({
            "secids": ",".join(secids),
            "fields": "f12,f14,f2,f3,f4",
        })
        req = urllib.request.Request(
            f"https://push2.eastmoney.com/api/qt/ulist.np/get?{params}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        try:
            payload = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore"))
        except Exception:
            return []
        rows = []
        for item in ((payload.get("data") or {}).get("diff") or []):
            market_key = next((key for key in secids if key.endswith("." + str(item.get("f12") or ""))), "")
            code, fallback_name = secids.get(market_key, ("", ""))
            price_raw = to_float(item.get("f2"), 0.0)
            pct_raw = to_float(item.get("f3"), 0.0)
            chg_raw = to_float(item.get("f4"), 0.0)
            if not code or price_raw <= 0:
                continue
            rows.append({
                "code": code,
                "name": item.get("f14") or fallback_name,
                "price": round(price_raw / 100.0, 4),
                "change": round(chg_raw / 100.0, 4),
                "pct_chg": round(pct_raw / 100.0, 4),
            })
        return rows

    codes = {
        "s_sh000001": "上证指数",
        "s_sz399001": "深证成指",
        "s_sz399006": "创业板指",
        "s_sh000300": "沪深300",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://finance.sina.com.cn/",
    }
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    req = urllib.request.Request(url, headers=headers)
    try:
        raw = urllib.request.urlopen(req, timeout=2).read().decode("gbk", errors="ignore")
    except Exception:
        rows = eastmoney_fallback()
        if rows:
            MARKET_INDEX_CACHE["rows"] = rows
            MARKET_INDEX_CACHE["expires_at"] = time.time() + 5.0
        return rows
    rows = []
    for line in raw.splitlines():
        if '="' not in line:
            continue
        left, payload = line.split('="', 1)
        key = left.split("hq_str_", 1)[-1]
        arr = payload.rstrip('";').split(",")
        if len(arr) < 4:
            continue
        rows.append({
            "code": key,
            "name": arr[0] or codes.get(key, key),
            "price": to_float(arr[1], 0.0),
            "change": to_float(arr[2], 0.0),
            "pct_chg": to_float(arr[3], 0.0),
        })
    rows = rows or eastmoney_fallback()
    if rows:
        MARKET_INDEX_CACHE["rows"] = rows
        MARKET_INDEX_CACHE["expires_at"] = time.time() + 5.0
    return rows


def build_market_intraday_snapshot(indices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = indices if indices is not None else fetch_market_index_snapshot()
    pct_values = [
        to_float(row.get("pct_chg"), float("nan"))
        for row in (rows or [])
        if math.isfinite(to_float(row.get("pct_chg"), float("nan")))
    ]
    if not pct_values:
        return {
            "source": "market_indices",
            "data_ok": False,
            "avg_pct_chg": 0.0,
            "red_count": 0,
            "index_count": 0,
            "is_intraday_strong": False,
            "is_intraday_weak": False,
            "reason": "盘中指数数据缺失",
            "indices": [],
        }
    avg_pct = mean(pct_values)
    red_count = len([x for x in pct_values if x > 0])
    weak_count = len([x for x in pct_values if x < -0.5])
    return {
        "source": "market_indices",
        "data_ok": True,
        "avg_pct_chg": round(avg_pct, 2),
        "red_count": red_count,
        "index_count": len(pct_values),
        "is_intraday_strong": avg_pct >= 0.35 and red_count >= max(2, len(pct_values) - 1),
        "is_intraday_weak": avg_pct <= -0.5 or weak_count >= 2,
        "reason": f"指数均涨跌{avg_pct:+.2f}%，红盘{red_count}/{len(pct_values)}",
        "indices": rows or [],
    }


def cached_market_index_snapshot() -> list[dict[str, Any]]:
    return list(MARKET_INDEX_CACHE.get("rows") or [])


def cached_market_regime_snapshot(now: datetime | None = None) -> dict[str, Any]:
    today = market_clock(now).date().isoformat()
    cached = MARKET_REGIME_CACHE.get(today)
    if isinstance(cached, dict) and cached:
        return dict(cached)
    return {
        "checked_at": "",
        "source": "cache_miss",
        "index_symbol": "000001",
        "index_name": "上证指数",
        "data_ok": False,
        "is_bull": False,
        "reason": "大盘环境缓存尚未生成，页面先返回状态",
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "close": None,
    }


def fetch_sina_quote_chunk(chunk: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not chunk:
        return out
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://finance.sina.com.cn/",
    }
    url = "https://hq.sinajs.cn/list=" + ",".join(market_code(s) for s in chunk)
    req = urllib.request.Request(url, headers=headers)
    try:
        raw = opener.open(req, timeout=6).read()
    except Exception:
        url = url.replace("https://", "http://", 1)
        req = urllib.request.Request(url, headers=headers)
        raw = opener.open(req, timeout=6).read()
    text = raw.decode("gbk", errors="ignore")
    for line in text.splitlines():
        if '="' not in line:
            continue
        left, payload = line.split('="', 1)
        key = left.split("hq_str_", 1)[-1]
        sym = normalize_symbol(key[2:])
        arr = payload.rstrip('";').split(",")
        if len(arr) < 22 or not sym:
            continue
        prev_close = to_float(arr[2], 0.0)
        price = to_float(arr[3], 0.0)
        pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        out[sym] = {
            "symbol": sym,
            "name": arr[0],
            "open": to_float(arr[1]),
            "prev_close": prev_close,
            "price": price,
            "high": to_float(arr[4]),
            "low": to_float(arr[5]),
            "volume": to_float(arr[8]),
            "amount": to_float(arr[9]),
            "bid1_volume": to_float(arr[10]),
            "bid1": to_float(arr[11]),
            "ask1_volume": to_float(arr[20]),
            "ask1": to_float(arr[21]),
            "pct_chg": round(pct, 2),
            "quote_time": now_iso(),
        }
    return out


def fetch_sina_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    syms = [normalize_symbol(s) for s in symbols if normalize_symbol(s)]
    if not syms:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunks = [syms[i : i + 80] for i in range(0, len(syms), 80)]
    workers = min(MARKET_SCAN_WORKERS, len(chunks))
    if workers <= 1:
        for chunk in chunks:
            out.update(fetch_sina_quote_chunk(chunk))
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk_out in pool.map(fetch_sina_quote_chunk, chunks):
            out.update(chunk_out)
    return out


def quote_age_seconds(quote: dict[str, Any]) -> float:
    try:
        return max(0.0, time.time() - datetime.fromisoformat(str(quote.get("quote_time") or "")).timestamp())
    except Exception:
        return float("inf")


def quote_is_today(quote: dict[str, Any], ref: datetime | None = None) -> bool:
    try:
        quote_time = datetime.fromisoformat(str(quote.get("quote_time") or ""))
    except Exception:
        return False
    return quote_time.date() == market_clock(ref).date()


def rank_candidates(quotes: dict[str, dict[str, Any]], max_age_sec: float = 300.0) -> list[dict[str, Any]]:
    rows = []
    for q in quotes.values():
        price = to_float(q.get("price"), 0.0)
        if price <= 0:
            continue
        if quote_age_seconds(q) > max_age_sec:
            continue
        pct = to_float(q.get("pct_chg"), 0.0)
        amount = to_float(q.get("amount"), 0.0)
        bid = to_float(q.get("bid1"), 0.0)
        ask = to_float(q.get("ask1"), 0.0)
        spread = (ask - bid) / price * 100 if ask > 0 and bid > 0 and price > 0 else 9.9
        score = 50 + min(20, max(-20, pct * 4)) + min(20, amount / 1e8) - min(10, spread * 3)
        rows.append({**q, "score": round(score, 2), "spread_pct": round(spread, 3)})
    return sorted(rows, key=lambda x: x.get("score", 0), reverse=True)


def eastmoney_secid_from_market_symbol(market_symbol: str) -> str:
    code = normalize_symbol(market_symbol)
    prefix = str(market_symbol or "")[:2].lower()
    market_id = "1" if prefix == "sh" or code.startswith(("5", "6", "9")) else "0"
    return f"{market_id}.{code}"


def fetch_eastmoney_daily_bars(market_symbol: str, count: int = 80) -> list[dict[str, Any]]:
    secid = eastmoney_secid_from_market_symbol(market_symbol)
    if not secid.endswith("." + normalize_symbol(market_symbol)):
        return []
    params = urllib.parse.urlencode({
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(max(count, 80)),
    })
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        payload = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    bars = []
    for line in (((payload.get("data") or {}).get("klines")) or []):
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        try:
            day = parts[0]
            if day >= market_clock().date().isoformat():
                continue
            bars.append({
                "day": day,
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5] or 0.0),
            })
        except Exception:
            continue
    return bars[-count:]


def fetch_tencent_daily_bars(market_symbol: str, count: int = 80) -> list[dict[str, Any]]:
    symbol = normalize_symbol(market_symbol)
    market_symbol = market_code(symbol)
    if not symbol or not market_symbol:
        return []
    params = urllib.parse.urlencode({
        "param": f"{market_symbol},day,,,{max(count + 1, 90)},qfq",
    })
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://gu.qq.com/",
        },
    )
    try:
        payload = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    stock_data = (payload.get("data") or {}).get(market_symbol) or {}
    rows = stock_data.get("qfqday") or stock_data.get("day") or []
    bars = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            day = str(row[0] or "")
            if day >= market_clock().date().isoformat():
                continue
            bars.append({
                "day": day,
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5] or 0.0),
            })
        except Exception:
            continue
    return bars[-count:]


def df_col_by_keywords(columns: Any, *keywords: str) -> str:
    for col in columns:
        text = str(col)
        if all(keyword in text for keyword in keywords):
            return text
    return ""


def fetch_akshare_fund_flow_snapshot() -> dict[str, dict[str, Any]]:
    try:
        import akshare as ak
    except Exception:
        return {}
    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
    except Exception:
        return {}
    if df is None or getattr(df, "empty", True):
        return {}
    columns = list(df.columns)
    code_col = df_col_by_keywords(columns, "代码") or df_col_by_keywords(columns, "股票代码")
    name_col = df_col_by_keywords(columns, "名称") or df_col_by_keywords(columns, "股票简称")
    pct_col = df_col_by_keywords(columns, "涨跌幅")
    amount_col = df_col_by_keywords(columns, "成交额")
    main_col = df_col_by_keywords(columns, "主力", "净流入", "净额")
    main_pct_col = df_col_by_keywords(columns, "主力", "净流入", "净占比")
    super_col = df_col_by_keywords(columns, "超大单", "净流入", "净额")
    large_col = df_col_by_keywords(columns, "大单", "净流入", "净额")
    mid_col = df_col_by_keywords(columns, "中单", "净流入", "净额")
    small_col = df_col_by_keywords(columns, "小单", "净流入", "净额")
    if not code_col or not main_col:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(df.to_dict("records"), 1):
        sym = normalize_symbol(item.get(code_col))
        if not sym:
            continue
        rows[sym] = {
            "symbol": sym,
            "name": item.get(name_col, ""),
            "fund_flow_rank": idx,
            "main_net": to_float(item.get(main_col), 0.0),
            "main_net_pct": to_float(item.get(main_pct_col), 0.0),
            "super_net": to_float(item.get(super_col), 0.0),
            "large_net": to_float(item.get(large_col), 0.0),
            "mid_net": to_float(item.get(mid_col), 0.0),
            "small_net": to_float(item.get(small_col), 0.0),
            "fund_flow_amount": to_float(item.get(amount_col), 0.0),
            "fund_flow_pct_chg": to_float(item.get(pct_col), 0.0),
            "fund_flow_checked_at": now_iso(),
            "fund_flow_source": "akshare_realtime_rank",
        }
    return rows


def fetch_akshare_fund_flow_history(sym: str, count: int = 5) -> list[dict[str, Any]]:
    code = normalize_symbol(sym)
    if not code:
        return []
    try:
        import akshare as ak
    except Exception:
        return []
    try:
        df = ak.stock_individual_fund_flow(stock=code, market=akshare_market_from_symbol(code))
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    columns = list(df.columns)
    day_col = df_col_by_keywords(columns, "日期")
    main_col = df_col_by_keywords(columns, "主力", "净流入", "净额")
    super_col = df_col_by_keywords(columns, "超大单", "净流入", "净额")
    large_col = df_col_by_keywords(columns, "大单", "净流入", "净额")
    if not day_col or not main_col:
        return []
    rows = []
    for item in df.tail(max(count, 5)).to_dict("records"):
        rows.append({
            "day": str(item.get(day_col) or ""),
            "main_net": to_float(item.get(main_col), 0.0),
            "super_net": to_float(item.get(super_col), 0.0),
            "large_net": to_float(item.get(large_col), 0.0),
        })
    return rows[-count:]


def fetch_eastmoney_fund_flow_snapshot(force: bool = False) -> dict[str, dict[str, Any]]:
    if not force and time.time() < float(FUND_FLOW_CACHE.get("expires_at") or 0):
        return dict(FUND_FLOW_CACHE.get("rows") or {})
    cached_rows = dict(FUND_FLOW_CACHE.get("rows") or {})
    if not cached_rows:
        try:
            state_cache = load_state().get("fund_flow_snapshot") or {}
            cached_rows = dict(state_cache.get("rows") or {})
        except Exception:
            cached_rows = {}
    ak_rows = fetch_akshare_fund_flow_snapshot()
    if ak_rows:
        FUND_FLOW_CACHE["rows"] = ak_rows
        FUND_FLOW_CACHE["expires_at"] = time.time() + HOT_LEADER_FLOW_TTL_SEC
        return ak_rows
    rows: dict[str, dict[str, Any]] = {}
    page_size = 20
    try:
        import requests
    except Exception:
        requests = None
    for page in range(1, max(1, HOT_LEADER_FLOW_MAX_PAGES) + 1):
        params = {
            "fid": "f62",
            "po": "1",
            "pz": str(page_size),
            "pn": str(page),
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f6,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
        }
        url = f"https://push2.eastmoney.com/api/qt/clist/get?{urllib.parse.urlencode(params)}"
        payload = None
        for attempt in range(3):
            try:
                if requests is not None:
                    resp = requests.get(
                        "https://push2.eastmoney.com/api/qt/clist/get",
                        params=params,
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Accept": "application/json,text/plain,*/*",
                            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
                        },
                        timeout=8,
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                    payload = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore"))
                break
            except Exception:
                try:
                    raw = subprocess.check_output(
                        [
                            "curl",
                            "-sS",
                            "--http1.1",
                            "-m",
                            "8",
                            "-A",
                            "Mozilla/5.0",
                            "-e",
                            "https://quote.eastmoney.com/center/gridlist.html",
                            url,
                        ],
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    ).decode("utf-8", errors="ignore")
                    payload = json.loads(raw)
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(0.35)
        if not payload:
            break
        diff = ((payload.get("data") or {}).get("diff")) or []
        if not diff:
            break
        for page_idx, item in enumerate(diff, 1):
            sym = normalize_symbol(item.get("f12"))
            if not sym or sym in rows:
                continue
            rows[sym] = {
                "symbol": sym,
                "name": item.get("f14", ""),
                "fund_flow_rank": (page - 1) * page_size + page_idx,
                "main_net": to_float(item.get("f62"), 0.0),
                "main_net_pct": to_float(item.get("f184"), 0.0),
                "super_net": to_float(item.get("f66"), 0.0),
                "large_net": to_float(item.get("f72"), 0.0),
                "mid_net": to_float(item.get("f78"), 0.0),
                "small_net": to_float(item.get("f84"), 0.0),
                "fund_flow_amount": to_float(item.get("f6"), 0.0),
                "fund_flow_pct_chg": to_float(item.get("f3"), 0.0),
                "fund_flow_checked_at": now_iso(),
                "fund_flow_source": "eastmoney_realtime_rank",
            }
        if len(diff) < page_size:
            break
    if rows:
        FUND_FLOW_CACHE["rows"] = rows
        FUND_FLOW_CACHE["expires_at"] = time.time() + HOT_LEADER_FLOW_TTL_SEC
        return rows
    return cached_rows


def fetch_eastmoney_fund_flow_history(sym: str, count: int = 5) -> list[dict[str, Any]]:
    code = normalize_symbol(sym)
    if not code:
        return []
    cache_key = f"{code}:{market_clock().date().isoformat()}"
    cached = FUND_FLOW_HISTORY_CACHE.get(cache_key)
    if cached and time.time() < float(cached.get("expires_at") or 0):
        return list(cached.get("rows") or [])[-count:]
    ak_rows = fetch_akshare_fund_flow_history(code, max(count, 5))
    if ak_rows:
        FUND_FLOW_HISTORY_CACHE[cache_key] = {"expires_at": time.time() + 900.0, "rows": ak_rows}
        return ak_rows[-count:]
    secid = eastmoney_secid_from_market_symbol(market_code(code))
    params = {
        "secid": secid,
        "klt": "101",
        "lmt": str(max(count, 5)),
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
    }
    url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?{urllib.parse.urlencode(params)}"
    try:
        try:
            import requests
        except Exception:
            requests = None
        if requests is not None:
            resp = requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            payload = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore"))
    except Exception:
        try:
            raw = subprocess.check_output(
                ["curl", "-sS", "--http1.1", "-m", "8", "-A", "Mozilla/5.0", url],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode("utf-8", errors="ignore")
            payload = json.loads(raw)
        except Exception:
            return list((cached or {}).get("rows") or [])[-count:]
    rows = []
    for line in (((payload.get("data") or {}).get("klines")) or []):
        parts = str(line).split(",")
        if len(parts) < 2:
            continue
        try:
            rows.append({
                "day": parts[0],
                "main_net": float(parts[1]),
                "super_net": float(parts[2]) if len(parts) > 2 else 0.0,
                "large_net": float(parts[3]) if len(parts) > 3 else 0.0,
            })
        except Exception:
            continue
    if rows:
        FUND_FLOW_HISTORY_CACHE[cache_key] = {"expires_at": time.time() + 900.0, "rows": rows}
    return rows[-count:]


def latest_history_fund_flow(sym: str) -> dict[str, Any]:
    history = fetch_eastmoney_fund_flow_history(sym, 5)
    if not history:
        return {}
    latest = history[-1]
    return {
        "symbol": normalize_symbol(sym),
        "fund_flow_rank": 9999,
        "main_net": to_float(latest.get("main_net"), 0.0),
        "super_net": to_float(latest.get("super_net"), 0.0),
        "large_net": to_float(latest.get("large_net"), 0.0),
        "fund_flow_checked_at": now_iso(),
        "fund_flow_source": f"eastmoney_history_{latest.get('day') or ''}",
    }


def recent_main_net_values(sym: str, today_main_net: float, count: int = 3) -> list[float]:
    today = market_clock().date().isoformat()
    history = fetch_eastmoney_fund_flow_history(sym, max(count + 2, 5))
    values: list[float] = []
    used_today = False
    for row in reversed(history):
        day = str(row.get("day") or "")
        value = to_float(row.get("main_net"), 0.0)
        if day == today:
            value = today_main_net
            used_today = True
        values.append(value)
        if len(values) >= count:
            break
    if not used_today:
        values.insert(0, today_main_net)
    return values[:count]


def fetch_sina_daily_bars(sym: str, count: int = 80, sina_code: str | None = None) -> list[dict[str, Any]]:
    symbol = normalize_symbol(sym)
    market_symbol = sina_code or sina_symbol(symbol)
    if not symbol or not market_symbol:
        return []
    cache_key = (market_symbol, market_clock().date().isoformat())
    cached = DAILY_BAR_CACHE.get(cache_key)
    if cached and len(cached) >= min(count, 20):
        return cached[-count:]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://finance.sina.com.cn/",
    }
    path = (
        "money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={market_symbol}&scale=240&ma=no&datalen={max(count, 80)}"
    )
    urls = [f"https://{path}", f"http://{path}"]
    payload = None
    try:
        for url in urls:
            req = urllib.request.Request(url, headers=headers)
            raw = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore")
            if "拒绝访问" in raw or not raw.strip().startswith("["):
                continue
            payload = json.loads(raw)
            break
    except Exception:
        fallback = fetch_eastmoney_daily_bars(market_symbol, count)
        if fallback:
            DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
            return fallback[-count:]
        fallback = fetch_tencent_daily_bars(market_symbol, count)
        if fallback:
            DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
            return fallback[-count:]
        return cached[-count:] if cached else []
    if payload is None:
        fallback = fetch_eastmoney_daily_bars(market_symbol, count)
        if fallback:
            DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
            return fallback[-count:]
        fallback = fetch_tencent_daily_bars(market_symbol, count)
        if fallback:
            DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
            return fallback[-count:]
        return cached[-count:] if cached else []
    bars = []
    for item in payload or []:
        try:
            day = str(item.get("day") or "")
            if day >= market_clock().date().isoformat():
                continue
            bars.append({
                "day": day,
                "open": float(item.get("open")),
                "high": float(item.get("high")),
                "low": float(item.get("low")),
                "close": float(item.get("close")),
                "volume": float(item.get("volume") or 0.0),
            })
        except Exception:
            continue
    if bars:
        DAILY_BAR_CACHE[cache_key] = bars[-max(count, 80):]
        return bars[-count:]
    fallback = fetch_eastmoney_daily_bars(market_symbol, count)
    if fallback:
        DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
        return fallback[-count:]
    fallback = fetch_tencent_daily_bars(market_symbol, count)
    if fallback:
        DAILY_BAR_CACHE[cache_key] = fallback[-max(count, 80):]
        return fallback[-count:]
    return cached[-count:] if cached else []


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def macd_diff(closes: list[float], fast: int = 12, slow: int = 26) -> float:
    if len(closes) < slow + 5:
        return float("nan")
    ef = ema(closes, fast)
    es = ema(closes, slow)
    return ef[-1] - es[-1]


def approx_limit_up(prev_close: float, close: float, pct: float = 0.10) -> bool:
    if prev_close <= 0 or close <= 0:
        return False
    limit_price = round(prev_close * (1.0 + pct) + 1e-8, 2)
    return close >= limit_price - 0.01 or close / prev_close - 1.0 >= pct - 0.002


def max_consecutive_true(values: list[bool]) -> int:
    best = cur = 0
    for value in values:
        cur = cur + 1 if value else 0
        best = max(best, cur)
    return best


def build_market_regime_snapshot(now: datetime | None = None) -> dict[str, Any]:
    current = market_clock(now)
    today = current.date().isoformat()
    cached = MARKET_REGIME_CACHE.get(today)
    if cached is not None:
        return cached
    bars = fetch_sina_daily_bars("000001", 80, sina_code="sh000001")
    snapshot: dict[str, Any] = {
        "checked_at": now_iso(),
        "source": "index_daily_bars_sina_with_eastmoney_fallback",
        "index_symbol": "000001",
        "index_name": "上证指数",
        "data_ok": False,
        "is_bull": False,
        "reason": "指数日线不足，不能确认大盘MA5/MA10/MA20多头",
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "close": None,
    }
    if len(bars) >= 25:
        closes = [bar["close"] for bar in bars]
        ma5 = mean(closes[-5:])
        ma10 = mean(closes[-10:])
        ma20 = mean(closes[-20:])
        close = closes[-1]
        rising_ma5 = ma5 > mean(closes[-6:-1])
        golden = ma5 > ma10 > ma20 and rising_ma5
        snapshot.update({
            "data_ok": True,
            "is_bull": bool(golden),
            "reason": (
                "上证指数MA5>MA10>MA20且MA5走升"
                if golden
                else "上证指数MA5/MA10/MA20未形成多头排列或MA5未走升"
            ),
            "ma5": round(ma5, 2),
            "ma10": round(ma10, 2),
            "ma20": round(ma20, 2),
            "close": round(close, 2),
            "last_bar_date": bars[-1].get("day", ""),
        })
    MARKET_REGIME_CACHE[today] = snapshot
    return snapshot


def is_market_golden() -> bool:
    today = market_clock().date().isoformat()
    cached = MARKET_REGIME_CACHE.get(today)
    if cached is not None:
        return bool(cached.get("is_bull"))
    return bool(build_market_regime_snapshot().get("is_bull"))


def historical_rebound_filter(q: dict[str, Any]) -> tuple[bool, list[str]]:
    sym = normalize_symbol(q.get("symbol"))
    bars = fetch_sina_daily_bars(sym, 80)
    reasons = []
    if len(bars) < 50:
        return False, ["历史日线不足"]

    yesterday = bars[-1]
    prev = bars[-2]
    if prev["close"] <= 0:
        return False, ["前收无效"]
    if approx_limit_up(prev["close"], yesterday["close"]):
        return False, ["昨日涨停不符合原N字策略"]
    y_ret = yesterday["close"] / prev["close"] - 1.0
    if not (N_SHAPE_Y_RET_MIN < y_ret < N_SHAPE_Y_RET_MAX):
        return False, [f"昨日跌幅不符{y_ret:+.2%}"]
    reasons.append(f"N字第二笔回踩，昨日跌幅{y_ret:+.2%}")

    limit_flags = [
        approx_limit_up(bars[i - 1]["close"], bars[i]["close"])
        for i in range(1, len(bars))
    ]
    impulse_idx = None
    impulse_score = -1.0
    start_idx = max(1, len(bars) - 16)
    end_idx = len(bars) - 1
    for i in range(start_idx, end_idx):
        prev_close = bars[i - 1]["close"]
        if prev_close <= 0:
            continue
        day_ret = bars[i]["close"] / prev_close - 1.0
        intraday_ret = bars[i]["close"] / bars[i]["open"] - 1.0 if bars[i]["open"] > 0 else 0.0
        is_impulse = approx_limit_up(prev_close, bars[i]["close"]) or day_ret >= 0.07 or intraday_ret >= 0.065
        if not is_impulse:
            continue
        score = day_ret + intraday_ret + min(0.08, bars[i]["volume"] / max(1.0, mean([b["volume"] for b in bars[max(0, i - 5):i]]) or 1.0) / 100)
        if score > impulse_score:
            impulse_score = score
            impulse_idx = i
    if impulse_idx is None:
        return False, ["N字第一笔不足：近15日无放量大阳/涨停"]
    if impulse_idx >= len(bars) - 1:
        return False, ["第一笔发生在昨日，缺少回踩"]

    impulse = bars[impulse_idx]
    impulse_prev = bars[impulse_idx - 1]
    impulse_ret = impulse["close"] / impulse_prev["close"] - 1.0 if impulse_prev["close"] > 0 else 0.0
    pullback_bars = bars[impulse_idx + 1:]
    pullback_days = len(pullback_bars)
    if not (1 <= pullback_days <= 10):
        return False, [f"N字第二笔时间不符：回踩{pullback_days}天"]
    reasons.append(f"N字第一笔放量上攻{impulse['day']} {impulse_ret:+.2%}")

    pullback_low = min(bar["low"] for bar in pullback_bars)
    pullback_high = max(bar["high"] for bar in pullback_bars)
    if impulse["close"] <= 0:
        return False, ["第一笔收盘无效"]
    pullback_depth = pullback_low / impulse["close"] - 1.0
    if pullback_depth < -0.18:
        return False, [f"N字回踩过深{pullback_depth:+.2%}"]
    if pullback_low < impulse["open"] * 0.985:
        return False, ["N字回踩跌破启动阳线支撑"]
    reasons.append(f"N字回踩深度{pullback_depth:+.2%}")

    impulse_vol = impulse["volume"]
    pullback_avg_vol = mean([bar["volume"] for bar in pullback_bars])
    if impulse_vol > 0 and pullback_avg_vol > impulse_vol * 0.95:
        return False, ["N字回踩未缩量"]
    reasons.append("N字回踩缩量")

    today_high = to_float(q.get("high"), 0.0)
    today_price = to_float(q.get("price"), 0.0)
    if today_high < pullback_high * 0.995:
        return False, [f"N字第三笔未突破回踩平台 {today_high:.2f}/{pullback_high:.2f}"]
    if today_price < yesterday["close"] * 1.01:
        return False, ["N字第三笔现价强度不足"]
    prev_ext = today_price / yesterday["close"] - 1.0 if yesterday["close"] > 0 else 9.9
    platform_ext = today_price / pullback_high - 1.0 if pullback_high > 0 else 9.9
    if prev_ext > MORNING_REBOUND_MAX_PREV_EXT:
        return False, [f"N字第三笔离昨收过远{prev_ext:+.2%}"]
    if platform_ext > MORNING_REBOUND_MAX_PLATFORM_EXT:
        return False, [f"N字第三笔离平台过远{platform_ext:+.2%}"]
    reasons.append(f"N字第三笔温和突破平台，离昨收{prev_ext:+.2%}，离平台{platform_ext:+.2%}")

    closes = [bar["close"] for bar in bars]
    ma10 = mean(closes[-10:])
    ma20 = mean(closes[-20:])
    if yesterday["open"] <= ma10:
        return False, [f"昨日开盘未站上MA10 {yesterday['open']:.2f}/{ma10:.2f}"]
    reasons.append(f"昨日开盘>MA10 {yesterday['open']:.2f}/{ma10:.2f}")

    today_open = to_float(q.get("open"), 0.0)
    if today_open <= ma20:
        return False, [f"今日开盘未站上昨MA20 {today_open:.2f}/{ma20:.2f}"]
    reasons.append(f"今日开盘>MA20 {today_open:.2f}/{ma20:.2f}")

    diff = macd_diff(closes)
    if not math.isfinite(diff) or diff >= 0.5:
        return False, [f"MACD diff不符 {diff:.3f}"]
    reasons.append(f"MACD diff {diff:.3f}")

    if max_consecutive_true(limit_flags[-20:]) >= 3:
        return False, ["近20日有连续3板"]
    reasons.append("近20日无连续3板")

    if not is_market_golden():
        return False, ["大盘MA5/MA10/MA20非多头"]
    reasons.append("大盘MA5>MA10>MA20")
    return True, reasons


def dedupe_symbols(symbols: list[str]) -> list[str]:
    return list(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)))


def get_market_scan_symbols(state: dict[str, Any], batch_size: int | None = None) -> list[str]:
    if not MARKET_UNIVERSE:
        return []
    size = batch_size or MARKET_SCAN_BATCH_SIZE
    cursor = int(state.get("market_scan_cursor") or 0) % len(MARKET_UNIVERSE)
    end = cursor + max(1, size)
    symbols = list(MARKET_UNIVERSE[cursor:end])
    if end >= len(MARKET_UNIVERSE):
        symbols.extend(MARKET_UNIVERSE[: end % len(MARKET_UNIVERSE)])
    state["market_scan_cursor"] = end % len(MARKET_UNIVERSE)
    RUNTIME["market_scan_cursor"] = state["market_scan_cursor"]
    return symbols


def refresh_state_quotes(state: dict[str, Any], quotes: dict[str, dict[str, Any]]) -> None:
    pinned = dedupe_symbols(
        (state.get("watchlist") or DEFAULT_WATCHLIST)
        + list((state.get("positions") or {}).keys())
    )
    retained = {sym: quotes[sym] for sym in pinned if sym in quotes}
    state["quotes"] = retained


def planned_order_symbols(plan: dict[str, Any]) -> list[str]:
    symbols = [order.get("symbol") for order in (plan.get("orders") or [])]
    return dedupe_symbols([symbol for symbol in symbols if normalize_symbol(symbol)])


def hydrate_execution_quotes(state: dict[str, Any], plan: dict[str, Any]) -> int:
    required_symbols = planned_order_symbols(plan)
    if not required_symbols:
        return 0
    existing_symbols = set((state.get("quotes") or {}).keys())
    missing_symbols = [symbol for symbol in required_symbols if symbol not in existing_symbols]
    if not missing_symbols:
        return 0
    fetched = fetch_sina_quotes(missing_symbols)
    if not fetched:
        return 0
    MARKET_QUOTE_CACHE.update(fetched)
    state.setdefault("quotes", {}).update(fetched)
    append_log(state, f"补拉成交行情：{len(fetched)} 只")
    return len(fetched)


def refresh_position_quotes_if_stale(state: dict[str, Any], max_age_sec: float | None = None) -> list[str]:
    symbols = dedupe_symbols((state.get("positions") or {}).keys())
    if not symbols:
        return []
    market_open, _, _ = market_status()
    ttl = max_age_sec if max_age_sec is not None else (
        POSITION_QUOTE_TTL_OPEN_SEC if market_open else POSITION_QUOTE_TTL_CLOSED_SEC
    )
    quotes = state.setdefault("quotes", {})
    stale_symbols = [
        sym for sym in symbols
        if not quote_is_today(quotes.get(sym) or {}) or quote_age_seconds(quotes.get(sym) or {}) > ttl
    ]
    if not stale_symbols:
        return []
    try:
        fetched = fetch_sina_quotes(stale_symbols)
    except Exception as exc:
        RUNTIME["last_error"] = f"持仓行情刷新失败：{exc}"
        return []
    if not fetched:
        return []
    quotes.update(fetched)
    MARKET_QUOTE_CACHE.update(fetched)
    for sym, quote in fetched.items():
        pos = (state.get("positions") or {}).get(sym)
        if pos:
            pos["last_price"] = to_float(quote.get("price"), to_float(pos.get("last_price"), pos.get("avg_cost")))
            pos["last_quote_time"] = quote.get("quote_time", "")
    return list(fetched.keys())


def build_symbol_pnl_ledger(state: dict[str, Any], current_positions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    ledger: dict[str, dict[str, Any]] = {}
    open_positions: dict[str, dict[str, Any]] = {}
    for trade in sorted(state.get("trades") or [], key=trade_sort_key):
        if not isinstance(trade, dict):
            continue
        sym = normalize_symbol(trade.get("symbol"))
        side = str(trade.get("side") or "").upper()
        qty = int(to_float(trade.get("qty"), 0.0))
        price = to_float(trade.get("price"), 0.0)
        if not sym or qty <= 0 or price <= 0:
            continue
        row = ledger.setdefault(sym, {
            "symbol": sym,
            "name": trade.get("name", ""),
            "buy_count": 0,
            "sell_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "gross_buy": 0.0,
            "gross_sell": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "current_qty": 0,
            "last_trade_time": "",
        })
        row["name"] = trade.get("name") or row.get("name", "")
        row["last_trade_time"] = max(str(row.get("last_trade_time") or ""), str(trade.get("time") or ""))
        pos = open_positions.get(sym)
        if side == "BUY":
            row["buy_count"] += 1
            row["buy_qty"] += qty
            row["gross_buy"] += qty * price
            if not pos:
                open_positions[sym] = {"qty": qty, "avg_cost": price}
            else:
                old_qty = int(pos.get("qty") or 0)
                old_cost = to_float(pos.get("avg_cost"), 0.0)
                new_qty = old_qty + qty
                pos["qty"] = new_qty
                pos["avg_cost"] = (old_qty * old_cost + qty * price) / new_qty if new_qty > 0 else price
        elif side == "SELL":
            row["sell_count"] += 1
            row["sell_qty"] += qty
            row["gross_sell"] += qty * price
            if not pos:
                continue
            sell_qty = min(qty, int(pos.get("qty") or 0))
            avg_cost = to_float(pos.get("avg_cost"), 0.0)
            row["realized_pnl"] += (price - avg_cost) * sell_qty
            remain = int(pos.get("qty") or 0) - sell_qty
            if remain <= 0:
                open_positions.pop(sym, None)
            else:
                pos["qty"] = remain

    for pos in current_positions or []:
        sym = normalize_symbol(pos.get("symbol"))
        if not sym:
            continue
        row = ledger.setdefault(sym, {
            "symbol": sym,
            "name": pos.get("name", ""),
            "buy_count": 0,
            "sell_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "gross_buy": 0.0,
            "gross_sell": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "current_qty": 0,
            "last_trade_time": "",
        })
        row["name"] = pos.get("name") or row.get("name", "")
        row["current_qty"] = int(pos.get("qty") or 0)
        row["unrealized_pnl"] = to_float(pos.get("pnl"), 0.0)

    rows = []
    for row in ledger.values():
        realized = to_float(row.get("realized_pnl"), 0.0)
        unrealized = to_float(row.get("unrealized_pnl"), 0.0)
        total = realized + unrealized
        gross_buy = to_float(row.get("gross_buy"), 0.0)
        rows.append({
            **row,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(total, 2),
            "total_pnl_pct": round(total / gross_buy, 6) if gross_buy > 0 else 0.0,
        })
    return sorted(rows, key=lambda item: (abs(to_float(item.get("total_pnl"), 0.0)), str(item.get("last_trade_time") or "")), reverse=True)


def account_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    quotes = state.get("quotes") or {}
    positions = []
    market_value = 0.0
    for sym, pos in (state.get("positions") or {}).items():
        qty = int(pos.get("qty") or 0)
        avg_cost = to_float(pos.get("avg_cost"), 0.0)
        q = quotes.get(sym) or {}
        price = to_float(q.get("price"), to_float(pos.get("last_price"), avg_cost))
        pct_chg = to_float(q.get("pct_chg"))
        value = qty * price
        pnl = value - qty * avg_cost
        market_value += value
        positions.append({**pos, "symbol": sym, "last_price": price, "pct_chg": pct_chg, "today_pct_chg": pct_chg, "quote_time": q.get("quote_time", ""), "market_value": value, "pnl": pnl, "pnl_pct": pnl / (qty * avg_cost) if qty * avg_cost > 0 else 0})
    stock_pnl_ledger = build_symbol_pnl_ledger(state, positions)
    stock_pnl_by_symbol = {row.get("symbol"): row for row in stock_pnl_ledger}
    for pos in positions:
        row = stock_pnl_by_symbol.get(normalize_symbol(pos.get("symbol"))) or {}
        pos["realized_pnl_total"] = to_float(row.get("realized_pnl"), 0.0)
        pos["symbol_total_pnl"] = to_float(row.get("total_pnl"), to_float(pos.get("pnl"), 0.0))
        pos["symbol_total_pnl_pct"] = to_float(row.get("total_pnl_pct"), 0.0)
    cash = to_float(state.get("cash"), DEFAULT_CASH)
    initial = to_float(state.get("initial_cash"), DEFAULT_CASH)
    total = cash + market_value
    return {
        "cash": cash,
        "initial_cash": initial,
        "market_value": market_value,
        "total_value": total,
        "total_pnl": total - initial,
        "total_pnl_pct": total / initial - 1 if initial > 0 else 0,
        "positions": positions,
        "stock_pnl_ledger": stock_pnl_ledger,
    }


def t_lot_qty(qty: float) -> int:
    return max(0, int(math.floor(qty / 100.0) * 100))


def position_is_sellable(pos: dict[str, Any], now: datetime | None = None) -> bool:
    return not is_same_trade_day(pos.get("opened_at"), market_clock(now))


def position_t_ma_snapshot(sym: str) -> dict[str, Any]:
    bars = fetch_sina_daily_bars(sym, 30)
    closes = [to_float(bar.get("close"), 0.0) for bar in bars if to_float(bar.get("close"), 0.0) > 0]
    volumes = [to_float(bar.get("volume"), 0.0) for bar in bars if to_float(bar.get("volume"), 0.0) > 0]
    if len(closes) < 20:
        return {"ok": False, "reason": "日线不足"}
    return {
        "ok": True,
        "ma5": mean(closes[-5:]),
        "ma10": mean(closes[-10:]),
        "ma20": mean(closes[-20:]),
        "avg_vol5": mean(volumes[-5:]) if len(volumes) >= 5 else 0.0,
        "last_vol": volumes[-1] if volumes else 0.0,
    }


def realtime_fund_flow_for_symbol(state: dict[str, Any], sym: str) -> dict[str, Any]:
    rows = ((state.get("fund_flow_snapshot") or {}).get("rows") or {})
    flow = rows.get(normalize_symbol(sym)) or {}
    source = str(flow.get("fund_flow_source") or "")
    if source in {"eastmoney_realtime_rank", "akshare_realtime_rank"}:
        return flow
    return {}


def active_t_ledger_by_symbol(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in state.get("t_ledger") or []:
        if str(row.get("status") or "").upper() not in {"OPEN", "PARTIAL"}:
            continue
        sym = normalize_symbol(row.get("symbol"))
        if not sym:
            continue
        out.setdefault(sym, []).append(row)
    return out


def build_t_signals(state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    if not T_MODULE_ENABLED:
        return []
    current = market_clock(now)
    account = account_snapshot(state)
    quotes = state.get("quotes") or {}
    ledger = active_t_ledger_by_symbol(state)
    signals: list[dict[str, Any]] = []
    for pos in account.get("positions") or []:
        sym = normalize_symbol(pos.get("symbol"))
        qty = int(pos.get("qty") or 0)
        if not sym or qty < 100:
            continue
        q = quotes.get(sym) or {}
        price = to_float(q.get("price"), to_float(pos.get("last_price"), 0.0))
        day_pct = to_float(q.get("pct_chg"), 0.0)
        open_price = to_float(q.get("open"), 0.0)
        volume = to_float(q.get("volume"), 0.0)
        ma = position_t_ma_snapshot(sym)
        sellable = position_is_sellable(pos, current)
        if ma.get("ok") and sellable:
            ma20 = to_float(ma.get("ma20"), 0.0)
            ma20_ext = price / ma20 - 1.0 if price > 0 and ma20 > 0 else 0.0
            if day_pct > T_OUT_MIN_DAY_PCT and ma20_ext > T_OUT_MIN_MA20_EXT:
                t_qty = t_lot_qty(qty * T_OUT_MAX_POSITION_PCT)
                if t_qty > 0:
                    signals.append({
                        "symbol": sym,
                        "name": pos.get("name", ""),
                        "type": "T_OUT",
                        "action_hint": "卖出不超过30%底仓，等待次日或回调至均线附近买回",
                        "qty": t_qty,
                        "trigger_price": round(price, 2),
                        "deadline": "",
                        "priority": 82,
                        "can_auto_execute": False,
                        "reason_fields": {
                            "day_pct": round(day_pct, 2),
                            "ma20_ext": round(ma20_ext, 4),
                            "ma20": round(ma20, 2),
                            "sellable": sellable,
                            "position_qty": qty,
                        },
                        "reason": f"T出：当日涨幅{day_pct:+.2f}%且偏离MA20 {ma20_ext:+.2%}，建议T出{t_qty}股，不超过底仓30%。",
                    })
        for row in ledger.get(sym, []):
            remaining = int(to_float(row.get("remaining_qty") or row.get("qty"), 0.0))
            if remaining <= 0 or not ma.get("ok"):
                continue
            ma_values = [to_float(ma.get("ma5"), 0.0), to_float(ma.get("ma10"), 0.0), to_float(ma.get("ma20"), 0.0)]
            touched = [value for value in ma_values if value > 0 and price <= value * 1.006 and price >= value * 0.985]
            avg_vol5 = to_float(ma.get("avg_vol5"), 0.0)
            shrink = bool(avg_vol5 > 0 and volume > 0 and volume <= avg_vol5 * 0.85)
            if touched and shrink:
                signals.append({
                    "symbol": sym,
                    "name": pos.get("name", ""),
                    "type": "T_BACK",
                    "action_hint": "只买回已T出的仓位，不开新仓",
                    "qty": t_lot_qty(remaining),
                    "trigger_price": round(price, 2),
                    "deadline": "",
                    "priority": 78,
                    "can_auto_execute": False,
                    "reason_fields": {
                        "touch_ma": round(min(touched, key=lambda value: abs(price - value)), 2),
                        "volume_shrink": shrink,
                        "remaining_t_qty": remaining,
                    },
                    "reason": f"T回：价格触及关键均线且缩量，最多回补已T出的{remaining}股。",
                })
        flow = realtime_fund_flow_for_symbol(state, sym)
        intraday_drop = price / open_price - 1.0 if price > 0 and open_price > 0 else 0.0
        main_net = to_float(flow.get("main_net"), 0.0)
        if sellable and flow and intraday_drop <= T_INTRADAY_DROP_PCT and main_net > 0:
            t_qty = t_lot_qty(qty * T_INTRADAY_BUY_PCT)
            if t_qty > 0:
                signals.append({
                    "symbol": sym,
                    "name": pos.get("name", ""),
                    "type": "INTRADAY_T",
                    "action_hint": "买入底仓10%-15%，反弹至分时均线/VWAP卖出同等数量旧仓；当天必须完成",
                    "qty": t_qty,
                    "trigger_price": round(price, 2),
                    "deadline": current.replace(hour=14, minute=50, second=0, microsecond=0).isoformat(timespec="seconds"),
                    "priority": 74,
                    "can_auto_execute": False,
                    "reason_fields": {
                        "intraday_drop": round(intraday_drop, 4),
                        "main_net_yi": round(main_net / 100000000.0, 3),
                        "fund_flow_source": flow.get("fund_flow_source", ""),
                        "stop_loss_pct": T_STOP_LOSS_PCT,
                    },
                    "reason": f"主力吸筹T：盘中较开盘急跌{intraday_drop:+.2%}但实时主力净流入{main_net / 100000000.0:+.2f}亿，建议只观察{t_qty}股日内T。",
                })
    return sorted(signals, key=lambda row: int(row.get("priority") or 0), reverse=True)[:12]


def review_date_value(review: dict[str, Any]) -> str:
    text = str(review.get("review_date") or "")
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def review_return_detail_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in review.get("realized_rows") or []:
        rows.append({
            "type": "已卖出",
            "symbol": normalize_symbol(row.get("symbol")),
            "name": row.get("name", ""),
            "qty": int(to_float(row.get("qty"), 0.0)),
            "pnl": round(to_float(row.get("pnl"), 0.0), 2),
            "return_pct": round(to_float(row.get("pnl_pct"), 0.0), 6),
            "price": round(to_float(row.get("price"), 0.0), 2),
            "avg_cost": round(to_float(row.get("avg_cost"), 0.0), 2),
            "note": row.get("reason", ""),
        })
    for row in review.get("unrealized_rows") or []:
        rows.append({
            "type": "持仓",
            "symbol": normalize_symbol(row.get("symbol")),
            "name": row.get("name", ""),
            "qty": int(to_float(row.get("qty"), 0.0)),
            "pnl": round(to_float(row.get("pnl"), 0.0), 2),
            "return_pct": round(to_float(row.get("pnl_pct"), 0.0), 6),
            "price": round(to_float(row.get("last_price"), 0.0), 2),
            "avg_cost": round(to_float(row.get("avg_cost"), 0.0), 2),
            "note": "当日持仓浮盈/浮亏",
        })
    return sorted(rows, key=lambda item: abs(to_float(item.get("pnl"), 0.0)), reverse=True)


def realtime_return_detail_rows(state: dict[str, Any], account: dict[str, Any], today: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    positions: dict[str, dict[str, Any]] = {}
    for trade in sorted(state.get("trades") or [], key=trade_sort_key):
        trade_date = parse_trade_date(trade)
        if not trade_date or trade_date > today:
            break
        side = str(trade.get("side") or "").upper()
        sym = normalize_symbol(trade.get("symbol"))
        if side == "SELL" and trade_date == today:
            pos = positions.get(sym)
            avg_cost = to_float(pos.get("avg_cost"), 0.0) if pos else 0.0
            qty = min(int(trade.get("qty") or 0), int(pos.get("qty") or 0) if pos else int(trade.get("qty") or 0))
            pnl = apply_trade_to_positions(positions, trade)
            rows.append({
                "type": "已卖出",
                "symbol": sym,
                "name": trade.get("name", ""),
                "qty": qty,
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / (avg_cost * qty) if avg_cost > 0 and qty > 0 else 0.0, 6),
                "price": round(to_float(trade.get("price"), 0.0), 2),
                "avg_cost": round(avg_cost, 2),
                "note": trade.get("reason", ""),
            })
            continue
        apply_trade_to_positions(positions, trade)
    for pos in account.get("positions") or []:
        if str(pos.get("trade_date") or "") != today:
            continue
        rows.append({
            "type": "持仓",
            "symbol": normalize_symbol(pos.get("symbol")),
            "name": pos.get("name", ""),
            "qty": int(pos.get("qty") or 0),
            "pnl": round(to_float(pos.get("pnl"), 0.0), 2),
            "return_pct": round(to_float(pos.get("pnl_pct"), 0.0), 6),
            "price": round(to_float(pos.get("last_price"), 0.0), 2),
            "avg_cost": round(to_float(pos.get("avg_cost"), 0.0), 2),
            "note": "今日持仓浮盈/浮亏",
        })
    return sorted(rows, key=lambda item: abs(to_float(item.get("pnl"), 0.0)), reverse=True)


def build_return_stats(state: dict[str, Any], account: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    current = market_clock(now)
    account = account or account_snapshot(state)
    initial = to_float(account.get("initial_cash"), DEFAULT_CASH)
    total_pnl = to_float(account.get("total_pnl"), 0.0)
    total_value = to_float(account.get("total_value"), initial)
    today = current.date().isoformat()
    month_start = current.replace(day=1).date().isoformat()
    year_start = current.replace(month=1, day=1).date().isoformat()
    reviews = sorted(
        [item for item in (state.get("reviews") or []) if review_date_value(item)],
        key=review_date_value,
    )

    def pct_value(pnl: float) -> float:
        return pnl / initial if initial > 0 else 0.0

    def total_before(date_text: str) -> float:
        previous = [
            item for item in reviews
            if review_date_value(item) < date_text
        ]
        return to_float(previous[-1].get("total_pnl"), 0.0) if previous else 0.0

    def current_period(label: str, start_date: str) -> dict[str, Any]:
        start_pnl = total_before(start_date)
        pnl = total_pnl - start_pnl
        return {
            "label": label,
            "start_date": start_date,
            "end_date": today,
            "start_total_pnl": round(start_pnl, 2),
            "pnl": round(pnl, 2),
            "return_pct": round(pct_value(pnl), 6),
        }

    daily_pnl = total_pnl - total_before(today)
    periods = {
        "daily": {
            "label": "今日",
            "start_date": today,
            "end_date": today,
            "start_total_pnl": round(total_before(today), 2),
            "pnl": round(daily_pnl, 2),
            "return_pct": round(pct_value(daily_pnl), 6),
        },
        "monthly": current_period("本月", month_start),
        "yearly": current_period("今年", year_start),
        "total": {
            "label": "总收益",
            "start_date": "",
            "end_date": today,
            "start_total_pnl": 0.0,
            "pnl": round(total_pnl, 2),
            "return_pct": round(to_float(account.get("total_pnl_pct"), pct_value(total_pnl)), 6),
        },
    }

    daily_rows: list[dict[str, Any]] = []
    for review in reviews[-20:]:
        pnl = to_float(review.get("day_pnl"), 0.0)
        daily_rows.append({
            "date": review_date_value(review),
            "pnl": round(pnl, 2),
            "return_pct": round(to_float(review.get("day_pnl_pct"), pct_value(pnl)), 6),
            "total_pnl": round(to_float(review.get("total_pnl"), 0.0), 2),
            "source": review.get("review_source", ""),
            "details": review_return_detail_rows(review),
        })
    if not daily_rows or daily_rows[-1].get("date") != today:
        daily_rows.append({
            "date": today,
            "pnl": round(daily_pnl, 2),
            "return_pct": round(pct_value(daily_pnl), 6),
            "total_pnl": round(total_pnl, 2),
            "source": "realtime",
            "details": realtime_return_detail_rows(state, account, today),
        })
    else:
        daily_rows[-1].update({
            "pnl": round(daily_pnl, 2),
            "return_pct": round(pct_value(daily_pnl), 6),
            "total_pnl": round(total_pnl, 2),
            "source": "realtime",
            "details": realtime_return_detail_rows(state, account, today),
        })

    return {
        "as_of": current.isoformat(timespec="seconds"),
        "initial_cash": round(initial, 2),
        "total_value": round(total_value, 2),
        "periods": periods,
        "daily_rows": daily_rows[-12:],
    }


def build_ai_context(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = market_clock(now)
    account = account_snapshot(state)
    candidate_sets = build_ai_buy_candidate_sets(state)
    review_memory = build_review_memory(state)
    buy_timing_memory = build_buy_timing_memory(review_memory)
    current_n_shape_symbols = n_shape_symbol_set(state)
    current_right_side_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in (state.get("right_side_watchlist") or [])
        if normalize_symbol(item.get("symbol"))
    }
    current_ai_candidate_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in (candidate_sets.get("raw", []) + candidate_sets.get("passed", []))
        if normalize_symbol(item.get("symbol"))
    }
    best_ai_buy_score = max(
        [to_float(item.get("score"), 0.0) for item in candidate_sets.get("passed", [])] or [0.0]
    )
    market_indices = fetch_market_index_snapshot()
    market_intraday = build_market_intraday_snapshot(market_indices)
    market_regime = build_market_regime_snapshot(current)
    market_instruction = market_state_instruction(market_intraday, market_regime)
    positions: list[dict[str, Any]] = []
    for pos in account.get("positions") or []:
        opened_at = pos.get("opened_at", "")
        opened_date = ""
        holding_days = None
        is_today_position = False
        try:
            opened_date = datetime.fromisoformat(str(opened_at)).date().isoformat() if opened_at else ""
            holding_days = (current.date() - datetime.fromisoformat(str(opened_at)).date()).days if opened_at else None
            is_today_position = bool(opened_date == current.date().isoformat())
        except Exception:
            opened_date = ""
            holding_days = None
            is_today_position = False
        sym = normalize_symbol(pos.get("symbol"))
        quote = (state.get("quotes") or {}).get(sym) or {}
        can_sell_today = not is_today_position
        pnl_pct = to_float(pos.get("pnl_pct"), 0.0)
        day_pct = to_float(quote.get("pct_chg"), 0.0)
        in_current_n_shape_pool = sym in current_n_shape_symbols
        in_current_right_side_pool = sym in current_right_side_symbols
        in_current_ai_candidate_pool = sym in current_ai_candidate_symbols
        is_core_candidate = in_current_n_shape_pool or in_current_right_side_pool or in_current_ai_candidate_pool
        early_observe, early_observe_reasons = early_sell_observe_status(pos, quote, is_core_candidate=is_core_candidate, now=current)
        rotation_score = 0.0
        rotation_reasons: list[str] = []
        if can_sell_today:
            sell_action_hint = ""
            if early_observe:
                rotation_score -= 3.0
                rotation_reasons.extend(early_observe_reasons)
                sell_action_hint = "早盘修复观察：未确认跌破开盘/VWAP前不建议机械止损"
            elif pnl_pct <= -0.03:
                rotation_score += 3.0
                rotation_reasons.append(f"浮亏{pnl_pct:+.2%}超过3%")
                sell_action_hint = "可独立SELL止损/去弱，不需要等待新买入标的"
            elif pnl_pct <= -0.015:
                rotation_score += 1.5
                rotation_reasons.append(f"浮亏{pnl_pct:+.2%}需要观察是否换弱")
                sell_action_hint = "可评估减弱，若继续跑输可只SELL不BUY"
            if day_pct <= -1.0:
                rotation_score += 1.5
                rotation_reasons.append(f"今日跌幅{day_pct:+.2f}%跑弱")
                if not sell_action_hint:
                    sell_action_hint = "今日跑弱，可独立SELL去弱"
            if not in_current_n_shape_pool:
                if pnl_pct <= -0.015 or day_pct <= -1.0:
                    rotation_score += 1.0
                    rotation_reasons.append("弱势且不在当前N字观察/严格池")
                else:
                    rotation_reasons.append("不在当前N字池，但未明显走弱")
            if best_ai_buy_score >= N_SHAPE_AI_MIN_SCORE + N_SHAPE_ROTATION_MIN_SCORE_ADVANTAGE and pnl_pct < 0:
                rotation_score += 1.0
                rotation_reasons.append(f"当前有明显更强AI候选最高分{best_ai_buy_score:.1f}")
            if pnl_pct >= 0.025:
                rotation_score -= 1.0
                rotation_reasons.append(f"已有浮盈{pnl_pct:+.2%}，卖出需有更强替代")
        positions.append({
            **pos,
            "opened_date": opened_date,
            "holding_days": holding_days,
            "is_today_position": is_today_position,
            "can_sell_today": can_sell_today,
            "today_pct_chg": day_pct,
            "in_current_n_shape_pool": in_current_n_shape_pool,
            "in_current_right_side_pool": in_current_right_side_pool,
            "in_current_ai_candidate_pool": in_current_ai_candidate_pool,
            "early_sell_observe": early_observe,
            "early_sell_observe_reasons": early_observe_reasons,
            "rotation_score": round(rotation_score, 2),
            "sell_action_hint": sell_action_hint if can_sell_today else "",
            "rotation_reasons": rotation_reasons[:5],
        })
    position_count = len(positions)
    available_slots = max(0, MAX_POSITIONS - position_count)
    sellable_count = len(sellable_position_symbols(state, current))
    buy_locked_no_sellable = no_sellable_position_buy_locked(state, current)
    trading_coach = build_trading_coach(state, current)
    rotation_candidates = sorted(
        [pos for pos in positions if pos.get("can_sell_today") and not pos.get("early_sell_observe") and to_float(pos.get("rotation_score"), 0.0) >= 2.0],
        key=lambda row: (to_float(row.get("rotation_score"), 0.0), -to_float(row.get("pnl_pct"), 0.0)),
        reverse=True,
    )[:5]
    t_signals = state.get("t_signals") or build_t_signals(state, current)
    return {
        "current_time": current.isoformat(timespec="seconds"),
        "market_date": current.date().isoformat(),
        "market_weekday": current.strftime("%A"),
        "market_session": market_status()[2],
        "market_regime": market_regime,
        "market_indices": market_indices,
        "market_intraday": market_intraday,
        "market_state_instruction": market_instruction,
        "previous_trade_day": previous_market_day(current),
        "account": account,
        "positions": positions,
        "rotation_candidates": rotation_candidates,
        "t_signals": t_signals,
        "t_module": {
            "enabled": T_MODULE_ENABLED,
            "mode": "signal_only",
            "rules": [
                f"T出：当日涨幅>{T_OUT_MIN_DAY_PCT:.1f}%且偏离MA20>{T_OUT_MIN_MA20_EXT:.0%}，单次不超过底仓{T_OUT_MAX_POSITION_PCT:.0%}",
                "T回：只回补已T出的仓位，不开新仓",
                "主力吸筹T：仅允许实时/当日资金流，不使用历史兜底资金流触发",
                "第一版只给信号，不自动执行做T订单",
            ],
        },
        "account_constraints": {
            "position_count": position_count,
            "max_positions": MAX_POSITIONS,
            "available_position_slots": available_slots,
            "sellable_position_count": sellable_count,
            "buy_locked_no_sellable_positions": buy_locked_no_sellable,
            "buy_lock_reason": f"当前持仓已满{MAX_POSITIONS}只且当日没有可卖仓位，AI选股/买入暂停" if buy_locked_no_sellable else "",
            "cash": account.get("cash"),
            "can_open_new_position": available_slots > 0 and to_float(account.get("cash"), 0.0) >= 100 and not buy_locked_no_sellable,
        },
        "candidates": compact_candidates_for_ai((state.get("candidates") or [])[:12]),
        "n_shape_candidates": compact_candidates_for_ai((state.get("strategy_signals") or [])[:12]),
        "n_shape_ai_pool": compact_candidates_for_ai((state.get("strategy_watchlist") or state.get("strategy_signals") or [])[:20]),
        "right_side_candidates": compact_candidates_for_ai((state.get("right_side_watchlist") or [])[:20]),
        "ai_buy_candidates_raw": compact_candidates_for_ai(candidate_sets.get("raw", [])),
        "ai_buy_candidates": compact_candidates_for_ai(candidate_sets.get("passed", [])),
        "coach_filtered_candidates": compact_candidates_for_ai(candidate_sets.get("filtered", [])),
        "candidate_counts": {
            "market_candidates_total": len(state.get("candidates") or []),
            "n_shape_candidates_total": len(state.get("strategy_signals") or []),
            "n_shape_ai_pool_total": len(state.get("strategy_watchlist") or state.get("strategy_signals") or []),
            "right_side_candidates_total": len(state.get("right_side_watchlist") or []),
            "ai_buy_candidates_raw": len(candidate_sets.get("raw", [])),
            "ai_buy_candidates": len(candidate_sets.get("passed", [])),
            "coach_filtered_candidates": len(candidate_sets.get("filtered", [])),
            "rotation_candidates": len(rotation_candidates),
        },
        "n_shape_diagnostics": state.get("strategy_diagnostics") or {},
        "risk": {
            "initial_cash": DEFAULT_CASH,
            "max_positions": MAX_POSITIONS,
            "position_count": position_count,
            "available_position_slots": available_slots,
            "sellable_position_count": sellable_count,
            "buy_locked_no_sellable_positions": buy_locked_no_sellable,
            "per_position_cash": PER_POSITION_CASH,
            "t_plus_1": True,
            "buy_mode": AI_BUY_MODE,
            "buy_whitelist": "ai_buy_candidates; coach_filtered_candidates require coach_override=true and a clear override_reason",
            "hard_guardrails": {
                "max_pct_chg": current_ai_guard_max_pct_chg(current),
                "morning_max_pct_chg": AI_GUARD_MAX_PCT_CHG,
                "afternoon_max_pct_chg": AI_GUARD_AFTERNOON_MAX_PCT_CHG,
                "min_amount": AI_GUARD_MIN_AMOUNT,
                "max_spread_pct": AI_GUARD_MAX_SPREAD_PCT,
                "allow_st": False,
                "announcement_guard_enabled": ANNOUNCEMENT_GUARD_ENABLED,
                "announcement_lookback_days": ANNOUNCEMENT_LOOKBACK_DAYS,
                "announcement_block_keywords": list(ANNOUNCEMENT_BLOCK_KEYWORDS),
            },
        },
        "announcement_risks": state.get("announcement_risks") or {},
        "latest_review": compact_latest_review_for_ai(compact_review(latest_review(state))),
        "review_memory": compact_review_memory_for_ai(review_memory, market_instruction),
        "buy_timing_memory": buy_timing_memory,
        "trading_coach": trading_coach,
    }


def n_shape_symbol_set(state: dict[str, Any]) -> set[str]:
    return {
        normalize_symbol(item.get("symbol"))
        for item in ((state.get("strategy_signals") or []) + (state.get("strategy_watchlist") or []))
        if normalize_symbol(item.get("symbol"))
    }


def ai_buy_guardrail(q: dict[str, Any], check_announcements: bool = False) -> tuple[bool, str]:
    sym = normalize_symbol(q.get("symbol"))
    name = str(q.get("name") or "")
    if not sym:
        return False, "代码无效"
    if not sym.startswith(("000", "001", "002", "003", "004", "005", "600", "601", "603", "605")):
        return False, "暂只允许主板/中小板"
    if "ST" in name.upper() or "退" in name:
        return False, "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    spread_pct = (ask - bid) / price * 100 if ask > 0 and bid > 0 and price > 0 else 9.9
    if price <= 0:
        return False, "价格无效"
    if amount < AI_GUARD_MIN_AMOUNT:
        return False, f"成交额低于{AI_GUARD_MIN_AMOUNT / 1e8:.2f}亿"
    source = str(q.get("ai_pool_source") or "")
    max_pct_chg = current_ai_guard_max_pct_chg()
    if source != "right_side_watch" and pct_chg > max_pct_chg:
        return False, f"涨幅过高{pct_chg:.2f}%>{max_pct_chg:.2f}%"
    if pct_chg < -6.5:
        return False, f"跌幅过深{pct_chg:.2f}%"
    if spread_pct > AI_GUARD_MAX_SPREAD_PCT:
        return False, f"盘口价差过大{spread_pct:.3f}%"
    if check_announcements:
        risk = announcement_risk_for_symbol(sym)
        if risk.get("blocked"):
            return False, str(risk.get("reason") or "公告风险")
    return True, ""


def right_side_entry_reject_reason(row: dict[str, Any]) -> str:
    source = str(row.get("ai_pool_source") or "")
    if source != "right_side_watch":
        return ""
    price = to_float(row.get("price"), 0.0)
    day_open = to_float(row.get("open"), 0.0)
    pct_chg = to_float(row.get("pct_chg"), 0.0)
    amount = to_float(row.get("amount"), 0.0)
    volume = to_float(row.get("volume"), 0.0)
    relative_open_gain = to_float(row.get("relative_open_gain"), float("nan"))
    if not math.isfinite(relative_open_gain) and price > 0 and day_open > 0:
        relative_open_gain = price / day_open - 1.0
    vwap_deviation = to_float(row.get("vwap_deviation"), float("nan"))
    if not math.isfinite(vwap_deviation) and price > 0 and amount > 0 and volume > 0:
        vwap = amount / volume
        vwap_deviation = price / vwap - 1.0 if vwap > 0 else float("nan")
    if pct_chg > RIGHT_SIDE_BUY_MAX_PCT_CHG:
        return f"右侧买点过高：涨幅{pct_chg:.2f}%>{RIGHT_SIDE_BUY_MAX_PCT_CHG:.2f}%"
    if math.isfinite(relative_open_gain) and relative_open_gain > RIGHT_SIDE_BUY_MAX_OPEN_GAIN:
        return f"右侧买点过高：相对开盘{relative_open_gain:+.2%}>{RIGHT_SIDE_BUY_MAX_OPEN_GAIN:.1%}"
    if math.isfinite(vwap_deviation) and vwap_deviation > RIGHT_SIDE_BUY_MAX_VWAP_EXT:
        return f"右侧买点过高：离VWAP{vwap_deviation:+.2%}>{RIGHT_SIDE_BUY_MAX_VWAP_EXT:.1%}"
    return ""


def current_ai_guard_max_pct_chg(now: datetime | None = None) -> float:
    current = market_clock(now)
    if current.time() >= MARKET_AFTERNOON_START:
        return AI_GUARD_AFTERNOON_MAX_PCT_CHG
    return AI_GUARD_MAX_PCT_CHG


def build_ai_buy_candidate_sets(state: dict[str, Any], limit: int = 24) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, dict[str, Any]] = {}
    coach = build_trading_coach(state)
    review_memory = build_review_memory(state)
    timing_memory = build_buy_timing_memory(review_memory)
    for item in state.get("strategy_signals") or []:
        sym = normalize_symbol(item.get("symbol"))
        if sym:
            merged[sym] = {**item, "ai_pool_source": "strict_n_shape", "ai_priority": 3}
    for item in state.get("strategy_watchlist") or []:
        sym = normalize_symbol(item.get("symbol"))
        if sym and sym not in merged:
            merged[sym] = {**item, "ai_pool_source": "n_shape_watch", "ai_priority": 2}
    for item in state.get("right_side_watchlist") or []:
        sym = normalize_symbol(item.get("symbol"))
        if sym and sym not in merged:
            merged[sym] = {**item, "ai_pool_source": "right_side_watch", "ai_priority": 2}
    for item in state.get("candidates") or []:
        sym = normalize_symbol(item.get("symbol"))
        if not sym or sym in merged:
            continue
        ok, reason = ai_buy_guardrail(item, check_announcements=False)
        if not ok:
            continue
        candidate = {
            **item,
            "score": round(min(to_float(item.get("score"), 50.0), 55.0), 2),
            "score_basis": "market_liquidity_reference_capped",
            "ai_pool_source": "market_candidate",
            "ai_priority": 1,
            "risk_tags": ["非N字候选，分数仅作流动性参考"],
        }
        merged[sym] = candidate
    raw_rows = []
    passed_rows = []
    filtered_rows = []
    for row in merged.values():
        row = annotate_candidate_style(row)
        ok, reason = ai_buy_guardrail(row, check_announcements=False)
        coach_ok, coach_reason = trading_coach_allows_candidate(row, coach)
        timing_profile = candidate_buy_timing_profile(row, timing_memory)
        enriched = {
            **row,
            **timing_profile,
            "guardrail_ok": ok,
            "guardrail_reason": reason,
            "trading_coach_ok": coach_ok,
            "trading_coach_reason": coach_reason,
        }
        if ok:
            raw_rows.append(enriched)
            if coach_ok:
                passed_rows.append(enriched)
            else:
                filtered_rows.append(enriched)
    sort_key = lambda row: (
        int(row.get("ai_priority") or 0),
        to_float(row.get("buy_timing_score"), to_float(row.get("score"), 0.0)),
        to_float(row.get("score"), 0.0),
    )
    raw_sorted = sorted(raw_rows, key=sort_key, reverse=True)
    passed_sorted = sorted(passed_rows, key=sort_key, reverse=True)
    filtered_sorted = sorted(filtered_rows, key=sort_key, reverse=True)
    announcement_risks = state.get("announcement_risks") or {}

    def visible(rows: list[dict[str, Any]], row_limit: int) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            sym = normalize_symbol(row.get("symbol"))
            cached_risk = announcement_risks.get(sym) or {}
            if announcement_risk_is_active(cached_risk):
                continue
            result.append({**row, "announcement_risk": None})
            if len(result) >= row_limit:
                break
        return result

    return {
        "raw": visible(raw_sorted, limit),
        "passed": visible(passed_sorted, limit),
        "filtered": visible(filtered_sorted, min(limit, 16)),
    }


def build_ai_buy_candidates(state: dict[str, Any], limit: int = 24) -> list[dict[str, Any]]:
    return build_ai_buy_candidate_sets(state, limit).get("passed", [])


def extract_question_symbols(text: str) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for raw in re.findall(r"(?<!\d)[036]\d{5}(?!\d)", text or ""):
        sym = normalize_symbol(raw)
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    return symbols[:12]


def iter_named_stock_refs(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_name in ("positions",):
        for sym, item in (state.get(source_name) or {}).items():
            if isinstance(item, dict):
                rows.append({"symbol": normalize_symbol(sym), "name": item.get("name", "")})
    for source_name in ("quotes",):
        for sym, item in (state.get(source_name) or {}).items():
            if isinstance(item, dict):
                rows.append({"symbol": normalize_symbol(sym), "name": item.get("name", "")})
    for source_name in ("orders", "trades", "candidates", "strategy_signals", "strategy_watchlist", "ai_buy_candidates"):
        for item in state.get(source_name) or []:
            if isinstance(item, dict):
                rows.append({"symbol": normalize_symbol(item.get("symbol")), "name": item.get("name", "")})
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = normalize_symbol(row.get("symbol"))
        name = str(row.get("name") or "").strip()
        key = (sym, name)
        if not sym or not name or key in seen:
            continue
        seen.add(key)
        out.append({"symbol": sym, "name": name})
    return out


STOCK_SEARCH_CACHE: dict[str, list[dict[str, str]]] = {}


def search_stock_symbols_by_name(keyword: str) -> list[dict[str, str]]:
    kw = re.sub(r"\s+", "", str(keyword or "")).strip()
    if not kw or len(kw) < 2:
        return []
    if kw in STOCK_SEARCH_CACHE:
        return list(STOCK_SEARCH_CACHE[kw])
    params = urllib.parse.urlencode({"input": kw, "type": "14"})
    req = urllib.request.Request(
        f"https://searchapi.eastmoney.com/api/suggest/get?{params}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )
    try:
        payload = json.loads(urllib.request.urlopen(req, timeout=4).read().decode("utf-8", errors="ignore"))
    except Exception:
        STOCK_SEARCH_CACHE[kw] = []
        return []
    rows = []
    for item in ((payload.get("QuotationCodeTable") or {}).get("Data") or []):
        sym = normalize_symbol(item.get("Code") or item.get("UnifiedCode"))
        name = str(item.get("Name") or "").strip()
        classify = str(item.get("Classify") or "")
        if sym and name and classify in ("", "AStock"):
            rows.append({"symbol": sym, "name": name})
    STOCK_SEARCH_CACHE[kw] = rows[:8]
    return list(STOCK_SEARCH_CACHE[kw])


def resolve_question_stock_names(question: str) -> list[str]:
    text = re.sub(r"\s+", "", str(question or ""))
    if not text:
        return []
    candidates: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z]{2,12}", text):
        if token in {"怎么样", "怎么看", "分析一下", "帮我分析", "问一下", "这个票", "这只票", "股票"}:
            continue
        cleaned = re.sub(r"(怎么样|怎么看|分析一下|帮我分析|这只票|这个票|股票)$", "", token)
        if len(cleaned) >= 2 and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates[:4]


def resolve_question_symbols(text: str, state: dict[str, Any]) -> list[str]:
    symbols = extract_question_symbols(text)
    seen = set(symbols)
    question = str(text or "")
    for row in iter_named_stock_refs(state):
        name = str(row.get("name") or "")
        sym = normalize_symbol(row.get("symbol"))
        if sym and name and name in question and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    if not symbols:
        for keyword in resolve_question_stock_names(question):
            for row in search_stock_symbols_by_name(keyword):
                name = str(row.get("name") or "")
                sym = normalize_symbol(row.get("symbol"))
                if sym and name and (keyword in name or name in question) and sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)
                    break
    return symbols[:12]


def latest_buy_record(state: dict[str, Any], sym: str) -> dict[str, Any] | None:
    code = normalize_symbol(sym)
    buys = [
        item for item in ((state.get("orders") or []) + (state.get("trades") or []))
        if normalize_symbol(item.get("symbol")) == code and str(item.get("side") or "").upper() == "BUY"
    ]
    if not buys:
        return None
    return sorted(buys, key=lambda row: str(row.get("time") or ""))[-1]


def latest_decision_for_symbol(state: dict[str, Any], sym: str) -> dict[str, Any] | None:
    code = normalize_symbol(sym)
    fallback: dict[str, Any] | None = None
    for decision in reversed(state.get("decisions") or []):
        orders = [o for o in (decision.get("orders") or []) if normalize_symbol(o.get("symbol")) == code]
        actions = [a for a in (decision.get("actions") or []) if normalize_symbol(a.get("symbol")) == code]
        blocked_orders = [o for o in (decision.get("blocked_orders") or []) if normalize_symbol(o.get("symbol")) == code]
        if not (orders or actions or blocked_orders):
            continue
        row = {
            "time": decision.get("time", ""),
            "summary": decision.get("summary", ""),
            "orders": orders,
            "actions": actions,
            "blocked_orders": blocked_orders,
        }
        if any(str(item.get("side") or item.get("action") or "").upper() == "BUY" for item in actions + orders):
            return row
        if fallback is None:
            fallback = row
    return fallback


def build_purchase_context(state: dict[str, Any], symbols: list[str]) -> list[dict[str, Any]]:
    rows = []
    positions = state.get("positions") or {}
    for sym in symbols:
        code = normalize_symbol(sym)
        buy = latest_buy_record(state, code)
        decision = latest_decision_for_symbol(state, code)
        pos = positions.get(code) or {}
        if not buy and not pos and not decision:
            continue
        rows.append({
            "symbol": code,
            "name": (buy or pos or {}).get("name", ""),
            "buy_time": (buy or {}).get("time", ""),
            "buy_price": to_float((buy or {}).get("price"), 0.0),
            "qty": int(to_float((buy or pos or {}).get("qty"), 0.0)),
            "amount": to_float((buy or {}).get("amount"), 0.0),
            "buy_reason": (buy or {}).get("reason", ""),
            "ai_source": (buy or {}).get("ai_source", ""),
            "position": pos,
            "decision": decision,
        })
    return rows


def asks_for_buy_rationale(question: str) -> bool:
    text = str(question or "")
    return bool(("买" in text or "买入" in text) and any(token in text for token in ("原理", "理由", "依据", "为什么", "逻辑")))


def ask_intent(question: str) -> str:
    text = str(question or "")
    simulation_tokens = (
        "模拟盘", "AI", "ai", "候选池", "为什么不买", "会买吗", "能买吗", "买不买",
        "买入", "卖出", "持仓", "仓位", "止盈", "止损", "做T", "做t", "决策",
    )
    if any(token in text for token in simulation_tokens):
        return "simulation_decision"
    return "stock_analysis"


def build_symbol_ask_context(state: dict[str, Any], symbols: list[str]) -> list[dict[str, Any]]:
    quotes = state.get("quotes") or {}
    strict_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in state.get("strategy_signals") or []
        if normalize_symbol(item.get("symbol"))
    }
    watch_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in state.get("strategy_watchlist") or []
        if normalize_symbol(item.get("symbol"))
    }
    ai_pool = {
        normalize_symbol(item.get("symbol")): item
        for item in build_ai_buy_candidates(state)
        if normalize_symbol(item.get("symbol"))
    }
    rows = []
    for sym in symbols:
        q = quotes.get(sym) or MARKET_QUOTE_CACHE.get(sym) or {}
        ok, guard_reason = ai_buy_guardrail(q, check_announcements=True) if q else (False, "未取到实时行情")
        announcement_risk = announcement_risk_for_symbol(sym)
        if announcement_risk_is_active(announcement_risk):
            ok = False
            guard_reason = str(announcement_risk.get("reason") or guard_reason)
        volume = to_float(q.get("volume"), 0.0)
        amount = to_float(q.get("amount"), 0.0)
        price = to_float(q.get("price"), 0.0)
        vwap = amount / volume if amount > 0 and volume > 0 else 0.0
        ma = position_t_ma_snapshot(sym)
        ma5 = to_float(ma.get("ma5"), 0.0)
        ma10 = to_float(ma.get("ma10"), 0.0)
        ma20 = to_float(ma.get("ma20"), 0.0)
        rows.append({
            "symbol": sym,
            "name": q.get("name", ""),
            "price": price,
            "pct_chg": to_float(q.get("pct_chg"), 0.0),
            "open": to_float(q.get("open"), 0.0),
            "prev_close": to_float(q.get("prev_close"), 0.0),
            "high": to_float(q.get("high"), 0.0),
            "low": to_float(q.get("low"), 0.0),
            "amount": amount,
            "bid1": to_float(q.get("bid1"), 0.0),
            "ask1": to_float(q.get("ask1"), 0.0),
            "vwap": vwap,
            "vwap_deviation_pct": ((price - vwap) / vwap * 100) if price > 0 and vwap > 0 else None,
            "strict_n_shape": sym in strict_symbols,
            "n_shape_watch": sym in watch_symbols,
            "in_ai_buy_pool": sym in ai_pool,
            "ai_pool_source": (ai_pool.get(sym) or {}).get("ai_pool_source", ""),
            "guardrail_ok": ok,
            "guardrail_reason": guard_reason,
            "announcement_risk": announcement_risk if announcement_risk_is_active(announcement_risk) else None,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma20_deviation_pct": ((price - ma20) / ma20 * 100) if price > 0 and ma20 > 0 else None,
            "trend_note": ("MA5>MA10>MA20" if ma5 > ma10 > ma20 > 0 else ("均线多头不足" if ma.get("ok") else "日线不足")),
            "quote_time": q.get("quote_time", ""),
        })
    return rows


def ask_analysis_steps(symbol_context: list[dict[str, Any]], account: dict[str, Any] | None = None, purchase_context: list[dict[str, Any]] | None = None, intent: str = "stock_analysis") -> list[dict[str, str]]:
    account = account or {}
    purchase_context = purchase_context or []
    steps: list[dict[str, str]] = []
    if intent == "simulation_decision":
        position_count = len(account.get("positions") or [])
        steps.append({
            "title": "账户/系统约束",
            "detail": f"当前持仓{position_count}/{MAX_POSITIONS}，可用仓位{max(0, MAX_POSITIONS - position_count)}；问股只分析，不下单。",
        })
    if purchase_context:
        buy = purchase_context[0]
        steps.append({
            "title": "真实成交",
            "detail": f"最近买入记录：{buy.get('buy_time') or '未知时间'}，价格{to_float(buy.get('buy_price'), 0.0):.2f}，数量{buy.get('qty') or 0}股。",
        })
    for row in symbol_context:
        pool = "AI可买池" if row.get("in_ai_buy_pool") else ("N字观察池" if row.get("n_shape_watch") else ("严格N字池" if row.get("strict_n_shape") else "池外"))
        if intent == "simulation_decision":
            steps.append({
                "title": f"{row.get('symbol')} 系统状态",
                "detail": f"{pool}；ai_pool_source={row.get('ai_pool_source') or '无'}；{'硬风控通过' if row.get('guardrail_ok') else '硬风控未过：' + str(row.get('guardrail_reason') or '未知')}。",
            })
        steps.extend([
            {
                "title": "行情位置",
                "detail": f"现价{to_float(row.get('price'), 0.0):.2f}，涨幅{to_float(row.get('pct_chg'), 0.0):+.2f}%，开盘{to_float(row.get('open'), 0.0):.2f}，高低{to_float(row.get('high'), 0.0):.2f}/{to_float(row.get('low'), 0.0):.2f}，VWAP偏离{to_float(row.get('vwap_deviation_pct'), 0.0):+.2f}%。",
            },
            {
                "title": "趋势结构",
                "detail": f"{row.get('trend_note') or '趋势未知'}；MA5/10/20={to_float(row.get('ma5'), 0.0):.2f}/{to_float(row.get('ma10'), 0.0):.2f}/{to_float(row.get('ma20'), 0.0):.2f}，离MA20 {to_float(row.get('ma20_deviation_pct'), 0.0):+.2f}%。",
            },
            {
                "title": "风险点",
                "detail": f"公告/风控：{row.get('guardrail_reason') or '未发现硬拦截'}。系统池状态仅供参考：{pool}。",
            },
        ])
    return steps[:10]


def local_ai_ask_answer(question: str, state: dict[str, Any]) -> dict[str, Any]:
    symbols = resolve_question_symbols(question, state)
    purchase_context = build_purchase_context(state, symbols)
    account = account_snapshot(state)
    intent = ask_intent(question)
    if not symbols:
        symbol_context: list[dict[str, Any]] = []
        answer = (
            "你可以直接问股票名称或 6 位代码。当前我能读取账户、持仓、真实成交原因、N字诊断、AI候选池和实时行情；"
            "这个入口只做分析，不会下单。"
        )
    elif asks_for_buy_rationale(question) and purchase_context:
        symbol_context = []
        parts = []
        for buy in purchase_context:
            pos = buy.get("position") or {}
            held_text = "当前仍持有" if pos else "当前已不在持仓"
            parts.append(
                f"{buy.get('symbol')} {buy.get('name') or ''} 的真实买入记录是："
                f"{buy.get('buy_time') or '未知时间'}，{buy.get('qty') or 0}股，成交价{buy.get('buy_price'):.2f}，"
                f"金额{buy.get('amount'):.2f}，来源{buy.get('ai_source') or '未知'}。"
                f"当时买入理由：{buy.get('buy_reason') or '订单未记录理由'}。"
                f"{held_text}。"
            )
        answer = " ".join(parts)
    else:
        symbol_context = build_symbol_ask_context(state, symbols)
        ai_pool = build_ai_buy_candidates(state)
        parts = []
        for row in symbol_context:
            if intent == "simulation_decision":
                pool_text = "在AI候选池" if row.get("in_ai_buy_pool") else "不在AI候选池"
                guard_text = "硬风控通过" if row.get("guardrail_ok") else f"硬风控未过：{row.get('guardrail_reason')}"
                n_text = "严格N字" if row.get("strict_n_shape") else ("N字观察" if row.get("n_shape_watch") else "非N字池")
                parts.append(
                    f"{row.get('symbol')} {row.get('name') or ''}：现价{row.get('price'):.2f}，"
                    f"涨幅{row.get('pct_chg'):.2f}%，{n_text}，{pool_text}，{guard_text}。"
                )
            else:
                parts.append(
                    f"{row.get('symbol')} {row.get('name') or ''}：现价{row.get('price'):.2f}，"
                    f"涨幅{row.get('pct_chg'):.2f}%，VWAP偏离{to_float(row.get('vwap_deviation_pct'), 0.0):+.2f}%，"
                    f"{row.get('trend_note') or '趋势未知'}，离MA20 {to_float(row.get('ma20_deviation_pct'), 0.0):+.2f}%。"
                )
        suffix = f" 当前AI买入池共{len(ai_pool)}只；这里只解释，不触发模拟买卖。" if intent == "simulation_decision" else " 这是股票本身分析；若你要问模拟盘会不会买，可以直接问“模拟盘会买吗”。"
        answer = " ".join(parts) + suffix
    return {
        "source": "local",
        "answer": answer,
        "symbols": symbols,
        "symbol_context": symbol_context,
        "purchase_context": purchase_context,
        "analysis_steps": ask_analysis_steps(symbol_context, account, purchase_context, intent),
        "ask_intent": intent,
        "verdict": "信息不足" if not symbols else "观察",
        "risk_points": [],
    }


def build_ai_ask_context(state: dict[str, Any], question: str, symbols: list[str], symbol_context: list[dict[str, Any]], purchase_context: list[dict[str, Any]]) -> dict[str, Any]:
    current = market_clock()
    intent = ask_intent(question)
    account = account_snapshot(state)
    positions = account.get("positions") or []
    ai_pool = build_ai_buy_candidates(state)
    position_count = len(positions)
    ctx = {
        "question": question,
        "ask_intent": intent,
        "asked_symbols": symbol_context,
        "purchase_context": purchase_context,
        "market_session": market_status(current)[2],
    }
    if intent != "simulation_decision":
        ctx["instruction"] = "用户在问股票本身怎么样，优先分析行情位置、趋势结构、VWAP/均线、公告/风险；不要把账户满仓或候选池状态放在首要结论。"
        ctx["system_reference"] = {
            "note": "仅当用户追问模拟盘是否会买时再展开。",
            "asked_symbol_pool_state": [
                {
                    "symbol": row.get("symbol"),
                    "in_ai_buy_pool": row.get("in_ai_buy_pool"),
                    "strict_n_shape": row.get("strict_n_shape"),
                    "n_shape_watch": row.get("n_shape_watch"),
                    "guardrail_ok": row.get("guardrail_ok"),
                    "guardrail_reason": row.get("guardrail_reason"),
                }
                for row in symbol_context
            ],
        }
        return ctx
    ctx.update({
        "account_constraints": {
            "position_count": position_count,
            "max_positions": MAX_POSITIONS,
            "available_position_slots": max(0, MAX_POSITIONS - position_count),
            "cash": account.get("cash"),
            "t_plus_1": True,
        },
        "positions": [
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "qty": row.get("qty"),
                "last_price": row.get("last_price"),
                "pnl": row.get("pnl"),
                "pnl_pct": row.get("pnl_pct"),
                "pct_chg": row.get("pct_chg"),
            }
            for row in positions
        ],
        "ai_buy_candidates": [
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "score": row.get("score"),
                "pct_chg": row.get("pct_chg"),
                "ai_pool_source": row.get("ai_pool_source"),
                "buy_timing_score": row.get("buy_timing_score"),
                "risk_tags": row.get("risk_tags") or [],
            }
            for row in ai_pool[:10]
        ],
    })
    return ctx


def deepseek_ai_ask(question: str, state: dict[str, Any]) -> dict[str, Any] | None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    symbols = resolve_question_symbols(question, state)
    symbol_context = build_symbol_ask_context(state, symbols)
    purchase_context = build_purchase_context(state, symbols)
    ask_context = build_ai_ask_context(state, question, symbols, symbol_context, purchase_context)
    prompt = (
        "你是A股模拟盘的问股分析助手。只能输出json，不能编造价格，不能输出订单，不能建议系统自动买入或卖出，"
        "也不能绕过上下文里的AI候选池和硬风控。先判断ask_intent：如果是stock_analysis，优先分析股票本身，"
        "包括行情位置、趋势结构、VWAP/均线、公告/风控风险，不要把账户约束/候选池作为首要分析；如果是simulation_decision，再解释模拟盘候选池、持仓和仓位。"
        "若股票不在ai_buy_candidates里，只有在simulation_decision语境下才强调模拟盘当前不会买它。"
        "当上下文包含account_constraints时，必须以account_constraints.available_position_slots作为仓位事实；如果为0，只能说总持仓已满/无可用仓位，"
        "禁止表述为交易教练限制今日新开仓为0只或今日不再新买。交易教练只收紧候选质量，不限制日内买入次数；只要总持仓不满5只就允许开到5只。"
        "如果用户问“如果持仓不满/如果有仓位会买哪个”，必须先说明真实状态，再基于ai_buy_candidates给出假设候选；"
        "假设候选必须排除当前positions里已经持有的股票，并说明候选来源、评分、主要风险。"
        "如果用户问买入原理、买入理由或为什么买，必须优先引用purchase_context里的真实buy_reason、buy_time、buy_price，"
        "并明确区分“当时买入理由”和“当前行情/候选池状态”；禁止用当前候选池评分冒充当时买入依据。"
        "如果asked_symbols为空，不要猜股票；要求用户补充名称或代码。"
        "你不能输出隐藏思维链，但必须输出可验证的analysis_steps，每一步只写使用了哪些上下文字段和得到的中间判断。"
        "analysis_steps在stock_analysis时建议包含：行情位置/VWAP、趋势结构/均线、公告/风控风险、买点风险、结论；在simulation_decision时再加入账户约束和候选池状态。"
        "格式：{\"answer\":\"...\",\"symbols\":[\"000001\"],\"verdict\":\"观察|不追|可继续盯|持有|止盈|止损|信息不足\","
        "\"analysis_steps\":[{\"title\":\"候选池状态\",\"detail\":\"...\"}],\"risk_points\":[\"...\"]}。上下文："
        f"{json.dumps(ask_context, ensure_ascii=False)}"
    )
    body = llm_chat_body(
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        prompt,
        temperature=0.2,
        max_tokens=900,
    )
    try:
        payload = llm_post_json(
            body,
            key,
            timeout=max(20.0, float(os.environ.get("DEEPSEEK_ASK_TIMEOUT", "45"))),
            retries=max(1, int(os.environ.get("DEEPSEEK_ASK_RETRIES", str(LLM_RETRIES)))),
        )
        text = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        try:
            result = parse_model_json_object(text)
        except Exception:
            if not text:
                raise
            result = {"answer": text, "symbols": symbols, "verdict": "观察", "risk_points": ["模型未按JSON格式返回，已按纯文本展示。"]}
        return {
            "source": AI_PROVIDER_LABEL,
            "answer": str(result.get("answer") or "").strip(),
            "symbols": [normalize_symbol(x) for x in (result.get("symbols") or symbols) if normalize_symbol(x)],
            "symbol_context": symbol_context,
            "purchase_context": purchase_context,
            "analysis_steps": [
                {"title": str((item or {}).get("title") or "分析"), "detail": str((item or {}).get("detail") or "")}
                for item in (result.get("analysis_steps") or [])
                if isinstance(item, dict)
            ][:10] or ask_analysis_steps(symbol_context, account_snapshot(state), purchase_context, ask_intent(question)),
            "ask_intent": ask_intent(question),
            "verdict": str(result.get("verdict") or "观察"),
            "risk_points": [str(x) for x in (result.get("risk_points") or [])][:6],
        }
    except Exception as exc:
        RUNTIME["deepseek_last_error"] = llm_error_summary(exc)
        return None


def is_same_trade_day(opened_at: str | None, now: datetime | None = None) -> bool:
    if not opened_at:
        return False
    try:
        return datetime.fromisoformat(opened_at).date() == market_clock(now).date()
    except Exception:
        return False


def sellable_position_symbols(state: dict[str, Any], now: datetime | None = None) -> list[str]:
    current = market_clock(now)
    symbols = []
    for sym, pos in (state.get("positions") or {}).items():
        code = normalize_symbol(sym)
        if not code or int(pos.get("qty") or 0) <= 0:
            continue
        if not is_same_trade_day(pos.get("opened_at"), current):
            symbols.append(code)
    return symbols


def no_sellable_position_buy_locked(state: dict[str, Any], now: datetime | None = None) -> bool:
    positions = state.get("positions") or {}
    active_position_count = len([
        normalize_symbol(sym)
        for sym, pos in positions.items()
        if normalize_symbol(sym) and int(pos.get("qty") or 0) > 0
    ])
    return active_position_count >= MAX_POSITIONS and not sellable_position_symbols(state, now)


def is_early_sell_observe_time(now: datetime | None = None) -> bool:
    current = market_clock(now)
    if not is_market_day(current):
        return False
    return dt_time(9, 30) <= current.time() <= EARLY_SELL_OBSERVE_END


def quote_vwap(q: dict[str, Any]) -> float:
    volume = to_float(q.get("volume"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    return amount / volume if amount > 0 and volume > 0 else 0.0


def early_sell_metrics(pos: dict[str, Any], q: dict[str, Any]) -> dict[str, float]:
    price = to_float(q.get("price"), to_float(pos.get("last_price"), 0.0))
    day_pct = to_float(q.get("pct_chg"), 0.0)
    open_price = to_float(q.get("open"), 0.0)
    vwap = quote_vwap(q)
    return {
        "pnl_pct": to_float(pos.get("pnl_pct"), 0.0),
        "price": price,
        "day_pct": day_pct,
        "open_ext": (price - open_price) / open_price if price > 0 and open_price > 0 else 0.0,
        "vwap_ext": (price - vwap) / vwap if price > 0 and vwap > 0 else 0.0,
    }


def early_sell_emergency_allowed(pos: dict[str, Any], q: dict[str, Any]) -> tuple[bool, list[str]]:
    metrics = early_sell_metrics(pos, q)
    pnl_pct = metrics["pnl_pct"]
    day_pct = metrics["day_pct"]
    open_ext = metrics["open_ext"]
    vwap_ext = metrics["vwap_ext"]
    reasons = [
        f"浮亏{pnl_pct:+.2%}",
        f"今日涨跌{day_pct:+.2f}%",
        f"相对开盘{open_ext:+.2%}",
        f"相对VWAP{vwap_ext:+.2%}",
    ]
    if pnl_pct <= EARLY_SELL_EMERGENCY_LOSS_PCT:
        reasons.append("达到早盘极端浮亏阈值")
        return True, reasons
    if (
        day_pct <= EARLY_SELL_EMERGENCY_DAY_PCT
        and open_ext <= EARLY_SELL_EMERGENCY_OPEN_EXT
        and vwap_ext <= EARLY_SELL_EMERGENCY_VWAP_EXT
    ):
        reasons.append("接近跌停且跌破开盘/VWAP，允许紧急风控")
        return True, reasons
    return False, reasons


def early_sell_observe_status(pos: dict[str, Any], q: dict[str, Any], *, is_core_candidate: bool, now: datetime | None = None) -> tuple[bool, list[str]]:
    if not is_early_sell_observe_time(now):
        return False, []
    metrics = early_sell_metrics(pos, q)
    pnl_pct = metrics["pnl_pct"]
    day_pct = metrics["day_pct"]
    open_ext = metrics["open_ext"]
    vwap_ext = metrics["vwap_ext"]
    if pnl_pct > -0.03 and day_pct > -3.0:
        return False, []
    emergency_allowed, emergency_reasons = early_sell_emergency_allowed(pos, q)
    reasons = [
        f"早盘{EARLY_SELL_OBSERVE_END.strftime('%H:%M')}前修复观察",
        f"浮亏{pnl_pct:+.2%}",
    ]
    if is_core_candidate:
        reasons.append("仍属N字/热门候选或当前强票池")
    if metrics["open_ext"]:
        reasons.append(f"相对开盘{open_ext:+.2%}")
    if metrics["vwap_ext"]:
        reasons.append(f"相对VWAP{vwap_ext:+.2%}")
    if day_pct:
        reasons.append(f"今日涨跌{day_pct:+.2f}%")
    if emergency_allowed:
        reasons.extend(emergency_reasons)
        return False, reasons
    should_observe = True
    return should_observe, reasons


def early_sell_block_reason(pos: dict[str, Any], q: dict[str, Any], now: datetime | None = None) -> str:
    if not is_early_sell_observe_time(now):
        return ""
    allowed, reasons = early_sell_emergency_allowed(pos, q)
    if allowed:
        return ""
    return f"早盘{EARLY_SELL_OBSERVE_END.strftime('%H:%M')}前禁止急杀止损，等待修复确认；" + "，".join(reasons)


def no_sellable_guard_plan(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    position_count = len([
        1
        for pos in (state.get("positions") or {}).values()
        if int(pos.get("qty") or 0) > 0
    ])
    return {
        "source": "no_sellable_guard",
        "summary": f"当前持仓已满{position_count}/{MAX_POSITIONS}且当日没有可卖仓位，AI选股/买入已暂停；仅刷新行情，等待出现可卖仓位后再恢复。",
        "orders": [],
    }


def local_ai_plan(state: dict[str, Any]) -> dict[str, Any]:
    account = account_snapshot(state)
    positions = {p["symbol"]: p for p in account["positions"]}
    core_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in (
            (state.get("strategy_signals") or [])
            + (state.get("strategy_watchlist") or [])
            + (state.get("right_side_watchlist") or [])
            + build_ai_buy_candidates(state)
        )
        if normalize_symbol(item.get("symbol"))
    }
    orders = []
    # Risk exits first.
    for sym, pos in positions.items():
        if is_same_trade_day(pos.get("opened_at")):
            continue
        pnl_pct = to_float(pos.get("pnl_pct"), 0.0)
        q = (state.get("quotes") or {}).get(sym) or {}
        pct = to_float(q.get("pct_chg"), 0.0)
        early_observe, early_reasons = early_sell_observe_status(pos, q, is_core_candidate=sym in core_symbols)
        if early_observe:
            continue
        if pnl_pct <= -0.05 or pnl_pct >= 0.08 or pct <= -4:
            reason = f"风控卖出 pnl={pnl_pct:.2%} pct={pct:.2f}%"
            if early_reasons:
                reason += "；" + "，".join(early_reasons)
            orders.append({"action": "SELL", "symbol": sym, "qty": int(pos.get("qty") or 0), "style": "aggressive", "reason": reason})
    if len(positions) >= MAX_POSITIONS:
        return {"source": "local_guardrail", "summary": "持仓已满，仅做风控检查", "orders": orders}
    if AI_BUY_MODE == "off":
        return {"source": "local_guardrail", "summary": "AI买入关闭：本地AI只做持仓风控。", "orders": orders}
    if no_sellable_position_buy_locked(state):
        return no_sellable_guard_plan(state)
    buy_pool = build_ai_buy_candidates(state) if AI_BUY_MODE == "ai_guided" else ((state.get("strategy_watchlist") or state.get("strategy_signals") or []) if AI_BUY_MODE == "n_shape_only" else state.get("candidates", []))
    for c in buy_pool[:5]:
        sym = c.get("symbol")
        if sym in positions:
            continue
        if to_float(c.get("score"), 0.0) >= 58 and -2 <= to_float(c.get("pct_chg"), 0.0) <= 8.5:
            source_label = c.get("ai_pool_source") or ("N字候选" if AI_BUY_MODE == "n_shape_only" else "候选池")
            orders.append({"action": "BUY", "symbol": sym, "budget_cash": PER_POSITION_CASH, "style": "aggressive", "reason": f"{source_label}分 {c.get('score')}，涨跌幅 {c.get('pct_chg')}%"})
            break
    return {"source": "local_guardrail", "summary": "本地AI规则完成一轮盘中检查", "orders": orders}


def is_morning_rebound_time(now: datetime | None = None) -> bool:
    current = market_clock(now)
    if not is_market_day(current):
        return False
    return dt_time(9, 31) <= current.time() <= MORNING_REBOUND_END


def is_mainboard_strategy_symbol(sym: str) -> bool:
    code = normalize_symbol(sym)
    return code.startswith(("000", "001", "002", "003", "004", "005", "600", "601", "603", "605"))


def quote_spread_pct(q: dict[str, Any]) -> float:
    price = to_float(q.get("price"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    return (ask - bid) / price * 100 if ask > 0 and bid > 0 and price > 0 else 9.9


def n_shape_live_reject_reason(q: dict[str, Any]) -> str:
    sym = normalize_symbol(q.get("symbol"))
    if not is_mainboard_strategy_symbol(sym):
        return "非主板/不在策略范围"
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    if min(price, day_open, prev_close) <= 0:
        return "实时行情无效"
    open_chg = day_open / prev_close - 1.0
    if not (N_SHAPE_OPEN_CHG_MIN < open_chg < N_SHAPE_OPEN_CHG_MAX):
        return "开盘不在原策略窗口"
    now_ret = price / day_open - 1.0
    if now_ret < N_SHAPE_TRIGGER_PCT:
        return "尚未达到开盘突破阈值"
    if now_ret > MORNING_REBOUND_MAX_OPEN_EXT:
        return "相对开盘涨太多"
    if to_float(q.get("pct_chg"), 0.0) > MORNING_REBOUND_MAX_PCT_CHG:
        return "当前涨幅过高"
    if amount < N_SHAPE_MIN_AMOUNT:
        return "成交额不足"
    if quote_spread_pct(q) > N_SHAPE_MAX_SPREAD_PCT:
        return "盘口价差过大"
    return "通过"


def n_shape_watch_source_reject_reason(q: dict[str, Any]) -> str:
    sym = normalize_symbol(q.get("symbol"))
    if not is_mainboard_strategy_symbol(sym):
        return "非主板/不在策略范围"
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return "实时行情无效"
    open_chg = day_open / prev_close - 1.0
    if not (N_SHAPE_WATCH_OPEN_CHG_MIN < open_chg < N_SHAPE_WATCH_OPEN_CHG_MAX):
        return "观察池开盘偏离过大"
    now_ret = price / day_open - 1.0
    high_ret = high / day_open - 1.0
    if now_ret < N_SHAPE_WATCH_MIN_OPEN_GAIN and high_ret < 0.008:
        return "观察池尚未走强"
    if now_ret > N_SHAPE_WATCH_MAX_OPEN_GAIN:
        return "观察池相对开盘涨太多"
    if to_float(q.get("pct_chg"), 0.0) > current_ai_guard_max_pct_chg():
        return "当前涨幅过高"
    if amount < N_SHAPE_MIN_AMOUNT:
        return "成交额不足"
    if quote_spread_pct(q) > N_SHAPE_MAX_SPREAD_PCT:
        return "盘口价差过大"
    return "通过"


def merged_quote_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    sources = [
        state.get("candidates") or [],
        list(MARKET_QUOTE_CACHE.values()),
        list((state.get("quotes") or {}).values()),
    ]
    for source in sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            sym = normalize_symbol(item.get("symbol"))
            if sym:
                merged[sym] = {**merged.get(sym, {}), **item}
    return list(merged.values())


def merged_quote_rows_for_n_shape(state: dict[str, Any]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float, float]:
        day_open = to_float(row.get("open"), 0.0)
        price = to_float(row.get("price"), 0.0)
        prev_close = to_float(row.get("prev_close"), 0.0)
        open_chg = day_open / prev_close - 1.0 if prev_close > 0 and day_open > 0 else 9.9
        now_ret = price / day_open - 1.0 if day_open > 0 and price > 0 else 9.9
        amount = to_float(row.get("amount"), 0.0)
        return (abs(now_ret - N_SHAPE_TRIGGER_PCT), abs(open_chg + 0.006), -amount)

    candidates = [row for row in merged_quote_rows(state) if n_shape_watch_source_reject_reason(row) == "通过"]
    return sorted(candidates, key=sort_key)[:N_SHAPE_SOURCE_SCAN_LIMIT]


def right_side_live_reject_reason(q: dict[str, Any]) -> str:
    sym = normalize_symbol(q.get("symbol"))
    if not is_mainboard_strategy_symbol(sym):
        return "非主板/不在策略范围"
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return "实时行情无效"
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    open_gain = price / day_open - 1.0
    if pct_chg < RIGHT_SIDE_MIN_PCT_CHG:
        return "右侧强度不足"
    if amount < RIGHT_SIDE_MIN_AMOUNT:
        return "成交额不足"
    if quote_spread_pct(q) > N_SHAPE_MAX_SPREAD_PCT:
        return "盘口价差过大"
    return "通过"


def merged_quote_rows_for_right_side(state: dict[str, Any]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float]:
        pct_chg = to_float(row.get("pct_chg"), 0.0)
        amount = to_float(row.get("amount"), 0.0)
        return (-pct_chg, -amount)

    candidates = [row for row in merged_quote_rows(state) if right_side_live_reject_reason(row) == "通过"]
    return sorted(candidates, key=sort_key)[:RIGHT_SIDE_SOURCE_SCAN_LIMIT]


def market_leader_heat(q: dict[str, Any]) -> dict[str, Any]:
    sym = normalize_symbol(q.get("symbol"))
    rows = []
    for row in MARKET_QUOTE_CACHE.values():
        item_sym = normalize_symbol(row.get("symbol"))
        if not item_sym or not is_mainboard_strategy_symbol(item_sym):
            continue
        if quote_age_seconds(row) > 900:
            continue
        amount = to_float(row.get("amount"), 0.0)
        price = to_float(row.get("price"), 0.0)
        if amount <= 0 or price <= 0:
            continue
        rows.append(row)
    amount_rank = 9999
    pct_rank = 9999
    amount_sorted = sorted(rows, key=lambda row: to_float(row.get("amount"), 0.0), reverse=True)
    pct_sorted = sorted(rows, key=lambda row: to_float(row.get("pct_chg"), -99.0), reverse=True)
    for idx, row in enumerate(amount_sorted, 1):
        if normalize_symbol(row.get("symbol")) == sym:
            amount_rank = idx
            break
    for idx, row in enumerate(pct_sorted, 1):
        if normalize_symbol(row.get("symbol")) == sym:
            pct_rank = idx
            break
    amount = to_float(q.get("amount"), 0.0)
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    amount_score = max(0.0, 30.0 - max(0, amount_rank - 1) * 30.0 / max(1, LEADER_TOP_AMOUNT_RANK))
    pct_rank_score = max(0.0, 22.0 - max(0, pct_rank - 1) * 22.0 / max(1, LEADER_TOP_PCT_RANK))
    amount_abs_score = min(18.0, amount / 1e8 * 3.2)
    pct_abs_score = min(18.0, max(0.0, pct_chg) * 2.4)
    heat_score = amount_score + pct_rank_score + amount_abs_score + pct_abs_score
    return {
        "market_heat_score": round(heat_score, 2),
        "amount_rank": amount_rank,
        "pct_rank": pct_rank,
        "market_scan_count": len(rows),
        "is_hot_amount": amount >= LEADER_MIN_AMOUNT or amount_rank <= LEADER_TOP_AMOUNT_RANK,
        "is_hot_pct": pct_rank <= LEADER_TOP_PCT_RANK or pct_chg >= 3.0,
    }


def ranked_market_leader_heat(
    q: dict[str, Any],
    *,
    amount_rank: int,
    pct_rank: int,
    scan_count: int,
) -> dict[str, Any]:
    amount = to_float(q.get("amount"), 0.0)
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    amount_score = max(0.0, 30.0 - max(0, amount_rank - 1) * 30.0 / max(1, LEADER_TOP_AMOUNT_RANK))
    pct_rank_score = max(0.0, 22.0 - max(0, pct_rank - 1) * 22.0 / max(1, LEADER_TOP_PCT_RANK))
    amount_abs_score = min(18.0, amount / 1e8 * 3.2)
    pct_abs_score = min(18.0, max(0.0, pct_chg) * 2.4)
    heat_score = amount_score + pct_rank_score + amount_abs_score + pct_abs_score
    return {
        "market_heat_score": round(heat_score, 2),
        "amount_rank": amount_rank,
        "pct_rank": pct_rank,
        "market_scan_count": scan_count,
        "is_hot_amount": amount >= LEADER_MIN_AMOUNT or amount_rank <= LEADER_TOP_AMOUNT_RANK,
        "is_hot_pct": pct_rank <= LEADER_TOP_PCT_RANK or pct_chg >= 3.0,
    }


def is_slow_bluechip_name(name: str) -> bool:
    text = str(name or "")
    return any(keyword and keyword in text for keyword in LEADER_AVOID_KEYWORDS)


def live_leader_profile(q: dict[str, Any], heat: dict[str, Any] | None = None, reason: str = "日线数据不足") -> dict[str, Any] | None:
    sym = normalize_symbol(q.get("symbol"))
    name = str(q.get("name") or "")
    if not sym or is_slow_bluechip_name(name):
        return None
    heat = heat or market_leader_heat(q)
    heat_score = to_float(heat.get("market_heat_score"), 0.0)
    if heat_score < LEADER_LIVE_MIN_HEAT_SCORE:
        return None
    if not (bool(heat.get("is_hot_amount")) and bool(heat.get("is_hot_pct"))):
        return None
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    volume = to_float(q.get("volume"), 0.0)
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return None
    open_gain = price / day_open - 1.0 if day_open > 0 else 9.9
    vwap = amount / volume if amount > 0 and volume > 0 else 0.0
    vwap_deviation = price / vwap - 1.0 if price > 0 and vwap > 0 else float("nan")
    score = min(88.0, 52.0 + heat_score / 2.2 + min(8.0, max(0.0, pct_chg - 1.0) * 2.2))
    risk_tags = [reason, "仅盘中热度观察"]
    if open_gain > RIGHT_SIDE_MAX_OPEN_GAIN:
        risk_tags.append("相对开盘偏高")
    if math.isfinite(vwap_deviation) and vwap_deviation > RIGHT_SIDE_MAX_VWAP_EXT:
        risk_tags.append("离VWAP偏远")
    return {
        "symbol": sym,
        "name": name,
        "price": price,
        "open": day_open,
        "prev_close": prev_close,
        "high": high,
        "pct_chg": pct_chg,
        "amount": amount,
        "bid1": to_float(q.get("bid1"), 0.0),
        "ask1": to_float(q.get("ask1"), 0.0),
        "score": round(max(0.0, min(88.0, score)), 2),
        "score_basis": "live_market_leader_heat",
        "strategy_style": "热门龙头观察",
        "right_side_watch": True,
        **heat,
        "relative_open_gain": round(open_gain, 4),
        "vwap": round(vwap, 3) if vwap > 0 else None,
        "vwap_deviation": round(vwap_deviation, 4) if math.isfinite(vwap_deviation) else None,
        "risk_tags": risk_tags[:5],
        "reason": "；".join([
            f"热门龙头观察：热度{heat_score:.1f}，成交额排名{heat.get('amount_rank')}，涨幅排名{heat.get('pct_rank')}",
            f"现涨{pct_chg:+.2f}%，成交额{amount / 1e8:.2f}亿",
            f"相对开盘{open_gain:+.2%}",
            f"离VWAP{vwap_deviation:+.2%}" if math.isfinite(vwap_deviation) else "VWAP暂缺",
            reason,
        ]),
        "time": now_iso(),
    }


def right_side_strength_profile(q: dict[str, Any]) -> dict[str, Any] | None:
    if not RIGHT_SIDE_ENABLED:
        return None
    sym = normalize_symbol(q.get("symbol"))
    if right_side_live_reject_reason(q) != "通过":
        return None
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    volume = to_float(q.get("volume"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    open_gain = price / day_open - 1.0 if day_open > 0 else 9.9
    bars = fetch_sina_daily_bars(sym, 90)
    heat = market_leader_heat(q)
    if len(bars) < 45:
        return live_leader_profile(q, heat, "日线数据不足，先按盘中热度入池")
    closes = [bar["close"] for bar in bars]
    highs = [bar["high"] for bar in bars]
    lows = [bar["low"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    ma5 = mean(closes[-5:])
    ma10 = mean(closes[-10:])
    ma20 = mean(closes[-20:])
    prev_ma5 = mean(closes[-6:-1])
    prev_ma10 = mean(closes[-11:-1])
    prev_ma20 = mean(closes[-21:-1])
    if not all(math.isfinite(v) and v > 0 for v in (ma5, ma10, ma20, prev_ma5, prev_ma10, prev_ma20)):
        return None
    ma5_ext = price / ma5 - 1.0
    ma10_ext = price / ma10 - 1.0
    vwap = amount / volume if amount > 0 and volume > 0 else 0.0
    vwap_deviation = price / vwap - 1.0 if price > 0 and vwap > 0 else float("nan")
    if price < ma5:
        return None
    if ma5 < ma10 or ma10 < ma20 * 0.995:
        return None
    if ma5 <= prev_ma5 or ma10 <= prev_ma10:
        return None
    if ma5_ext > RIGHT_SIDE_MAX_MA5_EXT:
        return None
    if is_slow_bluechip_name(str(q.get("name") or "")):
        return None
    heat_score = to_float(heat.get("market_heat_score"), 0.0)
    if heat_score < LEADER_MIN_HEAT_SCORE:
        return None
    recent_high_5 = max(highs[-5:])
    recent_high_10 = max(highs[-10:])
    recent_high_20 = max(highs[-20:])
    recent_low_5 = min(lows[-5:])
    prev_low_5 = min(lows[-10:-5])
    close_5_ago = closes[-5]
    close_20_ago = closes[-20]
    close_60_ago = closes[-60] if len(closes) >= 60 else closes[0]
    rel_5d = closes[-1] / close_5_ago - 1.0 if close_5_ago > 0 else 0.0
    rel_20d = price / close_20_ago - 1.0 if close_20_ago > 0 else 0.0
    rel_60d = price / close_60_ago - 1.0 if close_60_ago > 0 else 0.0
    ma20_slope = ma20 / prev_ma20 - 1.0 if prev_ma20 > 0 else 0.0
    today_breakout = high >= recent_high_5 * 0.998 or price >= recent_high_5 * 0.992
    near_20d_high = price >= recent_high_20 * (1.0 - RIGHT_SIDE_MAX_20D_HIGH_GAP)
    momentum_ok = (
        rel_20d >= RIGHT_SIDE_MIN_20D_RETURN
        or rel_60d >= RIGHT_SIDE_MIN_60D_RETURN
        or (near_20d_high and ma20_slope >= RIGHT_SIDE_MIN_MA20_SLOPE)
    )
    if not momentum_ok:
        return None
    leader_ok = bool(heat.get("is_hot_amount")) and (
        bool(heat.get("is_hot_pct"))
        or near_20d_high
        or rel_20d >= RIGHT_SIDE_MIN_20D_RETURN
        or rel_60d >= RIGHT_SIDE_MIN_60D_RETURN
    )
    if not leader_ok:
        return None
    higher_low = recent_low_5 >= prev_low_5 * 0.99
    near_high = price / high - 1.0 if high > 0 else -9.9
    avg_vol_10 = mean(volumes[-10:])
    vol_ratio = to_float(q.get("volume"), 0.0) / avg_vol_10 if avg_vol_10 and math.isfinite(avg_vol_10) and avg_vol_10 > 0 else float("nan")
    yesterday_limit_up = approx_limit_up(bars[-2]["close"], bars[-1]["close"])
    score = 58.0
    score += min(12.0, max(0.0, ma5_ext) * 420.0)
    score += min(8.0, max(0.0, ma10_ext) * 160.0)
    score += 8.0 if today_breakout else 0.0
    score += 10.0 if near_20d_high else 0.0
    score += 6.0 if higher_low else 0.0
    score += min(12.0, max(0.0, rel_20d - RIGHT_SIDE_MIN_20D_RETURN) * 90.0)
    score += min(8.0, max(0.0, rel_60d - RIGHT_SIDE_MIN_60D_RETURN) * 45.0)
    score += min(6.0, max(0.0, ma20_slope) * 180.0)
    score += min(16.0, heat_score / 5.0)
    score += max(0.0, 8.0 - abs(pct_chg - 1.8) * 2.5)
    score += max(0.0, 5.0 - max(0.0, open_gain - 0.012) * 180.0)
    score += min(3.0, amount / 1e9)
    if math.isfinite(vol_ratio):
        score += min(3.0, max(0.0, vol_ratio - 0.8) * 1.6)
    score -= max(0.0, ma5_ext - 0.025) * 220.0
    if math.isfinite(vwap_deviation):
        score -= max(0.0, vwap_deviation - 0.018) * 160.0
    score -= max(0.0, pct_chg - 2.8) * 4.0
    if yesterday_limit_up:
        score -= 10.0
    risk_tags = []
    if pct_chg > 2.8:
        risk_tags.append("接近右侧追高区")
    if ma5_ext > 0.025:
        risk_tags.append("离MA5偏远")
    if math.isfinite(vwap_deviation) and vwap_deviation > 0.022:
        risk_tags.append("离VWAP偏远")
    if open_gain > 0.018:
        risk_tags.append("相对开盘偏高")
    if yesterday_limit_up:
        risk_tags.append("昨日涨停溢价，不按右侧核心加分")
    if not heat.get("is_hot_amount"):
        risk_tags.append("成交额热度不足")
    if not heat.get("is_hot_pct"):
        risk_tags.append("涨幅排名不靠前")
    if not today_breakout:
        risk_tags.append("未明显突破近5日高点")
    if not near_20d_high:
        risk_tags.append("未贴近20日新高")
    if not higher_low:
        risk_tags.append("近5日低点未明显抬高")
    return {
        "symbol": sym,
        "name": q.get("name", ""),
        "price": price,
        "open": day_open,
        "prev_close": prev_close,
        "high": high,
        "pct_chg": pct_chg,
        "amount": amount,
        "bid1": bid,
        "ask1": ask,
        "score": round(max(0.0, min(96.0, score)), 2),
        "score_basis": "right_side_strength",
        "strategy_style": "热门龙头右侧",
        "right_side_watch": True,
        **heat,
        "yesterday_limit_up": yesterday_limit_up,
        "relative_open_gain": round(open_gain, 4),
        "ma5_ext": round(ma5_ext, 4),
        "ma10_ext": round(ma10_ext, 4),
        "vwap": round(vwap, 3) if vwap > 0 else None,
        "vwap_deviation": round(vwap_deviation, 4) if math.isfinite(vwap_deviation) else None,
        "recent_5d_return": round(rel_5d, 4),
        "recent_20d_return": round(rel_20d, 4),
        "recent_60d_return": round(rel_60d, 4),
        "ma20_slope": round(ma20_slope, 4),
        "recent_high_ext": round(price / recent_high_10 - 1.0, 4) if recent_high_10 > 0 else None,
        "recent_20d_high_ext": round(price / recent_high_20 - 1.0, 4) if recent_high_20 > 0 else None,
        "volume_ratio": round(vol_ratio, 3) if math.isfinite(vol_ratio) else None,
        "risk_tags": risk_tags[:5],
        "reason": "；".join([
            f"热门龙头右侧：热度{heat_score:.1f}，成交额排名{heat.get('amount_rank')}，涨幅排名{heat.get('pct_rank')}",
            f"价在MA5/10/20上方，MA5/MA10向上",
            f"现涨{pct_chg:+.2f}%，相对开盘{open_gain:+.2%}",
            f"离MA5{ma5_ext:+.2%}，离VWAP{vwap_deviation:+.2%}" if math.isfinite(vwap_deviation) else f"离MA5{ma5_ext:+.2%}",
            f"5/20/60日收益{rel_5d:+.2%}/{rel_20d:+.2%}/{rel_60d:+.2%}",
            f"{'接近/突破近5日高点' if today_breakout else '尚未明显突破近5日高点'}，{'贴近20日新高' if near_20d_high else '未贴近20日新高'}",
            "量能仅作加分，不作为硬门槛",
        ]),
        "time": now_iso(),
    }


def hot_leader_base_reject_reason(q: dict[str, Any]) -> str:
    sym = normalize_symbol(q.get("symbol"))
    if not is_mainboard_strategy_symbol(sym):
        return "非主板/不在策略范围"
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    if min(price, day_open, prev_close) <= 0 or amount <= 0:
        return "停牌/实时行情无效"
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    if pct_chg >= 9.7 or pct_chg <= -9.7:
        return "涨跌停附近"
    if quote_spread_pct(q) > N_SHAPE_MAX_SPREAD_PCT:
        return "盘口价差过大"
    return "通过"


def format_hot_leader_row(
    row: dict[str, Any],
    *,
    score: float,
    score_basis: str,
    strategy_style: str,
    reason_parts: list[str],
    risk_tags: list[str] | None = None,
) -> dict[str, Any]:
    flow = row.get("fund_flow") or {}
    sym = normalize_symbol(row.get("symbol"))
    price = to_float(row.get("price"), 0.0)
    day_open = to_float(row.get("open"), 0.0)
    amount = to_float(row.get("amount"), 0.0)
    volume = to_float(row.get("volume"), 0.0)
    today_main_net = to_float(flow.get("main_net"), 0.0)
    fund_flow_source = str(flow.get("fund_flow_source") or "")
    recent_values = list(row.get("recent_3d_main_net") or [])
    if len(recent_values) < 3:
        recent_values = recent_main_net_values(sym, today_main_net, 3) if flow else []
    prev_main_net = to_float(recent_values[1], 0.0) if len(recent_values) > 1 else 0.0
    main_net_change_1d = today_main_net - prev_main_net
    open_gain = price / day_open - 1.0 if day_open > 0 else 9.9
    vwap = amount / volume if amount > 0 and volume > 0 else 0.0
    vwap_deviation = price / vwap - 1.0 if price > 0 and vwap > 0 else float("nan")
    main_net_pct = today_main_net / amount if amount > 0 else 0.0
    return {
        "symbol": sym,
        "name": row.get("name", ""),
        "price": price,
        "open": day_open,
        "prev_close": to_float(row.get("prev_close"), 0.0),
        "high": to_float(row.get("high"), 0.0),
        "pct_chg": to_float(row.get("pct_chg"), 0.0),
        "amount": amount,
        "bid1": to_float(row.get("bid1"), 0.0),
        "ask1": to_float(row.get("ask1"), 0.0),
        "score": round(max(0.0, min(98.0, score)), 2),
        "score_basis": score_basis,
        "strategy_style": strategy_style,
        "right_side_watch": True,
        "amount_rank": int(row.get("amount_rank") or 9999),
        "amount_top_pct": round(to_float(row.get("amount_top_pct"), 9.9), 4),
        "recent_5d_return": round(to_float(row.get("recent_5d_return"), 0.0), 4),
        "recent_10d_return": round(to_float(row.get("recent_10d_return"), 0.0), 4),
        "recent_5d_rank": int(row.get("recent_5d_rank") or 9999),
        "recent_5d_top_pct": round(to_float(row.get("recent_5d_top_pct"), 9.9), 4),
        "ma5": round(to_float(row.get("ma5"), 0.0), 3),
        "ma20": round(to_float(row.get("ma20"), 0.0), 3),
        "ma60": round(to_float(row.get("ma60"), 0.0), 3),
        "ma20_slope": round(to_float(row.get("ma20_slope"), 0.0), 4),
        "main_net": round(today_main_net, 2),
        "main_net_pct": round(main_net_pct, 4),
        "main_net_change_1d": round(main_net_change_1d, 2),
        "main_net_rank_in_pool_c": int(row.get("main_net_rank_in_pool_c") or 9999),
        "fund_flow_source": fund_flow_source,
        "recent_3d_main_net": [round(to_float(value, 0.0), 2) for value in recent_values],
        "vwap": round(vwap, 3) if vwap > 0 else None,
        "vwap_deviation": round(vwap_deviation, 4) if math.isfinite(vwap_deviation) else None,
        "relative_open_gain": round(open_gain, 4),
        "risk_tags": (risk_tags or [])[:5],
        "reason": "；".join(reason_parts),
        "time": now_iso(),
    }


def build_flexible_hot_leader_candidates(
    rows: list[dict[str, Any]],
    *,
    amount_universe_count: int,
) -> list[dict[str, Any]]:
    if not HOT_LEADER_FLEXIBLE_FALLBACK or not rows:
        return []
    candidates = []
    for row in rows:
        flow = row.get("fund_flow") or {}
        if not flow:
            continue
        price = to_float(row.get("price"), 0.0)
        ma20 = to_float(row.get("ma20"), 0.0)
        ma60 = to_float(row.get("ma60"), 0.0)
        ma20_slope = to_float(row.get("ma20_slope"), 0.0)
        amount_top_pct = to_float(row.get("amount_top_pct"), 1.0)
        strength_top_pct = to_float(row.get("recent_5d_top_pct"), 1.0)
        recent_5d_return = to_float(row.get("recent_5d_return"), 0.0)
        recent_10d_return = to_float(row.get("recent_10d_return"), 0.0)
        main_net = to_float(flow.get("main_net"), 0.0)
        flow_available = bool(flow)
        flow_source = str(flow.get("fund_flow_source") or "")
        amount = to_float(row.get("amount"), 0.0)
        recent_values = list(row.get("recent_3d_main_net") or [])
        positive_days = sum(1 for value in recent_values if to_float(value, 0.0) > 0)
        amount_score = max(0.0, 25.0 * (1.0 - min(1.0, amount_top_pct)))
        strength_score = max(0.0, 20.0 * (1.0 - min(1.0, strength_top_pct)))
        if recent_10d_return > 0:
            strength_score += min(8.0, recent_10d_return * 45.0)
        trend_score = 0.0
        if price >= ma20 > 0:
            trend_score += 12.0
        if ma20_slope >= -0.002:
            trend_score += 8.0
        if ma20 >= ma60 * 0.985:
            trend_score += 6.0
        if to_float(row.get("ma5"), 0.0) > ma20:
            trend_score += 4.0
        fund_score = 0.0
        if main_net > 0:
            fund_score += 10.0
            fund_score += min(10.0, (main_net / max(amount, 1.0)) * 130.0)
        fund_score += positive_days * 3.0
        score = amount_score + strength_score + trend_score + fund_score
        risk_tags = []
        if not (to_float(row.get("ma5"), 0.0) > ma20 > ma60):
            risk_tags.append("柔性趋势，未严格多头")
        if positive_days < 3:
            risk_tags.append(f"近3日主力{positive_days}日为正" if flow_available else "资金流暂缺")
        if flow_source.startswith("eastmoney_history_"):
            risk_tags.append("资金流非实时")
        if recent_5d_return < 0 and recent_10d_return > 0:
            risk_tags.append("前强回踩观察")
        if price < ma20:
            risk_tags.append("未站上MA20")
        reason_parts = [
            f"热门龙头柔性评分：总分{score:.1f}，严格池为空时启用",
            f"成交额分位{amount_top_pct:.1%}，近5日强度分位{strength_top_pct:.1%}",
            f"近5/10日涨幅{recent_5d_return:+.2%}/{recent_10d_return:+.2%}",
            f"趋势：价{'站上' if price >= ma20 else '未站上'}MA20，MA20斜率{ma20_slope:+.2%}",
            f"资金流：{'实时' if flow_source in {'eastmoney_realtime_rank', 'akshare_realtime_rank'} else '历史兜底'}主力净额{main_net / 1e8:+.2f}亿，近3日{positive_days}日为正" if flow_available else "资金流：接口暂缺，本轮未给资金分",
        ]
        candidates.append(format_hot_leader_row(
            row,
            score=score,
            score_basis="hot_leader_flexible_score",
            strategy_style="热门龙头柔性候选",
            reason_parts=reason_parts,
            risk_tags=risk_tags,
        ))
    return sorted(candidates, key=lambda item: to_float(item.get("score"), 0.0), reverse=True)[:HOT_LEADER_FLEXIBLE_LIMIT]


def build_hot_leader_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not HOT_LEADER_ENABLED:
        return []
    universe = [
        row for row in merged_quote_rows(state)
        if hot_leader_base_reject_reason(row) == "通过"
    ]
    if not universe:
        return []
    amount_sorted = sorted(universe, key=lambda row: to_float(row.get("amount"), 0.0), reverse=True)
    amount_cut = max(1, math.ceil(len(amount_sorted) * HOT_LEADER_AMOUNT_TOP_PCT))
    pool_a = amount_sorted[:amount_cut]
    pct_sorted = sorted(universe, key=lambda row: to_float(row.get("pct_chg"), -99.0), reverse=True)
    pct_ranks = {
        normalize_symbol(row.get("symbol")): idx
        for idx, row in enumerate(pct_sorted, 1)
        if normalize_symbol(row.get("symbol"))
    }
    flow_snapshot = fetch_eastmoney_fund_flow_snapshot()
    enriched_a: list[dict[str, Any]] = []
    live_rows: list[dict[str, Any]] = []
    for amount_rank, q in enumerate(pool_a, 1):
        sym = normalize_symbol(q.get("symbol"))
        heat = ranked_market_leader_heat(
            q,
            amount_rank=amount_rank,
            pct_rank=pct_ranks.get(sym, 9999),
            scan_count=len(universe),
        )
        bars = fetch_sina_daily_bars(sym, 90)
        if len(bars) < HOT_LEADER_MIN_LISTING_DAYS:
            live = live_leader_profile(q, heat, "日线数据不足，先按盘中热度入池")
            if live:
                live_rows.append(live)
            continue
        price = to_float(q.get("price"), 0.0)
        closes = [bar["close"] for bar in bars]
        closes_with_live = closes + [price]
        if len(closes_with_live) < 61:
            continue
        close_5_ago = closes[-5] if len(closes) >= 5 else 0.0
        close_10_ago = closes[-10] if len(closes) >= 10 else 0.0
        recent_5d_return = price / close_5_ago - 1.0 if close_5_ago > 0 else -9.9
        recent_10d_return = price / close_10_ago - 1.0 if close_10_ago > 0 else -9.9
        ma5 = mean(closes_with_live[-5:])
        ma20 = mean(closes_with_live[-20:])
        ma60 = mean(closes_with_live[-60:])
        prev_ma20 = mean(closes_with_live[-21:-1])
        ma20_slope = ma20 / prev_ma20 - 1.0 if prev_ma20 and math.isfinite(prev_ma20) and prev_ma20 > 0 else 0.0
        if not all(math.isfinite(v) and v > 0 for v in (ma5, ma20, ma60)):
            continue
        flow = flow_snapshot.get(sym) or latest_history_fund_flow(sym)
        recent_main_values = recent_main_net_values(sym, to_float(flow.get("main_net"), 0.0), 3) if flow else []
        enriched_a.append({
            **q,
            "amount_rank": amount_rank,
            "amount_top_pct": amount_rank / max(1, len(amount_sorted)),
            "listing_days": len(bars),
            "recent_5d_return": recent_5d_return,
            "recent_10d_return": recent_10d_return,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "ma20_slope": ma20_slope,
            "bars": bars,
            "fund_flow": flow,
            "recent_3d_main_net": recent_main_values,
        })
    if not enriched_a:
        return sorted(live_rows, key=lambda row: to_float(row.get("score"), 0.0), reverse=True)[:HOT_LEADER_FLEXIBLE_LIMIT]
    strength_sorted = sorted(enriched_a, key=lambda row: to_float(row.get("recent_5d_return"), -9.9), reverse=True)
    strength_cut = max(1, math.ceil(len(strength_sorted) * HOT_LEADER_5D_TOP_PCT))
    pool_b = strength_sorted[:strength_cut]
    for idx, row in enumerate(strength_sorted, 1):
        row["recent_5d_rank"] = idx
        row["recent_5d_top_pct"] = idx / max(1, len(strength_sorted))
    pool_c = [
        row for row in pool_b
        if to_float(row.get("ma5"), 0.0) > to_float(row.get("ma20"), 0.0) > to_float(row.get("ma60"), 0.0)
    ]
    if not pool_c:
        flexible_rows = build_flexible_hot_leader_candidates(enriched_a, amount_universe_count=len(amount_sorted))
        combined_rows = flexible_rows + live_rows
        return sorted(combined_rows, key=lambda row: to_float(row.get("score"), 0.0), reverse=True)[:HOT_LEADER_FLEXIBLE_LIMIT]
    flow_ranked = sorted(
        [row for row in pool_c if row.get("fund_flow")],
        key=lambda row: to_float((row.get("fund_flow") or {}).get("main_net"), -float("inf")),
        reverse=True,
    )
    if not flow_ranked:
        flexible_rows = build_flexible_hot_leader_candidates(enriched_a, amount_universe_count=len(amount_sorted))
        combined_rows = flexible_rows + live_rows
        return sorted(combined_rows, key=lambda row: to_float(row.get("score"), 0.0), reverse=True)[:HOT_LEADER_FLEXIBLE_LIMIT]
    flow_cut = max(1, math.ceil(len(flow_ranked) * HOT_LEADER_MAIN_NET_TOP_PCT))
    flow_top_symbols = {normalize_symbol(row.get("symbol")) for row in flow_ranked[:flow_cut]}
    rows = []
    for main_net_rank, row in enumerate(flow_ranked, 1):
        sym = normalize_symbol(row.get("symbol"))
        if sym not in flow_top_symbols:
            continue
        flow = row.get("fund_flow") or {}
        today_main_net = to_float(flow.get("main_net"), 0.0)
        recent_values = list(row.get("recent_3d_main_net") or recent_main_net_values(sym, today_main_net, 3))
        if len(recent_values) < 3 or not all(value > 0 for value in recent_values):
            continue
        price = to_float(row.get("price"), 0.0)
        day_open = to_float(row.get("open"), 0.0)
        amount = to_float(row.get("amount"), 0.0)
        volume = to_float(row.get("volume"), 0.0)
        open_gain = price / day_open - 1.0 if day_open > 0 else 9.9
        vwap = amount / volume if amount > 0 and volume > 0 else 0.0
        vwap_deviation = price / vwap - 1.0 if price > 0 and vwap > 0 else float("nan")
        recent_5d_return = to_float(row.get("recent_5d_return"), 0.0)
        main_net_pct = today_main_net / amount if amount > 0 else 0.0
        prev_main_net = recent_values[1] if len(recent_values) > 1 else 0.0
        main_net_change_1d = today_main_net - prev_main_net
        score = 70.0
        score += min(10.0, max(0.0, recent_5d_return) * 45.0)
        score += min(8.0, max(0.0, main_net_pct) * 120.0)
        score += max(0.0, 8.0 - max(0, main_net_rank - 1) * 8.0 / max(1, len(flow_ranked)))
        score += max(0.0, 6.0 - max(0, int(row.get("amount_rank") or 9999) - 1) * 6.0 / max(1, len(amount_sorted)))
        score -= max(0.0, open_gain - 0.035) * 160.0
        if math.isfinite(vwap_deviation):
            score -= max(0.0, vwap_deviation - 0.035) * 120.0
        risk_tags = []
        if open_gain > 0.035:
            risk_tags.append("相对开盘偏高")
        if math.isfinite(vwap_deviation) and vwap_deviation > 0.035:
            risk_tags.append("离VWAP偏远")
        if today_main_net <= 0:
            risk_tags.append("今日主力净额非正")
        if str(flow.get("fund_flow_source") or "").startswith("eastmoney_history_"):
            risk_tags.append("资金流非实时")
        row["main_net_rank_in_pool_c"] = main_net_rank
        row["recent_3d_main_net"] = recent_values
        rows.append(format_hot_leader_row(
            row,
            score=score,
            score_basis="hot_leader_fund_flow",
            strategy_style="热门龙头候选池D",
            risk_tags=risk_tags,
            reason_parts=[
                f"热门龙头候选池D：成交额排名前{HOT_LEADER_AMOUNT_TOP_PCT:.0%}内第{int(row.get('amount_rank') or 9999)}名",
                f"近5日涨幅{recent_5d_return:+.2%}，强度排名前{HOT_LEADER_5D_TOP_PCT:.0%}",
                f"均线多头MA5>MA20>MA60 ({to_float(row.get('ma5'), 0.0):.2f}>{to_float(row.get('ma20'), 0.0):.2f}>{to_float(row.get('ma60'), 0.0):.2f})",
                f"{'今日' if flow.get('fund_flow_source') in {'eastmoney_realtime_rank', 'akshare_realtime_rank'} else '历史兜底'}主力净额{today_main_net / 1e8:+.2f}亿，较前日{main_net_change_1d / 1e8:+.2f}亿，池C排名{main_net_rank}",
                f"近3日主力净额持续为正：{', '.join(f'{value / 1e8:+.2f}亿' for value in recent_values)}",
            ],
        ))
    strict_rows = sorted(rows, key=lambda row: to_float(row.get("score"), 0.0), reverse=True)
    flexible_rows = build_flexible_hot_leader_candidates(enriched_a, amount_universe_count=len(amount_sorted))
    seen: set[str] = set()
    combined_rows: list[dict[str, Any]] = []
    for row in strict_rows + flexible_rows + sorted(live_rows, key=lambda item: to_float(item.get("score"), 0.0), reverse=True):
        sym = normalize_symbol(row.get("symbol"))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        combined_rows.append(row)
        if len(combined_rows) >= max(HOT_LEADER_FLEXIBLE_LIMIT, 12):
            break
    return combined_rows


def build_right_side_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not RIGHT_SIDE_ENABLED:
        return []
    if HOT_LEADER_ENABLED:
        return build_hot_leader_candidates(state)
    rows = []
    for q in merged_quote_rows_for_right_side(state):
        prof = right_side_strength_profile(q)
        if prof:
            rows.append(prof)
    return sorted(rows, key=lambda row: to_float(row.get("score"), 0.0), reverse=True)


def original_n_shape_quality_score(
    *,
    y_ret: float,
    open_chg: float,
    now_ret: float,
    pct_chg: float,
    pullback_depth: float,
    platform_ext: float,
    amount: float,
    pullback_shrink: bool,
    strict_ok: bool,
) -> float:
    score = 50.0
    score += max(0.0, 18.0 - abs(y_ret - (-0.04)) * 320.0)
    score += max(0.0, 12.0 - abs(open_chg - (-0.006)) * 430.0)
    score += max(0.0, 12.0 - abs(now_ret - 0.025) * 420.0)
    if -0.13 <= pullback_depth <= -0.025:
        score += 8.0
    elif -0.18 <= pullback_depth < -0.13 or -0.025 < pullback_depth <= -0.01:
        score += 4.0
    if -0.01 <= platform_ext <= MORNING_REBOUND_MAX_PLATFORM_EXT:
        score += max(0.0, 8.0 - abs(platform_ext - 0.006) * 160.0)
    if pullback_shrink:
        score += 5.0
    score += min(3.0, amount / 1e9)
    score -= max(0.0, pct_chg - 3.8) * 8.0
    score -= max(0.0, now_ret - 0.03) * 450.0
    if strict_ok:
        score += 9.0
    else:
        score = min(score, N_SHAPE_WATCH_SCORE_CAP)
    return max(0.0, min(99.0, score))


def adjust_n_shape_watch_score(
    score: float,
    *,
    strict_ok: bool,
    live_reason: str,
    y_ret: float,
    pullback_days: int,
    pullback_depth: float,
    platform_ext: float,
    pullback_shrink: bool,
    diff: float,
    day_open: float,
    ma10_open: float,
    ma20_open: float,
    yesterday_limit_up: bool,
) -> float:
    if strict_ok:
        return score
    adjusted = min(score, N_SHAPE_WATCH_SCORE_CAP)
    if live_reason != "通过":
        adjusted -= 4.0
    if yesterday_limit_up:
        adjusted -= 12.0
    if y_ret >= 0:
        adjusted -= 10.0
    elif not (N_SHAPE_Y_RET_MIN < y_ret < N_SHAPE_Y_RET_MAX):
        adjusted -= 5.0
    if not pullback_shrink:
        adjusted -= 7.0
    if not math.isfinite(diff) or diff >= 0.5:
        adjusted -= 4.0
    if day_open <= ma20_open:
        adjusted -= 4.0
    if day_open <= ma10_open:
        adjusted -= 2.0
    if pullback_days > 8:
        adjusted -= min(8.0, (pullback_days - 8) * 1.6)
    if platform_ext < -0.08:
        adjusted -= min(10.0, abs(platform_ext + 0.08) * 70.0)
    if pullback_depth < -0.15:
        adjusted -= min(8.0, abs(pullback_depth + 0.15) * 90.0)
    return max(0.0, min(N_SHAPE_WATCH_SCORE_CAP, adjusted))


def morning_rebound_score(q: dict[str, Any]) -> tuple[float, list[str]] | None:
    sym = normalize_symbol(q.get("symbol"))
    if not sym.startswith(("000", "001", "002", "003", "004", "005", "600", "601", "603", "605")):
        return None
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return None
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return None
    open_chg = day_open / prev_close - 1.0
    trigger_ret = high / day_open - 1.0
    now_ret = price / day_open - 1.0
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    spread_pct = (ask - bid) / price * 100 if ask > 0 and bid > 0 else 9.9

    reasons = []
    if not (N_SHAPE_OPEN_CHG_MIN < open_chg < N_SHAPE_OPEN_CHG_MAX):
        return None
    reasons.append(f"开盘相对昨收{open_chg:+.2%}")
    if trigger_ret < N_SHAPE_TRIGGER_PCT:
        return None
    reasons.append(f"盘中最高相对开盘{trigger_ret:+.2%}")
    if now_ret < N_SHAPE_TRIGGER_PCT:
        return None
    reasons.append(f"现价仍高于开盘{now_ret:+.2%}")
    if now_ret > MORNING_REBOUND_MAX_OPEN_EXT:
        return None
    reasons.append(f"未过度偏离开盘{now_ret:+.2%}")
    if pct_chg > MORNING_REBOUND_MAX_PCT_CHG:
        return None
    if amount < N_SHAPE_MIN_AMOUNT:
        return None
    reasons.append(f"成交额{amount / 1e8:.2f}亿")
    if spread_pct > N_SHAPE_MAX_SPREAD_PCT:
        return None
    reasons.append(f"价差{spread_pct:.3f}%")

    historical_ok, historical_reasons = historical_rebound_filter(q)
    if not historical_ok:
        return None
    reasons.extend(historical_reasons)

    score = 72.0
    score += max(0.0, 14.0 - abs(now_ret - 0.025) * 420.0)
    score += max(0.0, 8.0 - abs(open_chg - (-0.006)) * 430.0)
    score += min(3.0, amount / 1e9)
    score -= min(5.0, spread_pct * 18)
    score -= max(0.0, pct_chg - 3.8) * 8.0
    score -= max(0.0, now_ret - 0.03) * 450.0
    if -0.015 <= open_chg <= 0.005:
        score += 6.0
    if 1.0 <= pct_chg <= 3.8:
        score += 4.0
    return round(max(0.0, min(99.0, score)), 2), reasons


def morning_rebound_reject_reason(q: dict[str, Any]) -> str:
    sym = normalize_symbol(q.get("symbol"))
    if not sym.startswith(("000", "001", "002", "003", "004", "005", "600", "601", "603", "605")):
        return "非主板/不在策略范围"
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return "实时行情无效"
    open_chg = day_open / prev_close - 1.0
    trigger_ret = high / day_open - 1.0
    now_ret = price / day_open - 1.0
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    spread_pct = (ask - bid) / price * 100 if ask > 0 and bid > 0 else 9.9
    if not (N_SHAPE_OPEN_CHG_MIN < open_chg < N_SHAPE_OPEN_CHG_MAX):
        return "开盘不在原策略窗口"
    if trigger_ret < N_SHAPE_TRIGGER_PCT:
        return "盘中突破强度不足"
    if now_ret < N_SHAPE_TRIGGER_PCT:
        return "现价未确认向上"
    if now_ret > MORNING_REBOUND_MAX_OPEN_EXT:
        return "相对开盘涨太多"
    if pct_chg > MORNING_REBOUND_MAX_PCT_CHG:
        return "当前涨幅过高"
    if amount < N_SHAPE_MIN_AMOUNT:
        return "成交额不足"
    if spread_pct > N_SHAPE_MAX_SPREAD_PCT:
        return "盘口价差过大"
    historical_ok, historical_reasons = historical_rebound_filter(q)
    if not historical_ok:
        return historical_reasons[0] if historical_reasons else "历史N字不过"
    return "通过"


def build_strategy_diagnostics(state: dict[str, Any]) -> dict[str, Any]:
    source_rows = merged_quote_rows(state)[:300]
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    checked = 0
    for q in source_rows:
        sym = normalize_symbol(q.get("symbol"))
        if not sym:
            continue
        checked += 1
        reason = n_shape_watch_source_reject_reason(q)
        counts[reason] = counts.get(reason, 0) + 1
        if reason != "通过":
            examples.setdefault(reason, [])
            if len(examples[reason]) < 3:
                examples[reason].append(f"{sym} {q.get('name') or ''}".strip())
    top = sorted(
        ({"reason": reason, "count": count, "examples": examples.get(reason, [])} for reason, count in counts.items() if reason != "通过"),
        key=lambda item: item["count"],
        reverse=True,
    )[:10]
    return {
        "time": now_iso(),
        "checked": checked,
        "passed": counts.get("通过", 0),
        "top_reasons": top,
        "strict_limits": {
            "max_pct_chg": MORNING_REBOUND_MAX_PCT_CHG,
            "max_open_ext": MORNING_REBOUND_MAX_OPEN_EXT,
            "max_prev_ext": MORNING_REBOUND_MAX_PREV_EXT,
            "max_platform_ext": MORNING_REBOUND_MAX_PLATFORM_EXT,
        },
    }


def relaxed_n_shape_profile(q: dict[str, Any]) -> dict[str, Any] | None:
    sym = normalize_symbol(q.get("symbol"))
    if not is_mainboard_strategy_symbol(sym):
        return None
    name = str(q.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        return None
    price = to_float(q.get("price"), 0.0)
    day_open = to_float(q.get("open"), 0.0)
    prev_close = to_float(q.get("prev_close"), 0.0)
    high = to_float(q.get("high"), 0.0)
    amount = to_float(q.get("amount"), 0.0)
    bid = to_float(q.get("bid1"), 0.0)
    ask = to_float(q.get("ask1"), 0.0)
    if min(price, day_open, prev_close, high) <= 0:
        return None
    pct_chg = to_float(q.get("pct_chg"), 0.0)
    spread_pct = quote_spread_pct(q)
    open_chg = day_open / prev_close - 1.0
    now_ret = price / day_open - 1.0
    live_reason = n_shape_live_reject_reason(q)
    watch_source_reason = n_shape_watch_source_reject_reason(q)
    if watch_source_reason != "通过":
        return None

    bars = fetch_sina_daily_bars(sym, 80)
    if len(bars) < 50:
        return None
    limit_flags = [approx_limit_up(bars[i - 1]["close"], bars[i]["close"]) for i in range(1, len(bars))]
    yesterday_limit_up = approx_limit_up(bars[-2]["close"], bars[-1]["close"])
    y_ret = bars[-1]["close"] / bars[-2]["close"] - 1.0 if bars[-2]["close"] > 0 else 9.9
    recent_limit_indexes = [
        i
        for i in range(max(1, len(bars) - 15), len(bars) - 1)
        if approx_limit_up(bars[i - 1]["close"], bars[i]["close"])
    ]
    if not recent_limit_indexes:
        return None
    if max_consecutive_true(limit_flags[-20:]) >= 3:
        return None

    impulse_idx = recent_limit_indexes[-1]
    impulse_score = -1.0
    for i in recent_limit_indexes:
        prev_bar = bars[i - 1]
        bar = bars[i]
        if prev_bar["close"] <= 0 or bar["open"] <= 0:
            continue
        day_ret = bar["close"] / prev_bar["close"] - 1.0
        intraday_ret = bar["close"] / bar["open"] - 1.0
        score = day_ret + intraday_ret
        if score > impulse_score:
            impulse_score = score
            impulse_idx = i

    pullback_bars = bars[impulse_idx + 1:]
    if not (1 <= len(pullback_bars) <= 15):
        return None
    impulse = bars[impulse_idx]
    impulse_prev = bars[impulse_idx - 1]
    pullback_low = min(bar["low"] for bar in pullback_bars)
    pullback_high = max(bar["high"] for bar in pullback_bars)
    if impulse["close"] <= 0:
        return None
    pullback_depth = pullback_low / impulse["close"] - 1.0
    if pullback_depth < -0.24:
        return None
    impulse_ret = impulse["close"] / impulse_prev["close"] - 1.0 if impulse_prev["close"] > 0 else 0.0
    pullback_has_down_day = any(
        bars[i]["close"] < bars[i - 1]["close"]
        for i in range(max(impulse_idx + 1, 1), len(bars))
    )
    real_pullback = pullback_depth <= -0.01 and pullback_has_down_day
    if not real_pullback:
        return None
    platform_ext = price / pullback_high - 1.0 if pullback_high > 0 else 9.9
    if platform_ext > MORNING_REBOUND_MAX_PLATFORM_EXT:
        return None
    closes = [bar["close"] for bar in bars]
    ma10 = mean(closes[-10:])
    ma20 = mean(closes[-20:])
    diff = macd_diff(closes)
    pullback_avg_vol = mean([bar["volume"] for bar in pullback_bars])
    pullback_shrink = bool(impulse["volume"] > 0 and pullback_avg_vol <= impulse["volume"] * 0.95)
    strict_ok, strict_reasons = historical_rebound_filter(q)
    risk_tags = []
    reject_reason = strict_reasons[0] if not strict_ok and strict_reasons else ""
    if reject_reason:
        risk_tags.append(f"未过严格：{reject_reason}")
    if live_reason != "通过":
        risk_tags.append(f"未到早盘确认：{live_reason}")
    if yesterday_limit_up:
        risk_tags.append("昨日涨停票，按溢价风险处理")
    if not (N_SHAPE_Y_RET_MIN < y_ret < N_SHAPE_Y_RET_MAX):
        risk_tags.append(f"昨日跌幅偏离原策略{y_ret:+.2%}")
    if pullback_depth < -0.18:
        risk_tags.append("回踩偏深")
    if not pullback_shrink:
        risk_tags.append("回踩缩量不足")
    if not math.isfinite(diff) or diff >= 0.5:
        risk_tags.append("MACD diff偏高")
    if bars[-1]["open"] <= ma10:
        risk_tags.append("昨日开盘未站上MA10")
    if day_open <= ma20:
        risk_tags.append("今日开盘未站上昨日MA20")
    if not is_market_golden():
        risk_tags.append("大盘均线非多头")
    score = original_n_shape_quality_score(
        y_ret=y_ret,
        open_chg=open_chg,
        now_ret=now_ret,
        pct_chg=pct_chg,
        pullback_depth=pullback_depth,
        platform_ext=platform_ext,
        amount=amount,
        pullback_shrink=pullback_shrink,
        strict_ok=strict_ok,
    )
    score = adjust_n_shape_watch_score(
        score,
        strict_ok=strict_ok,
        live_reason=live_reason,
        y_ret=y_ret,
        pullback_days=len(pullback_bars),
        pullback_depth=pullback_depth,
        platform_ext=platform_ext,
        pullback_shrink=pullback_shrink,
        diff=diff,
        day_open=day_open,
        ma10_open=ma10,
        ma20_open=ma20,
        yesterday_limit_up=yesterday_limit_up,
    )
    return {
        "symbol": sym,
        "name": q.get("name", ""),
        "price": price,
        "open": day_open,
        "prev_close": prev_close,
        "high": high,
        "pct_chg": pct_chg,
        "amount": amount,
        "bid1": bid,
        "ask1": ask,
        "score": round(score, 2),
        "strict_pass": strict_ok,
        "yesterday_limit_up": yesterday_limit_up,
        "real_pullback": real_pullback,
        "pullback_days": len(pullback_bars),
        "pullback_depth": round(pullback_depth, 4),
        "open_chg": round(open_chg, 4),
        "relative_open_gain": round(now_ret, 4),
        "platform_ext": round(platform_ext, 4),
        "macd_diff": round(diff, 4) if math.isfinite(diff) else None,
        "score_basis": "original_n_shape_quality",
        "risk_tags": risk_tags[:5],
        "reason": "；".join(strict_reasons if strict_ok else [
            f"原N字观察池：近15日涨停上攻{impulse['day']} {impulse_ret:+.2%}",
            f"昨日回调{y_ret:+.2%}，今日开盘{open_chg:+.2%}",
            f"回踩{len(pullback_bars)}天，深度{pullback_depth:+.2%}",
            f"现价相对开盘{now_ret:+.2%}，相对平台{platform_ext:+.2%}",
            f"观察池封顶{N_SHAPE_WATCH_SCORE_CAP:.0f}分：{reject_reason or '等待严格确认'}",
        ]),
        "time": now_iso(),
    }


def build_ai_n_shape_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    source_rows = merged_quote_rows_for_n_shape(state)
    rows = []
    strict_symbols = {
        normalize_symbol(item.get("symbol"))
        for item in (state.get("strategy_signals") or [])
        if normalize_symbol(item.get("symbol"))
    }
    for q in source_rows:
        prof = relaxed_n_shape_profile(q)
        if not prof:
            continue
        if prof["symbol"] in strict_symbols:
            prof["strict_pass"] = True
            prof["score"] = max(to_float(prof.get("score"), 0.0), 85.0)
        rows.append(prof)
    return sorted(rows, key=lambda row: (bool(row.get("strict_pass")), to_float(row.get("score"), 0.0)), reverse=True)


def build_morning_rebound_signals(state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    signals = []
    source_rows = merged_quote_rows_for_n_shape(state)
    positions = state.get("positions") or {}
    for q in source_rows:
        scored = morning_rebound_score(q)
        if scored is None:
            continue
        score, reasons = scored
        sym = normalize_symbol(q.get("symbol"))
        signals.append({
            "symbol": sym,
            "name": q.get("name", ""),
            "price": to_float(q.get("price"), 0.0),
            "open": to_float(q.get("open"), 0.0),
            "prev_close": to_float(q.get("prev_close"), 0.0),
            "high": to_float(q.get("high"), 0.0),
            "pct_chg": to_float(q.get("pct_chg"), 0.0),
            "amount": to_float(q.get("amount"), 0.0),
            "bid1": to_float(q.get("bid1"), 0.0),
            "ask1": to_float(q.get("ask1"), 0.0),
            "score": score,
            "held": sym in positions,
            "reason": "；".join(reasons),
            "time": now_iso(),
        })
    return sorted(signals, key=lambda row: row.get("score", 0.0), reverse=True)


def morning_rebound_plan(state: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    if not MORNING_REBOUND_ENABLED or not is_morning_rebound_time(now):
        return None
    account = account_snapshot(state)
    positions = {p["symbol"]: p for p in account["positions"]}
    if no_sellable_position_buy_locked(state, now):
        return no_sellable_guard_plan(state, now)
    if len(positions) >= MAX_POSITIONS:
        return {"source": "n_shape", "summary": "N字策略发现机会前先检查仓位：持仓已满，不再开新仓。", "orders": []}
    signals = build_morning_rebound_signals(state, now)
    buys = []
    for signal in signals:
        sym = signal.get("symbol")
        if not sym or sym in positions:
            continue
        if len(buys) >= max(1, MORNING_REBOUND_MAX_BUYS):
            break
        buys.append({
            "action": "BUY",
            "symbol": sym,
            "budget_cash": PER_POSITION_CASH,
            "style": "rule",
            "reason": f"N字策略：{signal.get('reason', '')}；评分{signal.get('score')}",
        })
    if not buys:
        return {"source": "n_shape", "summary": "N字策略完成扫描，暂无可开仓标的。", "orders": []}
    names = "、".join(f"{order['symbol']}" for order in buys)
    return {"source": "n_shape", "summary": f"N字策略触发：{names}，按模拟盘卖一价开仓。", "orders": buys}


def deepseek_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    if no_sellable_position_buy_locked(state):
        return no_sellable_guard_plan(state)
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    ctx = build_ai_context(state)
    if AI_BUY_MODE == "off":
        buy_instruction = "当前关闭AI买入：你禁止输出BUY，只能输出SELL或HOLD；卖出只能卖可卖仓位。"
        order_schema = "{\"summary\":\"...\",\"orders\":[{\"action\":\"SELL|HOLD\",\"symbol\":\"000001\",\"qty\":100,\"style\":\"aggressive\",\"reason\":\"...\"}]}\n"
    elif AI_BUY_MODE == "n_shape_only":
        buy_instruction = "当前为AI N字池买入模式：BUY只能从上下文里的n_shape_ai_pool选择；n_shape_candidates是严格通过池，优先参考但不是唯一可买池。你必须结合risk_tags、盘口、涨幅、持仓和复盘自主判断是否买入；若n_shape_ai_pool为空，只能SELL或HOLD。严禁买入不在n_shape_ai_pool里的股票。卖出只能卖可卖仓位。"
        order_schema = "{\"summary\":\"...\",\"orders\":[{\"action\":\"BUY|SELL|HOLD\",\"symbol\":\"000001\",\"budget_cash\":20000,\"qty\":100,\"style\":\"aggressive\",\"reason\":\"...\"}]}\n"
    elif AI_BUY_MODE == "ai_guided":
        buy_instruction = "AI最终决策模式：BUY默认只能从ai_buy_candidates选择；严禁买入不在ai_buy_candidates_raw里的股票。coach_filtered_candidates仅在你明确设置coach_override=true并填写override_reason时才可买。right_side_watch代表热门龙头候选池：热度池可观察强票，但你必须结合buy_timing_score、buy_timing_penalty、buy_timing_notes判断买点；高热度但买点差时应HOLD观察，不要机械追买。"
        order_schema = "{\"summary\":\"...\",\"orders\":[{\"action\":\"BUY|SELL|HOLD\",\"symbol\":\"000001\",\"budget_cash\":20000,\"qty\":100,\"style\":\"aggressive\",\"coach_override\":false,\"override_reason\":\"...\",\"reason\":\"...\"}]}\n"
    else:
        buy_instruction = "买入只能从candidates选择，卖出只能卖可卖仓位。"
        order_schema = "{\"summary\":\"...\",\"orders\":[{\"action\":\"BUY|SELL|HOLD\",\"symbol\":\"000001\",\"budget_cash\":20000,\"qty\":100,\"style\":\"aggressive\",\"reason\":\"...\"}]}\n"
    prompt = (
        "你是A股AI盯盘模拟盘交易员。只能输出JSON，不要输出解释性文本。后端会用实时买一/卖一成交，禁止编造价格。\n\n"
        "优先级从高到低：\n"
        "1. 硬约束：A股T+1；holding_days=0或can_sell_today=false的持仓禁止卖出。公告风险、硬风控、仓位限制不可覆盖。\n"
        f"2. 仓位事实只看account_constraints。available_position_slots=0才算无新仓位；buy_locked_no_sellable_positions=true时表示满{MAX_POSITIONS}只且没有可卖仓，禁止BUY。\n"
        "3. 卖出和买入独立。可卖弱仓可以只SELL不BUY；满仓只限制BUY，不是拒绝SELL的理由。必须阅读rotation_candidates并逐只判断是否止损/去弱。\n"
        f"4. 早盘卖出纪律：09:30-{EARLY_SELL_OBSERVE_END.strftime('%H:%M')} 内禁止急杀止损。positions里early_sell_observe=true的旧仓必须HOLD等待修复确认；弱市、浮亏、跌幅大、不在候选池，都不能单独作为早盘SELL理由。只有达到后端极端风控阈值时才会允许成交，否则SELL会被拦截。强势/热门股低开急杀优先等反抽或09:45后再评估。\n"
        "5. 市场判断只看market_regime、market_intraday、market_indices，禁止用候选池数量反推大盘强弱。market_intraday强时，不能把盘面描述成弱市。\n"
        "6. 买入池规则："
        f"{buy_instruction}\n"
        "7. N字规则：yesterday_limit_up=true不是标准N字回踩；real_pullback=false说明没有真实回踩，除非信号极强，否则优先回避。\n"
        "8. 热门龙头池：来源为right_side_watch时，先看score_basis。hot_leader_fund_flow表示严格池D，hot_leader_flexible_score表示严格池为空后的柔性候选。必须解释成交额分位、近5/10日强度、趋势状态、main_net、main_net_change_1d、recent_3d_main_net和fund_flow_source；若fund_flow_source是历史兜底，必须降低确信度，不能当成实时当日主力净额。\n"
        "9. 买点学习：阅读buy_timing_memory和每个候选的buy_timing_score/buy_timing_notes。这是复盘滚动学习信号，不是死规则；若仍决定买入高penalty候选，reason必须说明为什么当前盘面足以覆盖追高风险，否则应HOLD观察。\n"
        "10. 做T模块：t_signals只是底仓做T提醒，第一版不自动执行T订单；T_BACK/INTRADAY_T不能当作普通新开仓理由。若某股触发t_signals，普通AI买入该股会被后端拦截，除非未来走独立做T账本。\n"
        "11. 复盘记忆：阅读review_memory，遵守habit_rules，避免avoid_patterns。买入非严格N字时，reason要说明没有违反近期核心教训。\n"
        "12. 教练过滤：阅读coach_filtered_candidates并在summary简述主要过滤原因。coach_override只能覆盖trading_coach，不能覆盖硬约束。right_side_watch不属于形态教练过滤对象。\n\n"
        "输出格式："
        f"{order_schema}"
        f"上下文：{json.dumps(ctx, ensure_ascii=False)}"
    )
    body = llm_chat_body(
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        prompt,
        temperature=0.2,
        max_tokens=800,
    )
    try:
        payload = llm_post_json(
            body,
            key,
            timeout=max(30.0, float(os.environ.get("DEEPSEEK_DECISION_TIMEOUT", "45"))),
            retries=max(1, int(os.environ.get("DEEPSEEK_DECISION_RETRIES", str(LLM_RETRIES)))),
        )
        text = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if not text:
            RUNTIME["deepseek_last_error"] = "返回内容为空"
            return None
        plan = parse_model_json_object(text)
        plan["source"] = AI_PROVIDER_LABEL
        RUNTIME["deepseek_last_error"] = ""
        return plan
    except Exception as exc:
        RUNTIME["deepseek_last_error"] = llm_error_summary(exc)
        return None


def execute_plan(state: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    blocked_orders = []
    quotes = state.get("quotes") or {}
    positions = state.setdefault("positions", {})
    cash = to_float(state.get("cash"), DEFAULT_CASH)
    plan_source = str(plan.get("source") or "")
    n_shape_symbols = n_shape_symbol_set(state)
    candidate_sets = build_ai_buy_candidate_sets(state)
    ai_buy_map = {
        normalize_symbol(item.get("symbol")): item
        for item in (candidate_sets.get("passed") or [])
        if normalize_symbol(item.get("symbol"))
    }
    ai_buy_raw_map = {
        normalize_symbol(item.get("symbol")): item
        for item in (candidate_sets.get("raw") or [])
        if normalize_symbol(item.get("symbol"))
    }
    ai_buy_symbols = set(ai_buy_map)
    ai_buy_raw_symbols = set(ai_buy_raw_map)
    trading_coach = build_trading_coach(state)
    for order in plan.get("orders") or []:
        action = str(order.get("action") or "HOLD").upper()
        sym = normalize_symbol(order.get("symbol"))
        q = quotes.get(sym) or {}
        if action == "HOLD" or not sym:
            continue
        if action == "BUY":
            t_signal_symbols = {
                normalize_symbol(item.get("symbol"))
                for item in state.get("t_signals") or []
                if normalize_symbol(item.get("symbol"))
            }
            if sym in t_signal_symbols and plan_source not in RULE_BUY_SOURCES:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "该股已触发做T信号，当日不参与普通AI买入；T回补必须走做T账本"})
                continue
            if no_sellable_position_buy_locked(state):
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": f"当前持仓已满{MAX_POSITIONS}只且当日没有可卖仓位，AI选股/买入暂停"})
                continue
            if AI_BUY_MODE == "off" and plan_source not in RULE_BUY_SOURCES:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "AI买入关闭：非规则买入已拦截"})
                continue
            if AI_BUY_MODE == "n_shape_only" and plan_source not in RULE_BUY_SOURCES and sym not in n_shape_symbols:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "N字候选买入模式：该股不在当前N字候选池"})
                continue
            if AI_BUY_MODE == "ai_guided" and plan_source not in RULE_BUY_SOURCES:
                override_requested = bool(order.get("coach_override"))
                override_reason = str(order.get("override_reason") or "").strip()
                if sym not in ai_buy_raw_symbols:
                    blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "AI最终决策模式：该股不在原始AI候选池或未过硬风控"})
                    continue
                if sym not in ai_buy_symbols and not (TRADING_COACH_ALLOW_OVERRIDE and override_requested and override_reason):
                    blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "交易教练过滤：若要覆盖需设置coach_override=true并填写override_reason"})
                    continue
            coach_ok, coach_reason = trading_coach_allows_buy(state, order, q, trading_coach, ai_buy_raw_map.get(sym))
            if not coach_ok:
                override_requested = bool(order.get("coach_override")) and bool(str(order.get("override_reason") or "").strip())
                override_allowed = TRADING_COACH_ALLOW_OVERRIDE and AI_BUY_MODE == "ai_guided" and plan_source not in RULE_BUY_SOURCES and sym in ai_buy_raw_symbols
                if not (override_allowed and override_requested):
                    blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": coach_reason})
                    continue
                order["reason"] = f"{order.get('reason', '')}；覆盖交易教练：{order.get('override_reason')}".strip("；")
            announcement_risk = announcement_risk_for_symbol(sym, force=True)
            if announcement_risk.get("blocked"):
                state.setdefault("announcement_risks", {})[sym] = announcement_risk
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": str(announcement_risk.get("reason") or "公告风险")})
                continue
            ok, guard_reason = ai_buy_guardrail({**q, **(ai_buy_raw_map.get(sym) or {})}, check_announcements=False)
            if not ok:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": f"硬风控拦截：{guard_reason}"})
                continue
            if sym in positions:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": "已有持仓，不重复买入"})
                continue
            if len(positions) >= MAX_POSITIONS:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": f"仓位已满：{len(positions)}/{MAX_POSITIONS}"})
                continue
            price = to_float(q.get("ask1"), 0.0) or to_float(q.get("price"), 0.0)
            source = "ask1" if to_float(q.get("ask1"), 0.0) > 0 else "last_price"
            budget = min(cash, PER_POSITION_CASH, to_float(order.get("budget_cash"), PER_POSITION_CASH))
            qty = lot_qty(budget, price)
            if qty <= 0:
                continue
            amount = qty * price
            cash -= amount
            positions[sym] = {
                "symbol": sym,
                "name": q.get("name", ""),
                "qty": qty,
                "avg_cost": price,
                "last_price": price,
                "opened_at": now_iso(),
                "trade_date": market_clock().date().isoformat(),
                "source": plan.get("source"),
            }
        elif action == "SELL":
            pos = positions.get(sym)
            if not pos:
                continue
            if is_same_trade_day(pos.get("opened_at")):
                continue
            early_block = early_sell_block_reason(pos, q)
            if early_block:
                blocked_orders.append({**order, "action": action, "symbol": sym, "blocked_reason": early_block})
                continue
            price = to_float(q.get("bid1"), 0.0) or to_float(q.get("price"), 0.0)
            source = "bid1" if to_float(q.get("bid1"), 0.0) > 0 else "last_price"
            qty = min(int(order.get("qty") or pos.get("qty") or 0), int(pos.get("qty") or 0))
            qty = int(math.floor(qty / 100) * 100)
            if qty <= 0:
                continue
            amount = qty * price
            cash += amount
            if qty >= int(pos.get("qty") or 0):
                positions.pop(sym, None)
            else:
                pos["qty"] = int(pos.get("qty") or 0) - qty
                pos["last_price"] = price
        else:
            continue
        rec = {"time": now_iso(), "side": action, "symbol": sym, "name": q.get("name", ""), "qty": qty, "price": price, "price_source": source, "amount": amount, "reason": order.get("reason", ""), "ai_source": plan.get("source", "")}
        if action == "BUY":
            candidate_meta = annotate_candidate_style(ai_buy_raw_map.get(sym) or ai_buy_map.get(sym) or {})
            rec["yesterday_limit_up"] = bool(candidate_meta.get("yesterday_limit_up"))
            rec["real_pullback"] = bool(candidate_meta.get("real_pullback"))
            rec["ai_pool_source"] = candidate_meta.get("ai_pool_source", "")
        state.setdefault("trades", []).append(rec)
        state.setdefault("orders", []).append({**rec, "status": "FILLED"})
        actions.append(rec)
    state["cash"] = cash
    state["trades"] = state.get("trades", [])[-200:]
    state["orders"] = state.get("orders", [])[-200:]
    summary = str(plan.get("summary", "") or "")
    if blocked_orders:
        summary = f"{summary} 已拦截{len(blocked_orders)}笔越界买入。".strip()
    state.setdefault("decisions", []).append({"time": now_iso(), "summary": summary, "source": plan.get("source"), "orders": plan.get("orders", []), "blocked_orders": blocked_orders, "actions": actions})
    state["decisions"] = state.get("decisions", [])[-120:]
    return actions


def run_one_cycle(force_ai: bool = False) -> None:
    acquired = False
    try:
        if not CYCLE_LOCK.acquire(blocking=False):
            with LOCK:
                state = load_state()
                append_log(state, "AI决策请求已收到，但当前已有行情扫描/AI决策在运行，本次跳过。")
                save_state(state)
            return
        acquired = True
        market_open = update_market_runtime()
        maybe_run_daily_review()
        if not market_open:
            return
        with LOCK:
            state = load_state()
            watchlist = dedupe_symbols(state.get("watchlist") or DEFAULT_WATCHLIST)
            positions = list((state.get("positions") or {}).keys())
            scan_rounds = 4 if force_ai else 1
            scan_symbols: list[str] = []
            for _ in range(scan_rounds):
                scan_symbols.extend(get_market_scan_symbols(state, MARKET_SCAN_BATCH_SIZE))
            scan_symbols = dedupe_symbols(watchlist + positions + scan_symbols)
            RUNTIME["market_scan_total"] = len(MARKET_UNIVERSE)
            RUNTIME["market_scan_batch_size"] = MARKET_SCAN_BATCH_SIZE
            save_state(state)
        quotes = fetch_sina_quotes(scan_symbols)
        should_refresh_strategy = False
        strategy_snapshot: dict[str, Any] | None = None
        with LOCK:
            state = load_state()
            MARKET_QUOTE_CACHE.update(quotes)
            state.setdefault("quotes", {}).update(quotes)
            refresh_state_quotes(state, quotes)
            state["candidates"] = rank_candidates(MARKET_QUOTE_CACHE)
            state["candidates"] = state["candidates"][:200]
            last_strategy = str(state.get("strategy_last_scan_at") or "")
            should_refresh_strategy = force_ai or not last_strategy
            if last_strategy and not force_ai:
                try:
                    should_refresh_strategy = time.time() - datetime.fromisoformat(last_strategy).timestamp() >= 90
                except Exception:
                    should_refresh_strategy = True
            if should_refresh_strategy:
                strategy_snapshot = json.loads(json.dumps(state, ensure_ascii=False))
            else:
                state["ai_buy_candidates"] = build_ai_buy_candidates(state)
                state["strategy_diagnostics"] = build_strategy_diagnostics(state)
            RUNTIME["last_quote_at"] = now_iso()
            RUNTIME["market_scan_cursor"] = int(state.get("market_scan_cursor") or 0)
            risk_count = len(state.get("announcement_risks") or {})
            risk_text = f"，公告风险拦截 {risk_count} 只" if risk_count else ""
            append_log(state, f"行情扫描：{len(quotes)} 只，候选池 {len(state.get('candidates', []))} 只{risk_text}")
            save_state(state)
        if should_refresh_strategy and strategy_snapshot is not None:
            previous_right_side = list(strategy_snapshot.get("right_side_watchlist") or [])
            strategy_snapshot["strategy_signals"] = build_morning_rebound_signals(strategy_snapshot)[:50]
            strategy_snapshot["strategy_watchlist"] = build_ai_n_shape_candidates(strategy_snapshot)[:50]
            strategy_snapshot["right_side_watchlist"] = build_right_side_candidates(strategy_snapshot)[:50]
            if not strategy_snapshot["right_side_watchlist"] and previous_right_side:
                strategy_snapshot["right_side_watchlist"] = previous_right_side[:50]
                append_log(strategy_snapshot, "热门龙头池：本轮资金流源不可用，保留上一轮有效候选池。")
            strategy_snapshot["ai_buy_candidates"] = build_ai_buy_candidates(strategy_snapshot)
            strategy_snapshot["strategy_diagnostics"] = build_strategy_diagnostics(strategy_snapshot)
            strategy_snapshot["strategy_last_scan_at"] = now_iso()
            strategy_snapshot["t_signals"] = build_t_signals(strategy_snapshot)
            cached_flow = dict(FUND_FLOW_CACHE.get("rows") or {})
            if cached_flow:
                strategy_snapshot["fund_flow_snapshot"] = {
                    "time": now_iso(),
                    "rows": cached_flow,
                }
            with LOCK:
                state = load_state()
                for key in ("strategy_signals", "strategy_watchlist", "right_side_watchlist", "ai_buy_candidates", "strategy_diagnostics", "strategy_last_scan_at", "fund_flow_snapshot", "t_signals"):
                    state[key] = strategy_snapshot.get(key)
                save_state(state)
        if not RUNTIME.get("watching") and not force_ai:
            return
        last = RUNTIME.get("last_decision_at") or ""
        due = force_ai or not last
        if last and not force_ai:
            try:
                due = time.time() - datetime.fromisoformat(last).timestamp() >= AI_INTERVAL_SEC
            except Exception:
                due = True
        if not due:
            return
        with LOCK:
            state = load_state()
            RUNTIME["running"] = True
            RUNTIME["deepseek_enabled"] = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
            save_state(state)
        rule_plan = morning_rebound_plan(state)
        if rule_plan is not None:
            hydrate_execution_quotes(state, rule_plan)
            with LOCK:
                current_state = load_state()
                current_state.setdefault("quotes", {}).update(state.get("quotes") or {})
                state = current_state
                if rule_plan.get("orders"):
                    actions = execute_plan(state, rule_plan)
                    append_log(state, f"规则策略({rule_plan.get('source')}): {rule_plan.get('summary', '')}，成交 {len(actions)} 笔")
                else:
                    append_log(state, f"规则策略({rule_plan.get('source')}): {rule_plan.get('summary', '')}，无成交")
                save_state(state)

        plan = deepseek_plan(state)
        if plan is None:
            deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if os.environ.get("ALLOW_LOCAL_AI", "").strip() == "1":
                plan = local_ai_plan(state)
            elif deepseek_key:
                detail = RUNTIME.get("deepseek_last_error") or "未知原因"
                plan = {"source": f"{AI_PROVIDER_LABEL}_failed", "summary": f"{AI_PROVIDER_LABEL} 调用失败：{detail}；严格模式下只刷新行情，不自动交易。", "orders": []}
            else:
                plan = {"source": f"{AI_PROVIDER_LABEL}_missing", "summary": f"{AI_PROVIDER_LABEL} API Key 未配置；严格模式下只刷新行情，不自动交易。", "orders": []}
        hydrate_execution_quotes(state, plan)
        with LOCK:
            current_state = load_state()
            current_state.setdefault("quotes", {}).update(state.get("quotes") or {})
            state = current_state
            actions = execute_plan(state, plan)
            append_log(state, f"AI决策({plan.get('source')}): {plan.get('summary', '')}，成交 {len(actions)} 笔")
            RUNTIME["last_decision_at"] = now_iso()
            RUNTIME["last_error"] = ""
            save_state(state)
    except Exception as exc:
        with LOCK:
            state = load_state()
            RUNTIME["last_error"] = str(exc)
            append_log(state, f"AI决策失败：{exc}")
            save_state(state)
    finally:
        RUNTIME["running"] = False
        if acquired:
            CYCLE_LOCK.release()


def watch_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            now = datetime.now()
            review_at = next_review_time(now)
            if now < review_at:
                review_delay = max(1.0, (review_at - now).total_seconds())
            else:
                review_delay = max(1.0, QUOTE_INTERVAL_SEC)
            if update_market_runtime():
                run_one_cycle(False)
                STOP_EVENT.wait(max(1.0, QUOTE_INTERVAL_SEC))
            else:
                maybe_run_daily_review(now)
                next_wake = min(
                    max(30.0, (get_next_market_open(now) - now).total_seconds()),
                    review_delay,
                )
                STOP_EVENT.wait(next_wake)
        except Exception as exc:
            with LOCK:
                RUNTIME["last_error"] = str(exc)


def blogger_watch_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            poll_blogger_posts(False)
        except Exception as exc:
            with LOCK:
                state = load_state()
                RUNTIME["blogger_last_check_at"] = now_iso()
                RUNTIME["blogger_last_error"] = str(exc)
                append_log(state, f"博主新帖检查异常：{exc}")
                save_state(state)
        STOP_EVENT.wait(THS_BLOGGER_INTERVAL_SEC)


def holdings_watch_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            poll_influencer_holdings(False)
        except Exception as exc:
            with LOCK:
                state = load_state()
                RUNTIME["holdings_last_check_at"] = now_iso()
                RUNTIME["holdings_last_error"] = str(exc)
                append_log(state, f"游神持仓检查异常：{exc}")
                save_state(state)
        STOP_EVENT.wait(THS_HOLDINGS_INTERVAL_SEC)


def start_thread() -> None:
    global WATCH_THREAD_STARTED, BLOGGER_THREAD_STARTED, HOLDINGS_THREAD_STARTED
    try:
        RUNTIME["watching"] = bool(load_state().get("watching_enabled"))
    except Exception:
        pass
    if not WATCH_THREAD_STARTED:
        try:
            import nautilus_trader
            RUNTIME["nautilus_ok"] = True
            RUNTIME["nautilus_version"] = getattr(nautilus_trader, "__version__", "installed")
        except Exception as exc:
            RUNTIME["nautilus_ok"] = False
            RUNTIME["nautilus_version"] = str(exc)
        threading.Thread(target=watch_loop, daemon=True, name="ai-paper-watch-loop").start()
        WATCH_THREAD_STARTED = True
    if THS_BLOGGER_ENABLED and not BLOGGER_THREAD_STARTED:
        threading.Thread(target=blogger_watch_loop, daemon=True, name="ths-blogger-watch-loop").start()
        BLOGGER_THREAD_STARTED = True
    if THS_HOLDINGS_ENABLED and not HOLDINGS_THREAD_STARTED:
        threading.Thread(target=holdings_watch_loop, daemon=True, name="ths-holdings-watch-loop").start()
        HOLDINGS_THREAD_STARTED = True


def run_manual_decision_async() -> None:
    try:
        run_one_cycle(True)
    except Exception as exc:
        with LOCK:
            state = load_state()
            append_log(state, f"手动AI决策异常：{type(exc).__name__}: {exc}")
            save_state(state)


def maybe_kick_stale_watchdog(state: dict[str, Any]) -> bool:
    if not RUNTIME.get("watching") or CYCLE_LOCK.locked():
        return False
    market_open, _, _ = market_status()
    if not market_open:
        return False
    last_quote = str(RUNTIME.get("last_quote_at") or "")
    last_state_scan = str(state.get("strategy_last_scan_at") or "")
    newest_text = max(last_quote, last_state_scan)
    stale = True
    if newest_text:
        try:
            stale = time.time() - datetime.fromisoformat(newest_text).timestamp() > max(30.0, QUOTE_INTERVAL_SEC * 4)
        except Exception:
            stale = True
    if not stale:
        return False
    threading.Thread(target=run_manual_decision_async, daemon=True, name="watchdog-ai-cycle").start()
    return True


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    size = int(handler.headers.get("Content-Length", "0") or 0)
    if size <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(size).decode("utf-8"))
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{now_iso()}] {fmt % args}")

    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def serve_static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        f = STATIC / rel
        if not f.exists():
            self.send_json({"error": "not found"}, 404)
            return
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}.get(f.suffix, "application/octet-stream")
        self.send_bytes(f.read_bytes(), ctype)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/blogger-alerts":
            with LOCK:
                state = load_state()
                payload = {
                    "runtime": {
                        "blogger_enabled": THS_BLOGGER_ENABLED,
                        "blogger_user_id": THS_BLOGGER_USER_ID,
                        "blogger_last_check_at": RUNTIME.get("blogger_last_check_at", ""),
                        "blogger_last_error": RUNTIME.get("blogger_last_error", ""),
                        "blogger_need_cookie": RUNTIME.get("blogger_need_cookie", False),
                    },
                    "alerts": (state.get("blogger_alerts") or [])[-8:],
                    "posts": (state.get("blogger_posts") or [])[-12:],
                }
            self.send_json(payload)
            return
        if path == "/api/status":
            lock_acquired = LOCK.acquire(timeout=0.05)
            try:
                state = load_state()
                if state.get("watching_enabled"):
                    RUNTIME["watching"] = True
                update_market_runtime()
                RUNTIME["blogger_enabled"] = THS_BLOGGER_ENABLED
                RUNTIME["blogger_user_id"] = THS_BLOGGER_USER_ID
                RUNTIME["blogger_interval_sec"] = THS_BLOGGER_INTERVAL_SEC
                RUNTIME["holdings_enabled"] = THS_HOLDINGS_ENABLED
                RUNTIME["holdings_share_id"] = THS_HOLDINGS_SHARE_ID
                RUNTIME["holdings_interval_sec"] = THS_HOLDINGS_INTERVAL_SEC
                RUNTIME["ai_buy_enabled"] = AI_BUY_ENABLED
                RUNTIME["ai_buy_mode"] = AI_BUY_MODE
                RUNTIME["sellable_position_count"] = len(sellable_position_symbols(state))
                RUNTIME["ai_buy_blocked_no_sellable"] = no_sellable_position_buy_locked(state)
                kicked_watchdog = maybe_kick_stale_watchdog(state)
                if kicked_watchdog:
                    append_log(state, "盯盘watchdog：检测到行情扫描/AI决策停滞，已后台补跑一轮。")
                    save_state(state)
                runtime_snapshot = dict(RUNTIME)
            finally:
                if lock_acquired:
                    LOCK.release()
            refreshed_symbols = refresh_position_quotes_if_stale(state)
            if refreshed_symbols:
                refreshed_quotes = {
                    sym: (state.get("quotes") or {}).get(sym)
                    for sym in refreshed_symbols
                    if (state.get("quotes") or {}).get(sym)
                }
                with LOCK:
                    latest_state = load_state()
                    latest_state.setdefault("quotes", {}).update(refreshed_quotes)
                    for sym, quote in refreshed_quotes.items():
                        pos = (latest_state.get("positions") or {}).get(sym)
                        if pos:
                            pos["last_price"] = to_float(quote.get("price"), to_float(pos.get("last_price"), pos.get("avg_cost")))
                            pos["last_quote_time"] = quote.get("quote_time", "")
                    append_log(latest_state, f"刷新持仓行情：{len(refreshed_quotes)} 只")
                    save_state(latest_state)
                    state = latest_state
            account = account_snapshot(state)
            t_signals = build_t_signals(state)
            if t_signals != (state.get("t_signals") or []):
                with LOCK:
                    latest_state = load_state()
                    latest_state["t_signals"] = t_signals
                    save_state(latest_state)
                    state = latest_state
                    account = account_snapshot(state)
            market_indices = cached_market_index_snapshot()
            market_intraday = build_market_intraday_snapshot(market_indices)
            market_regime = cached_market_regime_snapshot()
            display_state = dict(state)
            display_state["orders"] = (state.get("orders") or [])[-50:]
            display_state["trades"] = (state.get("trades") or [])[-50:]
            display_state["decisions"] = (state.get("decisions") or [])[-30:]
            display_state["logs"] = (state.get("logs") or [])[-40:]
            display_state["candidates"] = (state.get("candidates") or [])[:50]
            display_state["right_side_watchlist"] = (state.get("right_side_watchlist") or [])[:50]
            display_state["quotes"] = {}
            display_state["reviews"] = [sanitize_review_t1_language(item) for item in (state.get("reviews") or [])[-12:]]
            display_state["blogger_posts"] = []
            display_state["blogger_alerts"] = []
            display_state["blogger_seen_ids"] = []
            display_state["influencer_holdings"] = {}
            display_state["influencer_holding_alerts"] = []
            payload = {
                "runtime": runtime_snapshot,
                "account": account,
                "market_regime": market_regime,
                "market_indices": market_indices,
                "market_intraday": market_intraday,
                "return_stats": build_return_stats(state, account),
                "state": display_state,
                "quote_interval_sec": QUOTE_INTERVAL_SEC,
                "ai_interval_sec": AI_INTERVAL_SEC,
            }
            self.send_json(payload)
            return
        if path == "/" or path.startswith("/static/"):
            self.serve_static(path.replace("/static/", "", 1) if path.startswith("/static/") else "index.html")
            return
        self.serve_static(path)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/start":
            with LOCK:
                state = load_state()
                state["watching_enabled"] = True
                append_log(state, "盯盘已开启")
                save_state(state)
            RUNTIME["watching"] = True
            run_one_cycle(True)
            self.send_json({"ok": True})
            return
        if path == "/api/stop":
            with LOCK:
                state = load_state()
                state["watching_enabled"] = False
                append_log(state, "盯盘已暂停")
                save_state(state)
            RUNTIME["watching"] = False
            self.send_json({"ok": True})
            return
        if path == "/api/decide":
            with LOCK:
                state = load_state()
                if CYCLE_LOCK.locked():
                    append_log(state, "手动AI决策已点击，但当前已有行情扫描/AI决策在运行，请稍等。")
                    save_state(state)
                    self.send_json({"ok": True, "queued": False, "reason": "cycle_running"})
                    return
                append_log(state, f"手动AI决策已排队，后台正在刷新候选池并等待{AI_PROVIDER_LABEL}返回。")
                save_state(state)
            threading.Thread(target=run_manual_decision_async, daemon=True, name="manual-ai-decision").start()
            self.send_json({"ok": True, "queued": True})
            return
        if path == "/api/ask":
            body = read_body(self)
            question = str(body.get("question") or "").strip()
            local_only = bool(body.get("local_only"))
            if not question:
                self.send_json({"error": "question required"}, 400)
                return
            with LOCK:
                state_snapshot = json.loads(json.dumps(load_state(), ensure_ascii=False))
            symbols = resolve_question_symbols(question, state_snapshot)
            fetched: dict[str, dict[str, Any]] = {}
            if symbols:
                try:
                    fetched = fetch_sina_quotes(symbols)
                except Exception as exc:
                    RUNTIME["last_error"] = f"问股行情失败：{type(exc).__name__}: {exc}"
            with LOCK:
                state = load_state()
                if fetched:
                    MARKET_QUOTE_CACHE.update(fetched)
                    quotes = state.setdefault("quotes", {})
                    quotes.update(fetched)
                    save_state(state)
                state_snapshot = json.loads(json.dumps(state, ensure_ascii=False))
            use_grounded_local = asks_for_buy_rationale(question) and bool(build_purchase_context(state_snapshot, symbols))
            answer = local_ai_ask_answer(question, state_snapshot) if (local_only or use_grounded_local) else (deepseek_ai_ask(question, state_snapshot) or local_ai_ask_answer(question, state_snapshot))
            record = {
                "time": now_iso(),
                "question": question,
                "source": answer.get("source", "local"),
                "answer": answer.get("answer", ""),
                "symbols": answer.get("symbols", symbols),
                "symbol_context": answer.get("symbol_context", []),
                "purchase_context": answer.get("purchase_context", []),
                "analysis_steps": answer.get("analysis_steps", []),
                "ask_intent": answer.get("ask_intent", ask_intent(question)),
                "verdict": answer.get("verdict", ""),
                "risk_points": answer.get("risk_points", []),
            }
            with LOCK:
                state = load_state()
                history = list(state.get("ai_ask_history") or [])
                history.append(record)
                state["ai_ask_history"] = history[-50:]
                append_log(state, f"AI问股：{question[:80]}")
                save_state(state)
            self.send_json({"ok": True, "answer": record})
            return
        if path == "/api/watchlist":
            body = read_body(self)
            symbols = [normalize_symbol(x) for x in body.get("symbols", []) if normalize_symbol(x)]
            with LOCK:
                state = load_state()
                state["watchlist"] = symbols or DEFAULT_WATCHLIST
                save_state(state)
            self.send_json({"ok": True})
            return
        self.send_json({"error": "not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    start_thread()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI paper dashboard: http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
