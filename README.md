# 期货交易看板 v3.1

基于平安证券慧赢风格的期货实时交易看板。Flask 后端 + 单页前端，用于多品种信号监控与实时推送。

---

## 快速启动

```bash
pip install flask flask-cors pandas akshare
python server.py          # http://localhost:8877
```

Docker：
```bash
docker compose up -d --build
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  dashboard/index.html  （单文件前端，~2000行）           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │ K线主图  │  │  波段王副图  │  │ 自选+信号侧边栏    │ │
│  │ kChart   │  │  bsdChart    │  │ _watchlistNotified │ │
│  └──────────┘  └──────────────┘  └────────────────────┘ │
│  轮询 /api/signals/pending（3s）+ scanAllWatchlist（60s）│
└────────────────────┬────────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────────┐
│  server.py  （Flask，all-in-one）                        │
│  ├─ 数据拉取：akshare → 内存缓存（_minute_cache）        │
│  ├─ 指标计算：indicators.py / data_fetcher.py            │
│  ├─ 信号队列：_pending_signals（内存列表）               │
│  ├─ 去重DB：data/signals.db（SQLite）                    │
│  └─ 后台线程：_scanner_loop（每60s，收盘时刻才扫描）     │
└─────────────────────────────────────────────────────────┘

scheduler.py  （可选独立进程，通过 HTTP POST 推送信号）
```

---

## 文件速查

| 文件 | 作用 | 关键内容 |
|------|------|----------|
| `server.py` | Flask API + 数据层 + 后台扫描器 | `get_data()` `_scanner_loop()` `_is_new_signal()` `push_pending_signal()` |
| `indicators.py` | 核心指标计算 | `calc_main_signals()` `calc_bsd_wang()` `get_latest_signals()` |
| `data_fetcher.py` | 辅助计算（不拉数据） | `calculate_support_resistance()` `calculate_capital_flow()` |
| `scheduler.py` | 可选独立调度进程 | 与 server.py 共用 signals.db；通过 `/api/signals/push` 推送 |
| `dashboard/index.html` | 单文件前端（CSS+JS全内嵌） | 见下方前端函数表 |
| `indicators_pkg/` | 指标插件（可热加载） | 每个 `.py` 需有 `META` + `compute(df)` |
| `tdx_parser/` | TDX公式 → Python插件 | `TDXParser.to_plugin_source()` |
| `data/` | 日线CSV缓存 + signals.db | 由 Docker volume 挂载持久化 |

---

## 前端关键函数（dashboard/index.html）

| 函数 | 行号约 | 说明 |
|------|--------|------|
| `initCharts()` | ~430 | 初始化 lightweight-charts 主图+副图 |
| `renderAll(data)` | ~792 | 全量渲染（切换品种/周期时调用） |
| `updateBars(bars)` | ~771 | 增量刷新（定时刷新，只更新最后3根） |
| `drawBsdCanvas(bars)` | ~840 | Canvas 画波段王色块柱 |
| `setupLegends()` | ~702 | 订阅 crosshair，更新 OHLC 图例 + kbar-time |
| `checkAndNotify(data, period)` | ~1751 | 检测信号，触发弹窗+桌面通知 |
| `showSignalToast(data, sigType, period)` | ~1544 | 显示做多/做空弹窗（最多同时3个） |
| `showResonanceToast(data, periods, sigType)` | ~1635 | 显示多周期共振弹窗 |
| `scanAllWatchlist()` | ~1293 | 静默扫描所有自选品种（60s间隔） |
| `updateHeader(data)` | ~927 | 更新顶部品种名/价格/涨跌幅 |
| `updateSidebar(data)` | ~948 | 更新侧边信号状态面板 |
| `_consumePending()` | ~1799 | 轮询 `/api/signals/pending`（3s间隔） |
| `setKbarTime(t)` | ~397 | 更新K线图内顶部时间显示 |
| `fmtBarTime(t)` | ~384 | Unix秒 → 可读日期字符串 |
| `getAlertPeriods()` | ~1429 | 读取用户选择的触发周期（localStorage） |
| `setAlertPeriods(periods)` | ~1433 | 设置触发周期，同时 POST /api/settings/period |

### 关键全局变量

| 变量 | 说明 |
|------|------|
| `currentSymbol` / `currentSymbolName` | 当前展示的品种代码和名称 |
| `currentPeriod` | 当前K线周期（'1'/'5'/'15'/'30'/'60'/'120'/'daily'/'weekly'） |
| `allData` | 最新一次 API 响应的完整数据 |
| `_watchlistNotified` | 各品种+周期的上次信号状态（去重用） |
| `_silentInit` | `true`=页面刚加载，第一轮扫描静默不弹窗；扫完后自动 `false` |
| `_sessionStart` | 页面加载时间（ISO字符串），传给 `since=` 参数过滤历史信号 |
| `viewInitialized` | `false`=首次加载，需重置视图范围 |

