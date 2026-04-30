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

qlib 官方 `cn_data` v3 截止 **2022-12-30**。我们的 v7 IS 用的是 2015-2024，
DSR #30 OOS 用的是 2018-2026。**对比期只能取重叠区 2018-01-02 ~ 2022-12-30**
（约 5 年 OOS），不是原 issue body 设想的 10 年。

为什么不用我们自己的 tushare 数据：
- tushare 缓存只有 `daily_basic.close`（pro.daily 全 OHLCV 接口被吊销，详见
  `research/factors/tushare_factors/neutralize_and_cost.py:76`）
- Alpha158 大量特征要 open/high/low/volume/amount，close-only 顶多跑 Alpha360 的
  退化子集
- 想拉全 OHLCV 要用 akshare 重新爬 5477 × 12 年，~小时级成本，超出 #48 范围
- qlib 官方数据虽然是 yahoo 来源（数据质量不完美），但作为「行业标准 baseline 参照系」
  本来就是用这套数据训练 Alpha158 的 —— 用它就是用业界默认对照

如果 Phase B 跑通后想把范围扩到 2024，再单独立个 issue 做 akshare 补 OHLCV。

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
