# RIAD — Retail-Institution Attention Divergence

**状态**: 2026-04-22 首轮评估完成, 等 jialong 决定 Option A/B/C (见 `journal/riad_mfd_factor_result_20260422.md`)
**Issue**: #33

## 假设

A 股散户占比高 (> 60% 交易额), 散户注意力由热度榜 (ths_hot / dc_hot) 驱动,
容易 overreact 到热门概念; 机构注意力由调研 (stk_surv) 驱动, 选择更有 discipline.
两者在同一股票上的 divergence 应预测未来收益:

- 散户高 ∩ 机构低 → negative alpha (attention-driven retail trap)
- 机构高 ∩ 散户低 → positive alpha (informed accumulation, not yet crowded)

## 因子构造

```
retail_attn_s,t  = sum_{past 20d} score_s,t
                   score = (top_n - rank + 1) / top_n  (ths_hot ∪ dc_hot A 股榜 max)
inst_attn_s,t    = sum_{past 60d} 调研机构数 s,t  (stk_surv, 按机构去重后)
RIAD_s,t         = cross-section zscore(retail_attn) - zscore(log1p(inst_attn))
信号方向         = 做多 RIAD 低, 做空 RIAD 高 (负向因子)
```

## 数据覆盖

| 数据 | 起始 | 终止 | 每股行数 |
|---|---|---|---|
| `ths_hot/` | 2020-01 | 2026-04 | 每日榜 300 A 股 |
| `dc_hot/` | 2020-01 | 2026-04 | 每日榜 200 A 股 |
| `stk_surv/` | **2023-10** | 2026-03 | 稀疏, per-stock |

机构调研 2023-10 起点决定 RIAD 样本窗口 = 2023-10 ~ 至今.

## 首轮结果 (2023-10 ~ 2025-12, 周频采样, 20 日 fwd)

| 分段 | n | IC | ICIR | HAC t | Q1-Q5/期 |
|---|---:|---:|---:|---:|---:|
| FULL | 99 | −0.070 | −0.89 | −5.16 | +1.40% |
| IS 2023-10~2024-12 | 55 | −0.076 | −0.84 | −3.40 | +1.60% |
| **OOS 2025** | 45 | **−0.059** | **−1.25** | **−13.30** | +1.08% |

**Size-neutral** (防小盘代理): corr=0.996, IC 微增, → 不是 size proxy.

## 代码

- `factor.py` — 核心因子计算 (`build_attention_panel`, `compute_riad_factor`)
- `evaluate_riad.py` — IC/ICIR + 分层回测脚本, 输出 `logs/riad_eval_YYYYMMDD.json`
- `neutralize_eval.py` — size-neutralize 稳健性验证

## 跑法

```bash
# 最小验证 (2025Q1)
python -m research.factors.retail_inst_divergence.factor

# 全样本评估
python -m research.factors.retail_inst_divergence.evaluate_riad

# size-neutral 验证
python -m research.factors.retail_inst_divergence.neutralize_eval
```

## 下一步 (等 jialong 决)

- [ ] 行业中性化 (除 size 外, 控制风格)
- [ ] Long-only Q1 回测带双边 0.3% 成本
- [ ] Walk-forward 滚动 6 mo / refit 12 mo
- [ ] DSR (Deflated Sharpe) 纳入 n_trials = 32, 看 CI_low 是否过 0.5
- [ ] paper-trade pre-reg spec (参考 DSR #30 BB-only)
