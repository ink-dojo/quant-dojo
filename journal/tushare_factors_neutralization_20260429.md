# Tushare 四因子第二阶段：size + 行业中性化 + cost-aware 多空回测

_2026-04-29 — Issue #44, 上承 a750694 (raw 初筛)_

---

## 背景

a750694 (2026-04-26) 写了 4 个 tushare 因子的 raw IC 初筛，结论是 4 个都看上去
有信号 (HAC 不算的话)。但 raw IC 容易被 size / 行业 cluster 拉抬：A 股小盘
beta、热门行业季节性都会让一个其实只是 "买小票 + 押对赛道" 的因子在 raw IC
表里看起来很强。中性化 + cost 是把"可能的 alpha"和"已知的市场结构"分开的
最便宜检验。

四因子第二阶段做了三件事:

1. **fix**: 修了 a750694 commit 留下的 3 个 raw bug (见 §修复)，否则
   `quality_stocks=0`、`nb_ratio_chg` reindex 重复 label、`roe_stability`
   reindex 索引乱序，全部跑不完。
2. **neutralize**: 用 `utils.factor_analysis.neutralize_factor` 做 size
   (log circ_mv) + 申万一级 (38 大类，从 396 三级码取前 2 位) 的 OLS 残差化。
3. **cost-aware**: 月频 (HORIZON=21d) 抽样多空，按周转率扣双边 0.3% 的交易
   成本，看净年化和净 sharpe 是否还撑得住。

数据全部走 SSD parquet (`data/raw/tushare/`)，因为 jiaoch 高权限 token 在
2026-04-22 已被官方吊销 (`.env` 第 2 行有注释)，本地剩下的 56-char 官方
token 只能拿 `daily / adj_factor / moneyflow_hsgt`，daily_basic / moneyflow /
fina_indicator 全部权限拒绝。daily_basic 的 `close` 列被复用做价格面板，
绕开被吊销的 `pro.daily()`。

---

## 修复 (a750694 留下的 3 个 raw bug)

| 文件 | 行 | 问题 | 修法 |
|---|---|---|---|
| `factor_research.py` | run_analysis() | `fi_stocks` glob 用 `fina_*` 而 SSD 上实际是 `fina_indicator_*`, `quality_stocks` 永远是空集 | glob 改 `fina_indicator_*.parquet`, replace 改 `fina_indicator_` |
| `factor_research.py` | build_roe_stability | `fi_path = fina_{sym}.parquet` 找不到 | 改 `fina_indicator_{sym}.parquet` |
| `factor_research.py` | build_nb_ratio_chg | 北向 `ratio` 同日多档/多通道 → set_index("date") + drop_duplicates 不彻底, reindex 报 duplicate label | 改 `loc[~index.duplicated(keep="last")]` |
| `factor_research.py` | build_roe_stability | `ann_date` 设 index 但没 sort, ffill reindex 报 "index must be monotonic" | dedup 后加 `.sort_index()` |

a750694 commit message 报的 raw IC (roe_stability 0.036 / cfoni_precise 0.025
等) 与本 run 略有差异 — 不能 1:1 比对，因为原 commit 至少 quality_stocks 那
条路径根本没跑通过。这次的数字是真正跑出来的版本。

---

## 结果

### IC 对比 (Spearman, HAC t with NW lag = max(20, Andrews))

| factor | ic_raw | icir_raw | t_hac_raw | ic_neutral | icir_neutral | t_hac_neutral | ic_decay | n |
|---|---|---|---|---|---|---|---|---|
| inst_flow_20d | 0.0294 | 0.283 | 2.95 | 0.0315 | 0.528 | **5.66** | +0.0020 | 1425 |
| nb_ratio_chg  | 0.0077 | 0.114 | 2.91 | 0.0051 | 0.095 | 2.43 | -0.0026 | 1414 |
| roe_stability | 0.0337 | 0.613 | **6.20** | 0.0299 | 0.442 | **4.65** | -0.0038 | 1434 |
| cfoni_precise | 0.0115 | 0.139 | 1.41 | 0.0091 | 0.327 | **3.46** | -0.0024 | 1434 |

观察:

- **inst_flow_20d**: 中性化后 HAC t 从 2.95 → 5.66, ICIR 0.28 → 0.53 — 提升
  显著。说明 raw 信号里 size/行业 共线性把 IC 噪声放大了，残差因子反而更
  稳。这种"中性化让 t 更大"是好事，不是缩水。
- **roe_stability**: 中性化后 t 从 6.20 → 4.65 略弱，但仍在 4 个里最稳。质
  量类因子和市值天然有正相关 (大盘股 ROE 更稳)，剥离后仍 t≈4.6 是真信号。
- **cfoni_precise**: 中性化后 t 从 1.41 → 3.46, raw 时根本不显著, 中性化
  后才浮出来 — 说明 raw 信号被 size 因子吸走了。
