# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

期货交易看板 v3.1，慧赢（平安证券）风格。Flask 后端 + 单页前端，用于实时监控期货合约信号。

## 运行与部署

```bash
# 本地运行（端口 8877）
python server.py

# Docker 部署
docker-compose up -d
docker-compose build && docker-compose up -d   # 代码有改动时重建
```

无测试命令，无 lint 工具。验证方式：直接访问 http://localhost:8877 查看界面。

## 架构

```
server.py           Flask API + 数据获取（all-in-one，无独立路由文件）
indicators.py       TDX公式 Python 复现：主图信号（QRG/破浪/空仓）+ 波段王（K/D）
data_fetcher.py     支撑压力位、资金流向计算（仅计算，不获取数据）
indicators_pkg/     可热加载指标插件，每个 .py 文件需有 META + compute(df)
tdx_parser/         TDX/通达信公式 → Python 插件代码 的解析器
dashboard/index.html  单文件前端（CSS + JS 全嵌入，~1500行）
data/               日线数据本地 CSV 缓存（daily_<CODE>.csv）
```

## 数据流

1. 前端按钮触发 → `loadData()` → `GET /api/data?period=&symbol=`
2. `server.py:get_data()` → `get_minute_data()` 或 `get_daily_data()` (akshare)
3. `indicators.py:calc_main_signals()` + `calc_bsd_wang()` → 附加指标列
4. 序列化为 JSON → `indicator_series[]`（每根K线含 OHLCV + 所有指标值）
5. 前端 `renderAll()` → lightweight-charts 渲染

## 关键细节

**120分钟K线**：akshare 无直接接口，拉 60分钟后用 `pd.resample('120min')` 聚合（见 `server.py:get_minute_data()`）。

**周线**：需拉日线数据后按自然周（`resample('W-FRI')`）聚合，目前尚未实现。

**信号逻辑**：
- 做多：`破浪`=QRG上穿-10 且 K>30 且 K≥D
- 做空：`空仓`=QRG跌至-50（前值≥-30）且 K<80 且 K≤D

**全自选扫描**：`scanAllWatchlist()` 每60秒在前端触发，固定用30分钟周期，不受图表当前周期影响（`dashboard/index.html` 第1173行）。

**配色规范（慧赢风格）**：
- 阳线：红色 `#ef5350`，阴线：白色
- 多头：红色 (`var(--bull)` = `#ef5350`)，空头：绿色 (`var(--bear)` = `#26a69a`)
- M1~M5 均线：下降黄色 `#FFD700`，上升粉色 `#FF00FF`
- 波段王彩带：多头 `#CC0000`，空头 `#00AA00`

**插件热加载**：`POST /api/import_formula` → TDX 公式 → 写入 `indicators_pkg/<id>.py` → `ipkg.reload_all()`

**SYMBOLS 表**：`server.py` 顶部硬编码，主力连续合约用 `代码+0`（如 `P0`），免去换月维护。动态合约（如 `RB2510`）不在表中时，自动构造配置。

## 前端结构（dashboard/index.html）

- `initCharts()` — 初始化 lightweight-charts（主图 kChart + 副图 bsdChart）
- `renderAll(data)` — 全量渲染，切换品种/周期时调用
- `updateBars(bars)` — 增量刷新，定时刷新时调用（只更新最后3根K线）
- `drawBsdCanvas(bars)` — 用 Canvas 画波段王 STICKLINE 色块（K到D之间）
- `checkAndNotify(data)` — 检测信号，触发弹窗 + 桌面通知
- `showSignalToast(data, sigType)` — 显示信号弹窗（最多同时3个，超出进未读队列）
- `scanAllWatchlist()` — 静默扫描所有自选品种，每60秒执行

## 注意事项

- 前端是单一 HTML 文件，不拆分。改 UI 就改 `dashboard/index.html`。
- `server.py` 既是数据获取层也是路由层，保持这种合并结构，不引入蓝图或新文件。
- 日线数据本地缓存（`data/` 目录），akshare 失败时自动回退缓存。
- 目前无 `scheduler.py`，后端定时扫描逻辑尚未实现，信号扫描全在前端 `setInterval` 驱动。
