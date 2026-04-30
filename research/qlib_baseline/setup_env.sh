#!/usr/bin/env bash
# qlib_baseline 隔离环境装机脚本
# 用法: ./research/qlib_baseline/setup_env.sh
#
# 设计要点:
#   - 用独立 venv (research/qlib_baseline/.venv)，不污染主项目 quant-dojo 环境
#   - libomp 是 lightgbm macOS 运行时硬依赖，brew 安装
#   - cn_data v3 从 qlib 官方 yahoo 镜像下载，~230MB，截止 2022-12-30
#
# 跑完之后可以:
#   source research/qlib_baseline/.venv/bin/activate
#   python research/qlib_baseline/verify_data.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/research/qlib_baseline/.venv"

if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
pip install --upgrade pip wheel setuptools -q
pip install pyqlib lightgbm -q

if ! brew list libomp >/dev/null 2>&1; then
    brew install libomp
fi

if [ ! -d "$HOME/.qlib/qlib_data/cn_data" ]; then
    python -c "
from qlib.tests.data import GetData
GetData().qlib_data(
    target_dir='$HOME/.qlib/qlib_data/cn_data',
    region='cn',
    interval='1d',
    version='v3',
    delete_old=False,
    exists_skip=True,
)
"
fi

echo "[setup_env] done. activate via: source $VENV/bin/activate"
