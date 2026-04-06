"""
runtime_config.py — 统一运行时配置模块

从 config/config.yaml 读取运行时参数，若文件不存在则降级到
config/config.example.yaml，最终降级到硬编码默认值。

用法：
    from utils.runtime_config import get_config, get_local_data_dir
"""

from pathlib import Path
from typing import Any, Optional

import yaml

# 项目根目录（相对于本文件）
_PROJECT_ROOT = Path(__file__).parent.parent

# 配置文件查找顺序
_CONFIG_PATHS = [
    _PROJECT_ROOT / "config" / "config.yaml",
    _PROJECT_ROOT / "config" / "config.example.yaml",
]

# 默认值
_DEFAULTS = {
    "phase5": {
        "local_data_dir": str(Path.home() / "quant-data"),
        "signal_n_stocks": 30,
        "min_listing_days": 60,
        "min_price": 2.0,
        "transaction_cost_rate": 0.003,
        "drawdown_warning": -0.05,
        "drawdown_critical": -0.10,
        "concentration_limit": 0.15,
    },
    "pipeline": {
        "default_strategy": "v7",
        "daemon_run_time": "16:30",
        "data_stale_threshold_days": 3,
        "factor_mining": {
            "min_abs_ic": 0.015,
            "min_abs_icir": 0.2,
            "min_abs_t_stat": 1.5,
            "correlation_threshold": 0.7,
            "top_k": 5,
        },
        "strategy_upgrade": {
            "threshold": 1.15,
            "auto_upgrade": True,
        },
        "signal_validation": {
            "min_picks": 10,
            "max_picks": 60,
            "overlap_warning_threshold": 0.3,
        },
    },
    "alerts": {
        "webhook_url": "",
    },
}

# 模块级缓存，避免重复读取磁盘
_config_cache: Optional[dict] = None


def _deep_merge(base: dict, override: dict) -> dict:
    """
    深度合并两个字典，override 中的值覆盖 base。

    参数:
        base: 基础字典（默认值）
        override: 覆盖字典（用户配置）

    返回:
        合并后的字典
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_file(path: Path) -> dict:
    """
    读取单个 YAML 文件，失败时返回空字典。

    参数:
        path: YAML 文件路径

    返回:
        解析后的字典，读取失败则返回 {}
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_config() -> dict:
    """
    获取完整运行时配置字典（带缓存）。

    查找顺序：config/config.yaml → config/config.example.yaml → 硬编码默认值。
    返回的字典始终包含 phase5 节，保证各字段有值。

    返回:
        完整配置字典
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # 从文件中加载，优先使用第一个存在的文件
    file_config: dict = {}
    for path in _CONFIG_PATHS:
        if path.exists():
            file_config = _load_yaml_file(path)
            break

    # 深度合并：默认值 + 文件配置
    merged = _deep_merge(_DEFAULTS, file_config)
    _config_cache = merged
    return _config_cache


def _get_phase5(key: str) -> Any:
    """
    从 phase5 节读取单个配置项。

    参数:
        key: phase5 节中的键名

    返回:
        对应的配置值
    """
    return get_config().get("phase5", {}).get(key, _DEFAULTS["phase5"][key])


def get_local_data_dir() -> Path:
    """
    获取本地行情数据目录路径。

    从 config.yaml 的 phase5.local_data_dir 读取；
    若配置文件不存在，则使用默认路径 ~/quant-data。

    返回:
        数据目录的 Path 对象

    Raises:
        FileNotFoundError: 如果目录不存在，打印清晰错误提示（不抛出，仅警告）
    """
    raw = _get_phase5("local_data_dir")
    path = Path(raw).expanduser()
    if not path.exists():
        import warnings
        warnings.warn(
            f"[runtime_config] 本地数据目录不存在: {path}\n"
            "  请确认数据已下载，或在 config/config.yaml 的 phase5.local_data_dir 中修改路径。",
            stacklevel=3,
        )
    return path


def get_signal_n_stocks() -> int:
    """
    获取信号选股数量上限。

    返回:
        int，默认 30
    """
    return int(_get_phase5("signal_n_stocks"))


def get_min_listing_days() -> int:
    """
    获取最小上市天数过滤阈值。

    返回:
        int，默认 60（天）
    """
    return int(_get_phase5("min_listing_days"))


def get_min_price() -> float:
    """
    获取最低股价过滤阈值（元）。

    返回:
        float，默认 2.0
    """
    return float(_get_phase5("min_price"))


def get_transaction_cost_rate() -> float:
    """
    获取交易成本率（双边）。

    返回:
        float，默认 0.003（即双边 0.3%）
    """
    return float(_get_phase5("transaction_cost_rate"))


def get_drawdown_warning() -> float:
    """
    获取回撤预警阈值（负数）。

    返回:
        float，默认 -0.05（即 -5%）
    """
    return float(_get_phase5("drawdown_warning"))


def get_drawdown_critical() -> float:
    """
    获取回撤临界阈值（负数）。

    返回:
        float，默认 -0.10（即 -10%）
    """
    return float(_get_phase5("drawdown_critical"))


def get_concentration_limit() -> float:
    """
    获取单股仓位集中度上限。

    返回:
        float，默认 0.15（即 15%）
    """
    return float(_get_phase5("concentration_limit"))


def get_pipeline_config() -> dict:
    """
    获取流水线配置。

    返回:
        dict: pipeline 配置节
    """
    return get_config().get("pipeline", _DEFAULTS["pipeline"])


def get_pipeline_param(key: str, default=None):
    """
    获取单个流水线配置参数（支持点分路径）。

    示例:
        get_pipeline_param("factor_mining.min_abs_ic")  → 0.015
        get_pipeline_param("default_strategy")          → "v7"
    """
    cfg = get_pipeline_config()
    parts = key.split(".")
    for part in parts:
        if isinstance(cfg, dict):
            cfg = cfg.get(part)
        else:
            return default
    return cfg if cfg is not None else default


if __name__ == "__main__":
    cfg = get_config()
    print(f"✅ runtime_config ok | phase5 keys: {list(cfg.get('phase5', {}).keys())}")
    print(f"  local_data_dir      = {get_local_data_dir()}")
    print(f"  signal_n_stocks     = {get_signal_n_stocks()}")
    print(f"  min_listing_days    = {get_min_listing_days()}")
    print(f"  min_price           = {get_min_price()}")
    print(f"  transaction_cost    = {get_transaction_cost_rate()}")
    print(f"  drawdown_warning    = {get_drawdown_warning()}")
    print(f"  drawdown_critical   = {get_drawdown_critical()}")
    print(f"  concentration_limit = {get_concentration_limit()}")
