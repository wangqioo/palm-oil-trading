# 期货交易看板 v3.1

基于平安证券慧赢风格的期货实时交易看板。Flask 后端 + 单页前端，支持多品种自选、多周期K线、实时信号推送、TDX公式导入。

---

## 快速启动

```bash
pip install flask flask-cors pandas akshare
python server.py          # 访问 http://localhost:8877
```

Docker：

```bash
docker compose up -d --build
```

---

## 功能一览

| 功能 | 说明 |
|------|------|
| 多品种自选 | 搜索任意期货合约（主力连续或具体月份），本地持久化 |
| 多周期K线 | 1/5/15/30/60/120分钟、日线、周线，无闪烁增量刷新 |
| 主图信号 | 黄点（做多/破浪）、绿点（做空/空仓），标注在K线上 |
| 波段王副图 | K/D动能色块柱（红=多头 / 绿=空头），Canvas绘制 |
| 信号弹窗 | 最多同时3个，超出进未读队列；超时未操作自动归档至铃铛 |
| 多周期共振 | 多个周期同时触发时合并为共振弹窗（⚡⚡） |
| 桌面通知 | 浏览器授权后，后台也能收到信号推送 |
| 全自选扫描 | 每60秒扫描所有自选品种，固定用30分钟周期判断 |
| TDX公式导入 | 粘贴慧赢/通达信公式，自动解析生成副图插件并热加载 |
| 支撑压力位 | 侧边栏显示近期高低点位阶 |
| 多周期趋势 | 面板展示各周期K/D多空状态 |

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  dashboard/index.html  （单文件前端，~2000行）           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │ K线主图  │  │  波段王副图  │  │  自选 + 信号面板   │ │
│  └──────────┘  └──────────────┘  └────────────────────┘ │
│  轮询 /api/signals/pending（3s）+ scanAllWatchlist（60s）│
└────────────────────┬────────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────────┐
│  server.py  （Flask all-in-one）                         │
│  ├─ 数据拉取：akshare → 内存缓存（分钟线+日线TTL）      │
│  ├─ 指标计算：indicators.py / data_fetcher.py            │
│  ├─ 信号队列：_pending_signals（内存列表）               │
│  ├─ 去重DB：data/signals.db（SQLite）                    │
│  └─ 后台线程：_scanner_loop（每60s，收盘时刻才扫描）     │
└─────────────────────────────────────────────────────────┘
scheduler.py  （可选独立调度进程，HTTP POST 推送信号）
```

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `server.py` | Flask API + 数据拉取 + 后台扫描线程（all-in-one） |
| `indicators.py` | TDX公式 Python 复现：QRG / 破浪 / 空仓 / 波段王K/D |
| `data_fetcher.py` | 支撑压力位、资金流向计算（纯计算，不拉数据） |
| `scheduler.py` | 可选独立信号调度进程，与 server.py 共用 signals.db |
| `dashboard/index.html` | 单文件前端（CSS + JS 全内嵌） |
| `indicators_pkg/` | 指标插件目录，支持热加载 |
| `tdx_parser/` | TDX/慧赢公式 → Python 插件代码解析器 |
| `data/` | 日线 CSV 缓存 + signals.db（Docker volume 挂载） |

---

## 数据流

```
前端 loadData(mode)
  → GET /api/data?symbol=P0&period=30&mode=full
  → server.py: get_data()
      ├─ get_minute_data()   # 分钟线，按周期TTL缓存
      ├─ get_daily_data()    # 日线，5分钟内存缓存 + CSV回退
      ├─ get_weekly_data()   # 日线 resample('W-FRI')
      ├─ calc_main_signals() # 主图：QRG / 破浪 / 空仓
      ├─ calc_bsd_wang()     # 副图：K/D 波段王
      └─ indicator_series[]  # 每根K线的完整数据
  → 前端 renderAll(data) 或 updateBars(bars)
