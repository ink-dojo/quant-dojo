"""
数据新鲜度检查模块

检查数据目录中 CSV 文件的更新情况，包括：
- 最新交易日期
- 数据陈旧天数
- 缺失的股票代码
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import re
import random


def check_data_freshness(data_dir: str = "/Users/karan/Desktop/20260320/") -> dict:
    """
    检查数据目录的新鲜度和完整性。

    Args:
        data_dir: 数据目录路径，默认 /Users/karan/Desktop/20260320/

    Returns:
        dict: {
            'latest_date': '2026-03-20',  # 最新的交易日期
            'days_stale': 2,               # 距离今天的天数
            'missing_symbols': [],         # 缺失的股票代码
            'missing_count': 0,            # 缺失数量
            'sampled_files': 100,          # 采样的文件数
            'status': 'ok'                 # ok | stale | missing
        }
    """

    # 检查目录是否存在
    if not os.path.exists(data_dir):
        return {
            'latest_date': None,
            'days_stale': None,
            'missing_symbols': [],
            'missing_count': 0,
            'sampled_files': 0,
            'status': 'missing'
        }

    # 扫描 CSV 文件
    csv_pattern = re.compile(r'^(sh|sz)\.(\d+)\.csv$')
    csv_files = []
    symbols = set()

    for filename in os.listdir(data_dir):
        match = csv_pattern.match(filename)
        if match:
            csv_files.append(filename)
            symbols.add(filename)

    if not csv_files:
        return {
            'latest_date': None,
            'days_stale': None,
            'missing_symbols': [],
            'missing_count': 0,
            'sampled_files': 0,
            'status': 'missing'
        }

    # 性能优化：采样 100 个文件而不是全部读取
    sample_size = min(100, len(csv_files))
    sampled_files = random.sample(csv_files, sample_size)

    latest_date = None

    # 读取每个采样文件的最后一行
    for filename in sampled_files:
        filepath = os.path.join(data_dir, filename)
        try:
            # 读取最后一行（仅需第一列：交易所行情日期）
            df = pd.read_csv(filepath, usecols=['交易所行情日期'], dtype={'交易所行情日期': str})
            if len(df) > 0:
                last_date_str = df.iloc[-1, 0]
                last_date = datetime.strptime(last_date_str, '%Y-%m-%d').date()

                if latest_date is None or last_date > latest_date:
                    latest_date = last_date
        except Exception as e:
            # 跳过读取失败的文件
            continue

    # 计算天数
    days_stale = None
    if latest_date:
        today = datetime.now().date()
        days_stale = (today - latest_date).days

    # 检查缺失符号
    # 期望约 5477 个符号（3500 上海 + 2000 深圳 的近似）
    expected_symbols = 5477
    missing_count = max(0, expected_symbols - len(csv_files))
    missing_symbols = [] if missing_count <= 100 else [f"缺失 {missing_count} 个符号"]

    # 判断状态
    if days_stale is None:
        status = 'missing'
    elif missing_count > 100:
        status = 'missing'
    elif days_stale > 3:
        status = 'stale'
    else:
        status = 'ok'

    return {
        'latest_date': latest_date.isoformat() if latest_date else None,
        'days_stale': days_stale,
        'missing_symbols': missing_symbols,
        'missing_count': missing_count,
        'sampled_files': sample_size,
        'status': status
    }


if __name__ == "__main__":
    result = check_data_freshness()

    print("=" * 50)
    print("数据新鲜度检查报告")
    print("=" * 50)
    print(f"最新交易日期：{result['latest_date']}")
    print(f"数据陈旧天数：{result['days_stale']}")
    print(f"采样文件数：{result['sampled_files']}")
    print(f"缺失符号数：{result['missing_count']}")
    print(f"状态：{result['status'].upper()}")

    if result['missing_symbols']:
        print(f"异常：{result['missing_symbols']}")
    print("=" * 50)
