# CLAUDE.md — quant-dojo 项目规则

> 每次启动 Claude Code 自动加载。这里的规则优先于你的默认行为。

---

## 项目简介

A 股量化研究项目，目标是做出真正盈利的系统化策略。
三人团队：jialong（金融逻辑/因子设计）、xingyu（代码实现/框架）。
当前阶段：Phase 3（因子研究），详见 ROADMAP.md。

---

## 每次开始工作的强制流程

**不允许跳过任何一步，按顺序执行：**

### Step 1 — 拉取最新代码
```bash
# 确保用 SSH（HTTPS 在这台机器不行）
git remote set-url origin git@github.com:ink-dojo/quant-dojo.git
git pull origin main
```
如果有冲突，解决后再继续。

### Step 2 — 读上下文文件
按顺序读：
1. `ROADMAP.md` — 当前在哪个阶段
2. `TODO.md` — 当前具体任务
3. `WORKFLOW.md` — 代码和 git 规范
4. `BRAINSTORM.md` — 设计决策背景

### Step 3 — 为即将开始的任务创建 GitHub Issue

每个任务开工前必须先创建 Issue，然后移到 In Progress：

```bash
# 1. 创建 issue
ISSUE_URL=$(gh issue create \
  --repo ink-dojo/quant-dojo \
  --title "任务标题" \
  --body "## 目标\n\n## 完成标准\n\n## 关联 TODO\nTODO.md 第X项" \
  --label "research"  # 或 feat / fix / docs \
)
ISSUE_NUM=$(echo $ISSUE_URL | grep -o '[0-9]*$')

# 2. 加入 kanban
ITEM_ID=$(gh project item-add 2 \
  --owner ink-dojo \
  --url $ISSUE_URL \
  --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 3. 移到 In Progress
gh project item-edit \
  --project-id PVT_kwDOEAhsB84BSCnq \
  --id $ITEM_ID \
  --field-id PVTSSF_lADOEAhsB84BSCnqzg_sOx8 \
  --single-select-option-id 47fc9ee4
```

### Step 4 — 直接在 main 上 commit + push

**不再切 feature / research 分支**。commit message 里带 `Closes #编号` 即可，
push 到 main 之后 GitHub 会自动关闭 issue 并把 kanban 卡移到 Done。

```bash
# 确认当前在 main
git checkout main
git pull origin main

# 做你的修改 → 小步 commit（每个函数/章节一次）
git add <specific files>   # 不用 git add -A，避免误提交
git commit -m "feat: ...

Closes #${ISSUE_NUM}"

# push 即部署（Vercel 自动 deploy portfolio/）
git push origin main
```

**例外**：只有在做「大规模重构 / 真需要多轮 review 的实验」时才开分支 + PR。
日常研究、bug fix、portfolio 更新全部直接 main。

---

## Kanban 参考信息

- **Project ID**: `PVT_kwDOEAhsB84BSCnq`
- **Project URL**: https://github.com/orgs/ink-dojo/projects/2
- **Status Field ID**: `PVTSSF_lADOEAhsB84BSCnqzg_sOx8`

| 状态 | Option ID |
|------|-----------|
| Backlog | `f75ad846` |
| Ready | `61e4505c` |
| In Progress | `47fc9ee4` |
| In Review | `df73e18b` |
| Done | `98236657` |

| 优先级 Field ID | `PVTSSF_lADOEAhsB84BSCnqzg_sO4Y` |
|---|---|
| P0 | `79628723` |
| P1 | `0a877460` |
| P2 | `da944a9c` |

---

## 开工前环境自检（必跑）

```bash
pip install -e . -q
python -c "from utils import get_stock_history; from agents import LLMClient; print('✅ env ok')"
```

失败就先修环境，不要直接开始写代码。

---

## 写代码前先搜索

写任何新函数前，先确认 `utils/` 里没有现成的：

```bash
grep -r "关键词" utils/ strategies/ agents/
```

已有的直接复用，不要重复实现。

---

## 数据质量门（每次 load 数据后必查）