- **nb_ratio_chg**: t 2.91 → 2.43。在所有四个里最弱。raw IC 也只 0.0077。

### Cost-aware 多空回测 (月频, 双边 0.3%, 中性化后因子)

| factor | direction | n | avg_turnover | gross_ann | cost_drag | **net_ann** | sharpe_gross | **sharpe_net** |
|---|---|---|---|---|---|---|---|---|
| inst_flow_20d | Qn-Q1 | 68 | 0.60 | 10.26% | 2.14% | **8.11%** | 1.30 | **1.03** |
| nb_ratio_chg  | Q1-Qn | 68 | 0.64 | -5.31% | 2.31% | -7.62% | -0.76 | -1.09 |
| roe_stability | Qn-Q1 | 69 | 0.09 | 9.88% | 0.31% | **9.57%** | 1.49 | **1.44** |
| cfoni_precise | Qn-Q1 | 69 | 0.15 | 2.70% | 0.52% | 2.17% | 0.84 | 0.67 |

要点:

- **roe_stability**: 季频信号 → 月频换手只有 8.5%, cost drag 31bp/yr。net
  9.57%, sharpe 1.44。是这一轮里最干净的候选。
- **inst_flow_20d**: 高频信号 → 换手 60%, cost drag 2.14%/yr。但 gross
  10.3% 顶得住, net 8.1% sharpe 1.03。能过 WORKFLOW.md sharpe ≥ 0.8。
- **cfoni_precise**: t-stat 显著但 sharpe_net 0.67 < 0.8。临界，单独不达标。
- **nb_ratio_chg**: net 直接负 (-7.6%)。Q1 长 / Qn 短反向也试过 (raw IC 正
  IC 时反向就更负)，方向问题不是真正阻力，因子本身没什么 alpha。

### 候选库结论 (本轮)

- **进候选库 (HAC |t| > 4 且 net sharpe > 0.8)**:
  - `roe_stability` — 推荐为下一阶段 stacking 的基底, 周转极低
  - `inst_flow_20d` — 高频, 与 roe_stability 正交可能性高 (一个看 quality
    一个看 inst flow), 值得算 corr
- **临界 (单独不进, 待 stacking 看)**:
  - `cfoni_precise` — t 显著但 cost 后 sharpe 不达标。可作为 stacking 的
    候选, 不单独 pre-reg
- **拒绝**:
  - `nb_ratio_chg` — net 负, 无 alpha 证据

### 与 spec v4 的关系

spec v4 (RIAD + DSR#30 BB-only 50/50) 已被 jialong 在 2026-04-28 否决, 不
go-live。本轮的 roe_stability + inst_flow_20d 不是 spec v4 的延伸, 是另起
一组候选, 任何后续推进必须重跑完整 4/4 严格门 (DSR ≥ 0.95)：

- pre-registration (新 spec)
- walk-forward + 3-fold blocked CV
- stacking corr 检验 (与已有候选的 IC 序列相关性)
- DSR + bootstrap 双门
- capacity / stress / live-vs-backtest

不重复 spec v4 的"一次性例外"路径。

---

## 下一步

按收窄后的"少数候选复盘"主线 (740ea7e):

1. **算两腿 corr**: `corr(IC_roe_stability, IC_inst_flow_20d)`, 看是否能
   stacking。如果 corr < 0.3 (理想) 或 < 0.5 (可接受), 写一个 stacking
   spec 草稿, 再走完整 pre-reg + DSR 流程。
2. **不 sweep 参数**: 不为了把 cfoni_precise 拉过 sharpe 0.8 而调 horizon
   或 quintile 数。WORKFLOW.md 红线: "不基于 OOS 结果回头调参"。
3. **不重新激活 spec v4 路径**: 即使新组合过门, 也按 740ea7e 的收窄原则
   单独审 capacity / stress, 不复用 spec v4 的上线结论。

---

## 数据/代码出处

- 因子构造: `research/factors/tushare_factors/factor_research.py` (a750694 +
  本轮 3 处 fix)
- 中性化 + cost: `research/factors/tushare_factors/neutralize_and_cost.py`
- 数值结果: `research/factors/tushare_factors/neutralized_ic.csv`,
  `research/factors/tushare_factors/cost_aware_backtest.csv`
  (在 .gitignore, 不入 git, 重跑可复现)
- 中性化用工具: `utils.factor_analysis.neutralize_factor` (size + L1 OLS),
  `utils.factor_analysis.compute_ic_series`, `utils.factor_analysis.ic_summary`
- 行业映射: `data/raw/fundamentals/industry_sw.parquet` (申万 3 级 → 取前 2
  位 = 一级, 38 类)
- 数据范围: 2020-01-01 到 SSD 上 daily_basic 最新日 (2026-04-17), n_dates ≈ 1455

— 记录: jialong
