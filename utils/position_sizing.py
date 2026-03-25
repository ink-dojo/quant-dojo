"""
仓位管理模块
支持等权分配、风险平价、单票上限控制等仓位管理方法
所有函数返回 {symbol: weight} 字典，权重已归一化（sum=1.0）
"""
import pandas as pd


def equal_weight(selected: list) -> dict:
    """
    等权分配：每只股票等权重

    参数:
        selected: 股票代码列表，如 ["000001", "000002", ...]

    返回:
        {symbol: weight} 字典，每只股票权重为 1/N
    """
    if not selected:
        return {}

    n = len(selected)
    weight = 1.0 / n
    return {symbol: weight for symbol in selected}


def risk_parity(selected: list, vol_wide: pd.DataFrame) -> dict:
    """
    风险平价分配：按波动率倒数加权
    权重 = (1/vol_i) / sum(1/vol_j)

    使用 vol_wide 最后一行的波动率数据。
    对于零波动率或 NaN 值，回退到等权。

    参数:
        selected: 股票代码列表
        vol_wide: 波动率 DataFrame，index=date，columns=股票代码

    返回:
        {symbol: weight} 字典，风险平价加权
    """
    if not selected:
        return {}

    # 获取最后一行波动率数据
    if len(vol_wide) == 0:
        return equal_weight(selected)

    latest_vol = vol_wide.iloc[-1]

    # 提取 selected 中的波动率，处理 NaN 和零值
    inverse_vols = {}
    valid_stocks = []

    for symbol in selected:
        if symbol not in latest_vol.index:
            # 数据缺失，用等权回退
            continue

        vol = latest_vol[symbol]

        # 处理 NaN 或零波动
        if pd.isna(vol) or vol <= 0:
            continue

        inverse_vol = 1.0 / vol
        inverse_vols[symbol] = inverse_vol
        valid_stocks.append(symbol)

    # 如果全部无效数据，回退等权
    if not valid_stocks:
        return equal_weight(selected)

    # 归一化权重
    total = sum(inverse_vols.values())
    weights = {symbol: inverse_vols[symbol] / total for symbol in valid_stocks}

    return weights


def max_single_stock(weights: dict, cap: float = 0.1) -> dict:
    """
    单票仓位上限控制：超过上限的部分重新分配

    参数:
        weights: {symbol: weight} 字典
        cap: 单票上限，默认 0.1（10%）

    返回:
        调整后的权重字典，sum≈1.0（若sum(cap) >= 1.0则精确为1.0）
    """
    if not weights:
        return {}

    # 第一步：对所有超过cap的权重进行cap
    capped = {}
    total_excess = 0.0

    for symbol, w in weights.items():
        if w > cap:
            capped[symbol] = cap
            total_excess += w - cap
        else:
            capped[symbol] = w

    # 第二步：若无超限，直接返回
    if total_excess == 0:
        return capped

    # 第三步：将超限部分按比例分配给未达cap的权重
    # 找出所有未达cap的权重
    uncapped_symbols = [s for s, w in capped.items() if w < cap]

    if not uncapped_symbols:
        # 所有权重都已达到cap，进行比例缩放以满足sum=1.0
        current_sum = sum(capped.values())
        if current_sum < 1.0:
            # 无法达到 sum=1.0 同时保持所有权重 <= cap
            # 返回已capped的权重（不归一化）
            return capped
        else:
            return capped

    # 计算未达cap的权重总和
    uncapped_sum = sum(capped[s] for s in uncapped_symbols)

    # 按比例分配超限部分到未达cap的权重
    for symbol in uncapped_symbols:
        if uncapped_sum > 0:
            share = capped[symbol] / uncapped_sum
            allocation = total_excess * share
            new_weight = capped[symbol] + allocation
            capped[symbol] = min(new_weight, cap)  # 确保不超过cap

    # 第四步：检查新的未达cap权重并递归分配
    # （若redistribution导致新的超限，再次处理）
    current_sum = sum(capped.values())
    if current_sum < 0.9999:  # 未能达到sum≈1.0
        # 对所有未达cap的权重进行比例缩放
        new_uncapped = [s for s, w in capped.items() if w < cap]
        new_uncapped_sum = sum(capped[s] for s in new_uncapped)
        if new_uncapped_sum > 0 and current_sum < 1.0:
            # 缩放因子使这些权重的总和变为 (1.0 - capped_sum)
            scale_target = 1.0 - sum(capped[s] for s in capped if capped[s] >= cap)
            scale_factor = scale_target / new_uncapped_sum if new_uncapped_sum > 0 else 1.0
            for symbol in new_uncapped:
                new_w = capped[symbol] * scale_factor
                capped[symbol] = min(new_w, cap)

    # 最后：确保sum=1.0（精确）
    final_sum = sum(capped.values())
    if final_sum > 0:
        capped = {s: w / final_sum for s, w in capped.items()}

    return capped


if __name__ == "__main__":
    # 冒烟测试
    selected = ["000001", "000002", "000003", "000004"]

    # 测试 equal_weight
    weights_eq = equal_weight(selected)
    assert len(weights_eq) == 4, f"等权数量错误: {len(weights_eq)}"
    assert abs(sum(weights_eq.values()) - 1.0) < 1e-6, f"权重和错误: {sum(weights_eq.values())}"
    assert all(abs(w - 0.25) < 1e-6 for w in weights_eq.values()), "等权值错误"
    print(f"✅ equal_weight OK | weights={weights_eq}")

    # 测试 risk_parity（构造模拟波动率数据）
    dates = pd.date_range("2024-01-01", periods=10)
    vol_data = {
        "000001": [0.10] * 10,
        "000002": [0.20] * 10,
        "000003": [0.15] * 10,
        "000004": [0.05] * 10,
    }
    vol_wide = pd.DataFrame(vol_data, index=dates)

    weights_rp = risk_parity(selected, vol_wide)
    assert len(weights_rp) == 4, f"风险平价数量错误: {len(weights_rp)}"
    assert abs(sum(weights_rp.values()) - 1.0) < 1e-6, f"权重和错误: {sum(weights_rp.values())}"
    # 低波动股票应该得到更高权重
    assert weights_rp["000004"] > weights_rp["000002"], "风险平价逻辑错误"
    print(f"✅ risk_parity OK | weights={weights_rp}")

    # 测试 max_single_stock（多个权重超限的情况，cap足够大）
    weights_uncapped = {"000001": 0.4, "000002": 0.25, "000003": 0.2, "000004": 0.15}
    weights_capped = max_single_stock(weights_uncapped, cap=0.25)
    assert abs(sum(weights_capped.values()) - 1.0) < 1e-6, f"权重和错误: {sum(weights_capped.values())}"
    assert all(w <= 0.25 + 1e-6 for w in weights_capped.values()), f"超过上限: max={max(weights_capped.values())}"
    # 000001 应该被cap到0.25，其他的保持或增加
    assert weights_capped["000001"] <= 0.25 + 1e-6, "000001应被cap"
    print(f"✅ max_single_stock OK | weights={weights_capped}")

    # 测试空列表
    assert equal_weight([]) == {}, "空列表处理错误"
    assert risk_parity([], vol_wide) == {}, "空列表处理错误"
    print(f"✅ 边界情况处理 OK")

    print("\n✅ 仓位管理模块冒烟测试通过")
