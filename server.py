"""
棕榈油交易看板 — Flask API 服务
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from datetime import datetime
import json

app = Flask(__name__, static_folder="dashboard")
CORS(app)

LOG_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base", "signals", "signal_log.csv")


PERIOD_MAP = {'1': '1', '5': '5', '15': '15', '30': '30', '60': '60'}

def get_minute_data(period='15', limit=200):
    """获取分钟K线（period: 1/5/15/30/60）"""
    import akshare as ak
    import pandas as pd
    p = PERIOD_MAP.get(str(period), '15')
    try:
        df = ak.futures_zh_minute_sina(symbol='p2609', period=p)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('date').tail(limit).reset_index(drop=True)
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df
    except Exception as e:
        print(f'{p}分钟数据失败: {e}')
        return None

def get_15min_data(limit=200):
    return get_minute_data('15', limit)


def get_data(period='15'):
    from data_fetcher import (
        get_palm_oil_data_akshare, get_crude_oil_data_akshare,
        calculate_support_resistance, calculate_capital_flow, compare_palm_crude
    )
    from indicators import get_latest_signals, calc_main_signals, calc_bsd_wang
    import pandas as pd

    # 分钟数据用于指标计算和信号检测
    if str(period) == 'daily':
        palm_15m = None
    else:
        palm_15m = get_minute_data(period=period, limit=200)
    # 日线数据用于支撑压力、资金流、原油对比
    palm = get_palm_oil_data_akshare(days=80)
    crude = get_crude_oil_data_akshare(days=30)

    # 指标和信号优先用15分钟，回退到日线
    indicator_df = palm_15m if palm_15m is not None else palm

    if indicator_df is None:
        return None

    signals, meta = get_latest_signals(indicator_df)
    sr = calculate_support_resistance(palm if palm is not None else indicator_df)
    cf = calculate_capital_flow(palm if palm is not None else indicator_df)
    cmp = compare_palm_crude(palm, crude)

    # 历史信号（15分钟）
    df2 = calc_bsd_wang(calc_main_signals(indicator_df))
    df2["bsd_bull"] = (df2["K"] > 30) & (df2["K"] >= df2["D"])
    df2["bsd_bear"] = (df2["K"] < 80) & (df2["K"] <= df2["D"])
    df2["做多"] = df2["破浪"] & df2["bsd_bull"]
    df2["离场"] = df2["空仓"] & df2["bsd_bear"]
    hist_hits = df2[df2["做多"] | df2["离场"]].tail(10)
    history = []
    for _, r in hist_hits.iterrows():
        sigs = []
        if r["做多"]: sigs.append("▲做多")
        if r["离场"]: sigs.append("▼离场")
        history.append({
            "date": str(r["date"])[:10],
            "close": round(float(r["close"]), 0),
            "K": round(float(r["K"]), 1),
            "signal": " ".join(sigs)
        })

    # K线数据（近60根15分钟）
    kline = []
    src = indicator_df if indicator_df is not None else palm
    for _, r in src.tail(60).iterrows():
        kline.append({
            "date": str(r["date"])[:10],
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]),   "close": float(r["close"]),
            "volume": float(r.get("volume", 0))
        })

    # 指标序列（近60根15分钟）+ 黄点绿点标注
    import math
    def safe(v):
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
        except:
            return None

    indicator_series = []
    for _, r in df2.tail(60).iterrows():
        ts = int(pd.Timestamp(r["date"]).timestamp())
        indicator_series.append({
            "time":   ts,
            "date":   str(r["date"])[:16],
            "open":   safe(r.get("open",  r.get("close", 0))),
            "high":   safe(r.get("high",  r.get("close", 0))),
            "low":    safe(r.get("low",   r.get("close", 0))),
            "close":  safe(r.get("close", 0)),
            "volume": safe(r.get("volume", 0)),
            "QRG":    safe(r.get("QRG", 0)),
            "K":      safe(r.get("K", 0)),
            "D":      safe(r.get("D", 0)),
            "po":     bool(r.get("破浪", False)),
            "kong":   bool(r.get("空仓", False)),
        })

    # 支撑压力排序
    levels_sorted = []
    if sr:
        cur = sr["current_price"]
        for name, val in sorted(sr["levels"].items(), key=lambda x: -x[1]):
            levels_sorted.append({
                "name": name, "value": val,
                "current": abs(val - cur) < 30
            })

    import math
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k,v in obj.items()}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if hasattr(obj, 'item'):  # numpy scalar
            return obj.item()
        if isinstance(obj, bool):
            return bool(obj)
        return obj

    return clean({
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract": "P2609",
        "meta": meta,
        "signals": {k: bool(v) for k, v in signals.items()},
        "capital_flow": cf,
        "comparison": cmp,
        "levels": levels_sorted,
        "history": list(reversed(history)),
        "kline": kline,
        "indicator_series": indicator_series,
    })


@app.route("/api/data")
def api_data():
    period = request.args.get('period', '15')
    try:
        data = get_data(period=period)
        if data is None:
            return jsonify({"error": "数据获取失败"}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")


if __name__ == "__main__":
    os.makedirs("dashboard", exist_ok=True)
    print("启动看板服务: http://localhost:8080")
    app.run(host="0.0.0.0", port=8877, debug=False)
