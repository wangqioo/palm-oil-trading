# 交易系统配置文件
# 填入你的 Tushare Token（注册 tushare.pro 获取）
TUSHARE_TOKEN = ""  # TODO: 填入你的 token

# 棕榈油期货主力合约代码（大连商品交易所）
PALM_OIL_CODE = "P.DCE"       # Tushare 格式
PALM_OIL_AKSHARE = "棕榈油"   # AkShare 备用

# 原油期货（用于对比）
CRUDE_OIL_CODE = "SC.INE"     # 上海能源中心原油

# 交易时间段
TRADE_SESSIONS = [
    ("09:00", "10:15"),
    ("10:30", "11:30"),
    ("21:00", "23:00"),
]

# 主力均线参数（根据你的系统调整）
MA_PERIODS = [5, 10, 20, 30, 60]

# 振荡指标参数（待你提供公式后填入）
OSCILLATOR_PARAMS = {
    "fast_period": None,   # 快线周期，待确认
    "slow_period": None,   # 慢线周期，待确认
    "signal_method": None, # 信号触发方式，待确认
}
