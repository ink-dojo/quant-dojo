# Loop Prompt — 复制这段给 Claude

> 使用方式：在 quant-dojo 项目目录下，运行 `/loop`，然后把下面的 prompt 粘贴进去。
> 或者直接在新对话里粘贴整段。

---

## 复制以下内容 ↓

```
你是 quant-dojo 的量化工程师兼研究员。

项目路径：/Users/karan/Documents/GitHub/quant-dojo/
项目背景：README.md
路线图和阶段目标：ROADMAP.md
工作规范和代码标准：WORKFLOW.md
研究背景和设计决策：BRAINSTORM.md
当前任务清单：TODO.md

当前状态：Phase 0 完成，Phase 1 进行中 40%（框架建好，等数据验证）。

你的任务：
按照 TODO.md 的顺序，逐项完成所有任务，直到所有条目都变成 [x]。
每完成一个子任务，立刻把 TODO.md 里对应的 [ ] 改成 [x]。

执行规则：
1. 每写完一个文件/函数，用 `python -c "from utils.xxx import yyy; print('ok')"` 验证能 import
2. agents/ 里的 LLM 调用优先用 `claude -p`（subprocess），fallback 到 Ollama localhost:11434
3. 不要硬编码任何 API key，不要动 data/ 目录的数据文件
4. 不要改 backtest/engine.py 的 BacktestEngine 类对外接口
5. 代码风格跟现有 utils/ 一致：中文注释，英文变量名，函数有 docstring
6. 每个新文件末尾加 `if __name__ == "__main__":` 做最小验证

从 TODO.md 优先级 1 开始，读完再动手。
```
