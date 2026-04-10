"""
IdeaParser：自然语言策略想法 → 结构化因子规范

接收用户用中文描述的量化策略想法，调用 LLM 解析出：
  - 策略假设（hypothesis）
  - 策略名称（strategy_name）
  - 选用的因子及方向（selected_factors）
  - 持股数量、行业中性化设置
  - LLM 置信度

输出 dict 供下游 idea_to_strategy.py 使用。
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, LLMClient
from utils.alpha_factors import FACTOR_CATALOG


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

# 每个因子的 direction 说明（+1=高因子值→高未来收益，-1=高因子值→低未来收益）
# 这里把已知方向写死，LLM 只需选择合适因子，不用猜方向
_FACTOR_DIRECTION_HINTS: dict[str, tuple[int, str]] = {
    "reversal_1m":    (-1, "1月反转，近期涨幅越大未来预期收益越低，取反向"),
    "low_vol_20d":    (+1, "低波动异象，波动越小（因子值越高）未来收益越高，正向"),
    "turnover_rev":   (+1, "换手率反转，换手越低（因子值越高）未来收益越高，正向"),
    "enhanced_mom":   (+1, "风险调整动量，动量越强未来延续概率更高，正向"),
    "quality_mom":    (+1, "高质量动量（排除涨停），动量越强正向"),
    "ma_ratio_120":   (+1, "MA比率动量，价格在MA上方越多（因子值越高）正向"),
    "ep":             (+1, "盈利收益率，EP越高价值越被低估，正向"),
    "bp":             (+1, "账面市值比，BP越高价值越被低估，正向"),
    "roe":            (+1, "ROE质量因子，ROE越高企业盈利能力越强，正向"),
    "shadow_upper":   (+1, "上影线反向，上影线少（因子值越高）买盘健康，正向"),
    "shadow_lower":   (+1, "下影线支撑，下影线越长买盘支撑越强，正向"),
    "cgo_simple":     (+1, "处置效应CGO，浮亏越大（因子值越高）未来反弹概率高，正向"),
    "str_salience":   (+1, "凸显理论STR，关注度低被低估，正向"),
    "team_coin":      (+1, "球队硬币，低波动时动量延续、高波动时反转，正向"),
    "apm_overnight":  (+1, "APM隔夜因子，隔夜收益>日间收益说明知情交易者看好，正向"),
}

# LLM prompt 模板
_SYSTEM_PROMPT = """\
你是 A 股量化因子选择专家。你的任务是：
给定用户的策略想法（中文自然语言），从下面的 FACTOR_CATALOG 中选出合适的因子，
返回结构化 JSON，供量化回测框架直接使用。

=== FACTOR_CATALOG（只能从这里选，不能创造新因子）===
{catalog_text}

=== 因子方向说明（+1=正向：高因子值→高未来收益；-1=反向）===
{direction_text}

=== 项目约束 ===
- 目标年化收益 > 15%
- 夏普比率 > 0.8
- 最大回撤 < 30%
- 策略面向 A 股全市场，需要行业中性化（neutralize=True）以避免行业集中

=== 返回格式（严格 JSON，不加任何解释）===
{{
  "hypothesis": "用一句话描述策略假设（中文）",
  "strategy_name": "英文 snake_case，不超过20字符，只含 a-z 0-9 _",
  "selected_factors": [
    {{"name": "因子名（必须在 FACTOR_CATALOG 里）", "direction": 1, "reason": "选择理由（中文）"}},
    ...
  ],
  "n_stocks": 30,
  "neutralize": true,
  "confidence": 0.8,
  "parse_ok": true,
  "reason": ""
}}

