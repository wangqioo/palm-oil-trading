"""
期货交易看板 — Flask API 服务（多品种支持）
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from datetime import datetime
import pandas as pd

app = Flask(__name__, static_folder="dashboard")
CORS(app)

PERIOD_MAP = {'1': '1', '5': '5', '15': '15', '30': '30', '60': '60'}

# ── 品种配置表 ────────────────────────────────────────────────────
# sina_code: 新浪财经分钟线代码（小写）
# daily_code: 新浪财经日线代码
# warmup_codes: 历史合约列表（早→新），用于指标预热
# name: 显示名称
SYMBOLS = {
    'P2609': {
        'name': '棕榈油2609', 'type': 'futures',
        'sina_code': 'p2609',
        'daily_code': 'P2609',
        'warmup_codes': [
            'P1905','P1909','P2001','P2005','P2009',
            'P2101','P2105','P2109','P2201','P2205','P2209',
            'P2301','P2305','P2309','P2401','P2405','P2409',
            'P2501','P2505','P2509','P2601','P2605','P2609',
        ],
    },
    'AG2606': {
        'name': '白银2606', 'type': 'futures',
        'sina_code': 'ag2606',
        'daily_code': 'AG2606',
        'warmup_codes': [
            'AG2206','AG2209','AG2212','AG2303','AG2306','AG2309','AG2312',
            'AG2403','AG2406','AG2409','AG2412','AG2503','AG2506','AG2509','AG2512',
            'AG2603','AG2606',
        ],
    },
    'BC2505': {
        'name': '国际铜2505', 'type': 'futures',
        'sina_code': 'bc2505',
        'daily_code': 'BC2505',
        'warmup_codes': ['BC2209','BC2212','BC2303','BC2306','BC2309','BC2312',
                         'BC2403','BC2406','BC2409','BC2412','BC2503','BC2505'],
    },
    'CU2505': {
        'name': '铜2505', 'type': 'futures',
        'sina_code': 'cu2505',
        'daily_code': 'CU2505',
        'warmup_codes': [
            'CU2006','CU2009','CU2012','CU2103','CU2106','CU2109','CU2112',
            'CU2203','CU2206','CU2209','CU2212','CU2303','CU2306','CU2309','CU2312',
            'CU2403','CU2406','CU2409','CU2412','CU2503','CU2505',
        ],
    },
    'SA2509': {
        'name': '纯碱2509', 'type': 'futures',
        'sina_code': 'sa2509',
        'daily_code': 'SA2509',
        'warmup_codes': [
            'SA2101','SA2105','SA2109','SA2201','SA2205','SA2209','SA2301',
            'SA2305','SA2309','SA2401','SA2405','SA2409','SA2501','SA2505','SA2509',
        ],
    },
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(CACHE_DIR, exist_ok=True)

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

def get_minute_data(sina_code, period='15'):
    import akshare as ak
    p = PERIOD_MAP.get(str(period), '15')
    try:
        df = ak.futures_zh_minute_sina(symbol=sina_code, period=p)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('date').reset_index(drop=True)
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df
    except Exception as e:
        print(f'{sina_code} {p}分钟数据失败: {e}')
        return None

def get_daily_data(symbol_cfg):
    import akshare as ak
    code = symbol_cfg['daily_code']
    cache_key = f"daily_{code}"
    try:
        df = ak.futures_zh_daily_sina(symbol=code)
        if df is None or df.empty: raise ValueError("空数据")
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        _save_cache(cache_key, df)
        print(f"{code}: {len(df)} 条，收={df['close'].iloc[-1]:.0f}")
        return df
    except Exception as e:
        print(f"{code} 日线失败: {e}，用缓存")
        return _load_cache(cache_key)

def get_warmup_data(symbol_cfg):
    import akshare as ak
    codes = symbol_cfg.get('warmup_codes', [])
    cache_key = f"warmup_{symbol_cfg['daily_code']}"
    cached = _load_cache(cache_key)
    if cached is not None and len(cached) > 0:
        return cached
    frames = []
    for c in codes:
        try:
            df = ak.futures_zh_daily_sina(symbol=c)
            if df is not None and not df.empty:
                df.columns = [c2.lower() for c2 in df.columns]
                df["date"] = pd.to_datetime(df["date"])
                frames.append(df)
        except Exception:
            pass
    if not frames: return None
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    _save_cache(cache_key, combined)
    print(f"预热({symbol_cfg['daily_code']}): {len(combined)} 条")
    return combined

def resample_weekly(df):
    df = df.copy().set_index('date')
    w = df.resample('W').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna(subset=['open'])
    w.index = w.index - pd.tseries.frequencies.to_offset('6D')
    return w.reset_index().rename(columns={'index':'date'})

def resample_monthly(df):
    df = df.copy().set_index('date')
    m = df.resample('MS').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna(subset=['open'])
    return m.reset_index().rename(columns={'index':'date'})

# ── 核心数据计算 ──────────────────────────────────────────────────

def get_data(symbol='P2609', period='15', name=None):
    from data_fetcher import calculate_support_resistance, calculate_capital_flow
    from indicators import get_latest_signals, calc_main_signals, calc_bsd_wang

    sym = SYMBOLS.get(symbol)
    # 动态合约：不在 SYMBOLS 表，自动构造配置
    if sym is None:
        sym = {
            'name': name or symbol,
            'sina_code': symbol.lower(),
            'daily_code': symbol,
            'warmup_codes': [],
        }

    is_minute = str(period) not in ('daily', 'weekly', 'monthly')
    display_limit = 99999

    # 获取展示数据和预热数据
    daily = get_daily_data(sym)
    if is_minute:
        display_df = get_minute_data(sym['sina_code'], period)
        warmup_df = None
    elif period == 'daily':
        display_df = daily
        warmup_df = get_warmup_data(sym)
    elif period == 'weekly':
        display_df = resample_weekly(daily) if daily is not None else None
        wu = get_warmup_data(sym)
        warmup_df = resample_weekly(wu) if wu is not None else None
    elif period == 'monthly':
        display_df = resample_monthly(daily) if daily is not None else None
        wu = get_warmup_data(sym)
        warmup_df = resample_monthly(wu) if wu is not None else None

    if display_df is None or len(display_df) == 0:
        return {"error": "数据获取失败"}

    # 指标计算：预热数据足够时用预热，否则直接用展示数据
    if warmup_df is not None and len(warmup_df) > len(display_df):
        calc_df = warmup_df
        display_dates = set(display_df['date'].astype(str))
    else:
        calc_df = display_df
        display_dates = None

    signals, meta = get_latest_signals(calc_df)
    sr = calculate_support_resistance(daily if daily is not None else display_df)
    cf = calculate_capital_flow(daily if daily is not None else display_df)

    df2 = calc_bsd_wang(calc_main_signals(calc_df))
    if display_dates is not None:
        df2 = df2[df2['date'].astype(str).isin(display_dates)].reset_index(drop=True)

    df2["bsd_bull"] = (df2["K"] > 30) & (df2["K"] >= df2["D"])
    df2["bsd_bear"] = (df2["K"] < 80) & (df2["K"] <= df2["D"])
    df2["做多"] = df2["破浪"] & df2["bsd_bull"]
    df2["离场"] = df2["空仓"] & df2["bsd_bear"]

    history = []
    for _, r in df2[df2["做多"] | df2["离场"]].tail(10).iterrows():
        sigs = []
        if r["做多"]: sigs.append("▲做多")
        if r["离场"]: sigs.append("▼离场")
        history.append({"date": str(r["date"])[:10], "close": round(float(r["close"]), 0),
                         "K": round(float(r["K"]), 1), "signal": " ".join(sigs)})

    levels_sorted = []
    if sr:
        cur = sr["current_price"]
        for name, val in sorted(sr["levels"].items(), key=lambda x: -x[1]):
            levels_sorted.append({"name": name, "value": val, "current": abs(val - cur) < 30})

    indicator_series = []
    df2_tail = df2.tail(display_limit).reset_index(drop=True)
    for i, r in df2_tail.iterrows():
        ts = int(pd.Timestamp(r["date"]).timestamp())
        prev = df2_tail.iloc[i - 1] if i > 0 else None
        def rising(col):
            if prev is None: return False
            v, pv = r.get(col), prev.get(col)
            try: return float(v) > float(pv)
            except: return False
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
    symbol = request.args.get('symbol', 'P2609')
    name   = request.args.get('name', None)
    try:
        data = get_data(symbol=symbol, period=period, name=name)
        if data is None:
            return jsonify({"error": "数据获取失败"}), 500
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


@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")

if __name__ == "__main__":
    print("启动看板服务: http://localhost:8877")
    app.run(host="0.0.0.0", port=8877, debug=False)
