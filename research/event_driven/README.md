# research/event_driven — A 股事件驱动 alpha 探索

> 研究方向启动: 2026-04-18
> 前置结论: v16 长历史 OOS (2018-2025) FAIL — A 股日频 cross-sectional factor premium 被套利
> 本方向论据: A 股散户占比 ~60%+, 顶级私募 (九坤/幻方/明汯/灵均) 在事件驱动 / 中频量价上
> 千亿规模长期 alpha, 证明这类 alpha 源未被充分套利

## 本目录是什么

在 v16 方向 (低波动/动量/换手率等截面因子) 被证伪后, 把研究范式从
"cross-sectional factor" 换到 "离散事件窗口 alpha"。具体 Phase 0 目标:

**预注册一个可独立验证的事件驱动策略, 单次 OOS 检验, 失败就换子方向。**

## 第一个假设: PEAD (Post-Earnings Announcement Drift)

### 学术背景
- Bernard & Thomas (1989, 1990): US earnings surprise 之后 60 日 drift 显著
- Fama-French 等多次证伪这一异象能被日级 factor 吃掉, 保留为独立 anomaly
- A 股相关研究: 田利辉 (2014), 吴世农 (2010) 显示 A 股 PEAD 存在但持续窗口更短 (~20 日)
  且受 T+1 / 涨跌停 / 信息披露制度差异影响

### 本研究的 PEAD 定义 (预注册)
- **事件**: 上市公司财报披露日 (季报/半年报/年报, 优先 annual + Q3)
- **surprise 代理**: EPS YoY (本期 vs 去年同期), 不用 consensus (A 股分析师覆盖率低)
- **分层**: 全样本按 EPS YoY 排序, 取 top 30% (positive surprise) / bottom 30%
- **持仓窗口**: 公告后 T+1 ~ T+20 (避开 T+0 盘后信息吸收)
- **买卖**: long top / short bottom → market-neutral L/S, OR long-only top 30%
- **调仓**: 滚动 monthly, 每只股票持仓上限 = min(EPS surprise rank, 持仓窗口)

### 预注册 Admission 门槛 (不调, 不软化)
- 年化收益 ann > 15% (net of txn 0.3%)
- 夏普 sharpe > 0.8
- 最大回撤 mdd > -30%
- PSR_0 > 0.95
- DSR target: > 0.95 (n_trials 从 v34 的 11 继续累加)
- Bootstrap 95% CI 下界 > 0.5 (事件驱动放宽: 样本事件数 vs v16 日度样本大幅减少)

### OOS 样本设计
- IS: 2018-01-01 ~ 2021-12-31 (建模选 hyperparam, 本次无 hyperparam 故 IS=None)
- OOS: 2022-01-01 ~ 2025-12-31 (4 年, ~16 个季报季)
- 由于预注册零自由度, IS/OOS 合并为 "单次 2018-2025 实验" 更干净

### 严禁 (red lines)
- 不调持仓窗口 (T+1~T+20 固定)
- 不换 surprise 代理 (EPS YoY 固定)
- 不换分层比例 (30/30 固定)
- 不加 overlay (regime / vol target / stop-loss)
- 不按行业中性化 (首次跑 naive 版本, 避免事件驱动 debug 和因子 neutralization debug 绑一起)
- 失败就写结论, 不 re-tune 任何数字

### 为什么 PEAD 优先 (vs 减持公告 / 解禁日)
| 事件类型 | 数据可得性 | 学术基础 | A 股特殊性 | 首选理由 |
|:-|:-:|:-:|:-:|:-:|
| PEAD 财报 | akshare 免费 | 最厚 | 季报制度明确 | ✅ 首选 |
| 减持公告 | tushare 需 VIP | 较厚 | A 股大股东减持频繁 | 备选 (数据门槛) |
| 解禁日 | akshare 免费 | 薄 | A 股独有 | 备选 (机制复杂) |
| 指数调仓 | akshare 免费 | 中 | A 股换仓规则透明 | 备选 |

## 数据依赖

### 必需
- 股价宽表: 复用 `utils/local_data_loader` 既有 CSV (外接硬盘 5477 只)
- PIT universe: 复用 `data/raw/listing_metadata.parquet` (2026-04-17 已修好 delist_date)
- 财报披露日 + EPS: 通过 `utils/event_loader.py` 新建 (见 Phase 0 实现)

### 数据源优先级 (预注册)
1. **akshare 免费**: `ak.stock_financial_abstract_ths`, `ak.stock_report_disclosure`
2. **tushare 120 积分**: `pro.disclosure_date`, `pro.forecast` (如能接入 — 配额限制已知)
3. **不使用**: Wind / CapitalIQ / Bloomberg (成本) / 自建爬虫 (工作量)

## Phase 0 交付物 (本 session scope)

- [x] 本 README — 预注册 spec 就位
- [ ] `utils/event_loader.py` — API 骨架 + docstring (不含 API 调用实现)
- [ ] Commit 落档每项

## Phase 1 (tushare 配额重置后开工)

- [ ] `utils/event_loader.py` — 实现 akshare 拉 announcement date + EPS YoY
- [ ] 数据质量门: 覆盖率 ≥80%, 时间单调, 无未来函数
- [ ] 缓存到 `data/raw/events/` (parquet per symbol)

## Phase 2 (数据就绪后)

- [ ] `research/event_driven/01_pead_scan.ipynb` — 描述性统计 + event study plot
- [ ] `research/event_driven/pead_strategy.py` — 策略实现 (严格按预注册 spec)
- [ ] 预注册运行 + journal 结论 (pass/fail 都写)

## 不做什么 (防止 scope creep)

- 不做盘中分钟级事件驱动 (数据门槛高, 先验证日频)
- 不做 LLM 读公告 (agentic research 属于 Phase 7, 不混入因子研究)
- 不做多事件组合 (先跑单事件 PEAD, 有结果再扩展)

## 结果判读预案

| 结果 | 含义 | 下一步 |
|:-|:-|:-|
| 三重过门 (admission + DSR + CI) | A 股事件驱动有 alpha, PEAD 活着 | 开 paper-trade forward OOS |
| admission 过, DSR 不过 | 样本量不够, selection bias 压住 | 等 2 年再跑, 不 re-tune |
| admission 不过 | PEAD 方向也死 | 试下一个事件 (减持/解禁), 不重试 PEAD |
| 三重都烂 (sr<0.3) | A 股日频事件驱动也被套利 | 退到中频量价 (5-30min) 或 B-美股 |
