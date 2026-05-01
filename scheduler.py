"""
后端信号调度器（可选独立进程）
- server.py 已内置同款扫描线程，直接 python server.py 即可。
- 若需独立运行（如 Docker sidecar），执行 python scheduler.py。
  信号通过 HTTP POST /api/signals/push 推送给 server.py。
  去重通过与 server.py 共用同一个 data/signals.db 实现。
"""
import sys, os, time, datetime, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SERVER_URL = os.environ.get('SERVER_URL', 'http://localhost:8877')
DB_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'signals.db')

_PERIOD_LABEL = {
    '1':'1分','5':'5分','15':'15分','30':'30分',
    '60':'60分','120':'120分','daily':'日线','weekly':'周线',
}

# ── 品种交易时段（夜盘结束时间，单位：分钟；night_next=True 表示跨越次日凌晨）────
_SYMBOL_NIGHT_END = {
    'P0':  (23 * 60,        False),  # 大商所棕榈油      23:00
    'AG0': ( 2 * 60 + 30,  True),   # 上期所白银        次日 02:30
    'BC0': ( 1 * 60,        True),   # 上期能源国际铜    次日 01:00
    'CU0': ( 1 * 60,        True),   # 上期所铜          次日 01:00
    'SA0': (23 * 60,        False),  # 郑商所纯碱        23:00
    'SC0': ( 2 * 60 + 30,  True),   # 上期能源原油      次日 02:30
    'SN0': ( 1 * 60,        True),   # 上期所锡          次日 01:00
}

_MINUTE_PERIODS = {'1','5','15','30','60','120'}


def get_market_status(symbol, now=None):
    """返回品种当前交易状态。
    status: 'trading' | 'lunch' | 'closed'
    next_open: 下次开市时间字符串（交易中时为 None）
    """
    if now is None:
        now = datetime.datetime.now()
    wd = now.weekday()
    t  = now.hour * 60 + now.minute

    night_end, night_next = _SYMBOL_NIGHT_END.get(symbol, (15 * 60, False))

    if wd == 5:
        if night_next and t < night_end:
            return {'status': 'trading', 'next_open': None}
        return {'status': 'closed', 'next_open': '周一 09:00'}

    if wd == 6:
        return {'status': 'closed', 'next_open': '周一 09:00'}

    if 11 * 60 + 30 <= t < 13 * 60:
        return {'status': 'lunch', 'next_open': '13:00'}

    if (9 * 60 <= t < 11 * 60 + 30) or (13 * 60 <= t < 15 * 60):
        return {'status': 'trading', 'next_open': None}

    if 15 * 60 <= t < 21 * 60:
        return {'status': 'closed', 'next_open': '21:00'}

    if night_next:
        if t >= 21 * 60 or t < night_end:
            return {'status': 'trading', 'next_open': None}
        return {'status': 'closed', 'next_open': '09:00'}
    else:
        if 21 * 60 <= t < night_end:
            return {'status': 'trading', 'next_open': None}
        return {'status': 'closed', 'next_open': '09:00'}


# ── 数据库去重 ─────────────────────────────────────────────────────

def _init_db():
    conn = sqlite3.connect(DB_PATH)
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
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.execute(
            'INSERT OR IGNORE INTO signals (symbol,signal_type,candle_time,created_at) VALUES (?,?,?,?)',
            (symbol, signal_type, candle_time,
             datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        is_new = cur.rowcount > 0
        conn.close()
        return is_new
    except Exception as e:
        print(f"[db] {e}")
        return True  # fail open


# ── 收盘时刻判断 ───────────────────────────────────────────────────

def _is_kline_close(period):
    now = datetime.datetime.now()
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


# ── 与 server.py 通信 ─────────────────────────────────────────────

def _get_active_period():
    try:
        import requests
        r = requests.get(f'{SERVER_URL}/api/settings/period', timeout=2)
        return r.json().get('period', '30')
    except Exception:
        return '30'

def _push_signal(signal_dict):
    try:
        import requests
        requests.post(f'{SERVER_URL}/api/signals/push', json=signal_dict, timeout=2)
    except Exception as e:
        print(f"[push] 推送失败: {e}")


# ── 扫描逻辑 ──────────────────────────────────────────────────────

def _do_scan(period, get_data, SYMBOLS):
    now = datetime.datetime.now()
    for sym_code, sym_cfg in SYMBOLS.items():
        try:
            # 交易时段检查：非交易时段不推信号
            if period in _MINUTE_PERIODS:
                ms = get_market_status(sym_code, now)
                if ms['status'] != 'trading':
                    print(f"[scheduler] {sym_code} {ms['status']}，跳过")
                    continue

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
                    _push_signal({
                        'symbol': sym_code, 'name': sym_cfg['name'],
                        'period': period,   'sigType': sig_type,
                        'price':  meta.get('close'), 'time': candle_time,
                    })
                    print(f"[scheduler] ✦ {sym_code} {_PERIOD_LABEL.get(period,period)} "
                          f"{sig_type} @ {candle_time}")
        except Exception as e:
            print(f"[scheduler] {sym_code} 错误: {e}")


# ── 主循环 ────────────────────────────────────────────────────────

if __name__ == '__main__':
    from server import get_data, SYMBOLS

    _init_db()
    print(f"[scheduler] 启动，推送目标: {SERVER_URL}")
    print(f"[scheduler] 每分钟扫描一次，只在K线收盘且交易时段内推送信号")

    while True:
        try:
            period = _get_active_period()
            ts     = datetime.datetime.now().strftime('%H:%M:%S')

            if _is_kline_close(period):
                print(f"[{ts}] 扫描中... {_PERIOD_LABEL.get(period,period)}K线收盘✅ 检测信号")
                _do_scan(period, get_data, SYMBOLS)
            else:
                print(f"[{ts}] 扫描中... 未到收盘时刻 跳过")

        except Exception as e:
            print(f"[scheduler] 主循环错误: {e}")

        time.sleep(60)
