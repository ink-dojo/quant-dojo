"""一次性脚本：批量更新本地所有股票到指定日期。"""
import os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.baostock_provider import BaoStockProvider
from pipeline.data_update import _get_csv_path, _read_latest_date, _append_rows
from utils.runtime_config import get_local_data_dir

end_date = sys.argv[1] if len(sys.argv) > 1 else "2026-03-24"
data_dir = Path(get_local_data_dir())

pat = re.compile(r'^(sh|sz)\.(\d{6})\.csv$')
symbols = [pat.match(f).group(2) for f in sorted(os.listdir(data_dir)) if pat.match(f)]
print(f"共 {len(symbols)} 只，目标 {end_date}")

need = []
for sym in symbols:
    path = _get_csv_path(data_dir, sym)
    if path is None:
        continue
    latest = _read_latest_date(path)
    latest_str = str(latest)[:10] if latest is not None else None
    if latest_str is None or latest_str < end_date:
        need.append((sym, path, latest_str))
print(f"需更新: {len(need)}, 已最新: {len(symbols)-len(need)}")

if not need:
    print("全部已最新！"); sys.exit(0)

provider = BaoStockProvider()
ok, skip, fail = [], [], []
t0 = time.time()

for i, (sym, path, latest_str) in enumerate(need):
    try:
        since = latest_str if latest_str else "2020-01-01"
        df = provider.fetch_daily_history(sym, since, end_date)

        # 过滤掉已有的日期
        if latest_str and not df.empty:
            df = df[df["date"] > latest_str]

        if df.empty:
            skip.append(sym)
            continue

        _append_rows(path, df, is_new_file=False)
        ok.append(sym)

    except Exception as e:
        fail.append(sym)
        if len(fail) <= 3:
            print(f"  FAIL {sym}: {e}", flush=True)

    if (i+1) % 100 == 0:
        el = time.time()-t0; r = (i+1)/el; eta = (len(need)-i-1)/r/60
        print(f"  [{i+1}/{len(need)}] {r:.1f}/s ETA:{eta:.0f}m | OK:{len(ok)} SKIP:{len(skip)} FAIL:{len(fail)}", flush=True)

print(f"\n完成 {time.time()-t0:.0f}s | OK:{len(ok)} SKIP:{len(skip)} FAIL:{len(fail)}")
