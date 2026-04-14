# quant-dojo Pipeline Review & 优化建议
> 2026-04-14 | 基于完整代码阅读的修订版

---

## 一、系统现状的准确描述

### 1.1 数据与验证框架（更正之前的错误说法）

正式评审脚本（`scripts/v7_industry_neutral_eval.py`）实际使用的数据范围：

```
WARMUP_START = 2013-01-01   （因子预热，不计入回测结果）
IS_START     = 2015-01-01
IS_END       = 2024-12-31   → 样本内 10 年
OOS_START    = 2025-01-01
OOS_END      = 2025-12-31   → 样本外 1 年
```

CLI `backtest run` 在不传 `--start` 时默认 `today - 3年`，这是**快速调试用的默认值**，不代表正式评审的数据范围。两者不同，之前混淆了。

### 1.2 v7 评审结论的准确解读

| 维度 | 值 | 状态 |
|------|-----|------|
| IS 年化（2015-2024） | +17.70% | ✅ >15% |
| IS 夏普 | 0.9256 | ✅ >0.8 |
| IS 最大回撤 | -26.23% | ✅ <30% |
| WF 夏普均值（17窗口） | 0.4808 | ✅ 显著正 |
| WF 夏普中位数 | 0.0000 | ⚠️ 踩线 |
| OOS 年化（2025） | +10.28% | ✅ 绝对正收益 |
| OOS 超额（vs HS300） | -7.04% | ⚠️ 相对跑输 |

WF 中位数 = 0 的含义：17 个滚动窗口里约一半的 6 个月 OOS 区间 Sharpe 接近零，说明**策略在特定市场状态（趋势市、流动性宽松期）下均值回归类因子会系统性失效**，不是数据太短导致的。

---

## 二、过拟合风险的准确定位

### 2.1 哪些地方风险真实存在

**风险 A：WF 分布不对称**

```
WF 均值 = 0.48（好）
WF 中位数 = 0.00（踩线）
→ 少数几个特别好的窗口拉高了均值，但中位数揭示约一半时间没有 alpha
```

这不是数据问题，是策略在某些市场状态下的结构性弱点。

**风险 B：OOS 超额为负**

2025 年 HS300 强势（AI/科技板块驱动），行业中性化策略在板块大轮动期间牺牲了弹性。绝对收益正但相对跑输，可接受但需理解根因。

**风险 C：CLI 快速回测默认只用 3 年**

日常用 `python -m pipeline.cli backtest run v7` 不传参数时，只跑近 3 年。如果用这个结果做调参决策，等于在一个很窄的窗口上优化，高度容易过拟合。

**风险 D：换手率 85% 过高，隐性成本被低估**

```
月换手 85% × 双边 0.3% × 12月 ≈ 年化 6.1% 成本
策略年化 17.7% 里约 6% 被交易成本吃掉
真实 alpha ≈ 11.6%，不是 17.7%
```

### 2.2 哪些地方设计是对的，不是问题

- IS/OOS 切割是显式且正确的
- WF 17 轮覆盖 2013-2024，方法论没问题
- 前视偏差已处理（`shift(-1)`）
- 行业中性化用截面回归残差，标准做法
- Admission Gate 真实拒绝过策略（v6 系列），门禁有效

---

## 三、过拟合防控建议（修订版）

### 3.1 立即可做：用全量历史数据重跑 WF

外盘数据（`/Volumes/Crucial X10/20260320/`）从 1999/2013 开始，已通过 `config.yaml` 接入。

可以把 WF 的起点从 2013 推回到 2005-2008，新增覆盖：
- **2008 金融危机**（目前 WF 完全缺失这个压力期）
- **2010-2013 熊市**

```python
# scripts/v7_industry_neutral_eval.py 修改一行
WARMUP_START = "2007-01-01"   # 原来是 2013-01-01
# IS_START 保持 2015-01-01 不变（让 2007-2014 作为更长预热期）
```

预期效果：WF 窗口从 17 增加到约 30，中位数是否仍为 0 会更有统计意义。

### 3.2 CLI 默认日期改为 IS 起点

防止日常调参在错误窗口上过拟合：

```python
# pipeline/cli.py，改默认起点
# 原来：start = today - 3年
start = "2015-01-01"   # 与正式评审保持一致
```

或者加一个显式的 `--preset is`/`--preset quick` 开关，让用户明确选择。

### 3.3 换手率约束

