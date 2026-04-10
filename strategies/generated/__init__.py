"""
strategies/generated/ — idea-to-strategy 流水线自动生成的策略定义存放目录

本目录由 pipeline/idea_to_strategy.py 的 _stage_write_spec() 写入，
文件结构如下：
    auto_gen_latest.json        — 最新策略定义（每次流水线执行后覆盖）
    auto_gen_<name>_<date>.json — 带时间戳的历史备份

JSON 格式（auto_gen_loader.py 读取）：
{
  "strategy": {
    "name": "auto_gen",
    "factors": [{"name":..., "direction":..., "icir":..., "ic_mean":...}],
    "weighting": "ic_weighted",
    "neutralize": true,
    "n_stocks": 30,
    "generated_at": "..."
  }
}

注意：
    - 本目录不入 Git 数据追踪（auto_gen_latest.json 运行时生成）
    - __init__.py 本身是空包标记，确保 `import strategies.generated` 可正常解析
    - .gitkeep 确保空目录进入 Git 历史
"""
