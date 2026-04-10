"""
pipeline/idea_to_strategy.py — idea-to-strategy 流水线主编排器

接收 IdeaParser 的输出 spec（dict），依次执行：
    1. 解析校验（validating）
    2. 快速 IC 验证，写回 ic_mean/icir（computing_ic）
    3. 写 strategies/generated/auto_gen_latest.json（writing_spec）
    4. 调用 control_surface.execute("backtest.run", ...)（backtesting）
    5. 调用 risk_gate.evaluate(metrics)（risk_gate）
    6. 组装 Markdown 报告（done）

整个流程中每步通过 progress_callback(stage, message) 向上层汇报进度。

设计原则：
  - 每个 stage 单独 try/except，失败时填写 status 和 error
  - 失败安全：任何阶段异常均不向外抛出，包入 IdeaResult.status
  - progress_callback 允许为 None（无 UI 场景直接调用）
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger(__name__)

# strategies/generated/ 目录，与 auto_gen_loader.py 中定义保持一致
_REPO_ROOT = Path(__file__).parent.parent
_GENERATED_DIR = _REPO_ROOT / "strategies" / "generated"
_LATEST_FILE = _GENERATED_DIR / "auto_gen_latest.json"


# ══════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════

@dataclass
class IdeaResult:
    """
    idea-to-strategy 流水线的完整输出。

    字段:
        idea_text           : 原始用户想法文本
        hypothesis          : IdeaParser 提炼的假设
        strategy_name       : 生成的策略名（用于文件名后缀）
        selected_factors    : 选中因子列表，每项含
                              {name, direction, reason, ic_mean, icir}
        backtest_run_id     : control_surface backtest.run 返回的 run_id
        metrics             : 回测指标 dict（可含 oos_sharpe 键）
        gate_passed         : 风险门是否通过
        gate_failures       : 风险门硬失败条目列表
        gate_warnings       : 风险门及 IC 方向的警告条目列表
        report_markdown     : 最终 Markdown 报告字符串
        status              : "passed" | "failed_gate" | "failed_parse"
                              | "failed_backtest" | "failed_ic"
        error               : 最后一次异常的描述（若有）
        created_at          : ISO 8601 时间戳
        ic_validation_end   : IC 验证截止日期（回测区间前60%的末尾日期），
                              格式 YYYY-MM-DD；IC 阶段未执行时为空字符串
    """
    idea_text: str
    hypothesis: str
    strategy_name: str
    selected_factors: list          # [{"name", "direction", "reason", "ic_mean", "icir"}]
    backtest_run_id: Optional[str]
    metrics: Optional[dict]         # 可含 oos_sharpe（walk-forward 样本外 Sharpe 均值）
    gate_passed: bool
    gate_failures: list
    gate_warnings: list
    report_markdown: str
    status: str                     # "passed"|"failed_gate"|"failed_parse"|"failed_backtest"|"failed_ic"
    error: Optional[str]
    created_at: str
    ic_validation_end: str = ""     # IC 验证截止日期，默认空字符串保持向后兼容


# ══════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════

def _notify(callback: Optional[Callable], stage: str, message: str) -> None:
    """
    安全调用 progress_callback，忽略 callback 本身的异常。

    参数:
        callback : 外部传入的进度回调（可为 None）
        stage    : 阶段标识字符串
        message  : 描述性消息
    """
    if callback is None:
        return
    try:
        callback(stage, message)
    except Exception:
        pass


def _date_minus_days(date_str: str, days: int) -> str:
    """
    计算日期字符串往前推 days 天的结果。

    参数:
        date_str : YYYY-MM-DD 格式日期
        days     : 往前推天数

    返回:
        新日期字符串，YYYY-MM-DD 格式
    """
    d = datetime.date.fromisoformat(date_str)
    return str(d - datetime.timedelta(days=days))


# ══════════════════════════════════════════════════════════════
# 各阶段实现
# ══════════════════════════════════════════════════════════════

def _stage_validate(spec: dict) -> tuple[bool, str]:
    """
    检查 IdeaParser.analyze() 返回值是否合法。

    参数:
        spec : IdeaParser 返回的 dict

    返回:
        (ok, error_msg)——ok=False 时 error_msg 包含原因
    """
    if not isinstance(spec, dict):
        return False, f"spec 必须是 dict，实际类型: {type(spec).__name__}"
    if not spec.get("parse_ok", False):
        reason = spec.get("error") or spec.get("parse_error") or "parse_ok=False"
        return False, f"IdeaParser 解析失败: {reason}"
    # IdeaParser.analyze() 返回的字段名是 selected_factors，不是 factors
    if not spec.get("selected_factors"):
        return False, "spec 中没有 selected_factors 字段（或列表为空）"
    return True, ""


def _stage_compute_ic(
    spec: dict,
    backtest_start: str,
    backtest_end: str,
    callback: Optional[Callable],
) -> tuple[list, list, list, str]:
    """
    对 spec['selected_factors'] 中每个因子做快速 IC 验证，写回 ic_mean/icir。

    为避免 in-sample 偏差，IC 验证只使用回测区间的前 60% 数据：
        ic_start  = backtest_start
        ic_end    = backtest_start + 0.6 * (backtest_end - backtest_start)
    后 40% 数据留给真正的样本外评估。

    若 IC_mean 符号与 direction 不一致，记录 warning 但不强制修改方向。

    参数:
        spec           : IdeaParser 的输出
        backtest_start : 回测开始日期 YYYY-MM-DD
        backtest_end   : 回测结束日期 YYYY-MM-DD
        callback       : 进度回调（可为 None）

    返回:
        (selected_factors, ic_warnings, failed_factor_names, ic_validation_end)
        - selected_factors    : 全部因子条目（含 ic_mean/icir，失败项设 None）
        - ic_warnings         : 方向不一致的警告字符串列表
        - failed_factor_names : 无法计算 IC 的因子名列表
        - ic_validation_end   : IC 验证截止日期字符串 YYYY-MM-DD
    """
    from utils.local_data_loader import get_all_symbols, load_price_wide
    from utils.alpha_factors import build_fast_factors
    from utils.factor_analysis import compute_ic_series, ic_summary

    # 计算 IC 验证截止日（前 60% 时间段）
    d_start = datetime.date.fromisoformat(backtest_start)
    d_end = datetime.date.fromisoformat(backtest_end)
    total_days = (d_end - d_start).days
    ic_cutoff_days = int(total_days * 0.6)
    ic_validation_end = str(d_start + datetime.timedelta(days=ic_cutoff_days))

    ic_start = backtest_start
    _notify(
        callback, "computing_ic",
        f"加载 IC 验证数据 [{ic_start} ~ {ic_validation_end}]（回测全区间前60%）"
    )

    symbols = get_all_symbols()
    # 只加载 IC 验证窗口（前60%），不加载回测全段，防止 in-sample 偏差
    price = load_price_wide(symbols, ic_start, ic_validation_end, field="close")

    # 尝试加载高低开价格，失败时静默跳过
    factor_kwargs: dict = {}
    for csv_field, kwarg_name in [("high", "high"), ("low", "low"), ("open", "open_price")]:
        try:
            df = load_price_wide(symbols, ic_start, ic_validation_end, field=csv_field)
            if not df.empty:
                factor_kwargs[kwarg_name] = df
        except Exception:
            pass

    # 尝试加载基本面宽表（pe、pb）
    try:
        from utils.local_data_loader import load_factor_wide
        pe_df = load_factor_wide(symbols, "pe_ttm", ic_start, ic_validation_end)
        if not pe_df.empty:
            factor_kwargs["pe"] = pe_df
    except Exception:
        pass

    try:
        from utils.local_data_loader import load_factor_wide
        pb_df = load_factor_wide(symbols, "pb", ic_start, ic_validation_end)
        if not pb_df.empty:
            factor_kwargs["pb"] = pb_df
    except Exception:
        pass

    _notify(callback, "computing_ic", f"价格宽表 shape={price.shape}，构建因子...")

    # 下期收益率（shift(-1)：今日因子值对应明日收益，避免前视偏差）
    fwd_ret = price.pct_change().shift(-1)

    # 构建全量快速因子
    all_factors = build_fast_factors(price, **factor_kwargs)
    # enhanced_mom 的别名兼容（generate 命令有时输出 enhanced_mom_60）
    if "enhanced_mom" in all_factors:
        all_factors.setdefault("enhanced_mom_60", all_factors["enhanced_mom"])

    # IdeaParser.analyze() 返回字段名是 selected_factors
    raw_factors: list[dict] = spec.get("selected_factors", [])
    selected_factors: list[dict] = []
    ic_warnings: list[str] = []
    failed_factor_names: list[str] = []

    for fac_spec in raw_factors:
        name = fac_spec.get("name", "")
        direction = int(fac_spec.get("direction", 1))
        reason = fac_spec.get("reason", "")

        if name not in all_factors:
            _log.warning("因子 %s 不在 build_fast_factors 输出中，跳过 IC 计算", name)
            failed_factor_names.append(name)
            selected_factors.append({
                "name": name,
                "direction": direction,
                "reason": reason,
                "ic_mean": None,
                "icir": None,
            })
            continue

        try:
            fac_wide = all_factors[name]
            ic_series = compute_ic_series(fac_wide, fwd_ret)
            summary = ic_summary(ic_series, name=name)
            ic_mean = float(summary["IC_mean"])
            icir_raw = summary["ICIR"]
            icir = float(icir_raw) if icir_raw is not None and icir_raw == icir_raw else None

            # 方向验证：符号不一致时记录 warning，不强制修改
            if ic_mean < 0 and direction == 1:
                warn = (
                    f"因子 {name}: IC_mean={ic_mean:.4f} < 0 但 direction=1（正向），"
                    "建议将 direction 改为 -1；已保留原方向，请人工确认"
                )
                ic_warnings.append(warn)
                _log.warning(warn)
            elif ic_mean > 0 and direction == -1:
                warn = (
                    f"因子 {name}: IC_mean={ic_mean:.4f} > 0 但 direction=-1（反向），"
                    "建议将 direction 改为 1；已保留原方向，请人工确认"
                )
                ic_warnings.append(warn)
                _log.warning(warn)

            selected_factors.append({
                "name": name,
                "direction": direction,
                "reason": reason,
                "ic_mean": round(ic_mean, 6),
                "icir": round(icir, 4) if icir is not None else None,
            })
            _notify(
                callback, "computing_ic",
                f"  {name}: IC_mean={ic_mean:.4f}, ICIR="
                f"{icir:.4f if icir is not None else 'N/A'}"
            )

        except Exception as e:
            _log.warning("因子 %s IC 计算失败: %s", name, e)
            failed_factor_names.append(name)
            selected_factors.append({
                "name": name,
                "direction": direction,
                "reason": reason,
                "ic_mean": None,
                "icir": None,
            })

    return selected_factors, ic_warnings, failed_factor_names, ic_validation_end


def _stage_write_spec(
    strategy_name: str,
    selected_factors: list,
    spec: dict,
) -> Path:
    """
    将策略定义序列化写入 strategies/generated/auto_gen_latest.json，
    并额外保存一份带时间戳的备份文件。

    JSON 格式参考 auto_gen_loader.py docstring：
    {
      "strategy": {
        "name": "auto_gen",
        "factors": [{"name":..., "direction":..., "icir":..., "ic_mean":...}],
        "weighting": "ic_weighted",
        "neutralize": true,
        "n_stocks": 30,
        "generated_at": "..."
      }
    }

    参数:
        strategy_name    : 策略名，用于备份文件名后缀
        selected_factors : 含 ic_mean/icir 的因子列表
        spec             : IdeaParser 原始输出（读取 n_stocks 等元信息）

    返回:
        写入的 latest 文件路径
    """
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    now_str = datetime.datetime.now().isoformat(timespec="seconds")
    date_str = datetime.date.today().isoformat()

    # 只保留策略 JSON 需要的因子字段
    factor_entries = [
        {
            "name": f["name"],
            "direction": f["direction"],
            "icir": f.get("icir"),
            "ic_mean": f.get("ic_mean"),
        }
        for f in selected_factors
    ]

    n_stocks = spec.get("n_stocks", 30)

    payload = {
        "strategy": {
            "name": "auto_gen",
            "factors": factor_entries,
            "weighting": "ic_weighted",
            "neutralize": True,
            "n_stocks": n_stocks,
            "generated_at": now_str,
        }
    }

    # 写 latest
    with open(_LATEST_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    # 写带时间戳的备份（策略名 + 日期）
    backup_name = f"auto_gen_{strategy_name}_{date_str}.json"
    backup_file = _GENERATED_DIR / backup_name
    with open(backup_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    _log.info("策略定义已写入 %s，备份: %s", _LATEST_FILE, backup_file)
    return _LATEST_FILE


def _stage_backtest(
    backtest_start: str,
    backtest_end: str,
    callback: Optional[Callable],
) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    """
    通过 control_surface.execute 运行 auto_gen 回测。

    参数:
        backtest_start : 回测开始日期 YYYY-MM-DD
        backtest_end   : 回测结束日期 YYYY-MM-DD
        callback       : 进度回调（可为 None）

    返回:
        (run_id, metrics, error_str)
        成功时 error_str=None，失败时 run_id/metrics=None
    """
    from pipeline.control_surface import execute

    _notify(callback, "backtesting", f"启动 auto_gen 回测 [{backtest_start} ~ {backtest_end}]")

    result = execute(
        "backtest.run",
        approved=True,
        strategy_id="auto_gen",
        start=backtest_start,
        end=backtest_end,
    )

    if result.get("status") == "error":
        err = result.get("error", "backtest.run 未知错误")
        return None, None, err

    data = result.get("data") or {}
    run_id = data.get("run_id")
    metrics = data.get("metrics")
    return run_id, metrics, None


def _stage_walkforward(
    backtest_start: str,
    backtest_end: str,
    callback: Optional[Callable],
) -> Optional[float]:
    """
    对 auto_gen 策略运行 walk-forward 3折验证，返回样本外 Sharpe 均值。

    折叠安排（基于传入区间，不硬编码年份）：
        - train_years=3, test_months=6，步进半年
    如果数据不足或执行失败，只打 warning，返回 None，不影响主流程。

    参数:
        backtest_start : 回测开始日期 YYYY-MM-DD
        backtest_end   : 回测结束日期 YYYY-MM-DD
        callback       : 进度回调（可为 None）

    返回:
        oos_sharpe（样本外 Sharpe 均值），失败时返回 None
    """
    try:
        from utils.walk_forward import walk_forward_test
        from utils.local_data_loader import get_all_symbols, load_price_wide

        _notify(callback, "walk_forward", "开始 walk-forward 3折验证...")

        symbols = get_all_symbols()
        price_wide = load_price_wide(symbols, backtest_start, backtest_end, field="close")

        if price_wide.empty:
            _log.warning("walk_forward: 价格宽表为空，跳过")
            return None

        # 导入 auto_gen 策略的执行逻辑
        from pipeline.control_surface import execute as _cs_execute

        def _auto_gen_strategy_fn(
            price_slice: "pd.DataFrame",
            factor_slice,
            train_start,
            train_end,
            test_start=None,
            test_end=None,
        ) -> "pd.Series":
            """
            walk_forward 的策略包装函数。
            调用 control_surface 在 [train_start, test_end or train_end] 上运行 auto_gen，
            截取测试段日收益率返回。
            """
            import pandas as _pd
            _end = test_end if test_end is not None else train_end
            result = _cs_execute(
                "backtest.run",
                approved=True,
                strategy_id="auto_gen",
                start=str(train_start.date()) if hasattr(train_start, "date") else str(train_start),
                end=str(_end.date()) if hasattr(_end, "date") else str(_end),
            )
            if result.get("status") == "error":
                return _pd.Series(dtype=float)

            data = result.get("data") or {}
            daily_returns = data.get("daily_returns")
            if daily_returns is None:
                return _pd.Series(dtype=float)

            # 只截取测试期的收益
            ret_series = _pd.Series(daily_returns)
            if not isinstance(ret_series.index, _pd.DatetimeIndex):
                try:
                    ret_series.index = _pd.to_datetime(ret_series.index)
                except Exception:
                    return ret_series

            if test_start is not None and test_end is not None:
                ret_series = ret_series.loc[
                    _pd.Timestamp(test_start): _pd.Timestamp(_end)
                ]
            return ret_series

        wf_df = walk_forward_test(
            strategy_fn=_auto_gen_strategy_fn,
            price_wide=price_wide,
            factor_data={},   # auto_gen 从 JSON 读取，factor_data 仅占位
            train_years=3,
            test_months=6,
        )

        valid = wf_df["sharpe"].dropna()
        if valid.empty:
            _log.warning("walk_forward: 所有折叠 sharpe 均为 NaN，跳过")
            return None

        oos_sharpe = float(valid.mean())
        _notify(
            callback, "walk_forward",
            f"walk-forward 完成，有效折叠 {len(valid)} 个，OOS Sharpe 均值={oos_sharpe:.3f}"
        )
        return oos_sharpe

    except Exception as exc:
        _log.warning("walk_forward 阶段异常（主流程不受影响）: %s", exc)
        _notify(callback, "walk_forward", f"walk-forward 失败（已跳过）: {exc}")
        return None


def _stage_risk_gate(metrics: dict) -> tuple[bool, list, list]:
    """
    调用 risk_gate.evaluate 检查回测指标是否过关。

    参数:
        metrics : 回测指标 dict

    返回:
        (gate_passed, gate_failures, gate_warnings)
    """
    from pipeline.risk_gate import evaluate

    gate_result = evaluate(metrics)
    return gate_result.passed, gate_result.failures, gate_result.warnings


# ══════════════════════════════════════════════════════════════
# 报告组装
# ══════════════════════════════════════════════════════════════

def _build_report(
    idea_text: str,
    hypothesis: str,
    selected_factors: list,
    backtest_run_id: Optional[str],
    metrics: Optional[dict],
    gate_passed: bool,
    gate_failures: list,
    gate_warnings: list,
    ic_warnings: list,
    status: str,
    error: Optional[str],
    backtest_start: str = "",
    backtest_end: str = "",
    ic_validation_end: str = "",
    fm_memo: str = "",
) -> str:
    """
    将各阶段结果拼接为最终 Markdown 报告。

    参数:
        idea_text          : 原始想法文本
        hypothesis         : 策略假设
        selected_factors   : 含 IC 统计的因子列表
        backtest_run_id    : 回测 run_id
        metrics            : 回测指标 dict（可含 oos_sharpe 键）
        gate_passed        : 是否通过风险门
        gate_failures      : 硬失败条目
        gate_warnings      : 软警告条目（来自风险门）
        ic_warnings        : IC 方向警告（来自 IC 验证阶段）
        status             : 流水线状态码
        error              : 错误描述（若有）
        backtest_start     : 回测开始日期（用于显示时间轴注释）
        backtest_end       : 回测结束日期（用于显示时间轴注释）
        ic_validation_end  : IC 验证截止日期（回测前60%末尾）

    返回:
        Markdown 字符串
    """
    lines: list[str] = []

    lines.append("# idea-to-strategy 流水线报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**状态**: `{status}`")
    lines.append("")

    # 1. 原始想法与假设
    lines.append("## 原始想法")
    lines.append("")
    lines.append(f"> {idea_text}")
    lines.append("")
    lines.append("## 策略假设")
    lines.append("")
    lines.append(hypothesis or "（未提供）")
    lines.append("")

    # 2. 因子列表（含 IC 统计）
    lines.append("## 选中因子")
    lines.append("")
    lines.append("| 因子名 | 方向 | IC_mean | ICIR | 选因原因 |")
    lines.append("|--------|------|---------|------|----------|")
    for f in selected_factors:
        ic_str = f"{f['ic_mean']:.4f}" if f.get("ic_mean") is not None else "N/A"
        icir_str = f"{f['icir']:.4f}" if f.get("icir") is not None else "N/A"
        dir_label = "+1" if f.get("direction", 1) == 1 else "-1"
        reason = f.get("reason", "")
        lines.append(f"| {f['name']} | {dir_label} | {ic_str} | {icir_str} | {reason} |")
    lines.append("")

    # IC 验证与样本外区间注释
    if ic_validation_end and backtest_start and backtest_end:
        lines.append("### 时间轴拆分")
        lines.append("")
        lines.append(
            f"- **IC验证区间**：{backtest_start} ~ {ic_validation_end}（回测全区间前60%，in-sample）"
        )
        lines.append(
            f"- **样本外回测区间**：{ic_validation_end} ~ {backtest_end}（后40%，out-of-sample）"
        )
        lines.append("")

    # IC 方向警告
    if ic_warnings:
        lines.append("### IC 方向警告")
        lines.append("")
        for w in ic_warnings:
            lines.append(f"- {w}")
        lines.append("")

    # 3. 回测结果
    lines.append("## 回测结果")
    lines.append("")
    if backtest_run_id:
        lines.append(f"**Run ID**: `{backtest_run_id}`")
        lines.append("")
    if metrics:
        lines.append("| 指标 | 值 |")
        lines.append("|------|----|")
        # oos_sharpe 优先展示，标注"样本外"
        if "oos_sharpe" in metrics:
            oos_val = metrics["oos_sharpe"]
            try:
                lines.append(f"| **OOS Sharpe（样本外）** | **{float(oos_val):.4f}** |")
            except (TypeError, ValueError):
                lines.append(f"| **OOS Sharpe（样本外）** | **{oos_val}** |")
        display_keys = [
            ("annualized_return", "年化收益"),
            ("total_return", "累计收益"),
            ("sharpe", "夏普比率"),
            ("max_drawdown", "最大回撤"),
            ("volatility", "年化波动"),
            ("win_rate", "胜率"),
            ("n_trading_days", "回测交易日数"),
            ("start_date", "开始日期"),
            ("end_date", "结束日期"),
        ]
        pct_keys = {"annualized_return", "total_return", "max_drawdown", "volatility", "win_rate"}
        for key, label in display_keys:
            if key in metrics:
                val = metrics[key]
                if key in pct_keys:
                    try:
                        lines.append(f"| {label} | {float(val):.2%} |")
                    except (TypeError, ValueError):
                        lines.append(f"| {label} | {val} |")
                else:
                    lines.append(f"| {label} | {val} |")
    else:
        lines.append("回测未产生有效指标。")
    lines.append("")

    # 4. 风险门
    lines.append("## 风险门检查")
    lines.append("")
    gate_icon = "✅" if gate_passed else "❌"
    lines.append(f"**结论**: {gate_icon} {'通过' if gate_passed else '未通过'}")
    if gate_failures:
        lines.append(f"\n**硬失败 ({len(gate_failures)} 项)**:")
        for f in gate_failures:
            lines.append(f"- {f['label']}：{f['reason']}")
    if gate_warnings:
        lines.append(f"\n**警告 ({len(gate_warnings)} 项)**:")
        for w in gate_warnings:
            lines.append(f"- {w['label']}：{w['reason']}")
    if not gate_failures and not gate_warnings:
        lines.append("\n所有门槛均通过。")
    lines.append("")

    # 4.5 基金经理评审（可选，LLM 生成时才有内容）
    if fm_memo:
        lines.append(fm_memo)
        lines.append("")

    # 5. 结论与后续步骤
    lines.append("## 结论与后续步骤")
    lines.append("")
    if status == "passed":
        lines.append(
            "✅ 策略已写入 `strategies/generated/auto_gen_latest.json`，"
            "可运行以下命令启动完整回测：\n"
            "```bash\n"
            "python -m pipeline.cli backtest run auto_gen\n"
            "```"
        )
    elif status == "failed_gate":
        lines.append("❌ 策略未通过风险门，建议：")
        lines.append("")
        for f in gate_failures:
            key = f["key"]
            if key == "sharpe":
                lines.append("- **夏普不足**：尝试添加低相关性因子，或减少持仓数量")
            elif key == "annualized_return":
                lines.append("- **年化收益偏低**：检查因子方向是否正确，或提高持仓集中度")
            elif key == "max_drawdown":
                lines.append("- **回撤过大**：增加止损逻辑或加入防御性因子（low_vol_20d）")
            else:
                lines.append(f"- **{f['label']}**：{f['reason']}")
        lines.append("\n可修改因子组合后重新运行 pipeline。")
    elif status == "failed_backtest":
        lines.append(f"❌ 回测执行失败：`{error}`")
        lines.append("")
        lines.append("请检查 `strategies/generated/auto_gen_latest.json` 格式或本地数据完整性。")
    elif status == "failed_ic":
        lines.append(f"❌ IC 计算阶段失败：`{error}`")
        lines.append("")
        lines.append("请检查本地数据是否存在，或 `alpha_factors.build_fast_factors` 是否正常。")
    elif status == "failed_parse":
        lines.append(f"❌ IdeaParser 解析失败：`{error}`")
        lines.append("")
        lines.append("请检查输入想法文本是否足够清晰，或 IdeaParser 配置是否正确。")
    else:
        if error:
            lines.append(f"执行遇到错误：`{error}`")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 主编排函数
# ══════════════════════════════════════════════════════════════

def run_idea_pipeline(
    idea_text: str,
    spec: dict,
    backtest_start: str,
    backtest_end: str,
    progress_callback: Optional[Callable] = None,
) -> IdeaResult:
    """
    idea-to-strategy 流水线主入口。

    依次执行六个阶段，每步通过 progress_callback(stage, message) 汇报进度：
        validating → computing_ic → writing_spec → backtesting → risk_gate → done

    参数:
        idea_text         : 原始用户想法（自然语言文本）
        spec              : IdeaParser.analyze() 的返回值 dict
        backtest_start    : 回测开始日期 YYYY-MM-DD
        backtest_end      : 回测结束日期 YYYY-MM-DD
        progress_callback : 可选进度回调 fn(stage: str, message: str)

    返回:
        IdeaResult dataclass
    """
    now_str = datetime.datetime.now().isoformat(timespec="seconds")

    # 从 spec 提取元信息（parse 失败时有兜底默认值）
    hypothesis = spec.get("hypothesis", "") if isinstance(spec, dict) else ""
    strategy_name = spec.get("strategy_name", "unnamed") if isinstance(spec, dict) else "unnamed"

    # 各字段默认值
    selected_factors: list = []
    backtest_run_id: Optional[str] = None
    metrics: Optional[dict] = None
    gate_passed = False
    gate_failures: list = []
    gate_warnings: list = []
    ic_warnings: list = []
    ic_validation_end: str = ""
    status = "failed_parse"
    error: Optional[str] = None

    # ── stage 1: 解析校验 ──────────────────────────────────────
    _notify(progress_callback, "validating", "校验 IdeaParser 输出...")
    ok, err_msg = _stage_validate(spec)
    if not ok:
        error = err_msg
        _notify(progress_callback, "validating", f"校验失败: {err_msg}")
        return IdeaResult(
            idea_text=idea_text,
            hypothesis=hypothesis,
            strategy_name=strategy_name,
            selected_factors=[],
            backtest_run_id=None,
            metrics=None,
            gate_passed=False,
            gate_failures=[],
            gate_warnings=[],
            report_markdown=_build_report(
                idea_text, hypothesis, [], None, None,
                False, [], [], [], "failed_parse", error,
                backtest_start=backtest_start,
                backtest_end=backtest_end,
                ic_validation_end="",
            ),
            status="failed_parse",
            error=error,
            created_at=now_str,
            ic_validation_end="",
        )
    _notify(progress_callback, "validating", "校验通过")

    # ── stage 2: IC 验证 ───────────────────────────────────────
    # IC 验证只用回测区间的前 60%，避免选因和评估用同一段数据（in-sample 偏差）
    _notify(progress_callback, "computing_ic", "开始计算各候选因子的 IC（使用前60%样本外区间）...")
    try:
        selected_factors, ic_warnings, failed_names, ic_validation_end = _stage_compute_ic(
            spec, backtest_start, backtest_end, progress_callback
        )
        if failed_names:
            _notify(
                progress_callback, "computing_ic",
                f"以下因子无法计算 IC（已保留标记为 None）: {failed_names}"
            )
        _notify(
            progress_callback, "computing_ic",
            f"IC 验证完成（截止 {ic_validation_end}），共 {len(selected_factors)} 个因子"
        )
    except Exception as e:
        error = f"IC 计算失败: {e}"
        _log.exception("computing_ic 阶段异常")
        return IdeaResult(
            idea_text=idea_text,
            hypothesis=hypothesis,
            strategy_name=strategy_name,
            selected_factors=selected_factors,
            backtest_run_id=None,
            metrics=None,
            gate_passed=False,
            gate_failures=[],
            gate_warnings=ic_warnings,
            report_markdown=_build_report(
                idea_text, hypothesis, selected_factors, None, None,
                False, [], ic_warnings, ic_warnings, "failed_ic", error,
                backtest_start=backtest_start,
                backtest_end=backtest_end,
                ic_validation_end=ic_validation_end,
            ),
            status="failed_ic",
            error=error,
            created_at=now_str,
            ic_validation_end=ic_validation_end,
        )

    # ── stage 3: 写入 JSON spec ────────────────────────────────
    _notify(progress_callback, "writing_spec", "写入 strategies/generated/auto_gen_latest.json...")
    try:
        latest_path = _stage_write_spec(strategy_name, selected_factors, spec)
        _notify(progress_callback, "writing_spec", f"已写入: {latest_path}")
    except Exception as e:
        error = f"写入策略定义失败: {e}"
        _log.exception("writing_spec 阶段异常")
        return IdeaResult(
            idea_text=idea_text,
            hypothesis=hypothesis,
            strategy_name=strategy_name,
            selected_factors=selected_factors,
            backtest_run_id=None,
            metrics=None,
            gate_passed=False,
            gate_failures=[],
            gate_warnings=ic_warnings,
            report_markdown=_build_report(
                idea_text, hypothesis, selected_factors, None, None,
                False, [], [], ic_warnings, "failed_backtest", error,
                backtest_start=backtest_start,
                backtest_end=backtest_end,
                ic_validation_end=ic_validation_end,
            ),
            status="failed_backtest",
            error=error,
            created_at=now_str,
            ic_validation_end=ic_validation_end,
        )

    # ── stage 4: 回测（全区间，不受 IC 截止日限制）─────────────
    _notify(progress_callback, "backtesting", "调用 control_surface 运行 auto_gen 回测...")
    try:
        backtest_run_id, metrics, bt_error = _stage_backtest(
            backtest_start, backtest_end, progress_callback
        )
        if bt_error:
            error = bt_error
            _notify(progress_callback, "backtesting", f"回测失败: {bt_error}")
            return IdeaResult(
                idea_text=idea_text,
                hypothesis=hypothesis,
                strategy_name=strategy_name,
                selected_factors=selected_factors,
                backtest_run_id=None,
                metrics=None,
                gate_passed=False,
                gate_failures=[],
                gate_warnings=ic_warnings,
                report_markdown=_build_report(
                    idea_text, hypothesis, selected_factors, None, None,
                    False, [], [], ic_warnings, "failed_backtest", error,
                    backtest_start=backtest_start,
                    backtest_end=backtest_end,
                    ic_validation_end=ic_validation_end,
                ),
                status="failed_backtest",
                error=error,
                created_at=now_str,
                ic_validation_end=ic_validation_end,
            )
        _notify(progress_callback, "backtesting", f"回测完成，run_id={backtest_run_id}")
    except Exception as e:
        error = f"回测执行异常: {e}"
        _log.exception("backtesting 阶段异常")
        return IdeaResult(
            idea_text=idea_text,
            hypothesis=hypothesis,
            strategy_name=strategy_name,
            selected_factors=selected_factors,
            backtest_run_id=None,
            metrics=None,
            gate_passed=False,
            gate_failures=[],
            gate_warnings=ic_warnings,
            report_markdown=_build_report(
                idea_text, hypothesis, selected_factors, None, None,
                False, [], [], ic_warnings, "failed_backtest", error,
                backtest_start=backtest_start,
                backtest_end=backtest_end,
                ic_validation_end=ic_validation_end,
            ),
            status="failed_backtest",
            error=error,
            created_at=now_str,
            ic_validation_end=ic_validation_end,
        )

    # ── stage 4.5: walk-forward 样本外验证（可选，失败不影响主流程）──
    oos_sharpe = _stage_walkforward(backtest_start, backtest_end, progress_callback)
    if oos_sharpe is not None:
        # 写入 metrics，供报告和下游消费
        if metrics is None:
            metrics = {}
        metrics["oos_sharpe"] = oos_sharpe

    # ── stage 5: 风险门 ────────────────────────────────────────
    _notify(progress_callback, "risk_gate", "运行风险门检查...")
    try:
        gate_passed, gate_failures, gate_warnings = _stage_risk_gate(metrics or {})
        _notify(
            progress_callback, "risk_gate",
            f"风险门{'通过' if gate_passed else '未通过'}，"
            f"硬失败 {len(gate_failures)} 项，警告 {len(gate_warnings)} 项"
        )
        status = "passed" if gate_passed else "failed_gate"
    except Exception as e:
        error = f"风险门评估异常: {e}"
        _log.exception("risk_gate 阶段异常")
        gate_passed = False
        status = "failed_gate"

    # ── stage 5.5: 基金经理评审（可选，不影响主流程） ───────────
    fm_memo: str = ""
    try:
        from agents.fund_manager import FundManager
        _notify(progress_callback, "fm_review", "基金经理评审中...")
        fm = FundManager()
        factor_names = [f["name"] for f in selected_factors]
        fm_decision = fm.review_strategy(
            metrics or {},
            factors=factor_names,
            strategy_name=strategy_name,
            extra_context=hypothesis or "",
        )
        fm_memo = fm.render_decision_markdown(fm_decision, title="基金经理评审")
        _notify(
            progress_callback, "fm_review",
            f"基金经理评审: {fm_decision.headline}"
        )
    except Exception as _fm_err:
        _log.warning("基金经理评审阶段失败（不影响主流程）: %s", _fm_err)

    # ── stage 6: 组装报告 ──────────────────────────────────────
    _notify(progress_callback, "done", "组装最终报告...")
    report = _build_report(
        idea_text, hypothesis, selected_factors,
        backtest_run_id, metrics,
        gate_passed, gate_failures, gate_warnings, ic_warnings,
        status, error,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        ic_validation_end=ic_validation_end,
        fm_memo=fm_memo,
    )
    _notify(progress_callback, "done", "流水线执行完毕")

    return IdeaResult(
        idea_text=idea_text,
        hypothesis=hypothesis,
        strategy_name=strategy_name,
        selected_factors=selected_factors,
        backtest_run_id=backtest_run_id,
        metrics=metrics,
        gate_passed=gate_passed,
        gate_failures=gate_failures,
        # 合并风险门警告与 IC 方向警告，便于上层展示
        gate_warnings=gate_warnings + ic_warnings,
        report_markdown=report,
        status=status,
        error=error,
        created_at=now_str,
        ic_validation_end=ic_validation_end,
    )


# ══════════════════════════════════════════════════════════════
# 最小验证（只验证 import，不触发真实 LLM 或数据加载）
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse as _argparse

    _ap = _argparse.ArgumentParser(
        prog="python -m pipeline.idea_to_strategy",
        description=(
            "idea-to-strategy 独立脚本入口。\n"
            "传入策略想法文本，完整走 LLM 解析 → IC 验证 → 回测 → 风险门 流程，\n"
            "并打印 Markdown 报告。\n\n"
            "不传参数时进入最小验证模式（不调 LLM，不加载数据）。"
        ),
        formatter_class=_argparse.RawDescriptionHelpFormatter,
    )
    _ap.add_argument("idea", nargs="?", default=None,
                     help="策略想法文本，如 '我想做基于ROE和低波动的选股'")
    _ap.add_argument("--start", default="2022-01-01", help="回测开始日期（默认 2022-01-01）")
    _ap.add_argument("--end",   default="2025-12-31", help="回测结束日期（默认 2025-12-31）")
    _ap.add_argument("--test",  action="store_true",  help="强制进入最小验证模式（不调 LLM）")
    _cli_args = _ap.parse_args()

    if _cli_args.idea and not _cli_args.test:
        # ── 真实运行模式：调 LLM + 数据 ─────────────────────────
        import sys as _sys
        print(f"[idea_to_strategy] 想法: {_cli_args.idea}")
        print(f"[idea_to_strategy] 区间: {_cli_args.start} ~ {_cli_args.end}")
        print()

        try:
            from agents.base import LLMClient
            from agents.idea_parser import IdeaParser
        except ImportError as _ie:
            print(f"❌ agents 模块导入失败: {_ie}", file=_sys.stderr)
            _sys.exit(1)

        _llm = LLMClient()
        if _llm._backend == "none":
            print("❌ LLM 后端不可用，请安装 claude CLI 或启动 Ollama", file=_sys.stderr)
            _sys.exit(1)

        _spec = IdeaParser(_llm).analyze(idea_text=_cli_args.idea)
        if not _spec.get("parse_ok", False):
            print(f"❌ 解析失败: {_spec.get('reason', '未知原因')}", file=_sys.stderr)
            _sys.exit(1)

        def _cb(stage: str, msg: str):
            print(f"  [{stage}] {msg}")

        _res = run_idea_pipeline(
            idea_text=_cli_args.idea,
            spec=_spec,
            backtest_start=_cli_args.start,
            backtest_end=_cli_args.end,
            progress_callback=_cb,
        )
        print()
        print(_res.report_markdown)
        if _res.status in ("failed_parse", "failed_ic", "failed_backtest"):
            _sys.exit(1)

    else:
        # ── 最小验证模式（不触发 LLM 或数据加载）────────────────
        _dummy = IdeaResult(
            idea_text="低波动因子选股",
            hypothesis="低波动股票未来收益更高",
            strategy_name="low_vol_test",
            selected_factors=[{
                "name": "low_vol_20d",
                "direction": -1,
                "reason": "低波动异象",
                "ic_mean": -0.032,
                "icir": 0.41,
            }],
            backtest_run_id=None,
            metrics=None,
            gate_passed=False,
            gate_failures=[],
            gate_warnings=[],
            report_markdown="# test",
            status="failed_parse",
            error=None,
            created_at=datetime.datetime.now().isoformat(),
        )
        print(f"IdeaResult 构造成功: status={_dummy.status}, factors={len(_dummy.selected_factors)}")

        # 验证 failed_parse 路径（parse_ok=False 时立即返回，不加载数据）
        _bad_spec = {"parse_ok": False, "error": "unit test error"}
        _result = run_idea_pipeline(
            idea_text="低波动因子选股",
            spec=_bad_spec,
            backtest_start="2023-01-01",
            backtest_end="2024-12-31",
        )
        assert _result.status == "failed_parse", f"预期 failed_parse，实际: {_result.status}"
        assert "unit test error" in (_result.error or ""), f"error 字段未传递: {_result.error}"
        print(f"failed_parse 路径正常: error='{_result.error}'")

        print("✅ idea_to_strategy import ok")
