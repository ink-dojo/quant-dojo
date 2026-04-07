"""
quant_dojo generate — 自动生成策略

流程:
  1. 计算所有可用因子
  2. 评估每个因子的预测力（IC/ICIR）
  3. 过滤低质量因子
  4. 去除高相关因子（避免冗余）
  5. 自动组合最优因子组合
  6. 回测验证
  7. 输出新策略定义

用法:
  python -m quant_dojo generate                # 全自动
  python -m quant_dojo generate --top 5        # 选 top 5 因子
  python -m quant_dojo generate --min-icir 0.3 # ICIR 门槛
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_generate(
    top_n: int = 6,
    min_icir: float = 0.2,
    max_corr: float = 0.6,
    start: str = None,
    end: str = None,
    n_stocks: int = 30,
    activate: bool = False,
):
    """自动生成最优策略"""
    sys.path.insert(0, str(PROJECT_ROOT))
    t0 = time.time()

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 策略自动生成                      ║")
    print("╚═══════════════════════════════════════════════╝\n")
    print(f"  参数: top {top_n} 因子 | ICIR >= {min_icir} | 相关性 < {max_corr}")

    # 日期范围
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=730)
        start = start_dt.strftime("%Y-%m-%d")
    print(f"  区间: {start} ~ {end}")
    print()

    # ── Step 1: 加载数据 ──
    print("━━━ Step 1/6: 加载数据 ━━━")
    try:
        data = _load_data(start, end)
        n_symbols = len(data["price"].columns)
        n_days = len(data["price"])
        print(f"  [OK] {n_symbols} 只股票, {n_days} 个交易日\n")
    except Exception as e:
        print(f"  [失败] 数据加载失败: {e}")
        print("         请先运行: python -m quant_dojo init --download")
        sys.exit(1)

    # ── Step 2: 计算所有因子 ──
    print("━━━ Step 2/6: 计算因子 ━━━")
    factors = _compute_all_factors(data)
    print(f"  [OK] 计算了 {len(factors)} 个因子\n")

    # ── Step 3: 评估因子质量 ──
    print("━━━ Step 3/6: 评估因子质量 ━━━")
    ret_wide = data["price"].pct_change().shift(-1)  # 下一日收益
    factor_stats = _evaluate_factors(factors, ret_wide)

    # 打印因子评估表
    print(f"\n  {'因子':<20} {'IC均值':>8} {'ICIR':>8} {'IC>0%':>8} {'方向':>6}")
    print(f"  {'─'*18:<20} {'─'*6:>8} {'─'*6:>8} {'─'*6:>8} {'─'*4:>6}")
    for s in factor_stats:
        direction = "正向" if s["IC_mean"] > 0 else "反向"
        print(f"  {s['name']:<20} {s['IC_mean']:>+8.4f} {s['ICIR']:>8.4f} {s['pct_pos']:>7.1%} {direction:>6}")

    # ── Step 4: 筛选因子 ──
    print(f"\n━━━ Step 4/6: 筛选因子 (|ICIR| >= {min_icir}) ━━━")
    qualified = [s for s in factor_stats if abs(s["ICIR"]) >= min_icir]
    # 按 |ICIR| 排序
    qualified.sort(key=lambda x: abs(x["ICIR"]), reverse=True)

    if not qualified:
        print("  [错误] 没有因子达到 ICIR 门槛")
        print(f"         尝试降低门槛: --min-icir {min_icir * 0.5:.1f}")
        sys.exit(1)

    print(f"  合格因子: {len(qualified)} 个")
    for s in qualified:
        print(f"    {s['name']:<20} ICIR={abs(s['ICIR']):.4f}")

    # ── Step 5: 去冗余（相关性过滤）──
    print(f"\n━━━ Step 5/6: 去冗余 (相关性 < {max_corr}) ━━━")
    selected = _select_uncorrelated(qualified, factors, max_corr, top_n)

    print(f"  最终选中 {len(selected)} 个因子:")
    for s in selected:
        direction = 1 if s["IC_mean"] > 0 else -1
        print(f"    {s['name']:<20} ICIR={abs(s['ICIR']):.4f}  方向={'正' if direction > 0 else '反'}")

    if len(selected) < 2:
        print("  [错误] 有效因子不足 2 个，无法构建策略")
        sys.exit(1)

    # ── Step 6: 回测验证 ──
    print(f"\n━━━ Step 6/6: 回测验证 ━━━")
    strategy_def = _build_strategy_definition(selected)
    result = _backtest_strategy(strategy_def, data, ret_wide, n_stocks, start, end)

    if result is None:
        print("  [失败] 回测失败")
        sys.exit(1)

    # ── 结果 ──
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  策略自动生成完成 ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"\n  策略名: auto_gen")
    print(f"  因子数: {len(selected)}")
    print(f"  因子: {', '.join(s['name'] for s in selected)}")
    print(f"\n  回测指标:")
    print(f"    总收益: {result['total_return']:+.2%}")
    print(f"    年化:   {result['annualized_return']:+.2%}")
    print(f"    夏普:   {result['sharpe']:.2f}")
    print(f"    回撤:   {result['max_drawdown']:.2%}")

    # 保存策略定义
    out_path = _save_strategy(strategy_def, result, selected)
    print(f"\n  策略文件: {out_path}")

    # 与现有策略对比
    _compare_with_existing(result)

    # 激活
    if activate and result["sharpe"] >= 0.5:
        print(f"\n  自动激活 auto_gen 策略...")
        try:
            from pipeline.active_strategy import set_active_strategy, VALID_STRATEGIES
            VALID_STRATEGIES.add("auto_gen")
            set_active_strategy("auto_gen", reason=f"自动生成，夏普 {result['sharpe']:.2f}")
            print("  [OK] 策略已激活")
        except Exception as e:
            print(f"  [跳过] 激活失败: {e}")

    print(f"\n  下一步:")
    print(f"    python -m quant_dojo backtest --strategy auto_gen  # 详细回测")
    print(f"    python -m quant_dojo activate auto_gen              # 激活策略")
    print(f"{'='*60}")

    return strategy_def


def _load_data(start: str, end: str) -> dict:
    """加载回测所需数据"""
    from utils.local_data_loader import load_price_wide, get_all_symbols

    symbols = get_all_symbols()
    if not symbols:
        raise ValueError("未找到股票数据")

    # 多加载一年用于因子计算
    calc_start_dt = datetime.strptime(start, "%Y-%m-%d") - timedelta(days=365)
    calc_start = calc_start_dt.strftime("%Y-%m-%d")

    price = load_price_wide(symbols, calc_start, end, field="close")
    if price.empty:
        raise ValueError("价格数据为空")

    data = {"price": price}

    # 尝试加载额外数据
    for field in ["high", "low", "open", "pe_ttm", "pb"]:
        try:
            df = load_price_wide(symbols, calc_start, end, field=field)
            if not df.empty:
                data[field] = df
        except Exception:
            pass

    return data


def _compute_all_factors(data: dict) -> dict:
    """计算所有可用因子"""
    from utils.alpha_factors import build_fast_factors

    price = data["price"]
    kwargs = {}
    if "high" in data:
        kwargs["high"] = data["high"]
    if "low" in data:
        kwargs["low"] = data["low"]
    if "open" in data:
        kwargs["open_price"] = data["open"]
    if "pe_ttm" in data:
        kwargs["pe"] = data["pe_ttm"]
    if "pb" in data:
        kwargs["pb"] = data["pb"]

    factors = build_fast_factors(price, **kwargs)

    # 加上 cgo_simple（内联计算）
    factors["cgo_simple"] = -(price / price.rolling(60).mean() - 1)

    # 过滤掉全 NaN 因子
    valid_factors = {}
    for name, fac in factors.items():
        if fac.notna().any().any():
            valid_factors[name] = fac

    return valid_factors


def _evaluate_factors(factors: dict, ret_wide) -> list:
    """评估每个因子的预测力"""
    from utils.factor_analysis import compute_ic_series

    stats = []
    import numpy as np

    for name, fac in factors.items():
        try:
            ic = compute_ic_series(fac, ret_wide, method="spearman", min_stocks=30)
            ic_clean = ic.dropna()
            if len(ic_clean) < 20:
                continue

            mean_ic = ic_clean.mean()
            std_ic = ic_clean.std()
            icir = mean_ic / std_ic if std_ic > 0 else 0
            pct_pos = (ic_clean > 0).mean()

            stats.append({
                "name": name,
                "IC_mean": float(mean_ic),
                "IC_std": float(std_ic),
                "ICIR": float(icir),
                "pct_pos": float(pct_pos),
                "n_days": len(ic_clean),
            })
        except Exception:
            continue

    # 按 |ICIR| 排序
    stats.sort(key=lambda x: abs(x["ICIR"]), reverse=True)
    return stats


def _select_uncorrelated(qualified: list, factors: dict, max_corr: float, top_n: int) -> list:
    """从合格因子中选出互不冗余的 top N"""
    import numpy as np

    selected = []

    for candidate in qualified:
        if len(selected) >= top_n:
            break

        name = candidate["name"]
        fac = factors[name]

        # 检查与已选因子的相关性
        too_correlated = False
        for existing in selected:
            existing_fac = factors[existing["name"]]
            # 截面平均相关性
            common_cols = fac.columns.intersection(existing_fac.columns)
            common_dates = fac.index.intersection(existing_fac.index)
            if len(common_cols) < 10 or len(common_dates) < 20:
                continue

            # 取最后 120 天的平均截面相关性
            recent_dates = common_dates[-120:]
            corrs = []
            for d in recent_dates[-30:]:  # 抽样 30 天
                f1 = fac.loc[d, common_cols].dropna()
                f2 = existing_fac.loc[d, common_cols].dropna()
                common = f1.index.intersection(f2.index)
                if len(common) > 30:
                    c = f1[common].corr(f2[common])
                    if not np.isnan(c):
                        corrs.append(abs(c))

            if corrs and np.mean(corrs) > max_corr:
                too_correlated = True
                print(f"    [跳过] {name} 与 {existing['name']} 相关性 {np.mean(corrs):.2f}")
                break

        if not too_correlated:
            selected.append(candidate)

    return selected


def _build_strategy_definition(selected: list) -> dict:
    """从选中因子构建策略定义"""
    factors = []
    for s in selected:
        direction = 1 if s["IC_mean"] > 0 else -1
        factors.append({
            "name": s["name"],
            "direction": direction,
            "icir": abs(s["ICIR"]),
            "ic_mean": s["IC_mean"],
        })

    return {
        "name": "auto_gen",
        "factors": factors,
        "weighting": "ic_weighted",
        "neutralize": True,
        "n_stocks": 30,
        "generated_at": datetime.now().isoformat(),
    }


def _backtest_strategy(strategy_def: dict, data: dict, ret_wide, n_stocks: int,
                       start: str, end: str) -> dict:
    """对生成的策略进行回测"""
    import numpy as np
    import pandas as pd
    from utils.factor_analysis import compute_ic_series

    price = data["price"]
    factors_data = _compute_all_factors(data)

    # 按照策略定义计算复合因子
    factor_names = [f["name"] for f in strategy_def["factors"]]
    directions = {f["name"]: f["direction"] for f in strategy_def["factors"]}

    # 收集因子 IC 序列用于权重
    ic_series_dict = {}
    factor_dfs = {}
    for name in factor_names:
        if name not in factors_data:
            continue
        fac = factors_data[name]

        # 应用方向
        if directions.get(name, 1) == -1:
            fac = -fac

        factor_dfs[name] = fac
        ic = compute_ic_series(fac, ret_wide, method="spearman")
        ic_series_dict[name] = ic

    if len(factor_dfs) < 2:
        return None

    # IC 加权复合
    ic_df = pd.DataFrame(ic_series_dict)
    rolling_ic = ic_df.rolling(60, min_periods=20).mean().abs()

    # 标准化因子
    zscore_factors = {}
    for name, fac in factor_dfs.items():
        z = (fac.sub(fac.mean(axis=1), axis=0)).div(fac.std(axis=1), axis=0)
        z = z.clip(-3, 3)
        zscore_factors[name] = z

    # 对齐日期
    common_dates = price.index
    for name in zscore_factors:
        common_dates = common_dates.intersection(zscore_factors[name].index)
    common_dates = common_dates.intersection(rolling_ic.index)

    # 筛选回测区间
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    bt_dates = [d for d in common_dates if start_ts <= d <= end_ts]

    if len(bt_dates) < 60:
        return None

    # 逐日计算复合分数
    common_symbols = price.columns
    for name in zscore_factors:
        common_symbols = common_symbols.intersection(zscore_factors[name].columns)

    # 等权回测模拟
    portfolio_returns = []
    prev_holdings = set()

    # 月度调仓
    prev_month = None
    for i, date in enumerate(bt_dates[:-1]):
        current_month = date.month

        if current_month != prev_month:
            # 调仓日：计算复合分数
            ic_weights = rolling_ic.loc[date].dropna()
            if ic_weights.sum() <= 0:
                ic_weights = pd.Series(1.0, index=factor_names)
            ic_weights = ic_weights / ic_weights.sum()

            composite = pd.Series(0.0, index=common_symbols)
            weight_sum = pd.Series(0.0, index=common_symbols)

            for name in factor_dfs:
                if name in ic_weights.index and date in zscore_factors[name].index:
                    vals = zscore_factors[name].loc[date, common_symbols]
                    valid = vals.notna()
                    w = ic_weights.get(name, 0)
                    composite[valid] += vals[valid] * w
                    weight_sum[valid] += w

            composite = composite / weight_sum.replace(0, np.nan)
            composite = composite.dropna()

            # 选 top n_stocks
            if len(composite) >= n_stocks:
                top = composite.nlargest(n_stocks)
                prev_holdings = set(top.index)
            prev_month = current_month

        # 计算日收益
        if prev_holdings:
            next_date = bt_dates[i + 1]
            rets = []
            for sym in prev_holdings:
                if sym in price.columns:
                    try:
                        p0 = price.loc[date, sym]
                        p1 = price.loc[next_date, sym]
                        if p0 > 0 and not np.isnan(p0) and not np.isnan(p1):
                            rets.append(p1 / p0 - 1)
                    except (KeyError, TypeError):
                        pass
            if rets:
                portfolio_returns.append(np.mean(rets))
            else:
                portfolio_returns.append(0.0)
        else:
            portfolio_returns.append(0.0)

    if not portfolio_returns:
        return None

    returns = np.array(portfolio_returns)
    cum_return = np.cumprod(1 + returns)
    total_return = cum_return[-1] - 1
    n_years = len(returns) / 252
    annualized = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

    # 最大回撤
    peak = np.maximum.accumulate(cum_return)
    dd = (cum_return - peak) / peak
    max_dd = dd.min()

    metrics = {
        "total_return": float(total_return),
        "annualized_return": float(annualized),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "n_days": len(returns),
    }

    print(f"  [OK] 回测完成: {len(returns)} 个交易日")
    print(f"    收益 {total_return:+.2%} | 年化 {annualized:+.2%} | 夏普 {sharpe:.2f} | 回撤 {max_dd:.2%}")

    return metrics


def _save_strategy(strategy_def: dict, metrics: dict, selected: list) -> Path:
    """保存策略定义到文件"""
    out_dir = PROJECT_ROOT / "strategies" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"auto_gen_{timestamp}.json"

    output = {
        "strategy": strategy_def,
        "backtest_metrics": metrics,
        "factor_details": selected,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    # 同时保存为 latest
    latest_path = out_dir / "auto_gen_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    return out_path


def _compare_with_existing(metrics: dict):
    """与现有策略对比"""
    print(f"\n  与现有策略对比:")
    try:
        from pipeline.run_store import list_runs
        for strat in ["v7", "v8"]:
            runs = list_runs(strategy_id=strat, status="success", limit=1)
            if runs:
                m = runs[0].metrics or {}
                s = m.get("sharpe", 0)
                r = m.get("total_return", 0)
                diff = metrics["sharpe"] - s
                mark = ">" if diff > 0 else "<"
                print(f"    vs {strat}: 夏普 {s:.2f} ({mark} {abs(diff):.2f})")
    except Exception:
        print("    无历史回测数据可对比")
        print("    运行: python -m quant_dojo compare auto_gen v7 v8")
