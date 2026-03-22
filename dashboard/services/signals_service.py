"""
signals_service.py — 信号服务层

封装最新信号和历史信号查询，所有函数捕获异常并返回空值结构。
"""

from dashboard.services.data_loader import load_latest_signal, load_signal_history

# 信号缺失时的默认返回结构
_EMPTY_SIGNAL: dict = {
    "as_of_date": None,
    "picks": [],
    "scores": {},
    "excluded": {},
}


def get_latest_signal() -> dict:
    """
    获取最新一期信号的详情。

    从 live/signals/ 读取最新 json，提取 picks/scores/excluded/as_of_date。
    文件不存在或读取失败时返回空结构。

    返回:
        dict，包含:
          - as_of_date: str 或 None
          - picks: list[str]，选股代码列表
          - scores: dict，各股票评分
          - excluded: dict，被排除的股票及原因
    """
    try:
        data = load_latest_signal()
        if not data:
            return dict(_EMPTY_SIGNAL)

        picks = data.get("picks", data.get("selected_stocks", []))
        if not isinstance(picks, list):
            picks = []

        scores = data.get("scores", data.get("factor_scores", {}))
        if not isinstance(scores, dict):
            scores = {}

        excluded = data.get("excluded", data.get("excluded_stocks", {}))
        if not isinstance(excluded, dict):
            excluded = {}

        as_of_date = data.get("as_of_date", data.get("date", None))

        return {
            "as_of_date": as_of_date,
            "picks": picks,
            "scores": scores,
            "excluded": excluded,
        }
    except Exception:
        return dict(_EMPTY_SIGNAL)


def get_signal_history() -> list[dict]:
    """
    获取最近 10 期信号的日期和持仓数。

    返回:
        list[dict]，格式为 [{"date": "2026-03-20", "n_picks": 5}, ...]
        按日期升序排列；读取失败时返回 []
    """
    try:
        return load_signal_history(n=10)
    except Exception:
        return []


if __name__ == "__main__":
    print("=== latest signal ===")
    sig = get_latest_signal()
    print(f"as_of_date: {sig['as_of_date']}")
    print(f"picks 数量: {len(sig['picks'])}")
    print(f"excluded 数量: {len(sig['excluded'])}")

    print("\n=== signal history ===")
    hist = get_signal_history()
    print(f"共 {len(hist)} 期历史信号")
    for item in hist:
        print(f"  {item['date']} → {item['n_picks']} 只")

    print("\n✅ signals_service 检查完毕")
