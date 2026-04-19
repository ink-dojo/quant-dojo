# Phase 4 Pre-registration — 风险层 overlay 研究

**创建**: 2026-04-18
**前提**: Phase 3.5 post-mortem 修正了 gross-cap bug 后, ensemble 真实数字:
ann 10.56% / Sharpe 0.64 / MDD -26.77% / PSR 0.983 (2/5 PASS).
**MDD 门槛已通过**, 瓶颈变为 ann/Sharpe.

## 总策略

Phase 4 在 capped ensemble 基础上叠加 **标准风险管理层**
(vol targeting, regime filter, UNIT calibration). 这些是教科书技术,
有独立理论支持, 不是信号挖掘. 但每个独立 overlay 仍计 1 DSR penalty.

## 数据与基线

**基线**: `research/event_driven/ensemble_v1_capped_oos_returns.parquet`
(#17 capped + #23 capped, 50/50 equal-weight)
- 样本: 2018-01-02 ~ 2025-12-31, 1942 个交易日
- 当前 gate: 2/5 (MDD + PSR)

## 4 个 pre-registered hypothesis

### DSR #25 — Vol-managed ensemble (Moreira-Muir 2017)

**理论支撑**: Moreira-Muir (JF 2017) 在美股 equity anomaly 组合上显示
vol-managed strategy Sharpe 普遍 ↑ 30-50%. 因为 vol spikes 与 DD 事件
高度相关, scale down 在 vol 高时避开 tail loss.

**Spec (零 DoF)**:
```
scale_t = clip(target_vol / realized_vol_60d_{t-1}, 0, cap)
    target_vol = 0.12 (A 股 long-only 合理目标)
    window = 60 交易日
    cap = 1.5 (防止过度杠杆)
    floor = 0
ensemble_new = ensemble_capped × scale
```
全部参数 ex-ante 确定, 不调. `risk_overlay.vol_target_scale` 实现.

**预期**: Sharpe ↑, ann 大致保持, MDD 不恶化.

**Gate**: 标准 5 门 (ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5).

---

### DSR #26 — CSI300 regime filter (Faber 2007)

**理论支撑**: Faber (JWM 2007) 10-mo SMA 滤波器在全资产类别上降 DD 20-40%,
小损 CAGR. A 股 CSI300 200d SMA 是经典 trend proxy.

**Spec (零 DoF)**:
```
regime_on_t = CSI300_close_{t-1} >= SMA_200_{t-1}
scale_t = 1.0 if regime_on else 0.3
    (0.3 不是 0: 保留部分熊市回购 drift 暴露 — 回购公告往往在熊市集中)
ensemble_new = ensemble_capped × scale
```
CSI300 从 `data/raw/indices/sh000300.parquet` 加载.

**预期**: MDD 保持 < -30%, Sharpe 略升 (剔除熊市拖累), ann 或降.

**Gate**: 标准 5 门.

---

### DSR #27 — UNIT recalibration (pre-reg intent 补齐)

**理论支撑**: 原 pre-reg spec 声明 `gross 0.8 typical`, 但 capped 实际
mean gross 0.54 (因为 cap 削了 50% 资本利用率). UNIT 缩放到使
ex-ante mean gross → 1.0 更符合 spec 初衷 (且仍受 cap 保护上限).

**Spec (零 DoF, formula-based)**:
```
scale_factor = 1.0 / mean_capped_gross_baseline   # 实测 = 1 / 0.5 ≈ 2.0
W_raw' = W_raw × scale_factor
W_capped' = apply_gross_cap(W_raw', cap=1.0)
```
对 #17 和 #23 各自独立 rescale, 然后 50/50 重组 ensemble.

**注意**: 这 ARE 一个调参动作 (即使 formula-driven), 所以计 1 DSR penalty.

**预期**: ann 显著 ↑ (因为更多 capital 利用), Sharpe 大致同,
MDD 温和恶化 (更多暴露 → 更多 DD).

**Gate**: 标准 5 门.

---

### DSR #28 — Combined stack

**Spec**: 在 DSR #27 recalibrated ensemble 之上叠加 #25 (vol target)
+ #26 (regime filter). Order: scale_total = vol_scale × regime_scale.
One-shot integration, 无后续微调.

**预期**: 如果每层独立 +Sharpe, stack 有叠加效应. 如果某层负贡献,
stack 也保留它 (pre-commit, 不后验剔除).

**Gate**: 标准 5 门.

---

## 红线

- **任何一个 hypothesis 5/5 PASS** → 提交 jialong 作 paper-trade candidate
- **全部 fail 但 combined 有明显改善** → 报告给 jialong 作 option A 支持
  (接受 modified gate 或增加 paper-trade sample-size 门槛)
- **全部 fail 且无改善** → 结构化结论: A 股日频 event-driven long-only alpha
  在当前 pre-reg 约束下不足以独立成立. 建议 option B/C (数据升级 / gate 调整).

## DSR 计数

- 起点: n=24 (Phase 3 final)
- DSR #25, #26, #27, #28 = 4 个新 trial
- Phase 4 结束 n_trials = 28

## Execution Order

1. 先独立跑 #25, #26, #27 (并行合适)
2. 看结果再跑 #28 (combined)
3. 写 terminal 报告, journal, memory 更新

**Pre-registration lock time**: 2026-04-18 (执行前必须 git commit 本文件)
