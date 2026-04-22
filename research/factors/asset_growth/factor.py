"""
Asset Growth 异常 — Cooper, Gulen, Schill (2008) JF.

核心论点：公司年度总资产增长率越高，未来收益越差。
    AG = (TotalAssets_t − TotalAssets_{t-1y}) / TotalAssets_{t-1y}

机制：
    1. 管理层过度扩张（empire building）
    2. 资本配置效率下降
    3. 市场对高增长定价过度乐观 → 反转

A 股证据：田利辉 (2014)《中国股市资产成长异象研究》— AG long-short spread
          年化 8-12%，在小盘尤其显著。

预期：IC 应为负（AG 高 → 收益低）。
     Rank IC fwd=20d ~ −0.02 到 −0.04

参数：
    - 年频 AG，用最近的 annual report total_assets
    - 信号发布时间：用 ann_date (公告日) + 1 交易日（信息可用）
    - 锁定不调
"""
from __future__ import annotations
import pandas as pd


def compute_ag_panel(balance_sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    从单股 balancesheet 字典构建 AG 宽表（ann_date × symbol）。

    参数:
        balance_sheets : {symbol: 单股 DataFrame with columns
                          [ts_code, ann_date, f_ann_date, end_date, report_type, total_assets]}
    返回:
        wide DataFrame, index = ann_date (pd.Timestamp), columns = symbol,
        values = AG_yoy (同比资产增长率)
    """
    records = []
    for sym, df in balance_sheets.items():
        if df is None or df.empty or "total_assets" not in df.columns:
            continue
        d = df.copy()
        # 只取年报（report_type=1 = 合并年报）+ end_date 为 12-31 的
        d = d[d["end_date"].astype(str).str.endswith("1231")]
        if d.empty:
            continue
        d["end_date"] = pd.to_datetime(d["end_date"].astype(str))
        d["ann_date"] = pd.to_datetime(d["ann_date"].astype(str))
        d = d.dropna(subset=["total_assets"]).sort_values("end_date")
        # 取同 end_date 最早的 ann_date（原始公告日，避免更正稿）
        d = d.groupby("end_date", as_index=False).first()
        if len(d) < 2:
            continue
        d = d.sort_values("end_date")
        d["ta_prev"] = d["total_assets"].shift(1)
        d["ag"] = (d["total_assets"] - d["ta_prev"]) / d["ta_prev"]
        d = d.dropna(subset=["ag"])
        for _, row in d.iterrows():
            records.append((row["ann_date"], sym, row["ag"]))

    if not records:
        return pd.DataFrame()

    long_df = pd.DataFrame(records, columns=["ann_date", "symbol", "ag"])
    # 同一公告日同一 symbol 保留最新（一般不会重复）
    long_df = long_df.drop_duplicates(["ann_date", "symbol"], keep="last")
    wide = long_df.pivot(index="ann_date", columns="symbol", values="ag")
    wide = wide.sort_index()
    return wide


def broadcast_to_daily(ag_wide: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """把稀疏的年报 AG 信号 forward-fill 到日频，信号 T+1 才能用。"""
    # reindex to daily, forward fill; shift(1) 让 T 日公告的信号 T+1 才能用于交易
    out = ag_wide.reindex(daily_index).ffill()
    # 再做 .shift(1) 避免 point-in-time 泄漏（ann_date 当日就见信息可能已吃过）
    return out.shift(1)


if __name__ == "__main__":
    # smoke test: fake 2 stocks
    import numpy as np
    dates = pd.to_datetime(["2020-04-28", "2021-04-25", "2022-04-26"])
    dummy = {
        "000001": pd.DataFrame({
            "ts_code": "000001.SZ",
            "ann_date": ["20200428", "20210425", "20220426"],
            "end_date": ["20191231", "20201231", "20211231"],
            "report_type": [1, 1, 1],
            "total_assets": [100e9, 110e9, 125e9],
        }),
        "000002": pd.DataFrame({
            "ts_code": "000002.SZ",
            "ann_date": ["20200428", "20210425", "20220426"],
            "end_date": ["20191231", "20201231", "20211231"],
            "report_type": [1, 1, 1],
            "total_assets": [200e9, 180e9, 190e9],
        }),
    }
    wide = compute_ag_panel(dummy)
    print("AG panel:")
    print(wide)
    assert wide.loc["2021-04-25", "000001"] == 0.1  # 10% growth
    print("\n✅ smoke test passed")