在 `pipeline/daily_signal.py` 的信号生成环节加粘性约束：

```python
def apply_turnover_constraint(new_picks, current_positions, max_turnover=0.50):
    """每月最多换掉 50% 的持仓，保留当前持仓中仍在新信号前 N 的股票"""
    keep = set(current_positions) & set(new_picks)
    add  = set(new_picks) - set(current_positions)
    max_new = int(len(new_picks) * max_turnover)
    final = keep | set(list(add)[:max_new])
    # 不足 n_stocks 时补充排名靠前的新股
    ...
    return final
```

换手率从 85% 降到 50% 左右，年化成本节省约 2-3%。需回测验证是否影响 Sharpe。

### 3.4 参数敏感性分析（防止单点过拟合）

当前 v7 的参数：
- `n_stocks = 30`
- `IC 滚动窗口 = 60日`
- 5 个固定因子组合

建议做一次系统性敏感性检验（在 IS 期内）：

```python
for n in [20, 25, 30, 35, 40]:
    for ic_window in [40, 60, 80]:
        result = run_IS_backtest(n_stocks=n, ic_window=ic_window)
        print(n, ic_window, result['sharpe'])
```

**如果只有 n=30, window=60 这一个参数点通过 Sharpe > 0.8，那当前策略是过拟合的。**
如果大多数参数组合都能过，说明策略是真实稳健的。

### 3.5 市场状态分层验证

WF 中位数踩线说明在某些市场状态下策略失效。把 WF 17 个窗口按市场状态分类：

```python
# 根据 HS300 走势分类每个 WF 窗口
for window in wf_results:
    hs300_return = get_hs300_return(window['test_start'], window['test_end'])
    state = "bull" if hs300_return > 0.10 else "bear" if hs300_return < -0.10 else "flat"
    window['market_state'] = state

# 按状态统计夏普
bull_sharpe  = [w['sharpe'] for w in wf_results if w['market_state'] == 'bull']
flat_sharpe  = [w['sharpe'] for w in wf_results if w['market_state'] == 'flat']
bear_sharpe  = [w['sharpe'] for w in wf_results if w['market_state'] == 'bear']
```

预期结论：均值回归类策略在熊市/震荡市更好，在单边牛市失效。这是理论预期，如果数据验证了，就是"可解释的局限"，不是过拟合。

### 3.6 多重检验校正（如果未来大量挖因子）

当前 v7 是 5 个因子，不需要。但如果 Phase 7 AI 开始批量提议实验，需要：

```python
# 对每批实验的 p-value 做 BH 校正
from statsmodels.stats.multitest import multipletests

pvalues = [exp['ic_tstat_pvalue'] for exp in batch_experiments]
reject, pvals_corrected, _, _ = multipletests(pvalues, method='fdr_bh')
# 只有 reject=True 的实验才值得继续
```

防止 AI 在 100 个实验里找到 5 个"显著"结果，但这 5 个只是噪音中的幸运。

---

## 四、宏观 Pipeline 的结构性建议

### 4.1 Admission Gate 逻辑修正

当前 Gate 以 IS 为主判断，OOS/WF 只做参考。建议调整权重：

```
当前逻辑：
    IS 全过 → ALLOW
    IS 全过 + WF 踩线 → CONDITIONAL ALLOW

建议逻辑：
    WF 中位数 > 0.3 AND IS Sharpe > 0.8 → ALLOW
    WF 中位数 > 0.0 AND IS Sharpe > 0.8 → CONDITIONAL ALLOW（加强监控）
    WF 中位数 ≤ 0.0 → DENY（不管 IS 多好看）
```

v7 在新逻辑下仍是 CONDITIONAL ALLOW（中位数 = 0，踩零但不负），不影响当前决策，但未来能阻止 IS 好看、WF 很差的策略进入模拟盘。

### 4.2 主线唯一化

当前有两套"回测入口"容易造成混乱：
- `scripts/v7_industry_neutral_eval.py`（正式评审，2015-2024）
- `pipeline/cli.py backtest run`（日常调试，默认 3 年）

建议：给 CLI 加一个 `--mode formal` 参数，触发时自动使用 IS_START/IS_END/OOS 切割，和正式评审脚本保持一致，消除两套配置并存的混乱。

### 4.3 Tushare 接入后能做什么

Tushare Pro 相比 AkShare 能补充：

