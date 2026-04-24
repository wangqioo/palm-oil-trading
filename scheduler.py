"""
后端信号调度器 — 独立运行，按不同周期扫描信号，写入 /api/signals/pending 队列
用法：python scheduler.py
依赖：与 server.py 同目录运行，会在内部调用 server.get_data()
"""
import sys, os, time, threading, datetime, json
sys.path.insert(0, os.path.dirname(__file__))

# 导入 server 模块（不触发 Flask 启动）
from server import get_data, push_pending_signal, SYMBOLS

# 各周期扫描间隔（分钟）
SCAN_INTERVALS = {
    '15':     5,
    '30':     5,
    '60':    15,
    '120':   30,
    'daily': None,   # 每天 15:15
    'weekly': None,  # 每周五 15:15
}

_last_signals = {}   # (symbol, period) -> {type, time}


def scan_period(period, symbols):
    print(f"[scheduler] 扫描 {period} — {datetime.datetime.now().strftime('%H:%M:%S')}")
    for sym_code, sym_cfg in symbols.items():
        try:
            data = get_data(symbol=sym_code, period=period, name=sym_cfg['name'])
            if not data or data.get('error'):
                continue
            sig  = data.get('signals', {})
            meta = data.get('meta', {})
            sig_time = meta.get('datetime', '')
            key  = (sym_code, period)
            prev = _last_signals.get(key, {})

            for sig_type, sig_key in [('做多', '做多'), ('做空', '做空')]:
                if sig.get(sig_key) and not (prev.get('type') == sig_type and prev.get('time') == sig_time):
                    _last_signals[key] = {'type': sig_type, 'time': sig_time}
                    push_pending_signal({
                        'symbol':  sym_code,
                        'name':    sym_cfg['name'],
                        'period':  period,
                        'sigType': sig_type,
                        'price':   meta.get('close'),
                        'time':    sig_time,
                    })
                    print(f"[scheduler] ✦ {sym_code} {period} {sig_type} @ {sig_time}")
        except Exception as e:
            print(f"[scheduler] {sym_code} {period} 错误: {e}")


def _minute_job():
    """每5分钟轮询：15分/30分"""
    while True:
        scan_period('15', SYMBOLS)
        scan_period('30', SYMBOLS)
        time.sleep(5 * 60)


def _hourly_job():
    """每15分钟：60分"""
    while True:
        scan_period('60', SYMBOLS)
        time.sleep(15 * 60)


def _two_hour_job():
    """每30分钟：120分"""
    while True:
        scan_period('120', SYMBOLS)
        time.sleep(30 * 60)


def _daily_job():
    """每天 15:15 扫描日线"""
    while True:
        now = datetime.datetime.now()
        target = now.replace(hour=15, minute=15, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        wait = (target - now).total_seconds()
        time.sleep(wait)
        scan_period('daily', SYMBOLS)


def _weekly_job():
    """每周五 15:15 扫描周线"""
    while True:
        now = datetime.datetime.now()
        days_to_friday = (4 - now.weekday()) % 7   # 4 = Friday
        target = (now + datetime.timedelta(days=days_to_friday)).replace(
            hour=15, minute=15, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(weeks=1)
        wait = (target - now).total_seconds()
        time.sleep(wait)
        scan_period('weekly', SYMBOLS)


if __name__ == '__main__':
    print(f"[scheduler] 启动，监控品种: {list(SYMBOLS.keys())}")
    print("[scheduler] 需要 server.py 同时运行以消费 /api/signals/pending")

    for fn in [_minute_job, _hourly_job, _two_hour_job, _daily_job, _weekly_job]:
        t = threading.Thread(target=fn, daemon=True)
        t.start()

    # 主线程保活
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("[scheduler] 已停止")
