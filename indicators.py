"""
交易系统指标计算模块
来源：平安证券慧赢 TDX公式 → Python复现

已实现：
  1. 主图指标（破浪/空仓信号 — 黄绿点）
  2. 波段王（K/D动能柱 + 多/空文字信号）
待实现：
  3. JLHB 绝路航标（等待公式）
  4. 三速线（等待公式）
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────
# 工具函数：TDX 标准函数 Python 实现
# ─────────────────────────────────────────────

def ema(series, n):
    """指数移动平均，等价于 TDX EMA(series, n)"""
    return series.ewm(span=n, adjust=False).mean()


def ma(series, n):
    """简单移动平均，等价于 TDX MA(series, n)"""
    return series.rolling(n).mean()


def ref(series, n):
    """前N期数据，等价于 TDX REF(series, n)"""
    return series.shift(n)


def hhv(series, n):
    """N期最高值，等价于 TDX HHV(series, n)"""
    return series.rolling(n).max()


def llv(series, n):
    """N期最低值，等价于 TDX LLV(series, n)"""
    return series.rolling(n).min()


def cross(a, b):
    """上穿：前期 a<=b 且当期 a>b，等价于 TDX CROSS(a, b)"""
    return (ref(a, 1) <= ref(b, 1)) & (a > b)


def sma(series, n, m):
    """
    TDX SMA(X, N, M) = 威尔德平滑均值
    公式：Y = (M*X + (N-M)*Y') / N
    """
    result = series.copy().astype(float)
    result.iloc[:n] = np.nan
    alpha = m / n
    for i in range(1, len(series)):
        if pd.isna(result.iloc[i - 1]):
            result.iloc[i] = series.iloc[i]
        else:
            result.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * result.iloc[i - 1]
    return result


# ─────────────────────────────────────────────
# 指标一：主图指标（破浪/空仓信号）
# 黄点 = 破浪 = 做多信号
# 绿点 = 空仓 = 离场/空头信号
# ─────────────────────────────────────────────

def calc_main_signals(df):
    """
    输入：df 含 open/high/low/close 列（日线或分钟线）
    输出：原df 附加以下列
      M1-M5    : 五级叠加EMA均线
      支撑      : 动态支撑价位
      QRG      : 综合强度分(-50~+50)
      破浪      : True = 黄点做多信号
      空仓      : True = 绿点离场信号
    """
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)

    # 五级叠加EMA
    m1 = ema(c, 13)
    m2 = ema(m1, 3)
    m3 = ema(m2, 3)
    m4 = ema(m3, 3)
    m5 = ema(m4, 3)

    # 动态支撑
    hlc = ref(ma((h + l + c) / 3, 10), 1)
    hv  = ema(hhv(h, 10), 3)
    support = ema(hlc * 2 - hv, 3)

    # 综合强度评分
    vc = (
        np.where(c >= m1, 10, -10) +
        np.where(c >= m2, 10, -10) +
        np.where(c >= m3, 10, -10) +
        np.where(m1 >= m2, 10, -10) +
        np.where(m2 >= m3, 10, -10)
    )
    vc = pd.Series(vc, index=df.index)

    sn = (
        np.where(m5 > ref(m5, 1), 1, 0) *
        np.where(m4 > ref(m4, 1), 1, 0)
    )
    sn = pd.Series(sn, index=df.index)

    a   = vc - (1 - sn) * 10
    qrg = a.clip(lower=-50)

    # 信号检测
    po_lang = cross(qrg, pd.Series(-10, index=df.index))   # 黄点：破浪
    kong_cang = (qrg == -50) & (ref(qrg, 1) >= -30)         # 绿点：空仓

    result = df.copy()
    result["M1"] = m1
    result["M2"] = m2
    result["M3"] = m3
    result["M4"] = m4
    result["M5"] = m5
    result["支撑"] = support
    result["QRG"] = qrg
    result["破浪"] = po_lang
    result["空仓"] = kong_cang
    return result


# ─────────────────────────────────────────────
# 指标二：波段王
# 蓝柱(K>=D) = 多头动能；绿柱(K<=D) = 空头动能
# "多" 文字 = 做多信号；"空" 文字 = 做空信号
# ─────────────────────────────────────────────

def calc_bsd_wang(df):
    """
    输入：df 含 high/low/close 列
    输出：附加列
      K, D      : 动能线
      多头信号   : True = K上穿D且收盘>MA5
      空头信号   : True = D上穿K且收盘>MA5（卖出条件）
      柱色       : 'blue'(多) / 'green'(空) / None
    """
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)

    var1 = (c - llv(l, 15)) / (hhv(h, 15) - llv(l, 15)) * 100
    var2 = var1
    var3 = sma(var1, 5, 1)
    K    = sma(var3, 3, 1)
    D    = sma(K, 3, 1)

    ma5 = ma(c, 5)

    # 信号
    long_sig  = cross(K, D) & (ma5 < c)          # 多：K上穿D + 收盘>MA5
    short_sig = cross(D, K) & (ma5 > pd.Series(0, index=df.index))  # 空：D上穿K

    result = df.copy()
    result["K"] = K
    result["D"] = D
    result["波段王_多"] = long_sig
    result["波段王_空"] = short_sig
    return result


# ─────────────────────────────────────────────
# 综合信号检测（供实时监控使用）
# ─────────────────────────────────────────────

def get_latest_signals(df):
    """
    综合信号检测（15分钟K线）
    ──────────────────────────────────
    做多触发：主图黄点（破浪）AND 波段王 K>30 AND K>=D
    离场触发：主图绿点（空仓）AND 波段王 K<80 AND K<=D
    ──────────────────────────────────
    返回：(signals_dict, meta_dict)
    """
    df2 = calc_main_signals(df)
    df3 = calc_bsd_wang(df2)

    last = df3.iloc[-1]

    # 单项条件
    po_lang   = bool(last.get("破浪", False))          # 主图黄点
    kong_cang = bool(last.get("空仓", False))           # 主图绿点
    K_val     = float(last.get("K", 0))
    D_val     = float(last.get("D", 0))
    bsd_bull  = K_val > 30 and K_val >= D_val          # 波段王多头柱（蓝色）
    bsd_bear  = K_val < 80 and K_val <= D_val          # 波段王空头柱（绿色）

    signals = {
        # ── 组合信号（交易执行依据）──
        "做多":   po_lang and bsd_bull,    # 黄点 + 波段王>30且多头
        "离场":   kong_cang and bsd_bear,  # 绿点 + 波段王<80且空头
        # ── 单项信号（辅助参考）──
        "破浪_黄点":  po_lang,
        "空仓_绿点":  kong_cang,
        "波段王_多":  bsd_bull,
        "波段王_空":  bsd_bear,
    }

    meta = {
        "datetime": str(last.get("date", last.name)),
        "close":    round(float(last["close"]), 1),
        "QRG":      round(float(last.get("QRG", 0)), 1),
        "K":        round(K_val, 2),
        "D":        round(D_val, 2),
        "支撑":      round(float(last.get("支撑", 0)), 1),
        "K_gt30":   K_val > 30,
        "K_lt80":   K_val < 80,
    }
    return signals, meta


if __name__ == "__main__":
    # 快速测试
    from data_fetcher import get_palm_oil_data_akshare
    df = get_palm_oil_data_akshare(days=60)
    if df is not None:
        signals, meta = get_latest_signals(df)
        print("\n=== 最新指标状态 ===")
        print(f"时间: {meta['datetime']}  收盘: {meta['close']}")
        print(f"QRG: {meta['QRG']}  支撑: {meta['支撑']}")
        print(f"K: {meta['K']}  D: {meta['D']}")
        print("\n=== 信号 ===")
        for k, v in signals.items():
            status = "★ 触发！" if v else "  未触发"
            print(f"  {k}: {status}")
