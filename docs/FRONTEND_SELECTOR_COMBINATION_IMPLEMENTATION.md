# 选股器组合逻辑前端UI实现总结

## 任务概述
在前端回测启动页面添加选股器组合逻辑的UI配置选项，允许用户选择不同的组合模式（OR、AND、时间窗口、顺序确认），并与后端API对接。

## 修改文件清单

### 1. `/components/backtest/selector-config.tsx` ⭐核心文件
**修改内容**：
- 扩展 `SelectorConfigProps` 接口，添加以下 props：
  - `timeWindowDays`, `onTimeWindowDaysChange` - 时间窗口天数
  - `triggerSelectors`, `onTriggerSelectorsChange` - 触发选股器列表
  - `triggerLogic`, `onTriggerLogicChange` - 触发逻辑(OR/AND)
  - `confirmSelectors`, `onConfirmSelectorsChange` - 确认选股器列表
  - `confirmLogic`, `onConfirmLogicChange` - 确认逻辑(OR/AND)
  - `buyTiming`, `onBuyTimingChange` - 买入时机

- 添加组合模式选择按钮：
  - OR (任一满足)
  - AND (全部满足)
  - TIME_WINDOW (时间窗口)
  - SEQUENTIAL_CONFIRMATION (顺序确认)

- 添加时间窗口配置UI：
  - 仅在 TIME_WINDOW 和 SEQUENTIAL_CONFIRMATION 模式下显示
  - 输入框设置时间窗口天数(1-30)

- 添加顺序确认模式配置UI：
  - 触发选股器选择区域（可多选，带OR/AND逻辑切换）
  - 确认选股器选择区域（可多选，带OR/AND逻辑切换）
  - 买入时机选择（确认日买入 / 触发日买入）

**关键函数**：
- `toggleTriggerSelector()` - 切换触发选股器选择状态
- `toggleConfirmSelector()` - 切换确认选股器选择状态
- 使用 `activeSelectors` 过滤只显示已激活的选股器

### 2. `/components/backtest/backtest-form.tsx`
**修改内容**：
- 添加状态管理：
  ```typescript
  const [timeWindowDays, setTimeWindowDays] = useState(5);
  const [triggerSelectors, setTriggerSelectors] = useState<string[]>([]);
  const [triggerLogic, setTriggerLogic] = useState("OR");
  const [confirmSelectors, setConfirmSelectors] = useState<string[]>([]);
  const [confirmLogic, setConfirmLogic] = useState("OR");
  const [buyTiming, setBuyTiming] = useState("confirmation_day");
  ```

- 更新 `handleSubmit` 函数，构建完整的 `selector_combination` 配置：
  ```typescript
  const selectorCombination: Record<string, unknown> = {
    mode: combinationMode,
  };

  // 根据模式添加相应参数
  if (combinationMode === "TIME_WINDOW" || combinationMode === "SEQUENTIAL_CONFIRMATION") {
    selectorCombination.time_window_days = timeWindowDays;
  }

  if (combinationMode === "SEQUENTIAL_CONFIRMATION") {
    selectorCombination.trigger_selectors = triggerSelectors;
    selectorCombination.trigger_logic = triggerLogic;
    selectorCombination.confirm_selectors = confirmSelectors;
    selectorCombination.confirm_logic = confirmLogic;
    selectorCombination.buy_timing = buyTiming;
  }
  ```

- 传递所有新props到 `SelectorConfig` 组件

## 后端对接

### 数据格式
前端发送给后端的 `buy_config` 结构：

```json
{
  "buy_config": {
    "selectors": [
      {
        "class": "BBIKDJSelector",
        "alias": "少妇战法",
        "activate": true,
        "params": {...}
      }
    ],
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
}
```

### 后端处理路径
1. `POST /api/backtests` - 接收回测配置
2. `backend/app.py` 中的 `create_backtest()` 将payload传递给 `BacktestEngine`
3. `backtest/engine.py` 中的 `load_buy_selectors()` 解析 `selector_combination`
4. `get_buy_signals()` 根据配置应用组合逻辑

## UI/UX设计要点

