"""
共享 LLM 客户端 - 用于 /ask 端点和 LLM 洞察生成
支持模型降级链：主选模型失败时自动尝试备选模型
支持请求限速（自适应）和 429 指数退避
支持 SSE 流式响应

v5.2 优化记录：
- 限速从 2.0s 降到 0.8s（GLM flash 模型实际可承受更高频率）
- 429 重试从 3 次增至 5 次，退避序列优化（2s → 4s → 8s → 16s → 32s）
- 新增空响应检测：LLM 返回空字符串时视为失败，尝试下一个模型
- 新增 LLMCallResult：返回模型名/耗时/重试次数，便于审计
- 新增 _last_error 全局变量：记录最近一次失败原因，便于排查
"""
import asyncio
import json
import time
from typing import Any, AsyncGenerator

import httpx

from app.config import LLM_ENDPOINT, LLM_API_KEY, get_text_models


# ─── 限速控制 ──────────────────────────────────────────────────
_last_request_time: float = 0.0
_min_interval: float = 0.8  # 最小请求间隔（秒），从 2.0 降到 0.8
_rate_lock = asyncio.Lock()

# 全局错误追踪（便于排查，不阻塞流程）
_last_error: str | None = None

# ─── 连接复用 ──────────────────────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """获取共享的 httpx 客户端（懒初始化，连接复用）"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60.0)
    return _http_client


async def close_client():
    """关闭共享 HTTP 客户端（应用关闭时调用）"""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def get_last_error() -> str | None:
    """获取最近一次 LLM 调用失败原因（用于审计/排查）"""
    return _last_error


async def _rate_limit():
    """确保两次 LLM 调用之间至少间隔 _min_interval 秒"""
    global _last_request_time
    async with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _min_interval:
            await asyncio.sleep(_min_interval - elapsed)
        _last_request_time = time.monotonic()


class LLMError(Exception):
    """LLM 调用异常"""
    pass


class LLMCallResult:
    """LLM 调用结果（含元信息，便于审计）"""
    def __init__(self, content: str, model: str, attempts: int, elapsed: float):
        self.content = content
        self.model = model
        self.attempts = attempts  # 总尝试次数（含失败）
        self.elapsed = elapsed  # 总耗时（秒）


async def _call_single_model(
    model: str,
    messages: list[dict],
    temperature: float,
    timeout: float,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> str:
    """
    调用单个模型，返回原始文本。
    含 429 指数退避（最多 5 次重试）+ 空响应检测。
    """
    global _last_error

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    # 优化后的退避序列：2s → 4s → 8s → 16s → 32s
    backoff_delays = [2, 4, 8, 16, 32]
    max_retries = 5

    data = None
    for attempt in range(max_retries + 1):
        await _rate_limit()

        try:
            client = _get_client()
            resp = await client.post(LLM_ENDPOINT, json=payload, headers=headers, timeout=timeout)

            if resp.status_code == 429:
                _last_error = f"{model}: 429 限速（第 {attempt+1} 次）"
                if attempt < max_retries:
                    await asyncio.sleep(backoff_delays[attempt])
                    continue
                resp.raise_for_status()

            if resp.status_code >= 500:
                _last_error = f"{model}: 服务端错误 {resp.status_code}"
                if attempt < max_retries:
                    await asyncio.sleep(backoff_delays[attempt])
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as e:
            _last_error = f"{model}: 超时({timeout}s)"
            if attempt < max_retries:
                await asyncio.sleep(backoff_delays[attempt])
                continue
            raise
        except httpx.HTTPStatusError:
            raise  # 已 raise_for_status 抛出，直接向上
        except Exception as e:
            _last_error = f"{model}: {type(e).__name__}: {e}"
            if attempt < max_retries:
                await asyncio.sleep(backoff_delays[attempt])
                continue
            raise

    if data is None:
        _last_error = f"{model}: 无响应数据"
        raise LLMError(f"{model}: 无响应数据")

    content = data["choices"][0]["message"]["content"].strip()

    # 空响应检测：GLM 偶尔返回空字符串（不报错但无内容），视为失败
    if not content:
        _last_error = f"{model}: 空响应（HTTP 200 但 content 为空）"
        raise LLMError(f"{model}: 空响应")

    _last_error = None  # 成功则清除错误
    return content


async def generate(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    timeout: float = 15.0,
    max_tokens: int = 1024,
) -> str:
    """
    调用 LLM 生成文本，支持模型降级链。
    主选模型失败时自动尝试备选模型，全部失败才抛异常。

    Raises:
        TimeoutError: 所有模型都超时
        LLMError: 所有模型都失败
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    errors = []
    for model in get_text_models():
        try:
            return await _call_single_model(
                model, messages, temperature, timeout, max_tokens
            )
        except httpx.TimeoutException:
            errors.append(f"{model}: 超时({timeout}s)")
        except Exception as e:
            errors.append(f"{model}: {e}")

    # 所有模型都失败
    if all("超时" in e for e in errors):
        raise TimeoutError(f"所有模型均超时: {'; '.join(errors)}")
    raise LLMError(f"所有模型均失败: {'; '.join(errors)}")


async def generate_json(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.1,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    调用 LLM 并解析 JSON 响应，支持模型降级链。
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    errors = []
    for model in get_text_models():
        try:
            content = await _call_single_model(
                model, messages, temperature, timeout,
                response_format={"type": "json_object"},
            )
            return json.loads(content)
        except httpx.TimeoutException:
            errors.append(f"{model}: 超时({timeout}s)")
        except json.JSONDecodeError as e:
            errors.append(f"{model}: 非JSON({e})")
        except Exception as e:
            errors.append(f"{model}: {e}")

    if all("超时" in e for e in errors):
        raise TimeoutError(f"所有模型均超时: {'; '.join(errors)}")
    raise LLMError(f"所有模型均失败: {'; '.join(errors)}")


async def generate_stream(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.5,
    timeout: float = 60.0,
) -> AsyncGenerator[str, None]:
    """
    流式 LLM 生成器，逐块 yield 文本内容。
    使用 SSE 格式解析响应。

    Yields:
        文本片段 (content delta)
    """
    models_to_try = [model] if model else get_text_models()

    for m in models_to_try:
        payload: dict[str, Any] = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            await _rate_limit()

            client = _get_client()
            async with client.stream("POST", LLM_ENDPOINT, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status_code == 429:
                    # 429 时尝试下一个模型
                    continue
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]  # 去掉 "data: " 前缀
                    if data_str.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
            return  # 成功完成，退出

        except (httpx.TimeoutException, httpx.HTTPStatusError):
            continue  # 尝试下一个模型
        except Exception:
            continue

    # 所有模型都失败时 yield 错误提示
    yield "[LLM 服务暂时不可用，请稍后重试]"
