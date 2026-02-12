## 市场筛选与策略优化对比

| 范畴 | 优化前 | 优化后 |
|------|--------|--------|
| Outcome 解析 | 默认 `outcomes[0]==YES`、`outcomes[1]==NO`，一旦 Polymarket 返回顺序变化就会错价。 | 新增 `Market.get_yes_outcome()` / `get_no_outcome()` 和 token→market 索引，风控/执行/统计都按统一接口取价。 |
| WebSocket 更新 | 每条价格变动都遍历所有市场/Outcome 寻找 token，复杂度 O(n)。 | 维护 `token_id → (market, outcome)` 映射，更新为 O(1)，并只订阅筛选后的市场。 |
| Swing 数据 | 每分析一个市场都请求 BTC 价和新闻，极易触发 API 限流。 | 引入 `SwingMarketContext`，每轮扫描预取一次 BTC + 新闻，全局复用。 |
| 市场筛选 | 权重/阈值固定，不考虑历史收益或通知冷却；同一市场短期可能重复。 | Screener 支持动态权重、冷却惩罚，可读取 `OpportunityTracker` 反馈自动微调评分。 |
| 信号规范化 | Debate/LLM 返回的 action/置信度可能是字符串或 0–100 数值，导致阈值失真。 | 统一转为枚举 & 0–1 置信度，`SignalGenerator` 再做阈值判断，新增 pytest 覆盖。 |
| 执行安全 | 第二腿下单失败时直接退出，已成交的一腿敞口悬空。 | `OrderManager` 遇到单腿成功会尝试 SELL 对冲，并记录日志，模拟交易也依赖标准化 outcome。 |
| 持久化 | `OpportunityTracker` 每次事件都写文件，实时模式 I/O 压力大。 | 保存频率节流（默认 10 秒），仍保证定期固化数据供动态调参。 |
| 文档同步 | README 仅描述静态筛选流程。 | README 增加“动态权重 + 冷却 + 上下文缓存”说明，并在 docs 目录提供本对比表。 |

### 关键信息
1. **统一的市场元数据** 杜绝了 Polymarket 端顺序变化引起的隐患，也让 WebSocket 更新更高效。
2. **共享上下文与动态筛选** 降低外部 API 压力，同时让筛选结果反映历史收益和推送冷却。
3. **信号/执行闭环** 确保从多模型辩论到下单的每一步都有“规范化 + 兜底”机制，可为真实 Swing 交易打底。

### 日常运行指令
```bash
# 安装依赖
pip3 install -r requirements.txt

# 运行测试
python3 -m pytest
```
