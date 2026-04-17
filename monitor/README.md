# 美股强势股监控系统

基于OpenBB构建的美股监控系统，用于识别低波动率且偏强/偏弱的股票。

## 功能特性

- **监控池构建**: 自动从CSV数据中构建监控池，包含成交额前500只股票和涨幅排名前15的股票
- **低波动率检测**: 基于Julia参考实现的多均线粘合度算法
- **技术指标计算**: RSI(20)等技术指标
- **4小时数据聚合**: 从1小时数据生成4小时K线
- **市场条件判断**: 基于QQQ、SPY、DIA的看跌形态判断
- **智能报警**: 企业微信webhook推送
- **缓存机制**: 24小时缓存，提高效率

## 系统架构

```
├── config.py              # 配置管理
├── data_loader.py         # 数据加载和缓存
├── data_aggregator.py     # 4小时数据聚合
├── volatility_calculator.py # 波动率计算
├── technical_indicators.py  # 技术指标
├── market_condition.py    # 市场条件判断
├── alert_system.py        # 报警系统
├── stock_analyzer.py      # 主分析器
├── main.py               # 主程序入口
└── requirements.txt      # 依赖包
```

## 安装和配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `env.template` 为 `.env` 并填入配置：

```bash
cp env.template .env
```

编辑 `.env` 文件：

```bash
# OpenBB API Token (可选，但推荐用于提高速率限制)
OPENBB_TOKEN=your_openbb_token_here

# 企业微信Webhook URL
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_webhook_key_here
```

### 3. 准备数据文件

确保CSV数据文件存在，默认路径为 `20251020232140.csv`。文件应包含以下列：
- Symbol: 股票代码
- Volume: 成交量
- Price: 价格
- 5D Chg, 10D Chg, 20D Chg, 60D Chg: 不同周期的涨跌幅

## 使用方法

### 基本使用

```bash
python main.py
```

### 配置检查

```bash
python main.py --config-check
```

### 调试模式

```bash
python main.py --log-level DEBUG
```

### 干运行（不发送通知）

```bash
python main.py --dry-run
```

## 监控逻辑

### 1. 监控池构建

- 从CSV数据中取过去5日平均成交额前500只股票
- 按15天、30天、60天、120天涨幅排序，各取前15名
- 去重后形成最终监控池

### 2. 低波动率检测

基于Julia参考实现的算法：
- 计算多条均线（2,5,7,9,11,13,15,17,20日）
- 计算均线粘合度指标（MACO）
- 结合ATR和历史阈值判断低波动条件

### 3. 市场条件判断

在4小时和日线级别检查QQQ、SPY、DIA（4小时数据通过1小时数据聚合生成）：
- 看跌形态1：close < open
- 看跌形态2：close < 0.5 * (high + low)
- 3只ETF中有2只满足看跌形态才触发报警

### 4. 报警条件

- 波动率处于低位
- RSI ≥ 48：输出"低波动且偏强"
- RSI < 48：输出"低波动且偏弱"

## 输出格式

```
[偏强提醒] SYMBOL 在 4h 级别 出现低波动且偏强（RSI=52.3）
[偏弱提醒] SYMBOL 在 1d 级别 出现低波动且偏弱（RSI=45.1）
```

## 缓存机制

- 监控池缓存：24小时过期
- 成交额排名缓存：24小时过期
- 缓存文件存储在 `cache/` 目录

## 日志

- 控制台输出：实时显示分析进度
- 文件日志：保存到 `monitor.log`
- 结果文件：保存到 `analysis_results_YYYYMMDD_HHMMSS.json`

## 故障排除

### 常见问题

1. **CSV文件不存在**
   - 检查 `config.csv_data_path` 配置
   - 确保文件路径正确

2. **OpenBB认证失败**
   - 检查 `OPENBB_TOKEN` 环境变量
   - 确认token有效

3. **WeChat通知失败**
   - 检查 `WECHAT_WEBHOOK_URL` 配置
   - 确认webhook URL有效

4. **数据不足**
   - 确保CSV文件包含足够的历史数据
   - 检查数据格式是否正确

### 调试技巧

- 使用 `--log-level DEBUG` 查看详细日志
- 使用 `--config-check` 验证配置
- 使用 `--dry-run` 测试分析逻辑

## 扩展开发

### 添加新的技术指标

在 `technical_indicators.py` 中添加新方法：

```python
@staticmethod
def calculate_new_indicator(prices: np.ndarray, period: int) -> np.ndarray:
    # 实现新指标
    pass
```

### 修改报警条件

在 `alert_system.py` 中修改 `generate_alert` 方法：

```python
def generate_alert(self, symbol: str, timeframe: str, rsi_value: float, 
                  is_low_volatility: bool) -> Optional[Alert]:
    # 自定义报警条件
    pass
```

### 添加新的数据源

在 `data_loader.py` 中扩展数据加载逻辑：

```python
def load_from_new_source(self) -> List[str]:
    # 实现新数据源
    pass
```

## 许可证

本项目仅供学习和研究使用。
