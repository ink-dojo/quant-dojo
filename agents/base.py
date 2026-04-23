"""
Agent 基础模块
提供 LLM 客户端和 Agent 抽象基类
LLM 调用优先级：claude -p → Ollama → 报错
"""
import json
import os
import shutil
import subprocess
import warnings
from abc import ABC, abstractmethod

import requests


class LLMClient:
    """
    LLM 客户端，统一封装不同后端

    优先级：
        1. claude -p（Anthropic CLI，不需要 API key）
        2. Ollama（本地部署，localhost:11434）
        3. 报错提示用户配置

    使用示例:
        llm = LLMClient()
        response = llm.complete("分析一下平安银行的基本面")
        data = llm.complete_json("返回JSON格式的分析结果")
    """

    def __init__(
        self,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        claude_model: str | None = None,
    ):
        self.ollama_base_url = ollama_base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.ollama_model = ollama_model or os.environ.get(
            "OLLAMA_MODEL", "qwen2.5:7b"
        )
        # claude -p 默认继承 session 的 Opus, 贵 15×. 这里默认 haiku 避免烧钱.
        # 明确要高质量时, 调用方传 claude_model="opus" 或 "sonnet".
        self.claude_model = claude_model or os.environ.get("CLAUDE_CLI_MODEL", "haiku")
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        """检测可用的 LLM 后端"""
        # 优先用 claude CLI
        if shutil.which("claude"):
            return "claude"

        # 其次试 Ollama
        try:
            _detect_timeout = int(os.environ.get("OLLAMA_DETECT_TIMEOUT", "3"))
            resp = requests.get(
                f"{self.ollama_base_url}/api/tags", timeout=_detect_timeout
            )
            if resp.status_code == 200:
                return "ollama"
        except Exception:
            pass

        warnings.warn(
            "未检测到可用的 LLM 后端。"
            "请安装 claude CLI (npm install -g @anthropic-ai/claude-code) "
            "或启动 Ollama (ollama serve)。"
        )
        return "none"

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        """
        发送 prompt 并返回文本响应

        参数:
            prompt     : 输入提示
            max_tokens : 最大输出长度（仅 Ollama 生效）

        返回:
            LLM 的文本响应
        """
        if self._backend == "claude":
            return self._call_claude(prompt)
        elif self._backend == "ollama":
            return self._call_ollama(prompt, max_tokens)
        else:
            raise RuntimeError(
                "没有可用的 LLM 后端。"
                "请安装 claude CLI 或启动 Ollama。"
            )

    def complete_json(self, prompt: str) -> dict:
        """
        发送 prompt 并返回 JSON 字典

        参数:
            prompt : 输入提示（应明确要求返回 JSON）

        返回:
            解析后的 dict，解析失败时返回 {"error": "...", "raw": "..."}
        """
        # 在 prompt 末尾追加 JSON 格式要求
        json_prompt = (
            f"{prompt}\n\n"
            "请严格返回合法的 JSON 格式，不要包含 markdown 代码块或其他额外文本。"
        )
        raw = self.complete(json_prompt)

        # 尝试从响应中提取 JSON
        return self._parse_json(raw)

    def _call_claude(self, prompt: str) -> str:
        """通过 claude -p 子进程调用. 显式传 --model 防止继承 session 的 Opus (贵 15x)."""
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", self.claude_model, prompt],
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("CLAUDE_CLI_TIMEOUT", "120")),
            )
            if result.returncode != 0:
                raise RuntimeError(f"claude 调用失败: {result.stderr}")
            return result.stdout.strip()
        except FileNotFoundError:
            # claude 不在 PATH 了，fallback
            self._backend = "ollama"
            return self.complete(prompt)

    def _call_ollama(self, prompt: str, max_tokens: int = 2048) -> str:
        """通过 Ollama HTTP API 调用"""
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        try:
            resp = requests.post(
                url, json=payload,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", "120")),
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except Exception as e:
            raise RuntimeError(f"Ollama 调用失败: {e}")

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从 LLM 响应中提取 JSON"""
        # 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # 尝试找到第一个 { 到最后一个 }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        return {"error": "JSON 解析失败", "raw": text}


class BaseAgent(ABC):
    """
    Agent 抽象基类

    所有分析 Agent 继承此类，实现 analyze 方法。

    使用示例:
        class MyAgent(BaseAgent):
            def analyze(self, **kwargs) -> dict:
                prompt = f"分析 {kwargs['symbol']}"
                return self.llm.complete_json(prompt)

        agent = MyAgent(LLMClient())
        result = agent.analyze(symbol="000001")
        print(agent.format_report(result))
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    @abstractmethod
    def analyze(self, **kwargs) -> dict:
        """
        执行分析

        参数:
            **kwargs: 分析所需的输入参数

        返回:
            dict，分析结果
        """
        raise NotImplementedError

    def format_report(self, result: dict) -> str:
        """
        将分析结果格式化为 Markdown 报告

        参数:
            result : analyze() 返回的字典

        返回:
            Markdown 格式字符串
        """
        lines = []
        for key, value in result.items():
            if isinstance(value, list):
                lines.append(f"### {key}")
                for item in value:
                    lines.append(f"- {item}")
            elif isinstance(value, dict):
                lines.append(f"### {key}")
                for k, v in value.items():
                    lines.append(f"- **{k}**: {v}")
            else:
                lines.append(f"**{key}**: {value}")
            lines.append("")
        return "\n".join(lines)


if __name__ == "__main__":
    # 最小验证：检测后端
    llm = LLMClient()
    print(f"检测到 LLM 后端: {llm._backend}")

    if llm._backend != "none":
        resp = llm.complete("用一句话介绍平安银行")
        print(f"测试响应: {resp[:100]}...")
        print("✅ LLMClient 正常工作")
    else:
        print("⚠️ 没有可用后端，跳过调用测试")

    # 验证 BaseAgent 不能直接实例化
    try:
        BaseAgent(llm)
        print("❌ BaseAgent 不应该能直接实例化")
    except TypeError:
        print("✅ BaseAgent 抽象类验证通过")
