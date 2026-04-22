# GOAL — quant-dojo Phase 3 全面完工

> 这是给 /autoloop 的目标文件，描述理想终态。Supervisor 负责拆解任务。
> 当前日期：2026-03-21

---

## 背景

quant-dojo 是 A 股量化研究项目，当前在 Phase 3（因子研究）。

**已完成：**
- 价格/量数据管道（`utils/data_loader.py`）
- 因子分析框架（`utils/factor_analysis.py`）— IC/ICIR、分层回测、去极值、行业中性化
- 财务数据管道（`utils/fundamental_loader.py`）— PE/PB/PS、ROE、财务指标、行业分类
- 极坐标价量因子（`research/factors/polar_pv_factor/`）— Sharpe 3.41，已完成不动
- 动量因子（`research/factors/momentum/`）— 多周期5/10/20/60/120日，notebook已完成
- agents 模块骨架（`agents/base.py`, `agents/debate.py`）— LLMClient + BullBearDebate

**Phase 3 待完成（本 GOAL 的核心）：**
1. 价值因子（PE、PB 反转）
2. 质量因子（ROE、盈利稳定性）
3. 低波动因子（Beta、实现波动率）
4. 因子衰减分析工具
5. 多因子合成框架（打分法 + IC 加权）
6. 03_single_stock_analysis.ipynb（分析任意一只股票的工具性 notebook）
7. 单只股票分析 Agent（接入 BullBearDebate）
8. Phase 3 总结报告

---

## 理想终态（Success Criteria）

### 1. 价值因子 `research/factors/value/`

**文件结构：**
```
research/factors/value/
    value_factor.py
    06_value_factor.ipynb
    README.md
```

**`value_factor.py` 要实现：**
- `compute_ep(pe_wide: pd.DataFrame) -> pd.DataFrame`
  - EP = 1/PE（盈利收益率），对 PE < 0 的值置 NaN
  - 输入：宽表（date × symbol 的 PE_TTM）
- `compute_bp(pb_wide: pd.DataFrame) -> pd.DataFrame`
  - BP = 1/PB（净资产收益率），对 PB < 0 置 NaN
- `compute_sp(ps_wide: pd.DataFrame) -> pd.DataFrame`
  - SP = 1/PS
- `compute_composite_value(ep, bp, sp, weights=(1/3, 1/3, 1/3)) -> pd.DataFrame`
  - 等权合成，先各自标准化（z-score 截面）再加权

**`06_value_factor.ipynb` 要覆盖：**
1. 用 `fundamental_loader.get_pe_pb` 加载 PE/PB/PS 数据，构建宽表
2. 计算 EP、BP、SP 单因子及合成价值因子
3. IC/ICIR 分析（`utils/factor_analysis.compute_ic_series`）
4. 分层回测十分位（`utils/factor_analysis.quintile_backtest`）
5. 与动量因子相关性（正交性检验）
6. 结论：A股价值因子有效性

**`README.md` 格式参照 `research/factors/polar_pv_factor/README.md`，必须包含：**
- 因子逻辑
- 关键 IC/ICIR 数据
- 分层收益图
- 结论和局限性

---

### 2. 质量因子 `research/factors/quality/`

**文件结构：**
```
research/factors/quality/
    quality_factor.py
    07_quality_factor.ipynb
    README.md
```

**`quality_factor.py` 要实现：**
- `compute_roe_factor(financials_dict: dict) -> pd.DataFrame`
  - 输入：`{symbol: df}` 字典（来自 `fundamental_loader.get_financials`）
  - 输出：宽表（date × symbol 的 ROE 值，按季度对齐到日频）
  - 季度数据用 `ffill` 对齐到日频（不超前填充——用上一季度已公布数据）
- `compute_roe_stability(roe_wide: pd.DataFrame, window: int = 8) -> pd.DataFrame`
  - ROE 稳定性 = 滚动窗口内 ROE 的负标准差（越稳定值越大）
- `compute_gross_margin(financials_dict: dict) -> pd.DataFrame`
  - 毛利率宽表，同样按季度对齐
- `compute_composite_quality(roe, roe_stability, gross_margin) -> pd.DataFrame`
  - 等权合成，各维度截面 z-score 标准化后加权

