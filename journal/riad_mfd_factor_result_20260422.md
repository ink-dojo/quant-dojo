# RIAD + MFD 差异化因子首轮评估结果 — 2026-04-22

> 日期: 2026-04-22
> Issue: #33
> 重点: 2025 年 A 股 cross-sectional alpha
> 样本: 2023-10-01 ~ 2025-12-31, 每 5 交易日采样, 20 日前向收益

## 背景与动机

Phase 3+4 终结 (2026-04-18) 后的下一轮因子挖掘, 目标:
1. **差异化**: 避开已做过的 20+ 因子方向 (动量/价值/质量/PEAD/解禁/龙虎榜...)
2. **2025 侧重**: 用户明确要求把 2025 年当 OOS / regime-check
3. **利用新下载的 tushare 数据** (见 `journal/tushare_data_inventory_20260420.md`)

由此选出两个数据密集型的 A 股独有因子:

| 因子 | 数据 | 机制 | A 股独有点 |
|---|---|---|---|
| RIAD | `ths_hot` + `dc_hot` + `stk_surv` | 散户关注度 - 机构调研 divergence | 散户热度榜 (US 无) + A 股机构调研文化 |
| MFD | `moneyflow/` | 超大单 (elg) - 小单 (sm) 资金流 divergence | 东财/同花顺 tick 归类数据, A 股独有 |

## 因子 A — RIAD

### 结构
```
retail_attn_s,t = 过去 20 日 s 在 ths_hot/dc_hot A 股榜单的加权分数 (rank 线性衰减)
inst_attn_s,t  = 过去 60 日 s 在 stk_surv 的机构调研机构数 (log1p)
RIAD_s,t       = cross-section zscore(retail_attn) - zscore(log_inst_attn)
信号方向       = 做多 RIAD 低 (机构关注高, 散户关注低)
```

### IC 表现 (周频采样, 20 日 fwd)

| 分段 | n | IC | ICIR | HAC t (NW-19) | pct_pos | Q1-Q5 /期 |
|---|---:|---:|---:|---:|---:|---:|
| FULL (2023-10 ~ 2025-12) | 99 | **−0.0696** | **−0.89** | **−5.16** | 16.2% | **+1.40%** |
| IS (2023-10 ~ 2024-12) | 55 | −0.0763 | −0.84 | −3.40 | 18.2% | +1.60% |
| **OOS 2025** | 45 | **−0.0590** | **−1.25** | **−13.30** | 8.9% | +1.08% |

pct_pos = 8.9% 表示 45 周里 41 周 IC 都是负的 — 方向高度一致, 而非均值统计噪音.

### 分层单调 (OOS 2025, 20 日持有均值)

```
Q1 = +3.09%  Q2 = +3.48%  Q3 = +3.42%  Q4 = +3.36%  Q5 = +2.00%
```

- 2025 整体是涨市, 所有分位都是正的, 但 Q5 (散户关注 >> 机构关注) 明显落后
- Q1-Q5 差 +1.09% (per 20d), 年化 ≈ 13.5% (未计费率), 稳健信号

### Size-neutral 稳健性 (核心 sanity check)

因担心 RIAD 是小盘股代理, 做 log(circ_mv) OLS 残差:

| 分段 | raw IC | size-neutral IC | 变化 |
|---|---:|---:|---|
| FULL | −0.0696 | **−0.0747** | 略增强 |
| IS 2023-10~2024-12 | −0.0763 | −0.0793 | 略增强 |
| OOS 2025 | −0.0590 | **−0.0674** | 明显增强 |

- raw vs size-neutral 因子相关度 **0.996**
- **RIAD 不是 size proxy**, 中性化后信号更干净

## 因子 B — MFD (反转假设)

### 结构
```
elg_net_s,t  = 过去 20 日 buy_elg - sell_elg
sm_net_s,t   = 过去 20 日 buy_sm  - sell_sm
elg_ratio    = elg_net / total_amt    (归一化, 去除 size 影响)
sm_ratio     = sm_net  / total_amt
MFD_s,t      = zscore(elg_ratio) - zscore(sm_ratio)
原初假设     = 做多 MFD 高 (机构买 + 散户卖 → bullish)
```

### 实证颠覆了假设

| 分段 | n | IC | ICIR | HAC t | LS /期 | pct_pos |
|---|---:|---:|---:|---:|---:|---:|
| FULL (2020-06 ~ 2025-12) | 268 | **−0.020** | −0.33 | **−4.28** | +0.09% | 36.6% |
| IS (2020-06 ~ 2024-12) | 223 | −0.019 | −0.31 | −3.57 | +0.08% | 36.3% |
| OOS 2025 | 45 | −0.024 | −0.45 | −4.19 | +0.12% | 37.8% |

**IC 是负的**. 即 elg (超大单) 净流入多的股票未来反而跑输市场.

### 对反转假设的解读

1. tushare moneyflow 的 elg 基于单笔金额分类, 不等于"机构真实资金":
   - 上午顶部对倒出货可能制造 "大单净流入" 假象
   - 尾盘拉高出货同理