---

## 数据流

```
前端 loadData(mode)
  → GET /api/data?symbol=P0&period=30&mode=full
  → server.py: get_data()
      ├─ get_minute_data(sina_code, period)   # 分钟线，内存TTL缓存
      ├─ get_daily_data(symbol_cfg)           # 日线，akshare + CSV回退
      ├─ get_weekly_data()                    # 按自然周resample日线
      ├─ calc_main_signals(df)               # 主图：QRG/破浪/空仓
      ├─ calc_bsd_wang(df)                   # 副图：K/D波段王
      └─ indicator_series[]                  # 每根K线的完整数据
  → 前端 renderAll(data) / updateBars(bars)
```

### 120分钟K线
akshare 无原生接口，拉60分钟后 `resample('120min')` 聚合。

### 周线
日线数据 `resample('W-FRI', closed='right', label='right')` 聚合。

---

## 信号系统

### 触发逻辑

**做多**：`破浪`（QRG 上穿 -10）且 K > 30 且 K ≥ D
**做空**：`空仓`（QRG 跌至 -50，前值 ≥ -30）且 K < 80 且 K ≤ D

### 后台扫描器（server.py 内置线程）

- 启动：`python server.py` 时自动启动后台线程 `_scanner_loop`
- 间隔：每 60 秒扫一次
- 收盘判断（`_is_kline_close(period)`）：

| 周期 | 推送条件 |
|------|----------|
| 1分钟 | 每次都判断 |
| 5分钟 | minute % 5 == 0 |
| 15分钟 | minute % 15 == 0 |
| 30分钟 | minute % 30 == 0 |
| 60分钟 | minute == 0 |
| 120分钟 | minute == 0 且 hour % 2 == 0 |
| 日线 | hour == 15 且 minute == 1 |
| 周线 | weekday == 4 且 hour == 15 且 minute == 1 |

### 去重机制（三重保障）

1. **SQLite（data/signals.db）**：`UNIQUE(symbol, signal_type, candle_time)`，跨重启持久化
2. **`_silentInit` 旗标**：页面加载后第一次扫描静默录状态，不弹窗
3. **`since` 参数**：`_consumePending` 传 `?since=_sessionStart`，后端只返回本次连接后产生的信号

### 信号队列路径

```
后台扫描 _do_scan()
  → _is_new_signal(symbol, signal_type, candle_time)  # SQLite去重
  → push_pending_signal(signal_dict)                  # 写入内存队列
  ↓
前端 _consumePending()（3秒轮询）
  → GET /api/signals/pending?since=<_sessionStart>
  → showSignalToast() / showResonanceToast()
```

---

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/data` | GET | K线+指标数据。参数：`symbol` `period` `mode`（full/update） |
| `/api/symbols` | GET | 默认自选品种列表 |
| `/api/search?q=铜` | GET | 搜索期货品种名称或代码前缀 |
| `/api/resolve?symbol=RB2510` | GET | 验证合约代码存在性并返回名称 |
| `/api/trend?symbol=P0` | GET | 各周期K/D趋势状态（5分钟缓存） |
| `/api/indicators` | GET | 已加载指标插件列表 |
| `/api/import_formula` | POST | 导入TDX公式，body: `{"name":"","source":"","panel":"sub"}` |
| `/api/signals/pending` | GET | 取出并清空信号队列。`?since=` 过滤早于连接时间的历史信号 |
| `/api/signals/push` | POST | 外部进程（scheduler.py）推送信号入队 |
| `/api/settings/period` | GET | 查询当前后台扫描周期 |
| `/api/settings/period` | POST | 切换后台扫描周期，body: `{"period":"30"}` |
| `/api/test/signal` | POST | 测试用：直接注入信号触发弹窗 |

---

## 前端 UI 结构

```
#header（顶部）
  hdr-name（品种名）  hdr-clock（实时时钟，每秒更新）
  hdr-contract（合约代码）  hdr-price  hdr-chg
  hdr-ts（服务端更新时间）  [周期按钮]  [铃铛] [刷新] [全屏]

#sidebar（左侧240px）
  自选搜索框 → 自选列表 → 当前信号状态 → 历史信号 → 多周期趋势 → 触发周期设置

#charts-area
  #wrap-kline（55%高）
    .chart-label "K 线"  .chart-legend（OHLC）  #kbar-time（右上，K线时间）
    #chart-kline（lightweight-charts主图）
  [resizer拖动条]
  #wrap-bsd（26%高）
    .chart-label "波段王"  .chart-legend（K/D值）
    #bsd-canvas（Canvas色块柱）  #chart-bsd（bsdChart）
