# Pledge Filter 研究报告

**日期**：2026-04-21  
**作者**：jialong + Claude (factor mining sprint)  
**数据**：`pledge_stat/` 2754 股 × 623 周度 snapshot，2014-03 ~ 2026-04

---

## 摘要

质押比例**不是** cross-sectional alpha 因子（ICIR 0.07 / HAC t 0.97），
但在**特定压力 regime**（2018 质押危机 / 2024 小微盘崩盘）是有效风险 filter。
**用法定位**：regime-conditional universe filter，**不是独立 alpha**。

---

## A. 单因子 IC 测试（-pledge_ratio → 20日前瞻）

| 指标 | 值 | 判定 |
|---|---:|---|
| IC 均值 | 0.0045 | 极弱 |
| ICIR | 0.0697 | < 0.3 不合格 |
| 原始 t-stat | 3.59 | 虚高（自相关） |
| **HAC t (NW-19)** | **0.98** | **< 2 不显著** |
| IC>0 占比 | 52.75% | 接近随机 |
| 多空年化 (low-high pledge) | **-2.41%** | **反向** |
| 多空夏普 | -0.27 | 无效 |

**各分位组年化收益（pct 已 annualized）**：
- Q1 (最低 pledge): 17.3%
- Q2: 15.1%
- Q3: 13.5%
- Q4: 12.9%
- Q5 (最高 pledge): **17.5%** ← U 型反而最高

**结论**：pledge_ratio 与未来 20 日收益**不是单调关系**。Q1 / Q5 都高是典型 U 型——
Q1 是无质押的蓝筹（稳增长），Q5 是高质押的题材股（历史高 beta）。
**作为 cross-sectional alpha 因子 不合格**。

## B. Universe Filter 历史压力测试

| 压力区间 | 高质押(>50%) | 高质押(>30%) | 低质押(<5%) | 超额损失 (>50% vs <5%) |
|---|---:|---:|---:|---:|
| 2015-07 ~ 2016-01 股灾+熔断 | -14.6% (n=31) | -21.0% (n=179) | -26.5% (n=921) | **+11.9 pp** ⚠️ 反向 |
| 2018-07 ~ 2019-01 质押危机 | **-27.0%** (n=60) | -20.8% (n=434) | -12.7% (n=862) | **-14.3 pp** ✅ |
| 2024-01 ~ 2024-02 小微盘崩盘 | -15.8% (n=8) | -15.3% (n=88) | -11.6% (n=1613) | -4.2 pp ✅ |

**关键发现**：
- **2015 股灾时高质押 OUTPERFORM 低质押 11.9 pp** —— 因为 2015 是流动性危机、千股跌停无差别，
  质押爆仓尚未触发。
- **2018 是质押专属危机**，filter 效果最好（-14.3 pp）。
- **2024 小微盘崩盘** filter 效果弱（-4.2 pp），因为高质押股 sample 极小（n=8）且主要是退市预期股。

## C. 结论与建议使用方式

### ❌ 不作为 alpha 因子
- ICIR 0.07、HAC t < 2、U 型非单调 → 不进 v16 因子库

### ✅ 作为 regime-conditional risk filter
```
if (HS300.drawdown_from_peak > 15%) AND (CreditSpread.risk_flag):
    universe = universe[pledge_daily < 50]  # 硬过滤 >50%
```
- 2018-Q4 / 2024-Q1 这类危机期触发；平时不启用
- 历史测算：正常期启用会误伤 Q5（17.5% 组），反而降 alpha

### 📋 Follow-up
1. 构造"信用 stress regime flag"：融资余额下降 + HS300 < 200MA + 信用利差扩大
2. 只在 flag=True 时启用 pledge filter
3. Alternative：只排除 **质押 + 股价已跌破警戒线** 的双重条件（需要 pledge_detail 接口，Tushare 有）

---

## 产出文件
- `pledge_panel_daily.parquet`：2919 × 2754 日频 pledge_ratio 宽表（ffill + shift 1）
- `stress_test_results.parquet`：3 个压力区间的分组收益明细
