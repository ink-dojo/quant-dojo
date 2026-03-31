import pandas as pd

from utils.factor_analysis import neutralize_factor_by_industry


def test_neutralize_factor_by_industry_group_means_are_zero():
    dates = pd.to_datetime(["2026-01-02"])
    factor_wide = pd.DataFrame(
        {
            "A": [1.0],
            "B": [3.0],
            "C": [10.0],
            "D": [14.0],
        },
        index=dates,
    )
    industry_df = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "industry_code": ["bank", "bank", "tech", "tech"],
        }
    )

    neutral = neutralize_factor_by_industry(
        factor_wide, industry_df, min_stocks=1
    )

    row = neutral.loc[dates[0]]
    assert abs(row[["A", "B"]].mean()) < 1e-9
    assert abs(row[["C", "D"]].mean()) < 1e-9


def test_neutralize_factor_by_industry_requires_columns():
    factor_wide = pd.DataFrame({"A": [1.0]}, index=pd.to_datetime(["2026-01-02"]))
    bad_df = pd.DataFrame({"symbol": ["A"]})

    try:
        neutralize_factor_by_industry(factor_wide, bad_df, min_stocks=1)
    except ValueError as exc:
        assert "industry_df 缺少必要列" in str(exc)
    else:
        raise AssertionError("expected ValueError")