```

### 弹窗系统

- 容器：`#popup-stack`（最多同时3个）
- 超出进 `_unreadSignals` 队列，铃铛显示未读数
- 弹窗动画：`.signal-alert` 外框抖动（`sig-shake`），`.signal-alert-inner` 反向抖动（`sig-shake-counter`），内容文字静止

---

## 配色规范（慧赢风格）

| 元素 | 颜色 |
|------|------|
| 阳线 | `#ef5350`（红） |
| 阴线 | 白色 |
| 做多/多头 | `var(--bull)` = `#ef5350` |
| 做空/空头 | `var(--bear)` = `#26a69a` |
| M1~M5均线（下降） | `#FFD700`（黄） |
| M1~M5均线（上升） | `#FF00FF`（粉） |
| 波段王多头色块 | `#CC0000` |
| 波段王空头色块 | `#00AA00` |

---

## 默认品种（SYMBOLS 表，server.py 顶部）

| 代码 | 品种 | 交易所 |
|------|------|--------|
| P0 | 棕榈油主力 | 大商所 |
| AG0 | 白银主力 | 上期所 |
| BC0 | 国际铜主力 | 上期能源 |
| CU0 | 铜主力 | 上期所 |
| SA0 | 纯碱主力 | 郑商所 |

> 全部使用新浪主力连续合约格式（品种前缀+0），永远跟踪当前主力，无需换月。
> 不在 SYMBOLS 表的合约（如 RB2510）由 `get_data()` 自动构造配置。

---

## 已知细节与易踩坑

1. **120分钟K线无原生接口**：拉60分钟后 resample，见 `server.py: get_minute_data()`
2. **周线**：`resample('W-FRI')`，周五收盘作为周K收盘时间
3. **波段王色块**：Canvas 绘制在 `#bsd-canvas` 之上，不是 lightweight-charts 原生序列
4. **三图联动**：`kChart` / `bsdChart` / 动态副图通过 `timeScale().subscribeVisibleLogicalRangeChange` 同步，用 `_syncing` 旗防递归
5. **指标插件重载**：`POST /api/import_formula` → 写 `indicators_pkg/<id>.py` → `ipkg.reload_all()`
6. **弹窗文字抖动**：通过 `signal-alert-inner` 的反向动画（`sig-shake-counter`）抵消外框抖动
7. **`_silentInit`**：必须等 `scanAllWatchlist()` 完成后才置 false；`checkAndNotify` 也受此保护
8. **SQLite 路径**：`data/signals.db`，由 Docker volume `./data:/app/data` 挂载持久化
9. **scheduler.py 独立进程**：与 server.py 共用同一 signals.db 实现去重；通过 HTTP POST 推送，避免跨进程共享内存的问题

---

## 插件开发

`indicators_pkg/` 下新建 `.py`，格式：

```python
META = {
    "name": "我的指标", "id": "my_indicator", "panel": "sub",
    "outputs": [
        {"col": "LINE1", "type": "line", "color": "#FF0000", "width": 2},
        {"col": "SIG", "type": "marker", "position": "belowBar",
         "color": "#FFD700", "shape": "circle", "size": 1.2},
    ],
    "hlines": [{"value": 80, "color": "#888888", "width": 1}],
}

def compute(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["LINE1"] = df["close"].ewm(span=13).mean()
    result["SIG"]   = result["LINE1"] > result["LINE1"].shift(1)
    return result
```

---

## 版本历史

### v3.1（当前）
- 后台信号扫描：`_scanner_loop` 集成到 server.py，每60秒扫描，只在K线收盘时刻推送
- 三字段联合去重（symbol + signal_type + candle_time），SQLite持久化跨重启
- `_silentInit`：页面加载后第一轮扫描静默，解决"过时弹窗"问题
- `since` 参数：`/api/signals/pending?since=` 过滤本次连接前的历史信号
- `/api/settings/period`：动态切换后台扫描周期
- 左上角实时时钟（`hdr-clock`，每秒更新）
- K线图内顶部时间（`kbar-time`，crosshair联动，鼠标离开恢复末根K线时间）
- 弹窗文字静止修复（反向动画抵消外框抖动）
- 全自选扫描覆盖当前展示品种

### v3.0
- 切换为主力连续合约（X0格式）
- 全面代码清理：删除死代码，修复闭包bug
- Docker配置修复（端口、volume）
- 增量刷新 `mode=update`，图表无闪烁

### v2.0
- 指标插件系统 + TDX公式解析器
- 自选股面板 + 桌面通知 + 右锚缩放

### v1.0
- 主图信号（黄点/绿点）+ 波段王副图 + K/D色块柱

---

## License

MIT · 仅供学习研究，不构成投资建议