**`07_quality_factor.ipynb` 覆盖：**
1. 加载多只股票财务数据，构建 ROE、毛利率宽表
2. 计算质量因子
3. IC/ICIR 分析
4. 分层回测
5. 结论

**注意：** 财务数据是季度频率，股票池与价格数据对齐时要小心前视偏差——只用已发布的财报数据。

---

### 3. 低波动因子 `research/factors/low_vol/`

**文件结构：**
```
research/factors/low_vol/
    low_vol_factor.py
    08_low_vol_factor.ipynb
    README.md
```

**`low_vol_factor.py` 要实现：**
- `compute_realized_vol(ret_wide: pd.DataFrame, window: int = 20) -> pd.DataFrame`
  - 滚动20日年化波动率（标准差 * sqrt(252)）
  - 因子值取负（低波动 = 大值）
- `compute_beta(ret_wide: pd.DataFrame, market_ret: pd.Series, window: int = 60) -> pd.DataFrame`
  - 滚动60日 Beta，以沪深300作为市场组合
  - 因子值取负（低 Beta = 大值）
- `compute_composite_low_vol(vol_factor, beta_factor, weights=(0.5, 0.5)) -> pd.DataFrame`
  - 加权合成

**数据：**
- 用 `utils/data_loader.get_stock_history` 获取价格
- 沪深300指数代码：`000300`（akshare 格式）

**`08_low_vol_factor.ipynb` 覆盖：**
1. 计算全股票池的波动率和 Beta
2. IC/ICIR（低波动在 A 股是否有效？）
3. 分层回测
4. 结论

---

### 4. 因子衰减分析 `utils/factor_analysis.py` 新增函数

在现有 `utils/factor_analysis.py` 末尾新增：

```python
def factor_decay_analysis(
    factor_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    horizons: list = [1, 5, 10, 20, 60],
    method: str = "spearman",
) -> pd.DataFrame:
    """
    计算因子在不同持仓周期的 IC 衰减

    参数:
        factor_wide : 因子宽表（date × symbol）
        ret_wide    : 日收益率宽表
        horizons    : 持仓天数列表
        method      : 相关性方法

    返回:
        DataFrame，列为 horizon，行为统计量（mean_ic, icir, t_stat）
    """
```

逻辑：对每个 horizon h，计算 h 日累计收益 IC（避免前视——用 shift），返回 mean_IC 和 ICIR。

---

### 5. 多因子合成框架 `utils/multi_factor.py`

新建文件 `utils/multi_factor.py`，实现：

```python
def zscore_normalize(factor_wide: pd.DataFrame) -> pd.DataFrame:
    """截面 z-score 标准化"""

def rank_normalize(factor_wide: pd.DataFrame) -> pd.DataFrame:
    """截面排名标准化（转为 0-1）"""

def equal_weight_composite(factors: dict, normalize: str = "zscore") -> pd.DataFrame:
    """
    等权合成多因子

    参数:
        factors   : {"factor_name": factor_wide_df, ...}
        normalize : "zscore" 或 "rank"
    返回:
        合成因子宽表
    """

def ic_weighted_composite(
    factors: dict,
    ic_lookback: int = 60,
    ret_wide: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    IC 加权合成：用过去 ic_lookback 天的滚动 IC 作为权重
    权重每月更新一次（防止频繁调仓）
    """

def score_composite(factors: dict, direction: dict = None) -> pd.DataFrame:
    """
    打分法合成：每个因子截面排名后等权平均

    参数:
        direction : {"factor_name": 1 or -1}，-1 表示该因子取反
    """
```

并在 `utils/__init__.py` 中暴露主要函数。

---

### 6. `research/notebooks/03_single_stock_analysis.ipynb`

这是一个**工具性 notebook**，可以把任意股票代码填进去，一键输出完整分析：

**结构：**
```
Section 0: 参数配置（只需改这里）
    SYMBOL = "000001"  # 股票代码
    START = "2021-01-01"
    END = "2026-01-01"

Section 1: 价格与成交量分析
    - K线图（OHLC）+ 成交量
    - 移动均线（5/20/60日）
    - 月度收益率分布

Section 2: 财务数据分析
    - PE/PB 历史走势（相对行业均值）
    - ROE/毛利率趋势
    - 负债率走势

Section 3: 因子暴露分析
    - 该股在各因子上的历史暴露（动量/价值/质量/低波动）
    - 与沪深300的 Beta

Section 4: AI 综合分析（可选）
    - 调用 agents/debate.py 的 BullBearDebate
    - 输出多空论点 + 结论
```

