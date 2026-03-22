# quant-dojo 数据加载方案

> 写于 2026-03-22 凌晨，明天看

---

## 你桌面上有什么

`~/Desktop/20260320/` — 5477个CSV文件，沪深全市场日线数据

字段：
```
交易所行情日期, 证券代码, 开盘价, 最高价, 最低价, 收盘价, 前收盘价,
成交量, 成交额, 复权状态, 换手率, 交易状态, 涨跌幅,
滚动市盈率, 市净率, 滚动市销率, 滚动市现率, 是否ST
```

**这个数据集已经包含PE、PB等估值因子，直接可用。**

---

## 要做的事

把这5477个CSV合并成一个parquet文件，之后所有分析直接读parquet，速度快100倍。

---

## 数据加载脚本

在 `quant-dojo/data/load_local.py` 创建以下内容：

```python
"""
把桌面上的5477个CSV合并成一个parquet文件
运行一次，之后直接读parquet
"""

import pandas as pd
from pathlib import Path
import glob

# 修改这里的路径
DATA_DIR = Path.home() / "Desktop" / "20260320"
OUTPUT_PATH = Path(__file__).parent / "all_stocks.parquet"

def load_and_merge():
    print(f"开始加载 {DATA_DIR}...")
    csv_files = list(DATA_DIR.glob("*.csv"))
    print(f"找到 {len(csv_files)} 个文件")
    
    dfs = []
    for i, f in enumerate(csv_files):
        try:
            df = pd.read_csv(f, encoding="utf-8")
            dfs.append(df)
        except Exception as e:
            print(f"跳过 {f.name}: {e}")
        
        if (i + 1) % 500 == 0:
            print(f"  已处理 {i+1}/{len(csv_files)}...")
    
    print("合并中...")
    all_df = pd.concat(dfs, ignore_index=True)
    
    # 重命名列为英文（方便后续用）
    all_df.columns = [
        "date", "code", "open", "high", "low", "close", "prev_close",
        "volume", "amount", "adjust_type", "turnover", "trade_status",
        "pct_change", "pe_ttm", "pb", "ps_ttm", "pcf_ttm", "is_st"
    ]
    
    # 类型处理
    all_df["date"] = pd.to_datetime(all_df["date"])
    all_df = all_df[all_df["trade_status"] == 1]  # 只保留正常交易日
    all_df = all_df[all_df["is_st"] == 0]          # 去除ST股
    all_df = all_df.sort_values(["code", "date"]).reset_index(drop=True)
    
    print(f"保存到 {OUTPUT_PATH}...")
    all_df.to_parquet(OUTPUT_PATH, index=False)
    print(f"完成！共 {len(all_df):,} 行，{all_df['code'].nunique():,} 个标的")
    print(f"时间范围：{all_df['date'].min()} ~ {all_df['date'].max()}")
    return all_df


def load_parquet():
    """之后每次用这个函数加载，秒读"""
    return pd.read_parquet(OUTPUT_PATH)


if __name__ == "__main__":
    load_and_merge()
```

---

## 怎么用

**第一次运行（生成parquet，约1-2分钟）：**
```bash
cd ~/quant-dojo  # 或者你的项目路径
python data/load_local.py
```

**之后每次分析：**
```python
from data.load_local import load_parquet
df = load_parquet()  # 秒读

# 取单只股票
ping_an = df[df["code"] == "sh.601318"]

# 取某个时间段
df_2023 = df[df["date"] >= "2023-01-01"]

# 按PB筛低估值股票
low_pb = df[df["pb"] < 1.0]
```

---

## 还缺什么

ROE、毛利率、资产负债率等财务数据（这个数据集没有）。
等这个数据跑通了，再用AKShare补财务数据：

```python
import akshare as ak
import time

codes = df["code"].str.replace("sh.", "").str.replace("sz.", "").unique()
results = []
for code in codes[:100]:  # 先试100个
    try:
        fin = ak.stock_financial_analysis_indicator(symbol=code, start_year="2020")
        results.append(fin)
        time.sleep(0.3)
    except:
        pass
```

---

## 明天要做的

1. 运行 `python data/load_local.py` 生成parquet
2. 把quant-dojo里的BaoStock数据加载部分替换成 `load_parquet()`
3. 跑一个简单的PB因子回测验证数据正确

