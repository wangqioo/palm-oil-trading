"""
期货交易看板 — Flask API 服务（多品种支持）
"""
import sys, os, math, time as _time, sqlite3 as _sqlite3, threading as _threading
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from datetime import datetime
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__, static_folder="dashboard")
CORS(app)

PERIOD_MAP = {'1': '1', '5': '5', '15': '15', '30': '30', '60': '60', '120': '120'}

# 使用新浪主力连续合约（品种前缀+0），永远跟踪当前主力，无需换月维护
SYMBOLS = {
    'P0':  {'name': '棕榈油主力',  'sina_code': 'P0',  'daily_code': 'P0'},
    'AG0': {'name': '白银主力',    'sina_code': 'AG0', 'daily_code': 'AG0'},
    'BC0': {'name': '国际铜主力',  'sina_code': 'BC0', 'daily_code': 'BC0'},
    'CU0': {'name': '铜主力',      'sina_code': 'CU0', 'daily_code': 'CU0'},
    'SA0': {'name': '纯碱主力',    'sina_code': 'SA0', 'daily_code': 'SA0'},
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(CACHE_DIR, exist_ok=True)

# ── 信号数据库（去重 + 跨重启持久化） ────────────────────────────
DB_PATH = os.path.join(CACHE_DIR, "signals.db")

def _init_db():
    conn = _sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol      TEXT    NOT NULL,
        signal_type TEXT    NOT NULL,
        candle_time TEXT    NOT NULL,
        created_at  TEXT    NOT NULL,
        UNIQUE(symbol, signal_type, candle_time)
    )''')
    conn.commit()
    conn.close()

def _is_new_signal(symbol, signal_type, candle_time):
    """三字段联合去重：新信号写入DB返回True，重复返回False。"""
    try:
        conn = _sqlite3.connect(DB_PATH)
        cur  = conn.execute(
            'INSERT OR IGNORE INTO signals (symbol,signal_type,candle_time,created_at) VALUES (?,?,?,?)',
            (symbol, signal_type, candle_time, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        is_new = cur.rowcount > 0
        conn.close()
        return is_new
    except Exception as e:
        print(f"[db] {e}")
        return True  # fail open

# ── 后台扫描器 ────────────────────────────────────────────────────
_active_period      = '30'
_active_period_lock = _threading.Lock()

_PERIOD_LABEL = {
    '1':'1分','5':'5分','15':'15分','30':'30分',
    '60':'60分','120':'120分','daily':'日线','weekly':'周线',
}

def _is_kline_close(period):
    """判断当前时刻是否恰好是该周期K线的收盘时刻。"""
    now = datetime.now()
    m, h, wd = now.minute, now.hour, now.weekday()
    return {
        '1':      True,
        '5':      m % 5  == 0,
        '15':     m % 15 == 0,
        '30':     m % 30 == 0,
        '60':     m == 0,
        '120':    m == 0 and h % 2 == 0,
        'daily':  h == 15 and m == 1,
        'weekly': wd == 4 and h == 15 and m == 1,
    }.get(period, False)

def _do_scan(period):
    for sym_code, sym_cfg in SYMBOLS.items():
        try:
            data = get_data(symbol=sym_code, period=period, name=sym_cfg['name'])
            if not data or data.get('error'):
                continue
            sig         = data.get('signals', {})
            meta        = data.get('meta', {})
            candle_time = meta.get('datetime', '')
            if not candle_time:
                continue
            for sig_type in ('做多', '做空'):
                if sig.get(sig_type) and _is_new_signal(sym_code, sig_type, candle_time):
                    push_pending_signal({
                        'symbol': sym_code, 'name': sym_cfg['name'],
                        'period': period,   'sigType': sig_type,
                        'price':  meta.get('close'), 'time': candle_time,
                    })
                    print(f"[scanner] ✦ {sym_code} {_PERIOD_LABEL.get(period,period)} {sig_type} @ {candle_time}")
        except Exception as e:
            print(f"[scanner] {sym_code} 错误: {e}")

def _scanner_loop():
    _time.sleep(15)   # 等 Flask 完成启动
    while True:
        try:
            with _active_period_lock:
                period = _active_period
            ts = datetime.now().strftime('%H:%M:%S')
            if _is_kline_close(period):
                print(f"[{ts}] 扫描中... {_PERIOD_LABEL.get(period,period)}K线收盘✅ 检测信号")
                _do_scan(period)
            else:
                print(f"[{ts}] 扫描中... 未到收盘时刻 跳过")
        except Exception as e:
            print(f"[scanner] 主循环错误: {e}")
        _time.sleep(60)

def _save_cache(name, df):
    df.to_csv(os.path.join(CACHE_DIR, f"{name}.csv"), index=False)

def _load_cache(name):
    path = os.path.join(CACHE_DIR, f"{name}.csv")
    if not os.path.exists(path): return None
    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return None

def safe(v):
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except:
        return None

def clean(obj):
    if isinstance(obj, dict):  return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [clean(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return None
    if hasattr(obj, 'item'):   return obj.item()
    if isinstance(obj, bool):  return bool(obj)
    return obj

# ── 数据获取 ──────────────────────────────────────────────────────

# 分钟线内存缓存：按周期设定 TTL（秒），避免频繁重拉
_minute_cache = {}
_MINUTE_TTL = {'1': 20, '5': 60, '15': 180, '30': 300, '60': 600, '120': 1200}

# 日线内存缓存：TTL 300秒（每次请求均需日线用于支撑压力位计算）
_daily_cache = {}
_DAILY_TTL   = 300

def get_minute_data(sina_code, period='15'):
    import akshare as ak
    period = str(period)
    cache_key = (sina_code, period)
    ttl = _MINUTE_TTL.get(period, 180)
    now = _time.time()

    # 命中缓存
    if cache_key in _minute_cache:
        ts, df = _minute_cache[cache_key]
        if now - ts < ttl:
            return df

    fetch_p = '60' if period == '120' else PERIOD_MAP.get(period, '15')

    # 带重试的拉取（最多2次，间隔1秒）
    df = None
    for attempt in range(3):
        try:
            df = ak.futures_zh_minute_sina(symbol=sina_code, period=fetch_p)
            break
        except Exception as e:
            print(f'{sina_code} {period}分 第{attempt+1}次失败: {e}')
            if attempt < 2:
                _time.sleep(1)

    if df is None:
        # 返回上次缓存（哪怕已过期），降级兜底
        if cache_key in _minute_cache:
            print(f'{sina_code} {period}分 使用过期缓存')
            return _minute_cache[cache_key][1]
        return None

    try:
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('date').reset_index(drop=True)
        if 'volume' not in df.columns:
            df['volume'] = 0
        if period == '120':
            df = (df.set_index('date')
                    .resample('120min', closed='left', label='left')
                    .agg(open=('open', 'first'), high=('high', 'max'),
                         low=('low', 'min'),   close=('close', 'last'),
                         volume=('volume', 'sum'))
                    .dropna(subset=['close'])
                    .reset_index())
    except Exception as e:
        print(f'{sina_code} {period}分 处理失败: {e}')
        return _minute_cache.get(cache_key, (None, None))[1]

    _minute_cache[cache_key] = (now, df)
    return df

def get_daily_data(symbol_cfg):
    import akshare as ak
    code = symbol_cfg['daily_code']
    cache_key = f"daily_{code}"
    now = _time.time()

    if cache_key in _daily_cache:
        ts, df = _daily_cache[cache_key]
        if now - ts < _DAILY_TTL:
            return df

    for attempt in range(3):
        try:
            df = ak.futures_zh_daily_sina(symbol=code)
            if df is None or df.empty: raise ValueError("空数据")
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            _daily_cache[cache_key] = (now, df)
            _save_cache(cache_key, df)
            print(f"{code}: {len(df)} 条，收={df['close'].iloc[-1]:.0f}")
            return df
        except Exception as e:
            print(f"{code} 日线第{attempt+1}次失败: {e}")
            if attempt < 2:
                _time.sleep(1)

    print(f"{code} 日线全部失败，用过期缓存或CSV")
    if cache_key in _daily_cache:
        return _daily_cache[cache_key][1]
    return _load_cache(cache_key)


def get_weekly_data(symbol_cfg):
    daily = get_daily_data(symbol_cfg)
    if daily is None or daily.empty:
        return None
    try:
        weekly = (daily.set_index('date')
                  .resample('W-FRI', closed='right', label='right')
                  .agg(open=('open', 'first'), high=('high', 'max'),
                       low=('low', 'min'),    close=('close', 'last'),
                       volume=('volume', 'sum'))
                  .dropna(subset=['close'])
                  .reset_index())
        return weekly
    except Exception as e:
        print(f"周线聚合失败: {e}")
        return None


# ── 核心数据计算 ──────────────────────────────────────────────────

def get_data(symbol='P2609', period='15', name=None):
    from data_fetcher import calculate_support_resistance, calculate_capital_flow
    from indicators import get_latest_signals, calc_main_signals, calc_bsd_wang

    sym = SYMBOLS.get(symbol)
    # 动态合约：不在 SYMBOLS 表，自动构造配置
    if sym is None:
        sym = {
            'name': name or symbol,
            'sina_code': symbol,   # 新浪接口大小写均可
            'daily_code': symbol,
        }

    is_minute = str(period) not in ('daily', 'weekly')

    daily = get_daily_data(sym)
    if str(period) == 'weekly':
        display_df = get_weekly_data(sym)
    elif is_minute:
        display_df = get_minute_data(sym['sina_code'], period)
    else:
        display_df = daily

    if display_df is None or len(display_df) == 0:
        return {"error": "数据获取失败"}

    calc_df = display_df

    signals, meta = get_latest_signals(calc_df)
    sr = calculate_support_resistance(daily if daily is not None else display_df)
    cf = calculate_capital_flow(daily if daily is not None else display_df)

    df2 = calc_bsd_wang(calc_main_signals(calc_df))

    df2["做多"] = df2["破浪"]
    df2["做空"] = df2["空仓"]

    history = []
    for _, r in df2[df2["做多"] | df2["做空"]].tail(10).iterrows():
        sigs = []
        if r["做多"]: sigs.append("🟡 做多")
        if r["做空"]: sigs.append("🟢 做空")
        history.append({"date": str(r["date"])[:16], "close": round(float(r["close"]), 0),
                         "K": round(float(r["K"]), 1), "signal": " ".join(sigs)})

    levels_sorted = []
    if sr:
        cur = sr["current_price"]
        for name, val in sorted(sr["levels"].items(), key=lambda x: -x[1]):
            levels_sorted.append({"name": name, "value": val, "current": abs(val - cur) < 30})

    def _rising(row, prev_row, col):
        if prev_row is None: return False
        try: return float(row.get(col)) > float(prev_row.get(col))
        except: return False

    indicator_series = []
    df2_tail = df2.reset_index(drop=True)
    for i, r in df2_tail.iterrows():
        ts = int(pd.Timestamp(r["date"]).timestamp())
        prev = df2_tail.iloc[i - 1] if i > 0 else None
        def rising(col, _r=r, _p=prev): return _rising(_r, _p, col)
        indicator_series.append({
            "time": ts, "date": str(r["date"])[:16],
            "open":  safe(r.get("open",  r.get("close", 0))),
            "high":  safe(r.get("high",  r.get("close", 0))),
            "low":   safe(r.get("low",   r.get("close", 0))),
            "close": safe(r.get("close", 0)),
            "volume":safe(r.get("volume", 0)),
            "QRG":   safe(r.get("QRG", 0)),
            "K":     safe(r.get("K", 0)),
            "D":     safe(r.get("D", 0)),
            "M1": safe(r.get("M1")), "M1r": rising("M1"),
            "M2": safe(r.get("M2")), "M2r": rising("M2"),
            "M3": safe(r.get("M3")), "M3r": rising("M3"),
            "M4": safe(r.get("M4")), "M4r": rising("M4"),
            "M5": safe(r.get("M5")), "M5r": rising("M5"),
            "支撑": safe(r.get("支撑")),
            "po":   bool(r.get("破浪", False)),
            "kong": bool(r.get("空仓", False)),
        })

    return clean({
        "updated":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol":   symbol,
        "name":     sym['name'],
        "period":   str(period),
        "signals":  {k: bool(v) for k, v in signals.items()},
        "meta":     meta,
        "capital_flow": cf,
        "levels":   levels_sorted,
        "history":  list(reversed(history)),
        "indicator_series": indicator_series,
    })


@app.route("/api/data")
def api_data():
    period = request.args.get('period', '15')
    symbol = request.args.get('symbol', 'P0')
    name   = request.args.get('name', None)
    mode   = request.args.get('mode', 'full')   # full=全量 update=只返回最后3条
    try:
        data = get_data(symbol=symbol, period=period, name=name)
        if data is None:
            return jsonify({"error": "数据获取失败"}), 500
        if mode == 'update' and 'indicator_series' in data:
            data['indicator_series'] = data['indicator_series'][-3:]
        return jsonify(data)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/symbols")
def api_symbols():
    return jsonify([{"symbol": k, "name": v["name"]} for k, v in SYMBOLS.items()])

# ── 品种搜索：返回匹配的连续合约列表 ─────────────────────────────
_FUTURES_LIST = None  # 懒加载缓存

def _get_futures_list():
    global _FUTURES_LIST
    if _FUTURES_LIST is not None:
        return _FUTURES_LIST
    try:
        import akshare as ak
        df = ak.futures_display_main_sina()
        # symbol 去掉末尾 '0'，得到品种前缀（如 'P0' -> 'P'）
        df['prefix'] = df['symbol'].str.rstrip('0')
        _FUTURES_LIST = df.to_dict('records')
        return _FUTURES_LIST
    except Exception as e:
        print(f"品种列表加载失败: {e}")
        return []

@app.route("/api/search")
def api_search():
    q = request.args.get('q', '').strip().upper()
    if len(q) < 1:
        return jsonify([])
    items = _get_futures_list()
    results = []
    for it in items:
        prefix = it['prefix'].upper()
        name   = it['name']
        # 匹配：品种前缀开头 或 名称包含关键字
        if prefix.startswith(q) or q in name:
            results.append({'prefix': prefix, 'name': name.replace('连续',''), 'exchange': it['exchange']})
    return jsonify(results[:15])

@app.route("/api/resolve")
def api_resolve():
    """
    根据合约代码（如 RB2510）验证其是否存在并返回名称。
    先在 SYMBOLS 表查，否则用 AkShare 直接拉日线验证。
    """
    symbol = request.args.get('symbol', '').strip().upper()
    if not symbol:
        return jsonify({"error": "缺少 symbol"}), 400

    # 已在 SYMBOLS 表
    if symbol in SYMBOLS:
        return jsonify({"symbol": symbol, "name": SYMBOLS[symbol]['name'], "known": True})

    # 推断品种前缀 → 中文名
    items = _get_futures_list()
    import re
    m = re.match(r'^([A-Z]+)', symbol)
    prefix = m.group(1) if m else ''
    cname = ''
    for it in items:
        if it['prefix'].upper() == prefix:
            cname = it['name'].replace('连续', '')
            break

    # 尝试拉日线验证合约存在
    try:
        import akshare as ak
        df = ak.futures_zh_daily_sina(symbol=symbol)
        if df is None or df.empty:
            return jsonify({"error": f"合约 {symbol} 无数据"}), 404
        name = cname + symbol[len(prefix):] if cname else symbol
        return jsonify({"symbol": symbol, "name": name, "known": False})
    except Exception as e:
        return jsonify({"error": f"合约 {symbol} 不存在: {e}"}), 404

_trend_cache = {}   # symbol -> (timestamp, result_dict)
_TREND_TTL   = 300  # 5分钟缓存

@app.route("/api/trend")
def api_trend():
    """返回指定品种在各周期的 K/D 趋势状态（多头/空头/等待）"""
    symbol = request.args.get('symbol', 'P0')
    name   = request.args.get('name', None)

    now = _time.time()
    if symbol in _trend_cache:
        ts, cached = _trend_cache[symbol]
        if now - ts < _TREND_TTL:
            return jsonify(cached)

    sym = SYMBOLS.get(symbol)
    if sym is None:
        sym = {'name': name or symbol, 'sina_code': symbol, 'daily_code': symbol}

    from indicators import calc_main_signals, calc_bsd_wang

    PERIODS = [
        ('15',     '15分'),
        ('30',     '30分'),
        ('60',     '60分'),
        ('120',    '120分'),
        ('daily',  '日线'),
        ('weekly', '周线'),
    ]

    trend = {}
    daily_df = get_daily_data(sym)   # 日线只拉一次，各周期复用

    def _calc_one(p, lbl):
        try:
            if p == 'weekly':
                df = get_weekly_data(sym) if daily_df is not None else None
            elif p == 'daily':
                df = daily_df
            else:
                df = get_minute_data(sym['sina_code'], p)

            if df is None or len(df) < 15:
                return p, {'status': 'unknown', 'label': lbl, 'K': None, 'D': None}

            df2  = calc_bsd_wang(calc_main_signals(df))
            last = df2.iloc[-1]
            K    = round(float(last.get('K', 0)), 2)
            D    = round(float(last.get('D', 0)), 2)
            status = 'wait' if abs(K - D) < 1.0 else ('bull' if K > D else 'bear')
            return p, {'status': status, 'label': lbl, 'K': K, 'D': D}
        except Exception as e:
            print(f"trend {symbol} {p}: {e}")
            return p, {'status': 'unknown', 'label': lbl, 'K': None, 'D': None}

    # 并行拉取分钟线（日线/周线共用已拉好的 daily_df，不重复请求）
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_calc_one, p, lbl): p for p, lbl in PERIODS}
        for fut in as_completed(futures):
            p, result = fut.result()
            trend[p] = result

    result = {'symbol': symbol, 'name': sym['name'], 'trend': trend}
    _trend_cache[symbol] = (now, result)
    return jsonify(result)


# ── 后端信号队列（供扫描器写入，前端轮询） ────────────────────────
_pending_signals = []
_pending_lock    = _threading.Lock()

def push_pending_signal(signal_dict):
    """写入待通知信号（自动补 created_at）"""
    signal_dict.setdefault('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    with _pending_lock:
        _pending_signals.append(signal_dict)

@app.route("/api/signals/pending")
def api_signals_pending():
    """返回并清空待通知信号。
    ?since=YYYY-MM-DD HH:MM:SS  只返回 created_at >= since 的信号（用于页面重连过滤）
    """
    since = request.args.get('since', None)
    with _pending_lock:
        if since:
            out = [s for s in _pending_signals if s.get('created_at', '') >= since]
            for s in out:
                try: _pending_signals.remove(s)
                except ValueError: pass
        else:
            out = list(_pending_signals)
            _pending_signals.clear()
    return jsonify(out)

@app.route("/api/signals/push", methods=["POST"])
def api_push_signal():
    """外部 scheduler.py 可通过此接口推送信号"""
    body = request.get_json(force=True)
    push_pending_signal(body)
    return jsonify({"ok": True})

@app.route("/api/settings/period", methods=["GET", "POST"])
def api_period_settings():
    """GET: 查询当前扫描周期。POST body {period}: 切换扫描周期。"""
    global _active_period
    if request.method == 'POST':
        body   = request.get_json(force=True)
        period = str(body.get('period', '30'))
        if period not in _PERIOD_LABEL:
            return jsonify({"error": "无效周期"}), 400
        with _active_period_lock:
            _active_period = period
        print(f"[settings] 扫描周期切换 → {_PERIOD_LABEL.get(period, period)}")
        return jsonify({"ok": True, "period": period})
    else:
        with _active_period_lock:
            return jsonify({"period": _active_period})


@app.route("/api/indicators")
def api_indicators():
    """列出所有已加载的指标插件"""
    import indicators_pkg as ipkg
    result = []
    for name, mod in ipkg.get_all().items():
        meta = mod.META.copy()
        meta.pop('outputs', None)   # 输出列太长，不传给前端列表
        result.append(meta)
    return jsonify(result)


@app.route("/api/import_formula", methods=["POST"])
def api_import_formula():
    """
    接收 TDX 公式文本，解析后生成插件文件并热加载。
    POST body JSON: { "name": "指标名", "source": "TDX公式...", "panel": "sub" }
    """
    import re, indicators_pkg as ipkg
    from tdx_parser import TDXParser

    body = request.get_json(force=True)
    name   = body.get('name', '').strip()
    source = body.get('source', '').strip()
    panel  = body.get('panel', 'sub')

    if not name or not source:
        return jsonify({"error": "name 和 source 不能为空"}), 400

    # 生成合法文件名 id
    plugin_id = re.sub(r'[^a-z0-9_]', '_', name.lower())[:32]
    plugin_id = plugin_id.strip('_') or 'custom'

    try:
        parser = TDXParser(source)
        code   = parser.to_plugin_source(plugin_id, name, panel)
    except Exception as e:
        return jsonify({"error": f"公式解析失败: {e}"}), 400

    # 写入插件文件
    plugin_dir  = os.path.join(os.path.dirname(__file__), 'indicators_pkg')
    plugin_path = os.path.join(plugin_dir, f'{plugin_id}.py')
    with open(plugin_path, 'w', encoding='utf-8') as f:
        f.write(code)

    # 热加载
    ipkg.reload_all()

    return jsonify({"ok": True, "id": plugin_id, "name": name,
                    "outputs": parser.build_meta_outputs()})


@app.route("/api/test/signal", methods=["POST"])
def api_test_signal():
    """测试用：直接注入一条信号到队列，前端立即消费。
    sigType 支持 'long'/'做多' 和 'short'/'做空'，避免编码问题。
    """
    body = request.get_json(force=True)
    # 归一化 sigType：接受英文/中文两种写法
    raw = body.get('sigType', 'short')
    if raw in ('long', 'buy', '做多', 'LONG'):
        body['sigType'] = '做多'
    else:
        body['sigType'] = '做空'
    body.setdefault('symbol', 'P0')
    body.setdefault('name',   '棕榈油主力')
    body.setdefault('period', '30')
    body.setdefault('price',  9781)
    body.setdefault('time',   datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    push_pending_signal(body)
    return jsonify({"ok": True, "sigType": body['sigType'], "period": body['period']})


@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")

if __name__ == "__main__":
    _init_db()
    _threading.Thread(target=_scanner_loop, daemon=True).start()
    print("启动看板服务: http://localhost:8877")
    app.run(host="0.0.0.0", port=8877, debug=False, threaded=True)
