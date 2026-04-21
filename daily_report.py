"""
每日早报生成器 — 棕榈油期货
每天开盘前推送到微信 OpenClaw
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from data_fetcher import (
    get_palm_oil_data_akshare,
    get_crude_oil_data_akshare,
    calculate_support_resistance,
    calculate_capital_flow,
    compare_palm_crude,
)
from datetime import datetime


def generate_daily_report():
    """生成每日早报文本"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")

    report_lines = [
        f"【棕榈油期货早报】{date_str}",
        "=" * 30,
    ]

    # 1. 获取行情数据
    palm_df = get_palm_oil_data_akshare()
    crude_df = get_crude_oil_data_akshare()

    if palm_df is None:
        report_lines.append("数据获取失败，请检查网络")
        return "\n".join(report_lines)

    current_price = palm_df["close"].iloc[-1]
    prev_close = palm_df["close"].iloc[-2] if len(palm_df) >= 2 else current_price
    daily_chg = (current_price / prev_close - 1) * 100

    chg_symbol = "+" if daily_chg >= 0 else ""
    report_lines.append(f"当前价格: {current_price:.0f}  ({chg_symbol}{daily_chg:.2f}%)")

    # 2. 支撑压力位
    sr = calculate_support_resistance(palm_df, lookback=20)
    if sr:
        report_lines.append("")
        report_lines.append("【支撑/压力位】")
        levels = sr["levels"]
        for name, price in sorted(levels.items(), key=lambda x: x[1], reverse=True):
            marker = " ◀ 当前" if abs(price - current_price) < (sr["range_high"] - sr["range_low"]) * 0.05 else ""
            report_lines.append(f"  {name}: {price:.0f}{marker}")

    # 3. 资金流向
    cf = calculate_capital_flow(palm_df, lookback=5)
    if cf:
        report_lines.append("")
        report_lines.append("【资金流向（近5日）】")
        report_lines.append(f"  {cf['signal']} | 多头占比 {cf['bull_ratio']}% / 空头 {cf['bear_ratio']}%")

    # 4. 原油对比
    comp = compare_palm_crude(palm_df, crude_df, lookback=5)
    if comp:
        report_lines.append("")
        report_lines.append("【与原油对比】")
        palm_sym = "+" if comp["palm_5d_chg"] >= 0 else ""
        crude_sym = "+" if comp["crude_5d_chg"] >= 0 else ""
        report_lines.append(f"  棕榈油5日: {palm_sym}{comp['palm_5d_chg']}%")
        report_lines.append(f"  原油5日:   {crude_sym}{comp['crude_5d_chg']}%")
        report_lines.append(f"  走势: {comp['divergence']} — {comp['note']}")

    # 5. 综合判断
    report_lines.append("")
    report_lines.append("【今日倾向】")
    tendency = assess_tendency(daily_chg, cf, comp, sr, current_price)
    report_lines.append(f"  {tendency}")

    report_lines.append("")
    report_lines.append("⚠ 仅供参考，以你的系统信号为准")

    return "\n".join(report_lines)


def assess_tendency(daily_chg, cf, comp, sr, current_price):
    """综合判断今日偏向"""
    score = 0

    # 昨日涨跌
    if daily_chg > 0.5:
        score += 1
    elif daily_chg < -0.5:
        score -= 1

    # 资金流向
    if cf:
        if cf["bull_ratio"] > 60:
            score += 1
        elif cf["bull_ratio"] < 40:
            score -= 1

    # 原油联动
    if comp:
        if comp["divergence"] == "联动" and comp["crude_5d_chg"] > 0:
            score += 0.5
        elif comp["divergence"] == "联动" and comp["crude_5d_chg"] < 0:
            score -= 0.5

    # 价格位置
    if sr:
        mid = (sr["range_high"] + sr["range_low"]) / 2
        if current_price > mid:
            score += 0.5
        else:
            score -= 0.5

    if score >= 1.5:
        return "偏多 — 关注回调做多机会"
    elif score <= -1.5:
        return "偏空 — 谨慎操作，等待企稳"
    else:
        return "震荡 — 等待明确信号，不强追"


def send_to_wechat(message):
    """通过 OpenClaw 推送到微信（此处输出文本，由外部调度触发）"""
    # 实际推送由 HappyCapy 的 automation 机制或定时任务触发
    # 这里将报告写入文件，供调度读取
    report_path = os.path.join(os.path.dirname(__file__), "reports", "latest_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(message)
    print(message)
    return message


if __name__ == "__main__":
    report = generate_daily_report()
    send_to_wechat(report)
