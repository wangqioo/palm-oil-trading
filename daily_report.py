"""
每日早报生成器 — 期货看板
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from data_fetcher import calculate_support_resistance, calculate_capital_flow
from datetime import datetime


def generate_daily_report(symbol="P0", name="棕榈油主力"):
    """生成每日早报文本"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")

    report_lines = [
        f"【{name}期货早报】{date_str}",
        "=" * 30,
    ]

    try:
        import akshare as ak
        df = ak.futures_zh_daily_sina(symbol=symbol)
        if df is None or df.empty:
            raise ValueError("空数据")
        df.columns = [c.lower() for c in df.columns]
        import pandas as pd
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        report_lines.append(f"数据获取失败: {e}")
        return "\n".join(report_lines)

    current_price = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) >= 2 else current_price
    daily_chg = (current_price / prev_close - 1) * 100

    chg_symbol = "+" if daily_chg >= 0 else ""
    report_lines.append(f"当前价格: {current_price:.0f}  ({chg_symbol}{daily_chg:.2f}%)")

    sr = calculate_support_resistance(df, lookback=20)
    if sr:
        report_lines.append("")
        report_lines.append("【支撑/压力位】")
        for lv_name, price in sorted(sr["levels"].items(), key=lambda x: x[1], reverse=True):
            marker = " ◀ 当前" if abs(price - current_price) < (sr["range_high"] - sr["range_low"]) * 0.05 else ""
            report_lines.append(f"  {lv_name}: {price:.0f}{marker}")

    cf = calculate_capital_flow(df, lookback=5)
    if cf:
        report_lines.append("")
        report_lines.append("【资金流向（近5日）】")
        report_lines.append(f"  {cf['signal']} | 多头占比 {cf['bull_ratio']}% / 空头 {cf['bear_ratio']}%")

    report_lines.append("")
    report_lines.append("⚠ 仅供参考，以你的系统信号为准")

    return "\n".join(report_lines)


if __name__ == "__main__":
    report = generate_daily_report()
    print(report)
