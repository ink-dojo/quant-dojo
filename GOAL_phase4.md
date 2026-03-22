# GOAL — quant-dojo Phase 4 策略打磨

> 给 /autoloop 的目标文件。当前日期：2026-03-22

---

## 背景

**已完成：**
- Phase 0-3 全部完成
- 因子库：动量 / 价值（EP/BP/SP）/ 质量（ROE/毛利率）/ 低波动（Beta/Vol）
- 工具：IC/ICIR、分层回测、因子衰减、多因子合成、行业中性化
- agents：LLMClient、BullBearDebate、StockAnalyst

**新增数据源（本次最重要）：**
- 路径：`/Users/karan/Desktop/20260320/`
- 格式：`{sh|sz}.{代码}.csv`，共 5477 只股票
- 列名：`交易所行情日期, 证券代码, 开盘价, 最高价, 最低价, 收盘价, 前收盘价, 成交量, 成交额, 复权状态, 换手率, 交易状态, 涨跌幅, 滚动市盈率, 市净率, 滚动市销率, 滚动市现率, 是否ST`
- 时间跨度：1999 至 2026-03-20
- 已做前复权（复权状态=1/3均可直接用收盘价）

**股票代码格式转换规则：**
- 文件名 `sh.600000.csv` → 代码 `600000`（去掉前缀和点）
- 文件名 `sz.000001.csv` → 代码 `000001`

---

## 理想终态

### 1. 新增本地 CSV 数据加载器 `utils/local_data_loader.py`

实现以下函数：

```python
LOCAL_DATA_DIR = Path("/Users/karan/Desktop/20260320")

def load_local_stock(symbol: str) -> pd.DataFrame:
    """
    加载单只股票的本地 CSV 数据

    参数:
        symbol: 股票代码，如 "600000" 或 "000001"

    返回:
        标准化 DataFrame，列：date(index), open, high, low, close,
        volume, amount, turnover, pe_ttm, pb, ps_ttm, pcf, is_st, pct_change
        date 列为 DatetimeIndex，升序排列
    """

def load_price_wide(
    symbols: list,
    start: str = "2015-01-01",
    end: str = "2026-03-20",
    field: str = "close",
) -> pd.DataFrame:
    """
    批量加载多只股票，返回宽表（date × symbol）

    参数:
        symbols: 股票代码列表
        start/end: 日期范围
        field: 取哪列（close/open/volume 等）

    返回:
        宽表 DataFrame，index=date，columns=symbol
    """

def load_factor_wide(
    symbols: list,
    factor: str,
    start: str = "2015-01-01",
    end: str = "2026-03-20",
) -> pd.DataFrame:
    """
    直接从本地 CSV 加载估值因子宽表

    参数:
        factor: "pe_ttm" / "pb" / "ps_ttm" / "pcf" / "turnover"

    返回:
        宽表 DataFrame（date × symbol）
    """

def get_all_symbols() -> list:
    """返回本地数据目录下所有股票代码列表"""

def get_hs300_symbols() -> list:
    """返回沪深300成分股代码列表（从本地文件中筛选，或用akshare拉取）"""
```

列名映射（中文→英文）：
```python
COLUMN_MAP = {
    "交易所行情日期": "date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "prev_close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "涨跌幅": "pct_change",
    "滚动市盈率": "pe_ttm",
    "市净率": "pb",
    "滚动市销率": "ps_ttm",
    "滚动市现率": "pcf",
    "是否ST": "is_st",
}
```

**性能要求：**
- `load_price_wide(500只股票)` 在 60 秒内完成（用 ThreadPoolExecutor 并行读取）
- 带 parquet 缓存：第一次读 CSV，之后读缓存（缓存路径 `data/cache/local/`）

---

### 2. 更新 `utils/__init__.py`

暴露 `load_local_stock`, `load_price_wide`, `load_factor_wide`, `get_all_symbols`

---

### 3. 用真实数据验证 Phase 3 因子 `research/notebooks/09_factor_validation.ipynb`

用本地 5477 只股票真实数据跑一遍所有因子的验证：

**Section 1：数据准备**
```python
# 用沪深300或中证500成分股（约300-500只）
# 时间范围：2015-01-01 至 2024-12-31（留2025作为样本外）
symbols = get_hs300_symbols()
price_wide = load_price_wide(symbols, "2015-01-01", "2024-12-31")
ret_wide = price_wide.pct_change()
```

**Section 2：各因子 IC/ICIR（用真实数据）**
- 动量因子（20日、60日）
- 价值因子（EP = 1/pe_ttm，BP = 1/pb）—— 直接从本地 CSV 读，不需要 fundamental_loader
- 低波动因子（20日实现波动率）
- 换手率因子（turnover，反转信号）