| 数据类型 | 价值 | 用途 |
|---------|------|------|
| 日频北向资金 | 高 | 外资流向因子，A股有效 |
| 分钟线（过去2年） | 中 | 日内特征，暂不需要 |
| 分析师一致预期 | 高 | earnings_surprise 因子 |
| 股权质押比例 | 中 | 风险因子 |
| 龙虎榜数据 | 低 | 散户情绪，噪音多 |
| 融资融券余额 | 中 | 杠杆/情绪因子 |
| 财报原始数据 | 高 | 比 AkShare 更完整的基本面 |

**最值得先接的两个**：北向资金日频（直接可以作为新因子测试）+ 分析师一致预期（earnings_momentum 因子的数据来源）。

### 4.4 外盘数据已接入，下一步

`config.yaml` 已指向 `/Volumes/Crucial X10/20260320/`，数据从 1999/2013 年开始可用。

立即可执行：

```bash
# 用完整数据重跑 v7 WF，把 WARMUP_START 推回 2007
cd /Users/karan/work/quant-dojo
python scripts/v7_industry_neutral_eval.py
# 观察 WF 窗口数量是否增加，中位数 Sharpe 是否改变
```

---

## 五、优先级排序

| 优先级 | 任务 | 原因 | 预计影响 |
|--------|------|------|---------|
| P0 | WF 起点推回 2007 重跑 | 用已有数据填补 2008 危机 | 确认 WF 中位数是否真实 |
| P0 | 参数敏感性分析 | 验证策略是否在单点过拟合 | 决定 v7 是否值得继续 |
| P1 | CLI 默认日期改为 IS 起点 | 防止日常调参在错误窗口优化 | 低成本，高防护价值 |
| P1 | 换手率约束 | 年化节省 2-3% 成本 | 直接改善净收益 |
| P2 | Tushare 北向资金因子 | 新的有效 alpha 来源 | 潜在提升 IS Sharpe |
| P2 | Admission Gate 逻辑修正 | OOS/WF 权重应高于 IS | 防止未来错误决策 |
| P3 | 市场状态分层验证 | 理解 WF 中位数踩线的根因 | 研究价值，不影响当前决策 |
| P3 | 多重检验校正接入 AI 批量实验 | Phase 7 扩展时需要 | 当前 5 因子不急 |

---

## 六、新因子研究结果：ROGT（2026-04-14 更新）

本次 Session 从 0 到 1 创建并验证了 **ROGT（Retail Open Gap Trap，零售散户开盘追涨陷阱）** 因子。

### 6.1 因子逻辑

捕捉 A 股"高开低走"机构分配行为：机构借散户 FOMO 开盘追涨时高价减仓。
公式：`ROGT = -rolling_mean(gap_excess × intraday_fall × turnover_weight, 20)`

### 6.2 验证结论（6/6 通过）

| 指标 | IS（2015-2023） | OOS（2024） | 状态 |
|------|----------------|-------------|------|
| IC 均值 | +0.0257 | +0.0257 | ✅ ≥ 0.015 |
| ICIR | 0.3464 | 0.3861 | ✅ ≥ 0.20 |
| t 统计量 | 16.21 | 5.99 | ✅ ≥ 1.5 |
| IC>0 胜率 | 65.6% | 68.9% | ✅ ≥ 50% |
| 最高因子相关系数 | — | 0.207（vs turnover_rev）| ✅ < 0.70 |
| 加入 v7 后夏普 | 0.4050（vs 基准 0.3646）| — | ✅ +11.1% |

**裁定：KEEP，建议作为第 6 个因子加入 v7（升级为 v8 时需重跑完整 IS/OOS/WF）。**

### 6.3 关键发现

1. OOS ICIR（0.386）**高于** IS ICIR（0.346），无过拟合迹象
2. 因子在 2018 贸易战熊市（ICIR=0.460）和 2022 熊市（ICIR=0.409）均强劲有效
3. 仅在 2015 股灾极端流动性危机下短暂失效（ICIR=0.084），符合理论预期
4. 发现并修复了零值污染（illiquid 股票 factor=0 的系统性偏差），覆盖率 46%→19%，分层单调性恢复正常

### 6.4 相关文档

- 因子实现：`utils/alpha_factors.py` → `retail_open_trap()`
- 研究脚本：`research/factors/retail_open_trap/factor_research.py`
- 入库决议：`journal/factor_admission_rogt_20260414.md`
