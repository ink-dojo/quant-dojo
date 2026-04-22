# Handoff — MD&A drift Tier 1b (2026-04-22)

> 重启 Ghostty + 给 Claude 硬盘访问权限后,从这份文档继续。

## 当前状态

- 分支: `main`, HEAD = `11feabc` (refactor: pipeline 改 per-symbol stream)
- Issue #28 OPEN, kanban = In Progress
- 测试 21/21 通过 (`pytest tests/research/test_mda_drift.py`)
- Smoke (`--smoke --no-download`) 跑通,pipeline 结构 OK
- 内置盘 14GB free, 峰值占用 ~5MB (per-symbol + `--delete-pdf-after-tokens`)

## 已完成 (1a + 1b 基础设施)

- [x] `research/factors/mda_drift/` 四模块 (data_loader/text_processor/similarity/factor)
- [x] text_processor 支持 A 股年报 "第N章" + 页眉重复 + 跨章引用
- [x] 21 单测 + 章节变体回归测试
- [x] `scripts/mda_drift_tier1_eval.py` pre-reg runner (锁定参数)
- [x] `scripts/mda_drift_tier1b_ic_eval.py` IC 评估脚手架
- [x] pipeline 重构成 per-symbol stream (commit `11feabc`)
- [x] `--delete-pdf-after-tokens` flag 磁盘节流
- [x] manifest 持久化 (`data/processed/mda_drift_manifest.parquet`)

## 待做 — 按顺序跑

### Step A — 启动 subset 下载 (背景 1-2h)

```bash
cd /Users/karan/work/quant-dojo
# 如果 SSD 权限已给 (见下 "SSD 可选优化"), 可以把 PDF cache 移到 SSD
# 不给权限也没关系, 峰值 5MB 内置盘够用

python scripts/mda_drift_tier1_eval.py --subset --delete-pdf-after-tokens \
  > journal/tier1b_subset_run_$(date +%Y%m%d_%H%M).log 2>&1 &
echo $! > /tmp/tier1b.pid
```

产物:
- `data/processed/mda_drift_scores.parquet` (因子宽表, fiscal_year × symbol)
- `data/processed/mda_drift_manifest.parquet` (publish_date 映射)
- `data/processed/mda_tokens/{symbol}_{year}.parquet` (~500 × 8 = 4000 个)
- diagnostics 在 stdout log (status counts)

### Step B — 监控 + 覆盖率审计

```bash
# 实时看进度
tail -f journal/tier1b_subset_run_*.log

# 跑完后审计
python -c "
import pandas as pd
m = pd.read_parquet('data/processed/mda_drift_manifest.parquet')
scores = pd.read_parquet('data/processed/mda_drift_scores.parquet')
print(f'manifest: {len(m)} refs, {m.symbol.nunique()} symbols')
print(f'scores:   {scores.shape} (fiscal_year × symbol)')
print(f'non-null drift 比例: {scores.notna().mean().mean():.1%}')
"
```

门槛: **非 missing >= 90%**。不足 90% 先查 PDF 下载失败率 / MD&A 抽取失败率,不要直接上 IC。

### Step C — 跑 IC 评估

```bash
python scripts/mda_drift_tier1b_ic_eval.py 2>&1 | tee -a journal/tier1b_subset_run_*.log
```

自动写到 `journal/mda_drift_tier1_result_20260422.md`。

### Step D — Kill 决策 (锁定, 跑完不改)

月度 rank IC:
- `< 0.015` → 🔴 **STOP**. 空间 C Tier 1/2 方向封死, 直接跳 Tier 3 (跨文档 reasoning)
- `0.015 ~ 0.025` → 🟡 进 Tier 2 (LLM hedging 密度做增量)
- `> 0.025` → 🟢 Tier 2 暂缓, Tier 1 直接 paper-trade

附加必答 (不 kill 但要在 journal 标注):
- 前 5 年 (2018-2022) vs 后 3 年 (2023-2025) IC 衰减 >= 50% → 注册制后 regime shift
- top 20 drift 公司 HHI > 0.3 或单行业占比 > 30% → 行业中性化版本重测

### Step E — 收尾

```bash
git add journal/mda_drift_tier1_result_20260422.md
git commit -m "research: MD&A drift Tier 1b IC 评估结果 + kill 判读

Closes #28"
git push origin main
```

## SSD 可选优化 (给权限后)

重启后 `ls /Volumes/Crucial\ X10/` 能列出内容则权限 OK。不必强求 —
per-symbol stream 内置盘够跑, SSD 只是加速 + 保留 PDF 供调试。

可选:把 PDF cache 链接到 SSD (tokens 留在内置盘快):

```bash
mkdir -p "/Volumes/Crucial X10/quant-dojo/annual_reports"
rm -rf data/raw/annual_reports
ln -s "/Volumes/Crucial X10/quant-dojo/annual_reports" data/raw/annual_reports
ls -l data/raw/annual_reports  # 确认符号链接指向 SSD
```

若 SSD 能写入, 就不需要 `--delete-pdf-after-tokens` — 留着 PDF 后续可以
重新抽 MD&A (比如换 extraction 规则). 但当前 pipeline 先走有权限的路子,
别花时间搞权限。

## 如果 run 中断

重跑同一命令即可。tokens parquet + manifest parquet 都是增量落盘,
`compute_mda_drift_factor` 会短路已完成的 (symbol, year) 对。

## 关键文件

- `scripts/mda_drift_tier1_eval.py` — pre-reg runner (锁参数)
- `scripts/mda_drift_tier1b_ic_eval.py` — IC + kill 判读
- `research/factors/mda_drift/factor.py` — per-symbol stream pipeline (`compute_mda_drift_factor`)
- `research/factors/mda_drift/text_processor.py` — A 股年报 MD&A 抽取
- `TODO.md` 空间 C 章节 — 整体 roadmap
- `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md` — 战略锚

## 未完成 Tasks (TaskList)

- #10 启动 subset 下载 (背景) ← 下一步
- #11 MD&A 抽取覆盖率审计
- #12 跑 IC 评估 + 写 journal
