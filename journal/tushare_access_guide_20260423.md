# Tushare 访问方式与 token 管理 — 权威指南（2026-04-23）

> **为什么写这个**：过去多次误以为"10000 积分过期"而卡住工作。真实情况是：我们同时持有**两个 token**，分别走**两个不同的 endpoint**，互相不兼容。不理解这一点就会在 "token 无效" / "没有接口访问权限" / "Token 不对" 三种错误之间反复打转。此文档是所有后续 Claude 会话读 tushare 时的第一站。
>
> 本文档与 `tushare_data_inventory_20260420.md`（讲已经下了什么数据）是互补关系。那份讲存量，本份讲怎么调接口。

---

## 一句话总结

> **两个 token、两个 endpoint、必须配对使用**。交叉用一定失败。调之前先搞清楚**哪个接口走哪条路**。

---

## 1. Endpoint × Token 兼容矩阵

| # | Endpoint | URL | 兼容 token | 权限 |
|---|---|---|---|---|
| A | **官方** | `http://api.tushare.pro`（tushare 默认） | `725c8f6f...` (56 chars) | 基础：`cb_basic`、`ths_hot`、`trade_cal`、`daily`、`stock_basic`。**没有** `daily_basic`、`moneyflow`、`top_list`、`repurchase` 等研究常用接口（403）|
| B | **jiaoch 代理** | `http://jiaoch.site` | `38a05e6f...229d` (60 chars) | 全：10000 积分级别，研究因子用到的所有高权限接口（daily_basic / moneyflow / top_list / top_inst / repurchase / northbound / margin / financial / holder* 等）都能用 |

**交叉使用的失败信息**（便于排错）：

- 基础 token 送到 jiaoch → `"Token无效: Token不存在，请检查token是否正确"`
- 10000-pt token 送到官方 → `"您的token不对，请确认。"`
- 基础 token 送到官方的高权限接口 → `"抱歉，您没有接口(<name>)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。"`

---

## 2. jiaoch.site 代理怎么用

**本质**：别人把 10000 积分账号按周出租，调用地址换成 `jiaoch.site`，其余参数跟 tushare 官方一样。

### 调法 (1) — tushare SDK 改 http_url（**项目里的标准做法**）

```python
import tushare as ts

TOKEN = "38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d"
pro = ts.pro_api(TOKEN)
pro._DataApi__http_url = "http://jiaoch.site"   # 关键行，默认指向官方

df = pro.daily_basic(ts_code="000001.SZ", start_date="20260401", end_date="20260422")
```

项目里已经这样接了：
- `utils/tushare_loader.py:64`
- `scripts/bulk_download_tushare.py:176`
- `scripts/bulk_download_tushare_extras.py:120`

### 调法 (2) — 直接 HTTP POST（脱离 tushare 库，图中 PDF 的方式）

```python
import requests, pandas as pd

r = requests.post("http://jiaoch.site/daily", json={
    "api_name": "daily",
    "token":    "38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d",
    "params":   {"ts_code": "000001.SZ", "start_date": "20260401", "end_date": "20260422"},
    "fields":   "ts_code,trade_date,open,high,low,close,vol,amount",
}).json()
df = pd.DataFrame(r["data"]["items"], columns=r["data"]["fields"])
```

等价于 `curl -X POST http://jiaoch.site/<api_name> -H 'Content-Type: application/json' -d '{...}'`。用它当兜底：SDK 出问题（版本冲突、`_DataApi__http_url` 属性被改名）时仍然能绕过库直接拉。

### 调法 (3) — 通用行情（特殊）

```python
df = pro.pro_bar(ts_code="000001.SZ", adj="qfq", start_date="20260401",
                 end_date="20260422", api=pro)   # 加 api=pro
```

---

## 3. 租期 & 续租

- 当前租期：**2026-04-19 ~ 2026-04-25**（7 天）
- 04-25 之后 jiaoch token 作废，需要重新向出租方续租（一般是微信/QQ 群直购）
- 续租后新 token 也是 60 字节 hex，替换 `.env` 里原值即可；不用改代码
- 官方 725c token 是自注册账号，**不会过期**，但仅基础权限，**不能替代** 10000 积分 token 的用途

