"""
qlib bin 格式 writer (替代 GitHub 上 scripts/dump_bin.py, pip 包不带这个工具)

qlib bin 格式:
    {provider_uri}/
      ├── calendars/day.txt              每行一个日期 YYYY-MM-DD
      ├── instruments/<universe>.txt     每行 SYMBOL\tSTART\tEND (PIT-correct)
      └── features/<symbol_lower>/<feature>.day.bin
          二进制 float32 数组:
            [4 bytes uint32 = start_offset_in_calendar][values float32...]

参考: https://github.com/microsoft/qlib/blob/main/scripts/dump_bin.py

设计:
    - 输出目录是 SSD: /Volumes/Crucial X10/quant-dojo-data/qlib_bin/<dataset>/
    - 输入是 wide DataFrame (date × symbol per feature)
    - PIT universe 来自 tushare index_weight (历史成分股区间)
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pandas as pd

QLIB_SYMBOL_PREFIX = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}


def to_qlib_symbol(symbol: str) -> str:
    """000001 → SZ000001, 600000 → SH600000, 8/4 → BJ.

    qlib instrument naming: 上交所 6/9 开头 → SH, 深交所 0/3 开头 → SZ,
    北交所 4/8 开头 → BJ.
    """
    sym = symbol.split(".")[0]
    if sym.startswith(("60", "68", "9")):
        return f"SH{sym}"
    if sym.startswith(("00", "30", "20")):
        return f"SZ{sym}"
    if sym.startswith(("4", "8")):
        return f"BJ{sym}"
    raise ValueError(f"无法识别交易所前缀: {symbol}")


def write_calendar(out_dir: Path, dates: pd.DatetimeIndex) -> None:
    cal_dir = out_dir / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / "day.txt").write_text(
        "\n".join(d.strftime("%Y-%m-%d") for d in dates) + "\n"
    )


def write_instruments(
    out_dir: Path,
    universe_name: str,
    members: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]],
) -> None:
    """
    members: {qlib_symbol: [(start, end), ...]} — PIT-correct 多个区间允许
    """
    inst_dir = out_dir / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for sym, ranges in sorted(members.items()):
        for start, end in ranges:
            lines.append(
                f"{sym}\t{start.strftime('%Y-%m-%d')}\t{end.strftime('%Y-%m-%d')}"
            )
    (inst_dir / f"{universe_name}.txt").write_text("\n".join(lines) + "\n")


def write_feature(
    out_dir: Path,
    qlib_symbol: str,
    feature_name: str,
    series: pd.Series,
    calendar: pd.DatetimeIndex,
) -> None:
    """
    series.index 是 DatetimeIndex (该股票有数据的日期), values 是 float.
    qlib bin 格式: 第一个 4 字节 uint32 = start_offset (该 series 起始日在 calendar 里的位置),
    然后 N×float32 = 从 start_offset 起连续若干日的值。

    缺日填 NaN, qlib loader 会跳过。
    """
    cal_index = calendar.searchsorted(series.index, side="left")
    if len(series) == 0:
        return
    start_offset = int(cal_index[0])
    end_offset = int(cal_index[-1]) + 1
    full = pd.Series(np.nan, index=range(start_offset, end_offset), dtype="float32")
    for cal_pos, val in zip(cal_index, series.values):
        full[int(cal_pos)] = float(val) if pd.notna(val) else np.nan

    feat_dir = out_dir / "features" / qlib_symbol.lower()
    feat_dir.mkdir(parents=True, exist_ok=True)
    path = feat_dir / f"{feature_name}.day.bin"
    with open(path, "wb") as f:
        f.write(struct.pack("<I", start_offset))
        full.values.astype(np.float32).tofile(f)


def read_feature(
    out_dir: Path,
    qlib_symbol: str,
    feature_name: str,
    calendar: pd.DatetimeIndex,
) -> pd.Series:
    """读自家 dump 出的 bin 反向验证一致性."""
    path = out_dir / "features" / qlib_symbol.lower() / f"{feature_name}.day.bin"
    with open(path, "rb") as f:
        start_offset = struct.unpack("<I", f.read(4))[0]
        values = np.frombuffer(f.read(), dtype=np.float32)
    end_offset = start_offset + len(values)
    return pd.Series(values, index=calendar[start_offset:end_offset])


if __name__ == "__main__":
    # 自测: 合成 1 只股票 30 日 close 写 + 读, 验证一致
    import tempfile

    cal = pd.bdate_range("2024-01-02", periods=100)
    series = pd.Series(
        np.linspace(10.0, 20.0, 30, dtype=np.float32),
        index=cal[5:35],
    )
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        write_calendar(out, cal)
        write_instruments(out, "test", {"SH600000": [(cal[5], cal[34])]})
        write_feature(out, "SH600000", "close", series, cal)
        read_back = read_feature(out, "SH600000", "close", cal)
        assert (
            np.allclose(read_back.dropna().values, series.values, atol=1e-5)
        ), "读回不一致"
        print(f"✓ writer 自测通过 (写 30 日 close 读回 {read_back.notna().sum()} 个非空值)")
