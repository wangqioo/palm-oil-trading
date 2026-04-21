"""
实时信号监控器 — 棕榈油期货
指标：主图（破浪/空仓）+ 波段王
触发时微信推送
"""
import sys
import os
import time
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.join(os.path.dirname(__file__), "knowledge_base", "signals")
os.makedirs(LOG_DIR, exist_ok=True)


def get_realtime_bars(symbol="P2609", limit=120):
    """获取15分钟K线，失败则用日线兜底"""
    try:
        import akshare as ak
        df = ak.futures_zh_minute_sina(symbol=symbol, period="15")
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            if "datetime" not in df.columns:
                df = df.rename(columns={df.columns[0]: "datetime"})
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").tail(limit).reset_index(drop=True)
            for alias in [("vol", "volume"), ("amount", "volume")]:
                if alias[0] in df.columns and alias[1] not in df.columns:
                    df = df.rename(columns={alias[0]: alias[1]})
            if "volume" not in df.columns:
                df["volume"] = 0
            df["date"] = df["datetime"]
            return df
    except Exception:
        pass

    # 日线兜底
    try:
        from data_fetcher import get_palm_oil_data_akshare
        df = get_palm_oil_data_akshare(days=limit)
        if df is not None:
            df["datetime"] = df["date"]
            return df.tail(limit).reset_index(drop=True)
    except Exception:
        pass
    return None


def is_trading_hours():
    """是否在交易时间内"""
    now = datetime.now()
    h, m = now.hour, now.minute
    # 日盘 09:00-11:30 / 13:30-15:00
    # 夜盘 21:00-23:00（棕榈油无深夜盘）
    day = (h == 9) or (h == 10) or (h == 11 and m <= 30) or \
          (h == 13 and m >= 30) or (h == 14)
    night = 21 <= h <= 22
    return day or night


def run_monitor(interval_seconds=180, notify_fn=None):
    """
    主监控循环
    interval_seconds : 检测间隔（3分钟K线用180秒）
    notify_fn        : 发送通知的回调，None时只打印
    """
    from indicators import get_latest_signals

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 棕榈油信号监控启动（P2609，15分钟周期）")
    print("做多：主图黄点(破浪) + 波段王K>30且多头柱")
    print("离场：主图绿点(空仓) + 波段王K<80且空头柱\n")

    last_signal_bar = None   # 防重复：记录上次触发的K线时间

    while True:
        try:
            now = datetime.now()

            if not is_trading_hours():
                print(f"[{now.strftime('%H:%M')}] 非交易时间，休眠60s...")
                time.sleep(60)
                continue

            df = get_realtime_bars()
            if df is None or len(df) < 20:
                print(f"[{now.strftime('%H:%M:%S')}] 数据不足，重试...")
                time.sleep(30)
                continue

            signals, meta = get_latest_signals(df)

            # 当前K线标识（用最后一根时间防重复）
            current_bar = meta["datetime"]

            triggered = [k for k, v in signals.items() if v]

            k_status = f"K:{meta['K']}({'✓>30' if meta['K_gt30'] else '✗<30'}) D:{meta['D']}"
            print(f"[{now.strftime('%H:%M:%S')}] "
                  f"价:{meta['close']} | QRG:{meta['QRG']} | {k_status} | 支撑:{meta['支撑']}"
                  + (f"  ★★ {triggered}" if triggered else ""))

            # 只推送组合信号（做多/离场），单项仅打印
            triggered = [k for k, v in signals.items() if v and k in ("做多", "离场")]

            if triggered and current_bar != last_signal_bar:
                msg = _build_alert(meta, triggered)
                print(f"\n{'='*45}")
                print(msg)
                print(f"{'='*45}\n")

                if notify_fn:
                    notify_fn(msg)

                _log_signal(meta, triggered)
                last_signal_bar = current_bar

            time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n监控已停止")
            break
        except Exception as e:
            print(f"[错误] {e}")
            time.sleep(30)


def _build_alert(meta, triggered):
    is_long  = "做多" in triggered
    is_exit  = "离场" in triggered
    emoji    = "▲ 做多入场" if is_long else "▼ 离场平仓"
    lines = [f"【棕榈油15分钟 {emoji}】"]
    lines.append(f"时间：{meta['datetime']}")
    lines.append(f"品种：棕榈2609  现价：{meta['close']}")
    lines.append("")
    if is_long:
        lines.append("★ 主图黄点（破浪）✓")
        lines.append(f"★ 波段王 K={meta['K']} > 30，多头柱 ✓")
    if is_exit:
        lines.append("★ 主图绿点（空仓）✓")
        lines.append(f"★ 波段王 K={meta['K']} < 80，空头柱 ✓")
    lines.append("")
    lines.append(f"QRG：{meta['QRG']}  支撑：{meta['支撑']}")
    lines.append("⚠ 以你的系统判断为准")
    return "\n".join(lines)


def _log_signal(meta, triggered):
    import csv
    log_path = os.path.join(LOG_DIR, "signal_log.csv")
    write_header = not os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["datetime", "close", "signals", "QRG", "K", "D", "支撑"])
        writer.writerow([
            meta["datetime"], meta["close"],
            "|".join(triggered),
            meta["QRG"], meta["K"], meta["D"], meta["支撑"]
        ])


if __name__ == "__main__":
    run_monitor(interval_seconds=180)
