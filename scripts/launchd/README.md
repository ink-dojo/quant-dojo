# launchd plists for paper-trade cron

These are **reference copies** of the launchd agents installed to
`~/Library/LaunchAgents/`. Version-controlled so the schedule is
reproducible on a new machine.

## Schedule

| Plist | Trigger | What it runs |
|-------|---------|--------------|
| `dev.quantdojo.paper-trade-daily.plist` | Mon-Fri 09:30 local (= SH 21:30) | `scripts/paper_trade_cron.sh` |
| `dev.quantdojo.paper-trade-monthly.plist` | Day 1 of month 10:00 local | `scripts/paper_trade_monthly_cron.sh` |

## Install on a new machine

```bash
cp scripts/launchd/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.quantdojo.paper-trade-daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.quantdojo.paper-trade-monthly.plist
launchctl list | grep quantdojo   # 确认加载
```

## Constraints

- **User path hard-coded**: plists reference `/Users/karan/work/quant-dojo`. If
  repo lives elsewhere, search-replace before copying.
- **Python path hard-coded** in the wrapper scripts:
  `/opt/homebrew/opt/python@3.11/libexec/bin/python`. Check with `which python3`.
- **Sleep state**: launchd will NOT wake the Mac. If the machine is asleep at
  the trigger time, the job is **skipped** (not queued). After waking, run
  `python scripts/paper_trade_daily.py --date YYYY-MM-DD` manually to backfill.

## Management

```bash
# 下次触发时间 / 上次 exit code
launchctl print gui/$(id -u)/dev.quantdojo.paper-trade-daily | head

# 立即手动触发
launchctl kickstart gui/$(id -u)/dev.quantdojo.paper-trade-daily

# 卸载
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/dev.quantdojo.paper-trade-daily.plist

# 改完 plist 后重装
launchctl bootout  gui/$(id -u) ~/Library/LaunchAgents/dev.quantdojo.paper-trade-daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.quantdojo.paper-trade-daily.plist
```
