# qlib_baseline

外部独立基线轨道：用 microsoft/qlib 在 CSI300 上跑 Alpha158 + LightGBM workflow，
作为对照 DSR #30 BB 主板 rescaled 候选的判决型证据。

跟 #48 / W18-W20 三周计划：
- W18 数据 + 环境（Phase A）
- W19 跑 baseline（Phase B）
- W20 对比 + 决策（Phase C）

---

## 快速上手

```bash
# 一键装环境（独立 venv，不污染主项目）
./research/qlib_baseline/setup_env.sh

# 自检
source research/qlib_baseline/.venv/bin/activate
python research/qlib_baseline/verify_data.py
```

## 数据局限（必读）

qlib 官方 `cn_data` v3 有两个数据边界:
- **calendar 截止 2022-12-30** (这是 OHLCV 价格数据范围)
- **CSI300 PIT universe 截止 2020-09-25** (universe 名单刷新止于此日，之后退化成 snapshot)

后者更紧，是真实约束。**Phase B test_end 不能超过 2020-09-25**，否则违反幸存者偏差。

DSR #30 OOS 起 2018-01-02，所以**对比期只能取重叠区 2018-01-02 ~ 2020-09-25**
（约 2.5 年），不是原 issue body 设想的 10 年。这低于 CLAUDE.md 策略评审门槛
"回测时间跨度 > 3 年"，意味着 Phase C 输出的对比表只能作为**参考性外部基线**，
不能直接用来 go/no-go DSR #30 paper-trade 决策（决策仍要看完整 2018-2026 区间）。

为什么不用我们自己的 tushare 数据：
- tushare 缓存只有 `daily_basic.close`（pro.daily 全 OHLCV 接口被吊销，详见
  `research/factors/tushare_factors/neutralize_and_cost.py:76`）
- Alpha158 大量特征要 open/high/low/volume/amount，close-only 顶多跑 Alpha360 的
  退化子集
- 想拉全 OHLCV 要用 akshare 重新爬 5477 × 12 年，~小时级成本，超出 #48 范围
- qlib 官方数据虽然是 yahoo 来源（数据质量不完美），但作为「行业标准 baseline 参照系」
  本来就是用这套数据训练 Alpha158 的 —— 用它就是用业界默认对照

如果 Phase B 跑通后想把范围扩到 2024，再单独立个 issue 做 akshare 补 OHLCV。

## 交易成本对齐（Phase B 必做）

成本规则参见 `CLAUDE.md` 「回测质量红线」与 「Live-Tier v1」（双边 0.3% 用于
Tier 0 入门，双边 0.5% 用于 Tier 1 升级门）。

qlib `TopkDropoutStrategy` 默认 `open_cost=0.0005, close_cost=0.0015`（单边 0.2%），
与 CLAUDE.md 不一致。`run_baseline.py` 通过 `OPEN_COST = CLOSE_COST = 0.0015`
显式覆盖到单边 0.15% / 双边 0.30%。改成别的值会让 baseline 与 DSR #30 不可比 ——
1bp 在 5 年累积是显著偏差。

## 幸存者偏差（Phase A 已自检）

`verify_data.py` 在跑时会断言 CSI300 universe 含 ≥50 只"已退出"股票（PIT-correct
检查），失败直接 raise，避免 Phase B 用了 current snapshot 而不是历史成分股。

## 目录结构

```
research/qlib_baseline/
├── README.md           本文件
├── setup_env.sh        venv + qlib + cn_data 一键装机
├── verify_data.py      cn_data 自检（calendar/instruments/Alpha158）
└── .venv/              独立 venv（git 忽略）
```

## 隔离原则（不能动）

- 装在独立 venv，**绝不**改 quant-dojo 主项目 `pyproject.toml` 的依赖
- qlib 数据放 `~/.qlib/qlib_data/cn_data`，不进 git
- 所有 baseline 产物写到 `research/qlib_baseline/runs/<date>/`，与主 `live/runs/` 分开
- 决策证据（最终对比表、journal）写到主项目 `journal/qlib_baseline_dsr30_compare_<date>.md`
