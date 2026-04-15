# 基础设施 P0/P1 修复 · 2026-04-14

**目标**：把 pipeline 修到"小型私募及格线"。  
**范围**：幸存者偏差、数据可重现性、账本 ACID。  
**时间**：约 2 小时。

---

## 背景：pipeline 扫描结论

用户担心"重要 pipeline 流程是 AI 每次现跑的，没有 solid 代码"。扫描结论是
**这个担心是误会**：

- `pipeline/daily_signal.py` → `pipeline/control_surface.py` → `live/paper_trader.py`
  → `agents/risk_guard.py` → `reporter` 这条主链**全部是固定代码**，没有
  LLM 在关键路径上。
- AI 只出现在：dashboard 的解说、factor 挖掘工具、研究 notebook —— 这些是
  **离线/只读**路径，不会影响实盘。

真正差"及格线"的是三件事：
1. **幸存者偏差**：回测/信号生成用 `get_all_symbols()` 拿的是**今天**还活
   着的股票，历史回测把早就退市的股票默认当"不存在"，Sharpe 系统性虚高。
2. **数据 vintage 无记录**：两周后看一条 run_id 没法回答"当时用的哪版数据"。
3. **账本用 JSON**：`json.dump` 不是原子写，多进程调仓只有线程锁，
   trades.json 每次整表重写——崩溃/断电就是丢整段历史的风险。

---

## 三个修复

### P0.1 幸存者偏差 — `utils/listing_metadata.py`

- akshare 抓 SH/SZ/BJ 上市日期 + 当前退市清单
- 本地 parquet 首末日期反推退市日（akshare 不给）
- `data/raw/listing_metadata.parquet` 缓存，7 天 TTL
- API：
  - `universe_at_date(d)` — 当日已上市且未退市
  - `universe_alive_during(s, e)` — [s, e] 内任一时刻存活过的并集

**接入**：
- `backtest/standardized.py:490` 用 `universe_alive_during(lookback_start, end)`
- `pipeline/daily_signal.py:92` 用 `universe_at_date(end)`
- 元数据不可用时降级到 `get_all_symbols()` 并 warn

**历史验证（本地可用）**：

| 日期 | 股票数 | vs 当前 |
|------|-------:|--------:|
| 2010-01-04 | 1,657 | 30% |
| 2015-06-30 | 2,836 | 52% |
| 2020-03-20 | 3,888 | 71% |
| 2026-04-14 | 5,188 | 95% |

原先逻辑相当于在 2010 年的回测里用 2026 年的 5,477 只股票，70% 的股票还
没上市，这些空数据会被 `load_price_wide` 悄悄跳过，但组合构建的 universe
偏向长期存活者。

---

### P0.2 数据 vintage 快照 — `utils/data_manifest.py`

- `compute_data_manifest(symbols)`：扫 `~/quant-data/*.csv` + `data/cache/local/*.parquet`
  - 记录 `(size, mtime_ns)` 指纹，不读文件内容
  - 聚合 SHA256 + 上市元数据 parquet 的 SHA256
  - 5,477 文件约 1s 完成
- `verify_data_manifest(manifest)`：对比当前数据 vs 历史快照，列漂移字段

**接入**：
- `BacktestResult` 新增 `data_manifest` 字段
- `RunRecord.artifacts["data_manifest"]` 持久化
- 日频信号 JSON 的 `metadata.data_manifest` 也存一份

**用途**：
- 两周后回看任意 run_id 能答"当时用了哪版数据"
- 重跑时 verify 自动检测数据漂移（CSV 被重下/parquet 缓存变化）

---

### P1 SQLite ACID 账本 — `live/ledger.py`

替换原先 positions.json + trades.json + nav.csv 的脆弱持久化。

- SQLite WAL 模式：多进程读、独占写
- 三张表：
  - `trades`（append-only，`CHECK(shares > 0)` 硬约束）
  - `nav_history`（PRIMARY KEY trade_date，upsert）
  - `positions`
- 每次写用 `BEGIN IMMEDIATE` + `COMMIT` 事务，崩溃自动 ROLLBACK
- `migrate_from_json` 首次自动迁移历史
- `rehydrate_to_json` 从 SQLite 重建 JSON/CSV（JSON 损坏时用）

**接入 `live/paper_trader.py`**：
- 所有公开方法签名不变（15+ 调用方零侵入）
- `_record_trade` / `_append_nav` / `_save_positions` 改为双写：
  - SQLite 先入库（source of truth）
  - JSON/CSV 原子刷新（tmp + rename，防断电损坏）
- 新增 `rehydrate_from_ledger()` API

**对比原先脆弱点**：

| 问题 | 原先 | 现在 |
|------|------|------|
| 写入原子性 | `json.dump` 覆盖式写 | tmp + rename |
| 多进程安全 | `threading.Lock` 管不到 | SQLite WAL + `BEGIN IMMEDIATE` |
| 崩溃恢复 | trades.json 可能丢历史 | SQLite 自动回滚；JSON 可从 db 重建 |
| 约束校验 | 代码层面 assert | DB 层面 `CHECK` 约束 |

---

## 测试

- `live/ledger.py` 独立 smoke test ✅
- `PaperTrader` 双写同步 smoke test ✅
- `tests/test_phase5_smoke.py` + `tests/test_phase5_regression.py` +
  `tests/test_pipeline_agents.py` — 79 passed ✅

---

## commit 拆分（小步提交）

```
55e4fac  fix(bias): 引入 universe_at_date 修复幸存者偏差
7311cd7  feat(repro): 引入数据 vintage 快照 · 每次运行存 manifest
aa62104  feat(ledger): SQLite ACID 账本 · 防交易/净值丢失
```

---

## 下一步（不在本次范围）

- P2：接入真实申万行业分类替换 `10_industry_neutral.ipynb` 里的合成分桶
- P2：`winsorize()` 改 MAD 方法（`utils/factor_analysis.py:17`）
- P3：`quality_factor` 用 `announcement_date` 替代 `shift(1)` 近似公告延迟
- P3：`compute_beta` 向量化（5000 只股票时 Python 双循环会慢）
