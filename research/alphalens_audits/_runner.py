"""
alphalens 审计 runner

通用流程: 加载 factor_wide + 价格宽表 → 一致性校验 → tear sheet PNG → 写指标 JSON。
每个具体因子写一个薄脚本，参数化调 run_audit() 即可。

输出目录: research/alphalens_audits/<factor_name>/<run_date>/
    - tear_sheet.png       完整 tear sheet（matplotlib savefig 拼图）
    - returns_tear.png     收益分析 tear sheet（quantile cumulative returns）
    - ic_tear.png          IC 分析 tear sheet
    - turnover_tear.png    换手分析 tear sheet
    - summary.json         IC 均值 / ICIR / quantile spread / 一致性校验结果
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from alphalens import performance, plotting
from alphalens.performance import (
    factor_information_coefficient,
    mean_information_coefficient,
)
from alphalens.utils import get_clean_factor_and_forward_returns, rate_of_return

from utils.alphalens_adapter import (
    align_factor_pricing,
    consistency_check_ic,
    to_alphalens_factor,
    to_alphalens_pricing,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = PROJECT_ROOT / "research" / "alphalens_audits"


def _load_default_price_panel() -> pd.DataFrame:
    """复用 utils.data_loader.load_price_matrix 加载项目主价格宽表（2014-2025, 5477 只）"""
    from utils.data_loader import load_price_matrix
    panel = load_price_matrix(start="2014-01-01", end="2025-12-31", n_stocks=5477)
    if panel is None:
        raise FileNotFoundError(
            "load_price_matrix 没找到 price_wide 缓存；先在主目录跑数据下载脚本"
        )
    return panel


def _data_quality_gate(factor: pd.DataFrame, price: pd.DataFrame) -> None:
    assert factor.shape[0] > 100, f"因子行数异常: {factor.shape[0]}"
    assert price.shape[0] > 100, f"价格行数异常: {price.shape[0]}"
    common_dates = factor.index.intersection(price.index)
    assert len(common_dates) > 50, f"因子 vs 价格公共日期不足: {len(common_dates)}"
    common_assets = factor.columns.intersection(price.columns)
    assert len(common_assets) > 30, f"因子 vs 价格公共股票不足: {len(common_assets)}"


def _period_col(p: int) -> str:
    """alphalens 列名约定：1 → '1D', 5 → '5D'"""
    return f"{p}D"


def run_audit(
    factor_name: str,
    factor_wide: pd.DataFrame,
    price_wide: pd.DataFrame | None = None,
    periods: tuple[int, ...] = (1, 5, 10, 20),
    quantiles: int = 5,
    max_loss: float = 0.5,
    skip_consistency: bool = False,
) -> dict:
    """跑 alphalens 完整审计并保存产物：返回 {out_dir, summary}"""
    if price_wide is None:
        price_wide = _load_default_price_panel()

    _data_quality_gate(factor_wide, price_wide)

    factor_wide, price_wide = align_factor_pricing(factor_wide, price_wide)
    print(
        f"[{factor_name}] aligned shape: factor={factor_wide.shape}, "
        f"price={price_wide.shape}"
    )

    # 稀疏年频因子（如 mda_drift, 7×500 records）一致性会失败 —— 不是 bug，
    # 是 alphalens fill_method='pad' 在稀疏数据上的本质局限；此时传 skip_consistency=True。
    if skip_consistency:
        consistency = None
        print(f"[{factor_name}] consistency: SKIPPED (年频/稀疏因子)")
    else:
        consistency = consistency_check_ic(
            factor_wide, price_wide, fwd_period=periods[0], atol=5e-5
        )
        print(
            f"[{factor_name}] consistency: local={consistency['ic_mean_local']:.6e} "
            f"alphalens={consistency['ic_mean_alphalens']:.6e} "
            f"diff={consistency['abs_diff']:.2e} passed={consistency['passed']}"
        )
        if not consistency["passed"]:
            raise RuntimeError(
                f"一致性校验失败 (diff={consistency['abs_diff']:.2e}); "
                f"适配器或对齐有问题，先修再继续。"
            )

    factor_s = to_alphalens_factor(factor_wide)
    prices = to_alphalens_pricing(price_wide)
    factor_data = get_clean_factor_and_forward_returns(
        factor=factor_s,
        prices=prices,
        periods=periods,
        quantiles=quantiles,
        max_loss=max_loss,
    )
    del factor_s

    run_date = datetime.now().strftime("%Y%m%d")
    out_dir = AUDIT_ROOT / factor_name / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # 直接调 alphalens.plotting 子函数（tears.create_*_tear_sheet 内部 plt.show()，
    # Agg backend 下抓不到 figure；用 plotting 模块的细粒度函数自己控制 fig）。
    # 让每个 plotting 函数自建 figure (ax=None)，然后 plt.gcf() savefig。
    def _save_current(name: str) -> str:
        fig = plt.gcf()
        path = out_dir / f"{name}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path.name

    saved_pngs: list[str] = []
    plt.close("all")

    ic_df = factor_information_coefficient(factor_data)
    plotting.plot_ic_ts(ic_df)
    saved_pngs.append(_save_current("ic_ts"))

    plotting.plot_ic_hist(ic_df)
    saved_pngs.append(_save_current("ic_hist"))

    mean_monthly_ic = performance.mean_information_coefficient(
        factor_data, by_time="ME"
    )
    plotting.plot_monthly_ic_heatmap(mean_monthly_ic)
    saved_pngs.append(_save_current("ic_monthly_heatmap"))

    mean_ret_by_q, _ = performance.mean_return_by_quantile(
        factor_data, by_group=False
    )
    plotting.plot_quantile_returns_bar(mean_ret_by_q)
    saved_pngs.append(_save_current("returns_quantile_bar"))

    mean_quant_daily, _ = performance.mean_return_by_quantile(
        factor_data, by_date=True, by_group=False
    )
    base_period = factor_data.columns[0]
    quantile_returns = mean_quant_daily.apply(
        rate_of_return, axis=0, base_period=base_period
    )
    for period in periods:
        col = _period_col(period)
        if col not in quantile_returns.columns:
            continue
        plotting.plot_cumulative_returns_by_quantile(
            quantile_returns[col], period=col
        )
        saved_pngs.append(_save_current(f"cum_returns_quantile_{col}"))

    quantile_factor = factor_data["factor_quantile"]
    for period in periods:
        quantile_turnover = pd.concat(
            [
                performance.quantile_turnover(quantile_factor, q, period)
                for q in range(1, quantiles + 1)
            ],
            axis=1,
        )
        plotting.plot_top_bottom_quantile_turnover(quantile_turnover, period=period)
        saved_pngs.append(_save_current(f"turnover_top_bottom_{_period_col(period)}"))

    for period in periods:
        autocorr = performance.factor_rank_autocorrelation(factor_data, period=period)
        plotting.plot_factor_rank_auto_correlation(autocorr, period=_period_col(period))
        saved_pngs.append(_save_current(f"factor_rank_autocorr_{_period_col(period)}"))

    ic_mean = mean_information_coefficient(factor_data).to_dict()
    icir = (ic_df.mean() / ic_df.std()).to_dict()

    summary = {
        "factor_name": factor_name,
        "run_date": run_date,
        "n_dates": int(factor_wide.shape[0]),
        "n_assets": int(factor_wide.shape[1]),
        "n_observations": int(factor_data.shape[0]),
        "periods": list(periods),
        "quantiles": quantiles,
        "ic_mean": {str(k): float(v) for k, v in ic_mean.items()},
        "icir": {str(k): float(v) for k, v in icir.items()},
        "consistency": (
            None
            if consistency is None
            else {
                "ic_mean_local": float(consistency["ic_mean_local"]),
                "ic_mean_alphalens": float(consistency["ic_mean_alphalens"]),
                "abs_diff": float(consistency["abs_diff"]),
                "passed": bool(consistency["passed"]),
            }
        ),
        "outputs": saved_pngs,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    plt.close("all")
    print(f"[{factor_name}] saved → {out_dir}")
    return {"out_dir": str(out_dir), "summary": summary}