```

### 缓存 TTL

| 周期 | TTL |
|------|-----|
| 1分钟 | 20秒 |
| 5分钟 | 60秒 |
| 15分钟 | 3分钟 |
| 30分钟 | 5分钟 |
| 60分钟 | 10分钟 |
| 120分钟 | 20分钟 |
| 日线 | 5分钟（内存），过期后落盘CSV |

> **120分钟K线**：akshare 无原生接口，拉60分钟后 `resample('120min')` 聚合。  
> **周线**：日线 `resample('W-FRI', closed='right', label='right')` 聚合。

---

## 信号系统

### 触发条件

**做多**：`破浪`（QRG 上穿 -10）且 K > 30 且 K ≥ D  
**做空**：`空仓`（QRG 跌至 -50，前值 ≥ -30）且 K < 80 且 K ≤ D

### 后台扫描器

`python server.py` 启动时自动开启后台线程 `_scanner_loop`，每 60 秒扫描一次，仅在 K 线收盘时刻推送：

| 周期 | 推送条件 |
|------|----------|
| 1分钟 | 每次都判断 |
| 5分钟 | minute % 5 == 0 |
| 15分钟 | minute % 15 == 0 |
| 30分钟 | minute % 30 == 0 |
| 60分钟 | minute == 0 |
| 120分钟 | minute == 0 且 hour % 2 == 0 |
| 日线 | hour == 15 且 minute == 1 |
| 周线 | 周五 且 hour == 15 且 minute == 1 |

### 去重（三重）

1. **SQLite**：`UNIQUE(symbol, signal_type, candle_time)`，跨重启持久化
2. **`_silentInit`**：页面加载后第一轮扫描静默录入状态，不弹窗
3. **`since` 参数**：`/api/signals/pending?since=` 只返回本次连接后产生的信号

### 未读信号归档

弹窗超出3个时进 `_unreadSignals` 队列；**倒计时归零未操作也自动归档**，点铃铛图标可查看和回放。

---

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/data` | GET | K线+指标数据。参数：`symbol` `period` `mode`（full/update） |
| `/api/symbols` | GET | 默认自选品种列表 |
| `/api/search?q=铜` | GET | 搜索品种名称或代码前缀 |
| `/api/resolve?symbol=RB2510` | GET | 验证合约代码并返回名称 |
| `/api/trend?symbol=P0` | GET | 各周期K/D趋势状态（5分钟缓存） |
| `/api/indicators` | GET | 已加载插件列表 |
| `/api/import_formula` | POST | 导入TDX公式，body: `{"name":"","source":"","panel":"sub"}` |
| `/api/signals/pending` | GET | 取出并清空信号队列，`?since=` 过滤历史信号 |
| `/api/signals/push` | POST | 外部进程（scheduler.py）推送信号入队 |
| `/api/settings/period` | GET/POST | 查询/切换后台扫描周期 |

---

## 前端结构

### 布局

```
#header（顶部导航栏）
  左：hdr-name（品种名）hdr-contract（代码）hdr-price  hdr-chg
  右：[周期按钮] [铃铛未读] [刷新] [全屏]  hdr-clock（实时时钟）

#sidebar（左侧240px）
  自选搜索框 → 自选列表（含信号圆点状态）
  当前信号面板 → 历史信号 → 多周期趋势 → 触发周期设置

#charts-area
  #wrap-kline（55%高）
    chart-label "K线"  legend-kline（OHLC + K线时间，鼠标悬停联动）
    chart-kline（lightweight-charts 主图）
  [resizer 拖动条]
  #wrap-bsd（26%高）
    chart-label "波段王"  legend-bsd（K/D值）
    bsd-canvas（Canvas色块柱）  chart-bsd
```

### 关键函数

| 函数 | 说明 |
|------|------|
| `initCharts()` | 初始化 lightweight-charts 主图+副图 |
| `renderAll(data)` | 全量渲染，切换品种/周期时调用 |
| `updateBars(bars)` | 增量刷新，只推最后3根K线 |
| `drawBsdCanvas(bars)` | Canvas 绘制波段王色块柱 |
| `setupLegends()` | 订阅 crosshair，联动更新 OHLC+时间图例 |
| `updateKlineLegend(bar)` | 更新K线图内左上角 OHLC + 时间显示 |
| `checkAndNotify(data, period)` | 检测信号，触发弹窗+桌面通知 |
| `showSignalToast(data, sigType, period)` | 显示做多/做空弹窗（最多3个） |
| `showResonanceToast(data, periods, sigType)` | 显示多周期共振弹窗 |
| `scanAllWatchlist()` | 静默扫描所有自选品种（60s间隔） |
| `loadData(mode)` | 拉取数据，支持 AbortController 取消过期请求 |
| `_consumePending()` | 轮询 `/api/signals/pending`（3s间隔） |

