# 棕榈油期货交易信号系统

基于 TDX（通达信）指标公式的棕榈油期货自动信号检测系统，配备专业级 K 线看板。

---

## 功能概览

### 信号检测

系统重现了平安证券慧赢平台中的两套指标公式：

**主图指标（QRG 强度）**

- 多条 EMA 级联计算 QRG 强度分（-50 ~ +50）
- **破浪信号（黄点）**：QRG 由负转正，看多入场
- **空仓信号（绿点）**：QRG 由正转负，看空离场

**副图指标（波段王）**

- Stochastic 风格的 K/D 振荡器（0 ~ 100）
- K >= D 且 K > 30：多头结构
- K <= D 且 K < 80：空头结构

**组合触发条件（15分钟K线）**

| 信号 | 条件 |
|------|------|
| ▲ 做多 | 主图破浪（黄点）+ 波段王 K > 30 且 K >= D |
| ▼ 离场 | 主图空仓（绿点）+ 波段王 K < 80 且 K <= D |

---

### 可视化看板

使用 [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) 构建的专业交易看板：

- **K 线图**：蜡烛图 + 成交量 + 信号箭头标记 + 支撑压力位虚线
- **波段王**：K/D 色块填充（红色=多头，绿色=空头）+ K/D 折线
- **QRG 强度**：正负柱状图
- OHLC 图例（鼠标悬停实时显示）
- 周期切换：1分 / 15分 / 60分 / 日线
- 三图十字线联动 + 时间轴同步
- 面板高度可拖拽调整
- 全屏模式
- 每 60 秒自动刷新

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 数据源 | [AkShare](https://github.com/akfamily/akshare) 新浪财经期货接口 |
| 后端 | Python + Flask |
| 前端 | TradingView Lightweight Charts v4 |
| 部署 | Docker + Docker Compose |

---

## 快速部署

### 前置要求

- Docker & Docker Compose
- 公网服务器（或本地运行）

### 一键启动

```bash
git clone https://github.com/wangqioo/palm-oil-trading.git
cd palm-oil-trading

# 创建必要目录
mkdir -p logs data knowledge_base/signals

docker compose up -d
```

服务启动后访问：`http://<服务器IP>:8877`

---

## 项目结构

```
palm-oil-trading/
├── server.py            # Flask API 服务
├── indicators.py        # TDX 指标 Python 重现
├── data_fetcher.py      # AkShare 数据获取
├── signal_monitor.py    # 实时信号监控
├── daily_report.py      # 每日早报生成
├── config.py            # 配置文件
├── dashboard/
│   └── index.html       # 专业 K 线看板
├── Dockerfile
└── docker-compose.yml
```

---

## API 接口

### `GET /api/data`

获取当前合约数据、指标序列和信号状态。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `period` | 周期（1/5/15/30/60/daily） | `15` |

**返回字段：**

```json
{
  "contract": "P2609",
  "updated": "2026-04-16 14:15:00",
  "signals": {
    "做多": false,
    "离场": false
  },
  "indicator_series": [
    {
      "time": 1744780800,
      "open": 8600, "high": 8650, "low": 8580, "close": 8630,
      "volume": 12500,
      "K": 45.2, "D": 38.6, "QRG": 12.4,
      "po": false, "kong": false
    }
  ],
  "levels": [...],
  "history": [...]
}
```

---

## 历史信号回测

| 日期 | 信号 | 价格 |
|------|------|------|
| 2026-01-07 | ▲ 做多 | 8452 |
| 2026-02-11 | ▼ 离场 | 8886 |
| 2026-04-10 | ▼ 离场 | 9621 |

---

## 注意事项

- 本系统仅供学习与研究使用，不构成投资建议
- 期货交易具有高风险，入市需谨慎
- 信号基于历史数据计算，不保证未来收益

---

## License

MIT