> **文档里如果看到"10000 积分过期了"的表述**：大概率是把**租期到期**误写成**积分过期**了，两个概念不同。本账号的"10000 积分"是出租方账号自带的权限等级，不会掉；到期的只是我们租用的 token 有效期。

---

## 4. .env 约定与当前现状

### 约定

```bash
# .env（不入 git，每台机器本地配）
TUSHARE_TOKEN=<jiaoch 10000-pt token, 60 chars>            # 日常因子研究用这个
# 官方基础 token 单独存，不通过 TUSHARE_TOKEN 环境变量暴露
```

### 2026-04-23 实际状态（**不符合约定**，会导致 `utils/tushare_loader.get_pro()` 报 "Token 无效"）

```bash
# TUSHARE_TOKEN=38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d   # ← 10000-pt (注释掉了)
TUSHARE_TOKEN=725c8f6fdec5ec0b5bb5b6aebb782ba9ef078f53788246cf6e505ee8          # ← 官方基础
PAPER_TRADE_TUSHARE_TOKEN=725c8f6fdec5ec0b5bb5b6aebb782ba9ef078f53788246cf6e505ee8
```

**症状**：
- `utils/tushare_loader.py` 把 `TUSHARE_TOKEN=725c...` 送到 jiaoch → 立刻 `"Token无效"`
- 任何依赖 `get_pro()` 拉 high-priv 数据的 live 脚本**全部死掉**
- 历史数据在 SSD 上（`data/raw/tushare/` → `/Volumes/Crucial X10/...`），不受影响

**修复**（以后见到这个状态要第一时间做）：

```bash
# 把两行顺序反过来
TUSHARE_TOKEN=38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d     # jiaoch, 到期 2026-04-25
# TUSHARE_TOKEN_OFFICIAL=725c8f6fdec5ec0b5bb5b6aebb782ba9ef078f53788246cf6e505ee8  # 官方基础,备用
PAPER_TRADE_TUSHARE_TOKEN=38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d
```

> Paper trade 的 token 按说也该用 jiaoch 的，否则每日 signal pipeline 里任何 high-priv 调用会崩。具体 `PAPER_TRADE_TUSHARE_TOKEN` 消费在哪几行，`grep -rn PAPER_TRADE_TUSHARE_TOKEN` 自查。

---

## 5. 速查：这个接口走哪个 token？

研究常用 API 的归属（基于 2026-04-23 实测）：

