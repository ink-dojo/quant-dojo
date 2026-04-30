# D 路: Tier 0 paper smoke kickoff (Issue #51)

_2026-04-30 — Signal generator infra ready, calendar 30-day 跑等 jialong._

---

## TL;DR

- ✅ `scripts/daily_signal_roe_stability.py` 写好且首跑成功, 产 `live/signals/roe_stability_2026-04-17.json` (30 picks)
- ✅ `make signal-roe` Makefile target ready
- ✅ JSON schema 跟现有 `live/signals/YYYY-MM-DD.json` 一致 (date / picks / scores / factor_values / metadata)
- ⏸️ **30 天 calendar 跑** 不在我控制范围内 — 等 jialong 或 cron 启动 nightly job
- ⏸️ **PaperTrader 双 ledger 接入** 是 substantial refactor (PaperTrader 当前 singleton paths), 暂没做, 标 deferred

---

## 现状

### 已完成 (in this session)
1. **Signal generator** (`scripts/daily_signal_roe_stability.py`):
   - 复用 Issue #44/#47 中性化路径 (build_roe_stability + neutralize_factor + cross_section_rank)
   - 取最近交易日 top 30 picks (跟 v16 历史 picks 数量一致)
   - 输出 schema 兼容现有 `live/signals/*.json`
   - 加 `metadata.tier = "Live-Tier 0 (paper-only, Issue #51)"` 让下游 ledger 知道这是 Tier 0 不是真候选

2. **Makefile target** `make signal-roe`:
   - 一行命令产当日 signal
   - 跟 `make health / test / portfolio-data` 风格一致

3. **首跑成功**:
   - 2026-04-30 跑 → 用最近交易日 2026-04-17 (SSD parquet 截至日)
   - 30 picks: 600467, 600127, 603336, 300021, 002481, ...
   - 文件: `live/signals/roe_stability_2026-04-17.json`

### Deferred (calendar 时间不在 session 内)
- nightly cron / launchd schedule 启动 (jialong 手动启动或后续 issue)
- 30 天连续跑 + 每日 ledger 入账
- live-vs-backtest tracking error 监控 (Phase 8 Tier 1 已有 `pipeline/live_vs_backtest.py`, 接入需 ledger 数据)

### Deferred (substantial refactor, 单独 issue)
- **PaperTrader 多 ledger 接入**: 当前 PaperTrader 用 module-level paths
  (`live/portfolio/positions.json` 等), 双 ledger 需 refactor 接受 portfolio_dir
  override. 本 session 不做.
- 临时方案: roe_stability signal 只产文件, 不接 PaperTrader. v16 ops smoke 继续单独跑.

---

## 后续 30 天 (jialong / cron 启动)

```bash
# 每天盘后 16:30 跑 (示例 cron)
30 16 * * 1-5 cd /Users/karan/work/quant-dojo && make signal-roe
```

每日产文件 `live/signals/roe_stability_YYYY-MM-DD.json`. 30 天后:
- 若每天产出无 infra error → Tier 0 first criterion 通过
- jialong 阅 30 天 picks 一致性, 决定是否升 Tier 1 (per framework v1)
- Tier 1 升级需 jialong 独立 ratify (framework 红线 #7)

---

## 红线检查

- ✅ Signal 产出用纯 backtest 路径 (no live data)
- ✅ Tier 0 = paper-only, 0% 真钱 (per framework Live-Tier 0 定义)
- ✅ schema 兼容现有 signal 格式 (不破坏 v16 ops smoke 路径)
- ✅ deferred 项明确标记 (PaperTrader refactor + cron 启动) 不假装做完

---

## A → B → C → D 全 close 状态

| 路 | 状态 | 关键 issue |
|---|---|---|
| A | ✗ 4/4 候选全死 (LHB/回购/解禁/调研 framework_pass=0) | #56-#59 |
| B | ✓ Live-Tier 0/1/2/3 framework ratified | #50 |
| C | ✗ regime overlay 反恶化 | #60 |
| D | ✓ Signal generator infra ready, 30 天等 jialong | #51 |

**总结**: 没找到能上 Tier 1+ 的 strategy candidate. 最干净的 (roe_stability 5/7 切片 PASS) 进 Tier 0 paper smoke. 等 30 天真实 PnL.

教训: simplify review 跨 5 个 study 找到 10+ 真 bug (cost / unit / iterrows / decision logic / journal arithmetic), framework + utils 抽出可复用. Honest "做到头" 比假找到 alpha 更有价值.

— 记录: jialong