对每个因子输出：
```
因子名     IC均值    ICIR    t统计量    是否显著
动量20日   -0.xx     -0.xx   -x.xx     ✅/❌
EP         +0.xx     +0.xx   +x.xx     ✅/❌
...
```
显著标准：|ICIR| > 0.3 且 |t| > 2

**Section 3：因子相关性矩阵**
各因子两两相关性热力图（确认正交性）

**Section 4：多因子合成初步测试**
用有效因子（ICIR显著的）做等权合成，跑十分位回测，看多空对冲年化收益

**Section 5：样本外检验（2025全年）**
用2015-2024训练，2025验证，看因子是否过拟合

---

### 4. 多因子选股策略 `strategies/multi_factor.py`

```python
class MultiFactor Strategy(Strategy):
    """
    多因子选股策略

    流程：
        1. 每月第一个交易日调仓
        2. 计算各因子截面分位数
        3. 合成综合评分（只用 ICIR 显著的因子）
        4. 选前 N 只（默认30只），等权持有
        5. 排除 ST 股票、上市不足60日的次新股
        6. 扣除双边 0.3% 交易成本

    参数:
        n_stocks: 持仓股票数（默认30）
        rebalance_freq: 调仓频率（"monthly"/"weekly"）
        factors: 使用哪些因子及方向
    """
```

**必须满足回测质量红线：**
- 信号 `.shift(1)` 才用于交易（无未来函数）
- 排除 ST 股（`is_st == 1`）
- 交易成本双边 0.3%
- 基准：沪深300

---

### 5. 行业中性化验证 `research/notebooks/10_industry_neutral.ipynb`

- 用 `utils/factor_analysis.py` 的 `industry_neutralize()` 对各因子做行业中性化
- 对比中性化前后的 IC/ICIR 变化
- 判断是否需要在策略中加入行业中性化

---

### 6. Walk-forward 验证 `utils/walk_forward.py`

```python
def walk_forward_test(
    strategy_fn,
    price_wide: pd.DataFrame,
    factor_data: dict,
    train_years: int = 3,
    test_months: int = 6,
) -> pd.DataFrame:
    """
    滚动样本外验证

    每次用 train_years 年训练，预测 test_months 个月
    返回每个窗口的夏普、最大回撤、胜率等

    参数:
        strategy_fn: 接受 (price_wide, factor_data, start, end) 的函数
        train_years: 训练窗口（年）
        test_months: 测试窗口（月）

    返回:
        DataFrame，每行是一个滚动窗口的绩效指标
    """
```

---

### 7. 更新 ROADMAP.md 和 journal

- 把 Phase 4 已完成的条目标 [x]
- 在 `journal/weekly/` 当周文件追加工作记录

---

## 硬性约束

1. **禁止动的文件：**
   - `backtest/engine.py` 的 `__init__` 和 `run` 签名
   - `research/factors/polar_pv_factor/` 下所有文件

2. **数据路径固定：** `/Users/karan/Desktop/20260320/`（不要移动或复制数据）

3. **回测红线：**
   - 信号必须 `.shift(1)`
   - 排除 ST 股
   - 交易成本双边 0.3%
   - 样本外验证必须用 2025 年（2015-2024 训练）

4. **代码规范：**
   - 注释中文，变量名英文 snake_case
   - 每个函数有中文 docstring
   - 每个新文件末尾有 `if __name__ == "__main__":` 验证
   - **禁止** commit message 里加任何 AI 署名

5. **写完每个模块必须验证：**
   ```bash
   python -c "from utils.local_data_loader import load_price_wide; print('✅')"
   ```

---

## 完成验证标准

```bash
# 1. 本地数据加载器可用
python -c "from utils.local_data_loader import load_price_wide, get_all_symbols; syms = get_all_symbols(); print(f'✅ {len(syms)} 只股票')"

# 2. 宽表加载正常
python -c "
from utils.local_data_loader import load_price_wide
df = load_price_wide(['600000','000001'], '2020-01-01', '2024-12-31')
assert df.shape[0] > 100
assert df.shape[1] == 2
print('✅ load_price_wide OK')
"

# 3. 因子验证 notebook 存在
ls research/notebooks/09_factor_validation.ipynb

# 4. 行业中性化 notebook 存在
ls research/notebooks/10_industry_neutral.ipynb

# 5. 多因子策略可导入
python -c "from strategies.multi_factor import MultiFactorStrategy; print('✅ strategy OK')"

# 6. Walk-forward 可导入
python -c "from utils.walk_forward import walk_forward_test; print('✅ walk_forward OK')"
```
