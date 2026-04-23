# 因子研究 Template

## 目的

沉淀 Issue #33/#35/#36 这一轮研究流程, 标准化因子开发.
新因子只需要写 `factor.py` 里的 `compute_<name>()`, 其他 (IC/分层/中性化/cost/DSR/monitoring)
全部通过 `scripts/run_factor_evaluation.py <module>` 一键跑.

## 标准接口

### factor.py 必须实现

```python
def compute_<name>(start: str, end: str, **kwargs) -> pd.DataFrame:
    """
    返回 wide factor panel.

    Index:   pd.DatetimeIndex (每个交易日)
    Columns: ts_code 列表 (带 .SZ/.SH/.BJ 后缀)
    Values:  float, 因子分数 (NaN = 当日该股无因子值)

    要求:
        - 信号必须在交易日尾部发布前可用 (若依赖盘中数据, 自行 shift(1) 或在 runner 里开 shift)
        - 不能包含未来函数 (用 T 日的 T+1~T+N 收益构造因子)
        - universe 可以自行缩减 (事件驱动 factor 可能只有 ~100 股有值)
    """
```

### factor.py 推荐实现

- Module-level constants: `ROOT` (Path), 数据路径常量
- `load_<name>_raw(start, end) -> pd.DataFrame` 加载原始长表 (可选)
- `if __name__ == "__main__":` 最小验证, 打印 shape/分位/Top10

### 目录结构

```
research/factors/<name>/
  factor.py             # 必须: compute_<name>()
  README.md             # 研究结论 (模仿 retail_inst_divergence/README.md)
  evaluate_<name>.py    # 可选: 自定义评估 (如果 runner 不够用)
  logs/                 # 可选: 本地 artifacts (一般写到 ROOT/logs/)
```

## Runner 一键跑评估

```bash
# 跑标准 IC + 分层 + 分段 + size/industry 中性化
python scripts/run_factor_evaluation.py \
    research.factors.<name>.factor \
    --compute-fn compute_<name> \
    --start 2023-10-01 --end 2025-12-31 \
    --neutralize size,industry \
    --sign auto \
    --fwd 20

# 输出:
#   logs/<name>_eval_YYYYMMDD.json
#   journal/<name>_eval_YYYYMMDD.md
```

参数:
- `--neutralize` 逗号分隔: `none` / `size` / `industry` / `size,industry`
- `--sign auto` = 按 Pearson IC 符号自动判负/正向因子; `--sign neg` 强制负向
- `--fwd 20` = forward return 窗口 (连板 / 事件类短因子改成 5)
- `--sample-cadence 5` = IC 采样间隔 (默认每 5 日, 对应周频)

## 在 rx_factor_monitor 注册

评估通过后 (IC healthy/degraded), 加到 `pipeline/rx_factor_monitor.py::RX_REGISTRY`:

```python
def _build_<name>(start, end):
    from research.factors.<name>.factor import compute_<name>
    return compute_<name>(start, end)

RX_REGISTRY.append(FactorSpec(
    name="<NAME>",
    display="<一句话描述>",
    build_fn=_build_<name>,
    sign=-1,  # -1: 值越小越看好; +1: 值越大
    fwd_days=20,
    earliest_start="2023-10-01",
    tags=["<category>", "<subtype>"],
    notes="<研究发现简述>",
))
```

未来每周跑 monitor 时会自动包含.

## 红线 (来自 CLAUDE.md + Issue #33/35/36 教训)

1. **不在 compute_<name> 里 do data snooping** — 参数必须 pre-reg, 不基于后面 IC 结果回调
2. **不在 factor.py 里做 size/industry 中性化** — 留给 runner (便于对比 raw vs neutral)
3. **最小验证 if __name__** 必须跑通, 保证 2025 Q1 数据有有效输出
4. **融券/tradable 约束在 runner / evaluate 里加**, 不在 factor.py 层面硬过滤
5. **注释用中文, 函数名/变量英文 snake_case**
6. **每个因子 README 末尾写研究结论** (success/failure/pending), 不修饰

## 参考 (这一轮已做的因子)

标准实现范本:
- `research/factors/retail_inst_divergence/factor.py` (最 complete, RIAD)
- `research/factors/moneyflow_divergence/factor.py` (MFD, 简洁)

评估范本:
- `research/factors/retail_inst_divergence/evaluate_riad.py` (周采样 IC)
- `research/factors/limit_up_ladder/evaluate_lulr.py` (事件驱动 5 日持有)

中性化范本:
- `research/factors/retail_inst_divergence/neutralize_eval.py` (size)
- `research/factors/retail_inst_divergence/industry_eval.py` (SW1 industry)