### 1. 视觉层次
- 组合模式选择在顶部（右上角），使用按钮组
- 时间窗口配置用蓝色边框高亮 (`border-primary/30 bg-primary/5`)
- 顺序确认配置用紫色边框高亮 (`border-accent/30 bg-accent/5`)
- 选股器列表在配置区域下方

### 2. 交互逻辑
- 只有激活的选股器才能被选为触发/确认选股器
- 触发/确认选股器使用可点击的chip按钮显示
- 选中状态使用 `bg-accent text-accent-foreground shadow-sm`
- 未选中状态使用 `bg-secondary text-muted-foreground`

### 3. 条件显示
- 时间窗口设置：仅在 TIME_WINDOW 和 SEQUENTIAL_CONFIRMATION 模式下显示
- 顺序确认设置：仅在 SEQUENTIAL_CONFIRMATION 模式下显示

### 4. 辅助信息
- 每个配置区域都有简短说明文本
- 使用 Badge 标识模式类型
- 使用分隔线分隔触发器和确认器配置

## 测试建议

### 1. 功能测试
- [ ] 切换组合模式时，UI正确显示/隐藏对应配置
- [ ] 时间窗口天数可以正确输入和更新
- [ ] 触发/确认选股器可以正确选择和取消选择
- [ ] 触发/确认逻辑可以在OR/AND之间切换
- [ ] 买入时机可以正确选择
- [ ] 点击"启动回测"时，payload正确构建

### 2. UI测试
- [ ] 各组合模式的UI显示符合设计
- [ ] 选股器chip按钮选中/未选中状态清晰
- [ ] 响应式布局在不同屏幕尺寸下正常工作
- [ ] 颜色对比度符合可访问性标准

### 3. 集成测试
```bash
# 1. 启动后端
cd backend
uvicorn app:app --reload

# 2. 启动前端(如果使用Next.js)
cd ..
npm run dev

# 3. 测试流程
# - 访问 http://localhost:3000
# - 切换到"选股策略"标签
# - 选择不同组合模式
# - 配置参数并启动回测
# - 查看后端日志确认配置正确传递
```

### 4. 数据验证测试
使用以下脚本验证payload格式：
```bash
python scripts/test_selector_combination_ui.py
```

## 示例使用场景

### 场景1: OR模式（默认）
- 用户场景：希望捕捉更多机会
- 配置：激活3个选股器，选择OR模式
- 预期：任意一个选股器触发即生成买入信号

### 场景2: AND模式
- 用户场景：只做高确定性机会
- 配置：激活3个选股器，选择AND模式
- 预期：3个选股器同时触发才生成买入信号

### 场景3: 时间窗口模式
- 用户场景：验证趋势持续性
- 配置：激活2个选股器，选择TIME_WINDOW，设置5天窗口
- 预期：5天内2个选股器先后触发即可

### 场景4: 顺序确认模式
- 用户场景：先识别底部，再等待放量突破
- 配置：
  - 触发选股器：少妇战法 + SuperB1战法 (OR逻辑)
  - 确认选股器：上穿60放量战法 (OR逻辑)
  - 时间窗口：5天
  - 买入时机：确认日买入
- 预期：先有底部信号，5天内出现放量突破才买入

## 相关文档

- **用户指南**: `/docs/SELECTOR_COMBINATION_GUIDE.md` - 详细的配置指南和使用说明
- **测试脚本**: `/scripts/test_selector_combination_ui.py` - 包含各种模式的测试payload
- **后端文档**: 参考 `CLAUDE.md` 中的 Selector Combination 部分

## 后续优化建议

1. **模板保存/加载**：支持保存和加载组合配置模板
2. **预设方案**：提供几个预设的组合策略方案
3. **可视化说明**：添加流程图展示不同模式的工作原理
4. **验证提示**：当配置不合理时（如触发和确认选股器相同）给出警告
5. **历史对比**：对比不同组合模式的回测结果

## 版本信息
- 实现日期：2026-02-13
- 对应后端版本：backtest/engine.py (包含完整组合逻辑)
- 前端框架：Next.js + React + TypeScript
- UI组件库：shadcn/ui
