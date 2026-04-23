# 期货交易看板 v3.1

基于平安证券慧赢风格的期货实时交易看板，支持多品种自选、TDX公式导入、桌面信号推送。

---

## 功能概览

- **多品种自选**：搜索添加任意期货合约（连续主力或具体月份合约），支持本地持久化
- **实时K线图**：蜡烛图 + 成交量 + 五级叠加均线（M1~M5），与慧赢配色一致
- **主图信号**：黄点（破浪/做多入场）、绿点（破浪/做空入场），标记在K线上，不被任何线遮挡
- **波段王副图**：K/D动能色块柱（红=多头/绿=空头）+ 90参考线
- **信号面板**：实时显示6项条件是否满足（做多3条 + 做空3条），✔/✘逐项标注
- **历史信号**：最近10次做多/做空信号记录
- **桌面通知**：信号触发时弹出系统通知（需授权）
- **全自选扫描**：每60秒扫描自选列表所有品种（含当前展示品种），统一用15分钟周期判断信号，任意品种触发均推送桌面通知
- **TDX公式导入**：粘贴慧赢/通达信公式，自动解析生成副图插件并热加载
- **无闪烁刷新**：增量更新只推送最后3根K线，图表不重绘不跳动
- **右锚缩放**：滚轮以最新K线为固定轴缩放，与慧赢操作习惯一致

---

## 信号触发逻辑

### 做多信号（三条件同时满足）
1. 主图出现**黄点**（QRG 上穿 -10，破浪信号）
2. 波段王 **K > 30**
3. 波段王 **K ≥ D**（多头柱，红色）

### 做空信号（三条件同时满足）
1. 主图出现**绿点**（QRG 跌至 -50，空仓信号）
2. 波段王 **K < 80**
3. 波段王 **K ≤ D**（空头柱，绿色）

---

## 快速启动

### 本地运行

```bash
git clone https://github.com/wangqioo/palm-oil-trading.git
cd palm-oil-trading
pip install flask flask-cors pandas akshare
python server.py
# 访问 http://localhost:8877
```

### Docker 部署

```bash
git clone https://github.com/wangqioo/palm-oil-trading.git
cd palm-oil-trading
mkdir -p logs data knowledge_base/signals
docker compose up -d --build
# 访问 http://服务器IP:8877
```

---

## 项目结构

```
.
├── server.py              # Flask API 服务（数据获取 + 指标计算 + 路由）
├── indicators.py          # 核心指标计算（主图信号 + 波段王）
├── data_fetcher.py        # 辅助计算（支撑压力位 + 资金流向）
├── signal_monitor.py      # 独立信号监控脚本（命令行运行）
├── daily_report.py        # 每日早报生成脚本
├── dashboard/
│   └── index.html         # 前端单页应用（所有UI逻辑）
├── indicators_pkg/        # 指标插件系统
│   ├── __init__.py        # 插件自动发现 + 热加载
│   ├── main_signal.py     # 主图信号插件（M1~M5均线 + 黄绿点）
│   ├── bsd_wang.py        # 波段王插件（K/D色块柱）
│   └── *.py               # 用户通过「导入公式」自动生成的插件
├── tdx_parser/
│   ├── parser.py          # TDX 公式解析器（赋值/DRAWTEXT/STICKLINE）
│   └── functions.py       # TDX 内置函数库（EMA/MA/SMA/REF/HHV/LLV等）
├── data/                  # 日线数据缓存（gitignore，自动生成）
├── docker-compose.yml
└── Dockerfile
```

---

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/data` | GET | 获取K线 + 指标数据。参数：`symbol`（如P0）、`period`（1/5/15/30/60/daily）、`mode`（full/update） |
| `/api/symbols` | GET | 获取默认自选品种列表 |
| `/api/search?q=铜` | GET | 搜索期货品种名称或代码前缀 |
| `/api/resolve?symbol=RB2510` | GET | 验证合约代码是否存在并返回名称 |
| `/api/indicators` | GET | 列出所有已加载指标插件 |
| `/api/import_formula` | POST | 导入TDX公式，body: `{"name":"","source":"","panel":"sub"}` |

---

## 默认自选品种

| 代码 | 品种 | 说明 |
|------|------|------|
| P0 | 棕榈油主力 | 大连商品交易所 |
| AG0 | 白银主力 | 上海期货交易所 |
| BC0 | 国际铜主力 | 上海国际能源交易中心 |
| CU0 | 铜主力 | 上海期货交易所 |
| SA0 | 纯碱主力 | 郑州商品交易所 |

> 全部使用新浪**主力连续合约**格式（品种前缀+0），永远跟踪当前主力，无需手动换月。

---

## TDX公式导入

1. 点击顶部**「导入公式」**按钮
2. 填写指标名称，选择「副图」或「主图」
3. 粘贴慧赢/通达信公式代码，点击「解析并添加」
4. 副图立即出现在图表中，无需刷新页面；主图指标需刷新后生效

**支持的语法：**

```
{ 注释 }
VAR1:=EMA(CLOSE,13);          { 中间变量（不绘图） }
MYLINE,VAR1,COLORRED,2;       { 输出折线：名称,表达式,颜色,粗细 }
DRAWTEXT(CROSS(K,D),LOW,'买'); { K线标注文字 }
STICKLINE(K>=D,K,D,2,0),COLORRED; { 色块柱 }
```

**支持的内置函数：**
EMA、MA、SMA、REF、HHV、LLV、CROSS、IF、ABS、MAX、MIN、STD、SUM、COUNT、EVERY、EXIST、HHVBARS、LLVBARS、SLOPE

---

## 插件开发

在 `indicators_pkg/` 下新建 `.py` 文件，服务启动时自动加载：

```python
import pandas as pd

META = {
    "name":    "我的指标",
    "id":      "my_indicator",   # 唯一ID，与文件名一致
    "panel":   "sub",            # "main" 主图 / "sub" 副图
    "outputs": [
        {"col": "LINE1", "type": "line",   "color": "#FF0000", "width": 2},
        {"col": "SIG",   "type": "marker", "position": "belowBar",
         "color": "#FFD700", "shape": "circle", "size": 1.2},
    ],
    "hlines": [
        {"value": 80, "color": "#888888", "width": 1},
    ],
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
- 全自选扫描覆盖当前展示品种（之前会跳过）
- 扫描固定使用15分钟周期，不受图表周期切换影响

### v3.0
- 切换为主力连续合约（X0格式），数据永不过期
- 全面代码审查：删除所有死代码（`get_warmup_data`、`resample_weekly`等）
- 修复 `rising()` 闭包 bug（for循环内变量捕获问题）
- 修复 Docker 配置：端口 8080→8877，补全 volume 挂载
- 清理 `data_fetcher.py`，删除不再调用的数据获取函数
- 全自选品种静默扫描信号（每60秒）
- 增量刷新（`mode=update`），图表无闪烁

### v2.0
- 指标插件系统（`indicators_pkg/`），支持热加载
- TDX/慧赢公式解析器（`tdx_parser/`）
- 「导入公式」模态框，副图动态生成
- 桌面 Notification 信号推送（含去重）
- 自选股面板：搜索、添加、删除，localStorage持久化
- 右锚缩放（最新K线固定）

### v1.0
- 多品种期货交易看板
- 主图信号（黄点/绿点）+ 波段王副图
- K/D色块柱 + 支撑压力位
- 三图十字线联动

---

## 注意事项

- 本系统仅供学习与研究使用，不构成投资建议
- 期货交易具有高风险，入市需谨慎
- 信号基于历史数据计算，不保证未来收益

---

## License

MIT
