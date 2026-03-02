# 超额收益展示功能

## 功能概述

此功能为回测结果页面添加了详细的超额收益分析模块，能够完整展示策略相对于基准指数的表现，**支持正负值展示**。

## 实现的功能

### 1. 超额收益分析模块 (`ExcessReturnBreakdown`)

**位置**: `components/results/excess-return-breakdown.tsx`

**功能**:
- ✅ 展示策略收益 vs 基准收益对比
- ✅ 计算并显示超额收益（正值或负值）
- ✅ Jensen's Alpha (α) - 风险调整后的超额收益
- ✅ Beta (β) - 策略波动性相对基准的倍数
- ✅ 跟踪误差 - 策略与基准的偏离程度
- ✅ 信息比率 - 单位风险的超额收益
- ✅ 可视化对比条形图
- ✅ 详细的指标说明

**支持的基准指数**:
- 上证指数 (000001_SH)
- 沪深300 (000300_SH)
- 中证500 (000905_SH)
- 创业板指 (399006_SZ)
- 科创50 (000688_SH)

**负值处理**:
- 当超额收益为负时，显示为红色并标注"跑输基准"
- 当Alpha为负时，显示为红色
- 所有指标都正确处理负值显示

### 2. 收益分解模块优化 (`ReturnBreakdown`)

**位置**: `components/results/return-breakdown.tsx`

**改进**:
- ✅ 已实现收益支持负值展示（亏损时显示红色）
- ✅ 未实现收益支持负值展示（浮亏时显示红色）
- ✅ 动态图标颜色（盈利=绿色✓，亏损=红色⚠）
- ✅ 亏损时显示警告提示
- ✅ 改进的收益构成进度条（按绝对值计算）
- ✅ 添加颜色图例说明
- ✅ 浮亏时警告框变为红色背景

### 3. 后端API增强

**新增API**: `GET /api/backtests/{backtest_id}/analysis?benchmark={benchmark_name}`

**功能**:
- 根据指定的基准重新计算分析数据
- 支持动态切换基准进行对比
- 返回完整的benchmark metrics

**修改**:
- `backend/app.py` - 添加分析API端点
- `backtest/performance.py` - 已支持基准对比（`_calculate_benchmark_metrics`）

### 4. 前端集成

**文件修改**:
- `lib/api.ts` - 添加 `getBacktestAnalysis` API函数
- `lib/hooks.ts` - 添加 `useBacktestAnalysis` hook
- `app/results/page.tsx` - 集成超额收益模块

**工作流程**:
1. 用户选择回测任务
2. 用户选择基准指数（上证指数/沪深300/中证500等）
3. 前端调用 `/api/backtests/{id}/analysis?benchmark={name}`
4. 后端使用 `PerformanceAnalyzer` 重新计算包含基准对比的分析
5. 前端展示详细的超额收益分析

## 使用说明

### 启动后端服务

```bash
cd /Users/pengchuhan/Desktop/StockTrade_backtest
python backend/app.py
```

### 启动前端开发服务器

```bash
npm run dev
```

### 查看超额收益

1. 访问 `http://localhost:3000/results`
2. 从下拉菜单选择一个已完成的回测任务
3. 选择基准指数（默认为"上证指数"）
4. 页面会自动加载并显示：
   - KPI卡片（含超额收益率）
   - 收益分解（已实现/未实现，支持负值）
   - **超额收益分析**（新增模块）
   - 出场原因统计
   - 其他图表和分析

## 数据要求

### 基准数据文件

基准数据需存放在 `index_data/` 目录：

```
index_data/
├── 000001_SH.csv  # 上证指数
├── 000300_SH.csv  # 沪深300
├── 000905_SH.csv  # 中证500
├── 399006_SZ.csv  # 创业板指
└── 000688_SH.csv  # 科创50
```

**数据格式** (CSV):
```csv
date,open,high,low,close,volume
2024-01-02,3108.67,3126.87,3101.26,3124.40,298765000
2024-01-03,3125.32,3142.15,3118.90,3140.77,312456000
...
```

### 下载基准数据

使用项目的 `fetch_benchmark.py` 脚本：

```bash
python fetch_benchmark.py
```

## 示例输出

### 超额收益为正的情况

```
超额收益率: +8.45%
策略收益: +25.30%
基准收益: +16.85%
Alpha: +6.23%
Beta: 1.15
信息比率: 1.82
```

### 超额收益为负的情况

```
超额收益率: -3.25%  (红色显示)
策略收益: +12.60%
基准收益: +15.85%
Alpha: -2.10%  (红色显示)
Beta: 0.95
信息比率: -0.45  (红色显示)
```

### 收益分解 - 负值示例

```
已实现收益: -15,230  (红色，带⚠警告)
  -1.52% 来自已平仓交易
  ⚠ 平仓交易产生净亏损

未实现收益: -8,450  (红色，带⚠警告)
  -0.85% 来自未平仓持仓
  ⚠ 未平仓持仓产生浮亏
```

## 技术细节

### 超额收益计算

```python
# 在 backtest/performance.py 的 _calculate_benchmark_metrics 中
excess_return = portfolio_total_return - benchmark_total_return
```

### Alpha计算 (Jensen's Alpha)

```python
alpha = annualized_portfolio - (
    risk_free_rate + beta * (annualized_benchmark - risk_free_rate)
)
```

### Beta计算

```python
beta = covariance(portfolio_returns, benchmark_returns) / variance(benchmark_returns)
```

### 信息比率

```python
information_ratio = mean_excess_return / tracking_error
```

## 文件清单

### 新增文件
- `components/results/excess-return-breakdown.tsx` - 超额收益分析组件
- `docs/EXCESS_RETURN_FEATURE.md` - 本文档

### 修改文件
- `components/results/return-breakdown.tsx` - 优化负值展示
- `backend/app.py` - 添加分析API
- `lib/api.ts` - 添加API函数
- `lib/hooks.ts` - 添加hook
- `app/results/page.tsx` - 集成新组件

## 注意事项

1. **基准数据必须存在**: 如果选择的基准没有对应的CSV文件，会显示"暂无基准数据"提示
2. **日期范围对齐**: 基准数据的日期范围应覆盖回测的日期范围
3. **动态加载**: 切换基准时会重新计算分析数据，有短暂的loading状态
4. **负值处理**: 所有收益指标都正确支持负值，并用红色标识
5. **性能优化**: 使用SWR缓存，相同的backtest_id+benchmark组合不会重复请求

## 未来优化建议

1. 添加基准数据的健康检查API
2. 支持自定义基准上传
3. 添加超额收益的时间序列图表
4. 添加滚动窗口的超额收益分析
5. 支持多基准同时对比

## 更新日期

2026-02-13
