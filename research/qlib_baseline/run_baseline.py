"""
Alpha158 + LightGBM baseline 完整 workflow

跑 fit -> predict -> backtest, 输出对比 DSR #30 BB 主板候选所需的指标。

数据约束 (见 README):
    - calendar 截止 2022-12-30
    - PIT universe 截止 2020-09-25 (后面退化成 snapshot, 不能用)

时间切分:
    train  2008-01-01 ~ 2014-12-31  (7y, 跨 2008/2015 两次极端)
    valid  2015-01-01 ~ 2016-12-31  (2y, 含 2015 股灾)
    test   2017-01-01 ~ 2020-09-25  (~3.7y, 含 2018 熊 + 2020 疫情)

交易成本 (CLAUDE.md 红线):
    单边 0.15% (双边 0.30%); 覆盖 qlib 默认 0.2%

跑法:
    source research/qlib_baseline/.venv/bin/activate
    python research/qlib_baseline/run_baseline.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import lightgbm
import pandas as pd
import qlib
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.model.gbdt import LGBModel
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.data.dataset import DatasetH

QLIB_DATA_DIR = os.environ.get("QLIB_DATA_DIR", "~/.qlib/qlib_data/cn_data")

TRAIN_START = "2008-01-01"
TRAIN_END = "2014-12-31"
VALID_START = "2015-01-01"
VALID_END = "2016-12-31"
TEST_START = "2017-01-01"
TEST_END = "2020-09-25"

# CLAUDE.md 红线: 单边 0.15%
OPEN_COST = 0.0015
CLOSE_COST = 0.0015
MIN_COST = 5

# Topk-Drop 标准 baseline 参数 (qlib 官方 workflow_config_lightgbm_Alpha158.yaml)
TOPK = 50
N_DROP = 5

BENCHMARK = "SH000300"
ACCOUNT = 100_000_000
LIMIT_THRESHOLD = 0.095  # A股 ±10%, qlib 用 9.5% 留 buffer
DEAL_PRICE = "close"

# qlib 官方 LightGBM Alpha158 yaml 上对应的 hyperparams (复刻 + 加 seed 可复现)
LGB_PARAMS = dict(
    loss="mse",
    learning_rate=0.0421,
    num_leaves=210,
    feature_fraction=0.8879,
    bagging_fraction=0.8789,
    bagging_freq=5,
    max_depth=8,
    num_boost_round=1000,
    early_stopping_rounds=50,
    seed=2026,
    deterministic=True,
)

OUT_ROOT = Path(__file__).resolve().parent / "runs"


def main():
    qlib.init(provider_uri=QLIB_DATA_DIR, region="cn")
    run_date = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run_baseline] out_dir={out_dir}")

    # 1. Handler + Dataset
    print("[1/5] building Alpha158 handler...")
    handler = Alpha158(
        instruments="csi300",
        start_time=TRAIN_START,
        end_time=TEST_END,
        fit_start_time=TRAIN_START,
        fit_end_time=TRAIN_END,
        infer_processors=[
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
    )
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": (TRAIN_START, TRAIN_END),
            "valid": (VALID_START, VALID_END),
            "test": (TEST_START, TEST_END),
        },
    )

    # 2. LightGBM 模型
    print("[2/5] training LightGBM Alpha158...")
    model = LGBModel(**LGB_PARAMS)
    model.fit(dataset)

    # 3. predict on test
    print("[3/5] generating signals on test set...")
    pred_df = model.predict(dataset)
    if isinstance(pred_df, pd.Series):
        pred_df = pred_df.to_frame("score")
    pred_path = out_dir / "test_signals.parquet"
    pred_df.to_parquet(pred_path)
    print(f"          signals shape={pred_df.shape}, saved → {pred_path.name}")

    # 4. backtest with TopkDropout + 双边 0.3% 成本
    print("[4/5] backtesting TopkDropout strategy...")
    strategy = TopkDropoutStrategy(
        signal=pred_df,
        topk=TOPK,
        n_drop=N_DROP,
    )
    backtest_kwargs = dict(
        start_time=TEST_START,
        end_time=TEST_END,
        strategy=strategy,
        benchmark=BENCHMARK,
        account=ACCOUNT,
        exchange_kwargs={
            "freq": "day",
            "limit_threshold": LIMIT_THRESHOLD,
            "deal_price": DEAL_PRICE,
            "open_cost": OPEN_COST,
            "close_cost": CLOSE_COST,
            "min_cost": MIN_COST,
        },
    )
    report_normal, positions_normal = backtest_daily(**backtest_kwargs)

    report_path = out_dir / "test_report.parquet"
    report_normal.to_parquet(report_path)

    # 5. risk analysis (qlib 标准指标)
    print("[5/5] computing risk metrics...")
    analysis = {
        "excess_return_without_cost": risk_analysis(
            report_normal["return"] - report_normal["bench"]
        ),
        "excess_return_with_cost": risk_analysis(
            report_normal["return"] - report_normal["bench"] - report_normal["cost"]
        ),
    }
    analysis_df = pd.concat({k: v["risk"] for k, v in analysis.items()}, axis=0)
    analysis_path = out_dir / "test_risk_analysis.csv"
    analysis_df.to_csv(analysis_path)
    print(analysis_df)

    # 总结 metadata（reproducibility — Phase C 决策需要这个）
    meta = {
        "run_date": run_date,
        "qlib_version": qlib.__version__,
        "lightgbm_version": lightgbm.__version__,
        "train": [TRAIN_START, TRAIN_END],
        "valid": [VALID_START, VALID_END],
        "test": [TEST_START, TEST_END],
        "universe": "csi300 (PIT-correct, ends 2020-09-25)",
        "strategy": {
            "class": "TopkDropoutStrategy",
            "topk": TOPK,
            "n_drop": N_DROP,
        },
        "exchange": {
            "benchmark": BENCHMARK,
            "account": ACCOUNT,
            "limit_threshold": LIMIT_THRESHOLD,
            "deal_price": DEAL_PRICE,
            "open_cost": OPEN_COST,
            "close_cost": CLOSE_COST,
            "min_cost": MIN_COST,
            "note": "对齐 CLAUDE.md 红线 单边 0.15% / 双边 0.30%",
        },
        "model": LGB_PARAMS,
        "n_signals": int(pred_df.shape[0]),
        "n_test_days": int(report_normal.shape[0]),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )
    print(f"[run_baseline] done. all artifacts in {out_dir}")


if __name__ == "__main__":
    main()
