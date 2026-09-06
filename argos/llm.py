"""LLM 客户端：OpenAI 兼容 chat completions，纯标准库实现（零新依赖）。

铁律不变：LLM 只提议（措辞 / 归纳），代码决定执行 —— 本模块不产生任何动作，
只出文本；失败（无 key / 断网 / 超时 / 非 2xx / 响应畸形）→ 抛 LlmError，
由调用方降级到规则话术（狗永远不会因为模型坏了而哑巴）。

key 来源优先级：环境变量 ARGOS_API_KEY > 仓库根 api_key.txt（已 gitignore）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-chat"

# User-Agent 必须自己给：urllib 默认是 "Python-urllib/3.x"，
# 被 Cloudflare 挡在门外（实测 2026-09-06：同一请求 curl 200 / urllib 403，
# 返回体是 Cloudflare 的 `error code: 1010`）。换掉 UA 立刻正常。
# 只要目标 API 前面有 CF，不设这个就永远 403 —— 表现为"LLM 静默降级到规则话术"。
_UA = "ArgOS-llm/1.0 (+https://github.com/LiSheng5/argos)"


class LlmError(Exception):
    """LLM 调用失败（调用方应降级到规则话术）。"""


def load_api_key() -> Optional[str]:
    """环境变量 > 仓库根 api_key.txt。拿不到 → None（调用方走纯规则）。"""
    env = os.environ.get("ARGOS_API_KEY", "").strip()
    if env:
        return env
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        f = base / "api_key.txt"
        try:
            v = f.read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            continue
    return None


class LlmClient:
    """最简 chat 客户端。enabled() = 有 key 才敢真发请求。"""

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        self.base_url = (base_url or os.environ.get("ARGOS_BASE_URL")
                         or _DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("ARGOS_MODEL") or _DEFAULT_MODEL
        self.api_key = api_key if api_key is not None else load_api_key()
        # 超时可配：推理型/慢模型（如 nemotron-3-ultra-free）生成 500 token 会超过
        # 默认 20s，读超时直接 LlmError → 静默降级规则话术。用 ARGOS_TIMEOUT 覆盖。
        self.timeout = (timeout if timeout is not None
                        else float(os.environ.get("ARGOS_TIMEOUT", "20") or 20))

    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str,
             max_tokens: int = 120, temperature: float = 0.7) -> str:
        """一次对话补全 → 助手文本。任何失败 → LlmError。"""
        if not self.api_key:
            raise LlmError("no api key")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": _UA},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LlmError(f"http {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LlmError(f"network: {exc}") from exc
        except ValueError as exc:          # 响应不是 JSON
            raise LlmError("bad response") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("bad response shape") from exc
        return str(text).strip()