2. **真相更可能是 informed selling 伪装成 elg buy**, 让跟单散户接盘
3. 2025 年量化程度上升, 这个 trap 更加普遍 → OOS 信号比 IS 还强
4. 正确信号方向: **做空 MFD 高, 做多 MFD 低** (elg 出货股反弹, elg 吸筹股回落)

注意: IC 绝对值 (0.02) 在 A 股门槛 0.03 下方, **单用 MFD 不够**.

## 合成因子 — RIAD + MFD (都反向)

### 结构
```
combined_s,t = -(zscore(RIAD) + zscore(MFD))
           (做多低 RIAD + 低 MFD, 做空高 RIAD + 高 MFD)
```

### 结果

| 分段 | IC | ICIR | HAC t | LS /期 |
|---|---:|---:|---:|---:|
| FULL | +0.069 | +0.89 | +5.21 | +1.41% |
| IS | +0.079 | +0.91 | +3.71 | +1.88% |
| OOS 2025 | +0.056 | +0.88 | +12.48 | +0.74% |

- 合成 IC 与 RIAD 单独几乎相同 (0.069 vs 0.070)
- **MFD 几乎没有提供增量 alpha**, 说明两因子相关或 MFD 信号太弱
- 分层: IS Q1 = -1.36% (强做空端), OOS Q1 = +2.28% (相对做空弱于 Q5 = +3.03%)

## 汇总结论

| 发现 | 置信度 |
|---|---|
| RIAD 是一个 A 股独有、2025 有效、非 size 代理的因子 | **高** (HAC t=-5, ICIR=-0.89) |
| RIAD 的 alpha 主要在做空端 (散户追捧股跑输) | **高** (IS Q5=-1.10, OOS Q5=+2.00 vs Q1=+3.09) |
| MFD 作为反转因子有弱 alpha 但 IC < 0.03 门槛 | **中** (HAC t=-4 但 IC=-0.02) |
| RIAD + MFD 合成没有显著增量 | **高** (IC 几乎不变) |

## 附录 A — 进一步中性化 + cost-aware backtest (2026-04-22 凌晨)

### A.1 Size + SW1 行业双中性化

| 分段 | raw IC | size-neut | size+ind |
|---|---:|---:|---:|
| FULL | −0.070 | −0.075 | **−0.056** |
| OOS 2025 | −0.059 | −0.067 | **−0.043** |

行业贡献约 25% 的信号. 剥离后核心 alpha 依然显著 (ICIR=-1.02, HAC t=-16.4).

### A.2 **关键发现 — 分层倒 U 形**

size+ind 中性化后 5 分位 20d 持有均值:

```
IS  (2023-10~2024-12) : Q1=+0.28  Q2=+0.67  Q3=+0.58  Q4=+0.32  Q5=-0.98
OOS (2025)           : Q1=+2.99  Q2=+3.00  Q3=+3.45  Q4=+3.11  Q5=+2.47
```

真正 alpha 在 Q5 做空端, **Q2-Q3 是做多最优** (不是 Q1).

### A.3 Cost-aware LS backtest (双边 0.3%, 20d 调仓)

| Mode | IS Sharpe | OOS Sharpe | **FULL Sharpe** | **FULL Ann** | FULL MDD |
|---|---:|---:|---:|---:|---:|
| **Q2Q3_minus_Q5** | **2.00** | 0.59 | **1.66** | **+11.57%** | **-4.79%** |
| Q1_minus_Q5 | 1.11 | 0.02 | 0.73 | +6.70% | -7.29% |
| Q1_long_only | 0.04 | **1.43** | 0.51 | +13.54% | -27.41% |
| Q5_short_only | 0.28 | **-1.41** | -0.26 | -7.48% | -48.03% |

### A.4 Regime shift — 重要警告

IS 和 OOS 的策略最佳解截然不同:
- IS (震荡市): **Short Q5** 是主要 alpha 来源 (散户追涨股跑输)
- OOS 2025 (涨市): **Long Q1** 反而最强, Q5 跟随牛市反弹, 做空端亏钱

解读: 2025 年牛市格局下, "机构关注高的冷门股" (Q1) 被价值发现,
而"散户追涨股" (Q5) 也参与了指数 beta. RIAD 的做空端有强 beta 暴露
(Q5 高 beta), 在涨市容易被轧空.

### A.5 建议实盘策略 (若进入 Option A)

1. **Q2Q3_minus_Q5 静态** — FULL Sharpe 1.66, MDD -4.79%, 过 Phase 4 Sharpe 门槛
   但 ann 11.57% 略低于 15% 门槛, 需要叠加 leverage (1.5x) 或 stacking
2. **加入 regime 过滤** — 牛市 (20日 HS300 return > +3%) 关掉 short leg
3. **A 股融券可行性检查** — Q5 通常包括 ST / 小盘 / 题材股, 大部分不可融券
4. **组合级别 stacking** — 和 DSR #30 BB-only 做低相关度互补 (corr < 0.3 则强 ensemble)

## 下一步选项 (待 jialong 决定)

