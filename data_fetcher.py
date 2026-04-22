"""
数据获取模块 — 棕榈油期货 + 原油期货
数据源：
  棕榈油：新浪财经期货日K（单次请求，缓存兜底）
  原油：  yfinance 布伦特 BZ=F（Yahoo Finance，稳定）
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(CACHE_DIR, exist_ok=True)

# 已知主力合约（定期手动更新，或脚本自动更新）
PALM_MAIN_CONTRACT = "P2609"


def _save_cache(name, df):
    path = os.path.join(CACHE_DIR, f"{name}.csv")
    df.to_csv(path, index=False)


def _load_cache(name):
    path = os.path.join(CACHE_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return None


def get_palm_oil_data_akshare(days=40):
    """
    返回 P2609 当前合约日线数据（用于展示，和慧赢保持一致）
    同时在末尾附带 warmup 标记，供调用方识别
    """
    try:
        import akshare as ak
        import socket
        socket.setdefaulttimeout(15)

        df = ak.futures_zh_daily_sina(symbol=PALM_MAIN_CONTRACT)
        if df is None or df.empty:
            raise ValueError("返回空数据")

        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        _save_cache("palm_oil", df)
        print(f"棕榈油({PALM_MAIN_CONTRACT}): {len(df)} 条，"
              f"{df['date'].iloc[-1].date()} 收={df['close'].iloc[-1]:.0f}")
        return df

    except Exception as e:
        print(f"棕榈油API失败: {e}，使用缓存...")
        cached = _load_cache("palm_oil")
        if cached is not None:
            print(f"缓存数据: {len(cached)} 条 ⚠ 非实时")
        return cached


def get_palm_oil_warmup():
    """
    拼接历史合约用于指标预热（不用于展示），
    在 P2609 数据前面拼接足够的历史，确保 SMA/EMA 充分收敛
    """
    WARMUP_CONTRACTS = [
        'P1905','P1909',
        'P2001','P2005','P2009',
        'P2101','P2105','P2109',
        'P2201','P2205','P2209',
        'P2301','P2305','P2309',
        'P2401','P2405','P2409',
        'P2501','P2505','P2509',
        'P2601','P2605','P2609',
    ]
    try:
        import akshare as ak
        frames = []
        for c in WARMUP_CONTRACTS:
            try:
                df = ak.futures_zh_daily_sina(symbol=c)
                if df is not None and not df.empty:
                    df.columns = [c2.lower() for c2 in df.columns]
                    df["date"] = pd.to_datetime(df["date"])
                    frames.append(df)
            except Exception:
                pass

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("date")
        combined = combined.drop_duplicates(subset=["date"], keep="last")
        combined = combined.reset_index(drop=True)
        _save_cache("palm_oil_warmup", combined)
        print(f"预热数据: {len(combined)} 条，{combined['date'].iloc[0].date()} ~ {combined['date'].iloc[-1].date()}")
        return combined

    except Exception as e:
        print(f"预热数据失败: {e}")
        cached = _load_cache("palm_oil_warmup")
        return cached


def get_crude_oil_data_akshare():
    """
    布伦特原油历史数据，取全量可用历史
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker("BZ=F")
        hist = ticker.history(period="max")  # 取全部历史
        if hist.empty:
            raise ValueError("空数据")

        df = hist.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df.columns = ["date", "open", "high", "low", "close", "volume"]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)

        _save_cache("crude_oil", df)
        print(f"布伦特(BZ=F): {len(df)} 条，"
              f"{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}"
              f" 收={df['close'].iloc[-1]:.2f}美元")
        return df

    except Exception as e:
        print(f"原油yfinance失败: {e}")

    cached = _load_cache("crude_oil")
    if cached is not None:
        print(f"原油缓存: {len(cached)} 条 ⚠ 非实时")
    return cached


def calculate_support_resistance(df, lookback=20):
    """支撑/压力位：斐波那契 + 均线"""
    if df is None or len(df) < lookback:
        return None
    recent = df.tail(lookback)
    hi = recent["high"].max()
    lo = recent["low"].min()
    cur = float(df["close"].iloc[-1])
    r = hi - lo

    levels = {
        "压力1": round(hi, 0),
        "压力2": round(lo + r * 0.786, 0),
        "中轴":  round(lo + r * 0.618, 0),
        "支撑1": round(lo + r * 0.382, 0),
        "支撑2": round(lo + r * 0.236, 0),
        "支撑3": round(lo, 0),
    }
    for n in [5, 10, 20]:
        if len(df) >= n:
            levels[f"MA{n}"] = round(df["close"].rolling(n).mean().iloc[-1], 0)

    return {"current_price": cur, "levels": levels, "range_high": hi, "range_low": lo}


def calculate_capital_flow(df, lookback=5):
    """成交量加权多空比"""
    if df is None or len(df) < lookback:
        return None
    r = df.tail(lookback).copy()
    r["is_bull"] = r["close"] > r["open"]
    bv = r.loc[r["is_bull"], "volume"].sum()
    sv = r.loc[~r["is_bull"], "volume"].sum()
    total = bv + sv
    if total == 0:
        return None
    bull = bv / total * 100
    signal = "多头主导" if bull > 60 else ("空头主导" if bull < 40 else "多空均衡")
    return {"bull_ratio": round(bull, 1), "bear_ratio": round(100 - bull, 1), "signal": signal}


def compare_palm_crude(palm_df, crude_df, lookback=5):
    """对比棕榈油与原油走势"""
    if palm_df is None or crude_df is None:
        return None
    n = min(6, len(palm_df), len(crude_df))
    palm_5d = (palm_df["close"].iloc[-1] / palm_df["close"].iloc[-n] - 1) * 100
    crude_5d = (crude_df["close"].iloc[-1] / crude_df["close"].iloc[-n] - 1) * 100
    div = "联动" if palm_5d * crude_5d > 0 else "背离"
    note = "走势一致" if div == "联动" else "棕油独立走势，需关注"
    return {
        "palm_5d_chg": round(palm_5d, 2),
        "crude_5d_chg": round(crude_5d, 2),
        "divergence": div,
        "note": note,
    }


if __name__ == "__main__":
    print("=== 测试 ===")
    palm = get_palm_oil_data_akshare()
    crude = get_crude_oil_data_akshare(days=10)
