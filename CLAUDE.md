# CLAUDE.md — quant-dojo 项目规则

> 每次启动 Claude Code 自动加载。这里的规则优先于你的默认行为。

---

## 项目简介

A 股量化研究项目，目标是做出真正盈利的系统化策略。
三人团队：jialong（金融逻辑/因子设计）、xingyu（代码实现/框架）。
当前阶段：Phase 1（统计基础），详见 ROADMAP.md。

---

## 读文件的顺序

进入项目后，按这个顺序建立上下文：
1. `ROADMAP.md` — 当前在哪个阶段，下一步是什么
2. `TODO.md` — 当前具体任务
3. `WORKFLOW.md` — 代码和 git 规范
4. `BRAINSTORM.md` — 设计决策和研究背景

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

- 从 `dev` 切 `feature/` 或 `research/` 分支
- 不要直接 push 到 `main`，除非是文档类小改动
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
- commit 只署 jialong 的名字
- 不经过明确同意，不得以任何形式在提交记录里留下 AI 的痕迹

---

## 任务完成后

每完成 TODO.md 里的一项：
1. 把 `[ ]` 改成 `[x]`
2. 如果影响了 ROADMAP.md 的某个里程碑，更新进度条
3. commit message 用中文描述做了什么、为什么