| API | 官方基础 (725c) | jiaoch 10000 (38a0) |
|---|---|---|
| `stock_basic` | ✅ | ✅ |
| `trade_cal` | ✅ | ✅ |
| `daily` (行情) | ✅ | ✅ |
| `cb_basic` (转债列表) | ✅ | ✅ |
| `ths_hot` (同花顺热榜) | ✅ | ✅ |
| `daily_basic` (估值/市值) | ❌ 403 | ✅ |
| `moneyflow` (个股资金流) | ❌ | ✅ |
| `top_list` / `top_inst` (龙虎榜) | ❌ | ✅ |
| `repurchase` (回购, DSR #30 主数据源) | ❌ | ✅ |
| `share_float` (限售解禁) | ❌ | ✅ |
| `moneyflow_hsgt` (北向汇总) | ❌ | ✅ |
| `fina_indicator` / `income` / `balancesheet` / `cashflow` | ❌ | ✅ |
| `dc_hot` / `stk_surv` / `suspend` / `stk_managers` / `limit_list` / `broker_recommend` | ❌ | ✅ |
| `block_trade` (大宗) | ❌ | ✅ |
| `index_weight` | ❌ | ✅ |

**经验法则**：日常因子/事件/资金流/基本面研究 → jiaoch。只拉个交易日历或行情 → 官方也行。

---

## 6. 30 秒 sanity check 脚本

任何时候怀疑 token / 代理是否正常，粘贴这段跑一下：

```python
# 保存为 scripts/check_tushare.py 或直接 python3 -c 粘贴
from pathlib import Path
env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

import tushare as ts

TESTS = {
    "active .env token (官方)":   (env["TUSHARE_TOKEN"], None),
    "10000pt (jiaoch)":            ("38a05e6fb1fa6b55cf261c32a2ee3f14e451a5bb48f80acaa6d9c539229d",
                                    "http://jiaoch.site"),
}
for label, (tok, url) in TESTS.items():
    pro = ts.pro_api(tok)
    if url: pro._DataApi__http_url = url
    try:
        df = pro.daily(ts_code="000001.SZ", start_date="20260420", end_date="20260422")
        # 高权限探针
        try:
            db = pro.daily_basic(ts_code="000001.SZ", start_date="20260420", end_date="20260422")
            hi = f"daily_basic={len(db)}"
        except Exception as e:
            hi = f"daily_basic FAIL({str(e)[:40]})"
        print(f"[{label}] len={len(tok)} daily={len(df)} | {hi}")
    except Exception as e:
        print(f"[{label}] FAIL: {str(e)[:100]}")
```

期望输出（两个 token 都有效时）：
```
[active .env token (官方)] len=56 daily=3 | daily_basic FAIL(没有接口...访问权限)
[10000pt (jiaoch)]         len=60 daily=3 | daily_basic=3
```

---

## 7. 常见坑与诊断路径

| 现象 | 可能原因 | 诊断 |
|---|---|---|
| `Token无效: Token不存在` | 把官方 token 送到了 jiaoch | `len(token)` → 56 还是 60？60 才是 jiaoch 兼容 |
| `您的token不对，请确认` | 把 jiaoch token 送到了官方 | 检查 `pro._DataApi__http_url`，应是 `http://jiaoch.site` |
| `您没有接口(xxx)访问权限` | token 本身有效但权限不够 | 对 jiaoch 仍报这个 → 租期过期 or 本身不含该接口；对官方报 → 要换 jiaoch |
| `403 / 5xx` 间歇 | jiaoch 共享账号限流 (200 次/分 + 同时 3 连接) | 降并发，加 `time.sleep(0.3)` |
| 返回 DataFrame 是空的但无报错 | tushare 版本太老 (某些接口 schema 变了) | `pip install -U tushare==1.4.21`（记录里固定版本） |

---

## 8. 与下游基础设施的关系

- **SSD 数据** (`/Volumes/Crucial X10/quant-dojo-data/tushare/`)：16h28m 全量拉完，≈ 2.5 GB, 18 模块。**做研究不需要调 API**，直接读 parquet 就行。需要 live refresh 才用 jiaoch。
- **paper trade** (`scripts/paper_trade_cron.sh` + `pipeline/*_signal.py`)：每日都要调 API 拉最新一日数据，**必须**用 jiaoch token，否则静默失败。
- **portfolio/**（Vercel 前端）：读的是已落地的 JSON，和 tushare 无关。

---

## 9. 给未来 Claude 会话的检查清单

开工前如果要碰 tushare live API，先跑一遍：

```bash
# 1. SSD 是否挂上
ls /Volumes/Crucial\ X10/ > /dev/null && echo "SSD ok"

# 2. .env 里 TUSHARE_TOKEN 是否是 jiaoch 兼容 token
python3 -c "from pathlib import Path; tok=[l.split('=',1)[1].strip() for l in Path('.env').read_text().splitlines() if l.startswith('TUSHARE_TOKEN=')]; print('len=', len(tok[0]) if tok else 'none', '→ need 60 for jiaoch')"

# 3. jiaoch 是否还在租期
python3 -c "from datetime import date; print('剩余天数:', (date(2026,4,25) - date.today()).days)"
```

三项齐了再写代码。少一项就解决完再写。

---

## 10. 关联文件 / 记录

- `utils/tushare_loader.py` — 项目内 tushare 统一入口（强制 jiaoch）
- `scripts/bulk_download_tushare.py` / `scripts/bulk_download_tushare_extras.py` — 历史大规模下载脚本
- `journal/tushare_data_inventory_20260420.md` — 已下载数据清单（2.5 GB 细目）
- `.env` — 实际 token 值（不入 git）
- `corrections/rules.md:stale-journal` / `corrections/rules.md:api-token-debug` — 之前踩过的坑规则

---

## 变更历史

- **2026-04-23**: 初版。起因：误信"10000 积分过期"的无根据说法，耗时验证后发现 jiaoch rental 2026-04-25 才到期，实际是 `.env` 里 TUSHARE_TOKEN 被换成官方基础 token 导致 `utils/tushare_loader.get_pro()` 失败。此后所有 tushare 相关疑问先查此文档。