=== 重要规则 ===
1. selected_factors 里的 name 必须严格来自 FACTOR_CATALOG，拼写要完全一致
2. direction 只能是 +1 或 -1（整数）
3. 至少选 2 个因子，最多 6 个
4. n_stocks 在 10~100 之间
5. confidence 表示你对本次因子选择的把握程度（0~1 浮点数）
6. 如果策略想法完全无法对应任何因子，返回 parse_ok=false，reason 说明原因
"""


def _build_catalog_text() -> str:
    """
    将 FACTOR_CATALOG 格式化为 prompt 嵌入文本。

    返回:
        多行字符串，每行一个因子的完整描述
    """
    lines = []
    for name, info in FACTOR_CATALOG.items():
        lines.append(
            f"  {name:<18} | 类别: {info['category']:<8} "
            f"| 来源: {info['source']:<30} | 数据需求: {info['data']}"
        )
    return "\n".join(lines)


def _build_direction_text() -> str:
    """
    将因子方向说明格式化为 prompt 嵌入文本。

    返回:
        多行字符串，每行一个因子的方向和解释
    """
    lines = []
    for name, (direction, note) in _FACTOR_DIRECTION_HINTS.items():
        sign = f"+{direction}" if direction > 0 else str(direction)
        lines.append(f"  {name:<18} direction={sign}  {note}")
    return "\n".join(lines)


class IdeaParser(BaseAgent):
    """
    自然语言策略想法解析器。

    接收用户的量化策略描述（中文自然语言），
    通过 LLM 匹配 FACTOR_CATALOG，返回结构化因子规范 dict。

    使用示例:
        parser = IdeaParser(LLMClient())
        result = parser.analyze(idea_text="我想做基于ROE和低波动的选股策略")
        print(result)
    """

    # 编译一次正则，复用
    _STRATEGY_NAME_RE = re.compile(r"[^a-z0-9_]")

    def analyze(self, *, idea_text: str) -> dict:
        """
        解析自然语言策略想法，返回结构化因子规范。

        参数:
            idea_text : 用户描述的策略想法，例如 "做基于ROE和低波动的选股"

        返回:
            dict，包含以下字段：
              - hypothesis      : 策略假设（字符串）
              - strategy_name   : 英文 snake_case 策略名（≤20字符）
              - selected_factors: 因子列表，每项含 name/direction/reason
              - n_stocks        : 持股数量（10~100）
              - neutralize      : 是否行业中性化（bool）
              - confidence      : LLM 置信度（0~1）
              - parse_ok        : 解析是否成功（bool）
              - reason          : 失败原因（成功时为空字符串）
        """
        prompt = _SYSTEM_PROMPT.format(
            catalog_text=_build_catalog_text(),
            direction_text=_build_direction_text(),
        ) + f"\n\n=== 用户策略想法 ===\n{idea_text}"

        raw = self.llm.complete_json(prompt)

        return self._validate_and_fix(raw, idea_text)

    def _validate_and_fix(self, raw: dict, idea_text: str) -> dict:
        """
        校验 LLM 返回的 dict，过滤非法因子名，修正边界值。

        参数:
            raw       : LLM 返回的原始 dict
            idea_text : 原始策略想法（用于生成兜底的 reason）

        返回:
            校验和修正后的 dict，结构与 analyze 返回值相同
        """
        # LLM 调用本身失败
        if "error" in raw:
            return _fail_result(
                reason=f"LLM 调用失败: {raw.get('error', '')} | raw: {raw.get('raw', '')[:200]}"
            )

        # ── 1. parse_ok 字段 ──────────────────────────────────────
        parse_ok = bool(raw.get("parse_ok", True))
        if not parse_ok:
            return _fail_result(reason=raw.get("reason", "LLM 返回 parse_ok=false"))

        # ── 2. selected_factors 校验 ──────────────────────────────
        raw_factors = raw.get("selected_factors", [])
        if not isinstance(raw_factors, list):
            return _fail_result(reason="selected_factors 不是列表")

        valid_factors = []
        for item in raw_factors:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            direction = item.get("direction")
            reason = item.get("reason", "")

            # 因子名必须在 FACTOR_CATALOG 里
            if name not in FACTOR_CATALOG:
                # 跳过不存在的因子，不终止整个解析
                continue

            # direction 必须是 +1 或 -1
            if direction not in (1, -1, +1):
                # 尝试 int 转换
                try:
                    direction = int(direction)
                except (TypeError, ValueError):
                    direction = None
                if direction not in (1, -1):
                    continue

            valid_factors.append({
                "name": name,
                "direction": int(direction),
                "reason": str(reason),
            })

        # 至少需要 2 个有效因子
        if len(valid_factors) < 2:
            return _fail_result(
                reason=(
                    f"有效因子数量不足（有效: {len(valid_factors)} 个，"
                    f"需要至少 2 个）。原始返回: {[f.get('name') for f in raw_factors]}"
                )
            )

        # ── 3. n_stocks 限定 10~100 ───────────────────────────────
        try:
            n_stocks = int(raw.get("n_stocks", 30))
        except (TypeError, ValueError):
            n_stocks = 30
        n_stocks = max(10, min(100, n_stocks))

        # ── 4. strategy_name 清洗 ─────────────────────────────────
        raw_name = str(raw.get("strategy_name", "custom_strategy")).lower()
        clean_name = self._STRATEGY_NAME_RE.sub("_", raw_name)
        # 去掉首尾下划线，截断到20字符
        clean_name = clean_name.strip("_")[:20] or "custom_strategy"

        # ── 5. 其余字段 ───────────────────────────────────────────
        hypothesis = str(raw.get("hypothesis", idea_text))
        neutralize = bool(raw.get("neutralize", True))

        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "hypothesis": hypothesis,
            "strategy_name": clean_name,
            "selected_factors": valid_factors,
            "n_stocks": n_stocks,
            "neutralize": neutralize,
            "confidence": confidence,
            "parse_ok": True,
            "reason": "",
        }


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _fail_result(reason: str) -> dict:
    """
    生成解析失败的标准返回 dict。

    参数:
        reason : 失败原因说明

    返回:
        parse_ok=False 的标准 dict
    """
    return {
        "hypothesis": "",
        "strategy_name": "",
        "selected_factors": [],
        "n_stocks": 30,
        "neutralize": True,
        "confidence": 0.0,
        "parse_ok": False,
        "reason": reason,
    }


# ──────────────────────────────────────────────
# 最小验证
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json

    llm = LLMClient()
    print(f"LLM 后端: {llm._backend}")

    parser = IdeaParser(llm)
    idea = "我想做基于ROE和低波动的选股策略"
    print(f"\n策略想法: {idea}")
    print("解析中...")

    result = parser.analyze(idea_text=idea)

    print("\n解析结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 基本断言
    assert "parse_ok" in result, "缺少 parse_ok 字段"
    if result["parse_ok"]:
        assert len(result["selected_factors"]) >= 2, "因子数量不足"
        assert 10 <= result["n_stocks"] <= 100, "n_stocks 越界"
        assert re.match(r"^[a-z0-9_]+$", result["strategy_name"]), "strategy_name 格式错误"
        assert 0.0 <= result["confidence"] <= 1.0, "confidence 越界"
        # 验证所有因子名在 FACTOR_CATALOG 里
        for f in result["selected_factors"]:
            assert f["name"] in FACTOR_CATALOG, f"未知因子: {f['name']}"
            assert f["direction"] in (1, -1), f"非法 direction: {f['direction']}"
        print("\n所有断言通过")
    else:
        print(f"\n解析失败，原因: {result['reason']}")
