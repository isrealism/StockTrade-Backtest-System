# 选股器组合逻辑配置指南

## 概述

回测系统现在支持多种选股器组合逻辑,允许你灵活配置买入信号的生成方式。

## 四种组合模式

### 1. OR模式 (默认)
**说明**: 任意一个激活的选股器触发信号即可生成买入信号

**适用场景**:
- 希望捕捉更多交易机会
- 各选股器之间独立,不需要相互验证

**配置示例**:
```json
{
  "selector_combination": {
    "mode": "OR"
  }
}
```

### 2. AND模式
**说明**: 所有激活的选股器都必须同时触发信号才生成买入信号

**适用场景**:
- 需要多个条件同时满足,提高信号质量
- 降低交易频率,只做高确定性机会

**配置示例**:
```json
{
  "selector_combination": {
    "mode": "AND"
  }
}
```

### 3. 时间窗口模式 (TIME_WINDOW)
**说明**: 在指定的时间窗口内,不同选股器先后触发信号即可

**适用场景**:
- 需要验证趋势持续性
- 允许信号略有时间差异

**配置示例**:
```json
{
  "selector_combination": {
    "mode": "TIME_WINDOW",
    "time_window_days": 5
  }
}
```

**参数说明**:
- `time_window_days`: 时间窗口天数(1-30),默认5天

### 4. 顺序确认模式 (SEQUENTIAL_CONFIRMATION)
**说明**: 先由触发选股器生成初始信号,然后等待确认选股器在时间窗口内确认

**适用场景**:
- 需要两阶段验证的策略
- 先识别潜在机会,再等待确认信号
- 例如:先发现底部形态(触发),再等待放量突破(确认)

**配置示例**:
```json
{
  "selector_combination": {
    "mode": "SEQUENTIAL_CONFIRMATION",
    "time_window_days": 5,
    "trigger_selectors": ["BBIKDJSelector", "SuperB1Selector"],
    "trigger_logic": "OR",
    "confirm_selectors": ["MA60CrossVolumeWaveSelector"],
    "confirm_logic": "OR",
    "buy_timing": "confirmation_day"
  }
}
```

**参数说明**:
- `trigger_selectors`: 触发选股器列表(选择哪些选股器作为触发条件)
- `trigger_logic`: 触发逻辑 - "OR"(任意一个触发) 或 "AND"(全部触发)
- `confirm_selectors`: 确认选股器列表(选择哪些选股器作为确认条件)
- `confirm_logic`: 确认逻辑 - "OR"(任意一个确认) 或 "AND"(全部确认)
- `time_window_days`: 等待确认的时间窗口(天数)
- `buy_timing`: 买入时机
  - `"confirmation_day"`: 在确认日买入(默认)
  - `"trigger_day"`: 在触发日买入(确认后才真正执行)

## 前端使用说明

### 步骤1: 选择组合模式
1. 打开回测配置页面
2. 在"Buy Selectors"卡片中找到"组合模式"下拉菜单
3. 选择四种模式之一

### 步骤2: 配置参数(根据模式不同)

#### OR模式 / AND模式
- 无需额外配置
- 直接激活你想要使用的选股器

#### 时间窗口模式
1. 设置"时间窗口(天数)"
2. 激活你想要使用的选股器

#### 顺序确认模式
1. 设置"时间窗口(天数)"
2. 在"触发选股器"区域勾选作为触发条件的选股器
3. 选择"触发逻辑"(OR或AND)
4. 在"确认选股器"区域勾选作为确认条件的选股器
5. 选择"确认逻辑"(OR或AND)
6. 选择"买入时机"

### 步骤3: 运行回测
- 点击"Run Backtest"按钮
- 系统将使用你配置的组合逻辑生成买入信号

## 实战示例

### 示例1: 保守策略 - AND模式
**目标**: 只在多个信号同时出现时买入,降低风险

**配置**:
- 模式: AND
- 激活选股器: 少妇战法 + SuperB1战法 + 填坑战法

**预期效果**:
- 信号数量较少
- 但每个信号都经过多重验证
- 胜率可能较高

### 示例2: 激进策略 - OR模式
**目标**: 捕捉更多交易机会

**配置**:
- 模式: OR
- 激活选股器: 全部6个选股器

**预期效果**:
- 信号数量较多
- 交易频率高
- 需要配合合理的止损策略

### 示例3: 两阶段验证 - 顺序确认模式
**目标**: 先识别底部,再等待放量突破

**配置**:
- 模式: SEQUENTIAL_CONFIRMATION
- 触发选股器: 少妇战法 + SuperB1战法 (OR逻辑)
- 确认选股器: 上穿60放量战法 (OR逻辑)
- 时间窗口: 5天
- 买入时机: 确认日买入

**逻辑说明**:
1. 当"少妇战法"或"SuperB1战法"触发时,标记该股票为潜在机会
2. 在接下来5天内,等待"上穿60放量战法"确认
3. 一旦确认,在确认日生成买入信号
4. 如果5天内未确认,则放弃该机会

**预期效果**:
- 结合了底部形态识别和突破确认
- 提高信号质量
- 避免过早介入

## 技术细节

### 数据结构
前端发送给后端的payload结构:
```javascript
{
  "buy_config": {
    "selectors": [...],
    "selector_combination": {
      "mode": "SEQUENTIAL_CONFIRMATION",
      "time_window_days": 5,
      "trigger_selectors": ["BBIKDJSelector"],
      "trigger_logic": "OR",
      "confirm_selectors": ["MA60CrossVolumeWaveSelector"],
      "confirm_logic": "OR",
      "buy_timing": "confirmation_day"
    }
  }
}
```

### 后端处理
- 配置在`backtest/engine.py`中的`load_buy_selectors()`方法加载
- 信号生成逻辑在`get_buy_signals()`方法中处理
- 支持完整的lookahead bias prevention

## 测试

运行测试脚本查看示例payload:
```bash
python scripts/test_selector_combination_ui.py
```

## 注意事项

1. **AND模式风险**:
   - 可能导致信号数量极少
   - 确保所选选股器之间有一定相关性

2. **顺序确认模式建议**:
   - 触发选股器应识别早期信号(如形态、指标超卖)
   - 确认选股器应验证趋势启动(如放量、均线突破)
   - 时间窗口不宜过长(建议3-7天)

3. **性能考虑**:
   - 激活的选股器越多,计算时间越长
   - AND模式最快,SEQUENTIAL_CONFIRMATION最慢

4. **回测验证**:
   - 建议先在小范围日期测试新配置
   - 对比不同组合模式的效果
   - 关注信号数量、胜率、收益率等指标

## 常见问题

**Q: 如何知道我的配置是否生效?**
A: 查看回测日志,会显示"Selector combination mode: XXX"

**Q: 顺序确认模式下,如果触发和确认选股器重叠怎么办?**
A: 系统会正常处理,但建议将它们分开以体现两阶段逻辑

**Q: 可以动态修改配置吗?**
A: 可以,每次运行回测前都可以修改配置,也可以保存为模板

**Q: 时间窗口的起点是触发日还是触发后一天?**
A: 从触发日当天开始计算,所以5天窗口包含触发日+后续4天

## 更新日志

- 2026-02-13: 添加前端UI支持,完成前后端集成
- 2026-01-XX: 后端实现顺序确认逻辑
- 2025-12-XX: 后端实现基础组合逻辑(OR/AND/TIME_WINDOW)
