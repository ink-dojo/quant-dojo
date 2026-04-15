"""
signals_service.py — 信号服务层

封装最新信号和历史信号查询，所有函数捕获异常并返回空值结构。
"""

import json
from pathlib import Path

from dashboard.services.data_loader import load_latest_signal, load_signal_history

# 股票名称缓存
_STOCK_NAMES: dict[str, str] = {}
_NAMES_FILE = Path(__file__).parent.parent.parent / "data" / "cache" / "stock_names.json"


def _load_stock_names() -> dict[str, str]:
    global _STOCK_NAMES
    if _STOCK_NAMES:
        return _STOCK_NAMES
    try:
        _STOCK_NAMES = json.loads(_NAMES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _STOCK_NAMES


def _enrich_picks(picks: list) -> list[dict]:
    """把 ['600025', ...] 转成 [{'code': '600025', 'name': '华能水电'}, ...]"""
    names = _load_stock_names()
    result = []
    for p in picks:
        if isinstance(p, dict):
            code = p.get("code", "")
            result.append({**p, "name": names.get(code, code)})
        else:
            code = str(p)
            result.append({"code": code, "name": names.get(code, code)})
    return result

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
            "picks": _enrich_picks(picks),
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


def get_stock_detail(code: str) -> dict:
    """
    获取单只股票在最新信号中的详情。

    返回:
        {
          "code": str, "name": str,
          "composite_score": float | None,
          "rank": int | None,           # 在 picks 里排第几（1-based）
          "in_picks": bool,
          "factor_scores": {            # 各因子原始值 + 分位数排名
            "low_vol_20d": {"value": -0.009, "pct_rank": 0.82, "direction": 1},
            ...
          },
          "as_of_date": str | None,
          "strategy": str | None,
        }
    """
    try:
        data = load_latest_signal()
        if not data:
            return {"code": code, "error": "无信号数据"}

        names = _load_stock_names()
        picks = data.get("picks", data.get("selected_stocks", []))
        scores = data.get("scores", {})
        factor_values = data.get("factor_values", {})
        metadata = data.get("metadata", {})

        # 计算每个因子的原始值 + 全市场分位数排名
        factor_scores: dict = {}
        for factor_name, stock_vals in factor_values.items():
            if not isinstance(stock_vals, dict):
                continue
            val = stock_vals.get(code)
            if val is None:
                continue
            all_vals = [v for v in stock_vals.values() if v is not None]
            pct_rank = sum(1 for v in all_vals if v <= val) / len(all_vals) if all_vals else None
            factor_scores[factor_name] = {
                "value": round(float(val), 6),
                "pct_rank": round(pct_rank, 4) if pct_rank is not None else None,
            }

        rank = None
        if code in picks:
            try:
                rank = picks.index(code) + 1
            except Exception:
                pass

        return {
            "code": code,
            "name": names.get(code, code),
            "composite_score": scores.get(code),
            "rank": rank,
            "in_picks": code in picks,
            "factor_scores": factor_scores,
            "as_of_date": data.get("as_of_date", data.get("date")),
            "strategy": metadata.get("strategy"),
        }
    except Exception as exc:
        return {"code": code, "error": str(exc)}


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