**要求：**
- 复用所有已有工具函数，不重复实现
- 每个 Section 独立可运行
- Section 4 检测 LLMClient 后端，没有后端就跳过，不报错

---

### 7. 单只股票分析 Agent `agents/stock_analyst.py`

新建 `agents/stock_analyst.py`，实现：

```python
class StockAnalyst(BaseAgent):
    """
    单只股票综合分析 Agent

    流程：
        1. 拉取价格数据（utils/data_loader）
        2. 拉取财务数据（utils/fundamental_loader）
        3. 计算各因子暴露
        4. 调用 BullBearDebate 做多空辩论
        5. 返回结构化报告 dict
    """

    def analyze(self, symbol: str, start: str, end: str) -> dict:
        """
        返回:
            {
                "symbol": str,
                "price_summary": dict,  # 最新价、年化收益、波动率、夏普
                "factor_exposure": dict,  # 各因子分位数
                "fundamental": dict,     # PE/PB/ROE 最新值
                "debate": dict,          # BullBearDebate 输出
            }
        """
```

并在 `agents/__init__.py` 中暴露 `StockAnalyst`。

---

### 8. Phase 3 总结 `journal/phase3_summary.md`

工作完成后写一份总结：
- 已实现的所有因子及关键指标（IC 均值、ICIR）
- 各因子两两相关性矩阵（文字描述即可）
- 因子有效性排名（A股最有效 → 最无效）
- Phase 4 建议（哪些因子值得放进多因子策略）

---

## 硬性约束

1. **禁止动的文件：**
   - `backtest/engine.py` 的 `__init__` 和 `run` 签名
   - `research/factors/polar_pv_factor/` 下所有文件
   - `data/` 目录下任何数据文件

2. **回测质量红线：**
   - 因子信号必须 `.shift(1)` 再用于持仓
   - 财务数据不能用未来发布的季报（用发布时间而非报告期）
   - 交易成本默认双边 0.3%

3. **代码规范：**
   - 注释用中文，变量名用英文 snake_case
   - 每个函数必须有中文 docstring
   - 每个新文件末尾有 `if __name__ == "__main__":` 最小验证
   - 写新函数前先搜索 `utils/` 是否已有

4. **Git 规范：**
   - 每完成一个函数/一个 notebook section 就 commit
   - commit message 用中文，说清楚做了什么
   - **禁止**在 commit message 里加 `Co-Authored-By: Claude` 或任何 AI 署名

5. **环境验证：**
   - 每个新模块写完后运行 `python -c "from xxx import yyy; print('✅')"` 验证

6. **任务完成后：**
   - 更新 `TODO.md` 把新任务标 [x]
   - 更新 `ROADMAP.md` Phase 3 进度条
   - 在 `journal/weekly/` 当周文件追加工作记录

---

## 完成验证标准

所有以下检查通过，目标达成：

```bash
# 1. 模块可导入
python -c "from research.factors.value.value_factor import compute_ep, compute_bp; print('✅ value')"
python -c "from research.factors.quality.quality_factor import compute_roe_factor; print('✅ quality')"
python -c "from research.factors.low_vol.low_vol_factor import compute_realized_vol; print('✅ low_vol')"
python -c "from utils.multi_factor import equal_weight_composite, ic_weighted_composite; print('✅ multi_factor')"
python -c "from agents import StockAnalyst; print('✅ stock_analyst')"

# 2. factor_analysis 新函数存在
python -c "from utils.factor_analysis import factor_decay_analysis; print('✅ decay')"

# 3. Notebooks 存在
ls research/notebooks/03_single_stock_analysis.ipynb
ls research/factors/value/06_value_factor.ipynb
ls research/factors/quality/07_quality_factor.ipynb
ls research/factors/low_vol/08_low_vol_factor.ipynb

# 4. README 存在
ls research/factors/value/README.md
ls research/factors/quality/README.md
ls research/factors/low_vol/README.md

# 5. 总结报告存在
ls journal/phase3_summary.md
```