```python
assert df.shape[0] > 100, f"数据行数异常: {df.shape[0]}"
assert df.isnull().mean().max() < 0.1, f"缺失值过多: {df.isnull().mean().max():.1%}"
assert df.index.is_monotonic_increasing, "日期未排序"
print(f"✅ 数据质量 OK | 行数: {df.shape[0]} | 时间: {df.index[0].date()} ~ {df.index[-1].date()}")
```

---

## 小步提交原则

- 每完成一个函数 / 一个 notebook section 就 commit
- 不要等整个任务做完再一次性提交
- commit message 用中文，说清楚做了什么、为什么

---

## 工作结束前更新 journal

每次工作结束，在 `journal/weekly/` 当周文件里追加：
- 做了什么
- 发现了什么（结论/异常/坑）
- 下一步计划

格式参考 `journal/weekly/2026-W12.md`。

---

## 代码规则

### 语言和风格
- 注释用**中文**，变量名/函数名用**英文 snake_case**
- 每个函数必须有 docstring（中文说明参数和返回值）
- 每个新文件末尾加 `if __name__ == "__main__":` 做最小验证

### 必须复用的工具函数
- 数据加载 → `utils/data_loader.py`（不要重新写下载逻辑）
- 财务数据 → `utils/fundamental_loader.py`（建好后统一用这个）
- IC/分层回测 → `utils/factor_analysis.py`（`compute_ic_series`, `quintile_backtest` 等）
- 绩效指标 → `utils/metrics.py`
- 可视化 → `utils/plotting.py`

### 写完代码必须验证
```bash
python -c "from utils.xxx import yyy; print('✅ import ok')"
```
验证失败就修，不要跳过。

---

## 不能动的东西

| 禁止修改 | 原因 |
|----------|------|
| `backtest/engine.py` 的 `BacktestEngine.__init__` 和 `run` 签名 | notebooks 依赖这个接口 |
| `research/factors/polar_pv_factor/` 下任何文件 | 已完成的研究，不动 |
| `data/` 目录下的数据文件 | 不入 git，不要创建或删除 |
| `pyproject.toml` 的包结构 | editable install 依赖 |

---

## LLM / Agent 调用规则

- 优先用 `claude -p`（subprocess 调用，不需要 API key）
- fallback 顺序：`claude -p` → Ollama（localhost:11434）→ 报错提示用户配置
- **绝对不要**在代码里硬编码任何 API key
- Agent 相关代码放在 `agents/` 模块，不要混进 `utils/`

---

## Git 规范（来自 WORKFLOW.md）

```
feat: 新功能/新策略
fix: bug 修复
research: 研究性探索
docs: 文档更新
refactor: 重构
```

- **日常开发全部在 `main` 上 commit + push**（不切分支）
- 只有大型重构 / 多轮 review 的实验才切 `feature/` 分支
- `data/` 目录已在 `.gitignore`，不要强制 add

---

## 回测质量红线

写回测代码时，以下问题**不允许出现**：

1. **未来函数**：信号必须 `.shift(1)` 才能用于下一日交易
2. **幸存者偏差**：股票池必须用当时可用的成分股，不是现在的
3. **交易成本**：默认双边 0.3%（即单边 0.15%），必须扣除
4. **过拟合**：参数调优后必须在样本外（out-of-sample）验证

---

## 策略评审门槛（来自 WORKFLOW.md）

策略进入模拟盘前必须达到：
- 年化收益 > 15%
- 夏普比率 > 0.8
- 最大回撤 < 30%
- 回测时间跨度 > 3 年，覆盖牛熊

---

## Git 署名规则

- **禁止**在 commit message 里添加 `Co-Authored-By: Claude` 或任何 AI 署名
- commit 只署 jialong和xingyu 的名字
- 不经过明确同意，不得以任何形式在提交记录里留下 AI 的痕迹

---

## 任务完成后

每完成 TODO.md 里的一项：
1. 把 `[ ]` 改成 `[x]`
2. 如果影响了 ROADMAP.md 的某个里程碑，更新进度条
3. commit message 用中文描述做了什么、为什么
