# Tier 1 Decisions

## 2026-03-22 — notebooks 11 & 12

### 1. utils.local_data_loader → utils.data_loader
**Context:** Task spec says `utils.local_data_loader (file exists)` but no such file exists in the repo. The existing data loading module is `utils.data_loader` with `load_price_matrix`, `get_index_history`, etc.
**Decision:** Import from `utils.data_loader` instead. Notebooks use a `try/except` wrapper so they degrade gracefully to synthetic data if local cache is absent.

### 2. Factor construction for stress test / report
**Context:** No pre-built factor DataFrames exist at notebook runtime. Task asks to use `strategies.multi_factor.MultiFactorStrategy`.
**Decision:** Notebooks construct a minimal momentum factor (12-1 month price momentum) and a mean-reversion factor (1-month reversal) from the price data as illustrative inputs. This matches the strategy's expected `factors: dict` of `{name: (wide_df, direction)}`.

### 3. HS300 benchmark symbol
**Decision:** Use `sh000300` (default in `get_index_history`) as the HS300 benchmark.

### 4. Synthetic data fallback
**Decision:** When real data is unavailable (no local cache), notebooks generate synthetic price data with realistic GBM properties (drift 8% ann., vol 25% ann.) so the notebook still runs end-to-end.

### 5. Walk-forward strategy_fn signature
**Context:** `walk_forward_test` expects `strategy_fn(price_wide, factor_data_slice, train_start, train_end) -> returns_series`. The notebook wraps `MultiFactorStrategy` in a closure.

- [2026-03-22 23:32] 行业集中度检查：当前无 sector 映射数据，跳过该检查项。待接入行业分类数据后启用（参考 utils/fundamental_loader.py）

- [2026-03-22 23:41] 行业集中度检查：当前无 sector 映射数据，跳过该检查项。待接入行业分类数据后启用（参考 utils/fundamental_loader.py）

- [2026-03-22 23:50] 行业集中度检查：当前无 sector 映射数据，跳过该检查项。待接入行业分类数据后启用（参考 utils/fundamental_loader.py）

- [2026-03-23 00:10] 行业集中度检查：当前无 sector 映射数据，跳过该检查项。待接入行业分类数据后启用（参考 utils/fundamental_loader.py）