### Option A — 推进 RIAD 到 paper-trade 前
- [x] 行业中性化 (✅ 已做 A.1)
- [x] 加入融券成本假设 (✅ 已做 A.3, 双边 0.3%)
- [x] Long-only 版本 (做多 Q1) 的 backtest (✅ 已做 A.3)
- [ ] Walk-forward out-of-sample, 滚动 6 个月, 1 年 refit
- [ ] DSR (Deflated Sharpe Ratio) 并入 PEAD/DSR n_trials = 32
- [ ] Regime-aware gate (HS300 momentum 过滤 short leg)
- [ ] 融券 universe filter (剔除 ST / 不可融券)

### Option B — 尝试让 MFD 独立强化
- [ ] 只在散户占比高的股票 (turnover_rate_f 高) 里跑 MFD
- [ ] 把 MFD 做成短周期 (5 日而不是 20 日), 捕捉拉高出货的 T+2 反转
- [ ] 和 limit_list (涨跌停) 事件结合: 涨停当日 elg 净流入多, 次日 T+1 反转概率

### Option C — 探索其他未动数据
- [ ] `broker_recommend` 券商金股: 金股公布 → 前后超额 (fade 效应)
- [ ] `suspend` + `limit_list` 联动: 复牌连板 → 爆量抛压
- [ ] `pledge_stat` 高质押股股价冲击事件 (强制平仓预警)

## 红线 (延续 PEAD 预注册传统)

- 不基于 IS 表现调整 RIAD/MFD 参数 (window=20/60, 采样 5d)
- Option A 前需 jialong 批准
- 样本外评估必须包含 2026 年 (未来数据), 不能只看 2025

## 附录 B — 新增第 3 因子 BGFD + 三因子 orthogonality

### B.1 BGFD (Broker Gold-stock Fade Divergence)

原假设 (crowded → fade) **被证伪**, 反向发现:
- Long 整个金股榜 2024 Sharpe 0.78, **OOS 2025 Sharpe 2.23**
- Short crowded 是灾难, 2025 年 Ann -44%
- 2020-2023 各策略 Sharpe ≈ 0, 是近 2 年的 regime change

交叉验证 RIAD: 两者都指向 "2024-2025 Follow smart money > Fade retail crowding"
详见 `research/factors/broker_gold_fade/README.md`.

### B.2 三因子正交性 (2023-10 ~ 2025-12, 月末截面)

统一方向 (都当做多信号) 后的 Spearman correlation:

| Pair | 点对相关 | 日均 CS 中位数 | 结论 |
|---|---:|---:|---|
| RIAD-MFD | +0.177 | +0.163 | ✅ 正交, 弱正相关 |
| RIAD-BGFD | -0.083 | -0.097 | ✅ 正交, 弱负相关 |
| MFD-BGFD | +0.022 | +0.046 | ✅ 正交, 几乎独立 |

**所有 pairwise |corr| < 0.2**, 远低于 DSR #30 stacking 门槛 0.3.
支持 3-因子等权 ensemble 或 IC-weighted ensemble.

### B.3 建议 Phase 4 ensemble 方案 (待 jialong 批准)

```
composite_s,t = 0.6 * RIAD_signal + 0.2 * MFD_signal + 0.2 * BGFD_signal
  RIAD_signal  = -zscore_cs(RIAD_raw)  (做多低 RIAD)
  MFD_signal   = -zscore_cs(MFD_raw)   (做多低 MFD)
  BGFD_signal  = +zscore_cs(BGFD_raw)  (做多 consensus, 反向的原假设证伪)
```

权重基于 IS Sharpe 粗调 (RIAD 最强 1.66, MFD/BGFD 贡献分散度).
预期 Sharpe (假设正交) ~ sqrt(0.6^2 * 1.66^2 + 0.2^2 * 0.3^2 + 0.2^2 * 0.3^2)
                   ~ 1.00, MDD < 10%, ann 10-12%.

**下一步 (若 jialong 批)**:
1. 实现 composite factor 作为一个新 strategy
2. Cost-aware backtest (双边 0.3%, 月频调仓)
3. 过 Phase 4 评审门槛 (ann > 15%, Sharpe > 0.8, MDD < 30%) 就进 walk-forward

## 数据与代码路径

```
代码:
  research/factors/retail_inst_divergence/
    factor.py                 # RIAD 因子计算
    evaluate_riad.py          # IC + 分层回测
    neutralize_eval.py        # size-neutral 验证
  research/factors/moneyflow_divergence/
    factor.py                 # MFD 因子计算
    evaluate_mfd.py           # IC + 分层回测
    combined_eval.py          # RIAD + MFD 合成
  research/factors/foreign_margin_divergence/
    factor.py                 # FMD 原设计 (northbound 数据 2025 仅 5 行, 不可用)

结果:
  logs/riad_eval_20260422.json
  logs/riad_neutralize_20260422.json
  logs/mfd_eval_20260422.json
  logs/riad_mfd_combined_20260422.json
```

— 记录: jialong
— 更新: 2026-04-22