### 关键全局变量

| 变量 | 说明 |
|------|------|
| `currentSymbol` / `currentSymbolName` | 当前展示的品种 |
| `currentPeriod` | 当前K线周期 |
| `allData` | 最新一次 API 响应完整数据 |
| `_unreadSignals` | 未读/超时信号队列 |
| `_silentInit` | `true`=首轮扫描静默；扫完后自动置 `false` |
| `_loadAbort` | AbortController，快速切换时取消上一个未完成请求 |

---

## 配色规范（慧赢风格）

| 元素 | 颜色 |
|------|------|
| 阳线 | `#ef5350`（红） |
| 阴线 | 白色 |
| 做多 / 多头 | `var(--bull)` = `#ef5350` |
| 做空 / 空头 | `var(--bear)` = `#26a69a` |
| M1~M5 均线（下降） | `#FFD700`（黄） |
| M1~M5 均线（上升） | `#FF00FF`（粉） |
| 波段王多头色块 | `#CC0000` |
| 波段王空头色块 | `#00AA00` |

---

## 默认品种

| 代码 | 品种 |
|------|------|
| P0 | 棕榈油主力 |
| AG0 | 白银主力 |
| BC0 | 国际铜主力 |
| CU0 | 铜主力 |
| SA0 | 纯碱主力 |

全部使用新浪主力连续合约格式（品种前缀 + 0），永远跟踪当前主力，无需换月。不在列表的合约（如 `RB2510`）由 `get_data()` 自动构造配置。

---

## 指标插件开发

在 `indicators_pkg/` 下新建 `.py` 文件：

```python
import pandas as pd

META = {
    "name": "示例指标", "id": "my_indicator", "panel": "sub",
    "outputs": [
        {"col": "LINE1", "type": "line",   "color": "#FF0000", "width": 2},
        {"col": "SIG",   "type": "marker", "position": "belowBar",
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

保存后调用 `POST /api/import_formula` 或直接放入目录（服务端会自动热加载）。

---

## 注意事项

- `server.py` 是数据层+路由层 all-in-one，不引入蓝图，不拆分文件
- 前端是单一 HTML 文件，不拆分组件，改 UI 只改 `dashboard/index.html`
- 日线数据有本地 CSV 缓存（`data/` 目录），akshare 失败时自动回退
- 波段王色块由 Canvas 绘制，不是 lightweight-charts 原生序列
- 三图联动（主图/副图/动态插件）通过 `subscribeVisibleLogicalRangeChange` + `_syncing` 旗防递归同步

---

## 版本历史

### v3.1（当前）
- 实时时钟移至导航栏右侧，K线图内左上角合并显示 OHLC + K线时间
- 弹窗超时未操作自动归档至铃铛未读信号列表
- 日线数据加入5分钟内存 TTL 缓存，切换周期/品种速度大幅提升
- 前端 AbortController：快速切换时取消过期请求，防止旧响应覆盖
- 后台扫描器集成至 server.py，支持动态切换扫描周期
- 三字段联合去重（SQLite 持久化），`_silentInit` + `since` 双重保护防误弹

### v3.0
- 切换为主力连续合约（X0格式），无需手动换月
- 全面代码清理，修复闭包 bug
- Docker 配置修复（端口、volume）
- 增量刷新 `mode=update`，图表无闪烁

### v2.0
- 指标插件系统 + TDX公式解析器
- 自选股面板 + 桌面通知 + 右锚缩放

### v1.0
- 主图信号（黄点/绿点）+ 波段王副图 + K/D色块柱

---

## License

MIT · 仅供学习研究，不构成投资建议
