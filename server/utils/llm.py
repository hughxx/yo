import asyncio
import json
import logging
from typing import AsyncGenerator, Union

import httpx

from server.utils.settings import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_ID

logger = logging.getLogger(__name__)


async def chat_with_tools(
    messages: list,
    tools: list,
    temperature: float = 0.3,
) -> dict:
    """调用 LLM with tool use（OpenAI-compatible）。
    返回 assistant message dict，含 tool_calls 字段（可能为空列表）。
    """
    payload = {
        "model":        LLM_MODEL_ID,
        "messages":     messages,
        "temperature":  temperature,
        "tools":        tools,
        "tool_choice":  "auto",
        "stream":       False,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type":  "application/json",
    }
    url = f"{LLM_BASE_URL}/chat/completions"

    async with httpx.AsyncClient(proxy=None, trust_env=False, verify=False) as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=999.0)

    logger.info("chat_with_tools status=%s body_len=%d body_preview=%r",
                resp.status_code, len(resp.content), resp.text[:500])

    resp.raise_for_status()

    raw = resp.text.strip()
    if not raw:
        raise ValueError(f"chat_with_tools: empty response body (status={resp.status_code})")

    data = json.loads(raw)
    return data["choices"][0]["message"]


async def chat(
    messages: list,
    temperature: float = 0.3,
    stream: bool = False,
) -> Union[str, AsyncGenerator[str, None]]:
    """
    调用 LLM。
    ◦ stream=False：返回完整字符串

    ◦ stream=True ：返回异步生成器，逐段 yield 文本增量

    """
    payload = {
        "model": LLM_MODEL_ID,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{LLM_BASE_URL}/chat/completions"

    if not stream:
        async with httpx.AsyncClient(proxy=None, trust_env=False, verify=False) as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=999.0)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    # 流式：返回一个异步生成器
    async def _stream() -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(proxy=None, trust_env=False, verify=False) as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload, timeout=999.0
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue  # ← 末尾的 usage chunk 走这里跳过

                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    return _stream()


if __name__ == "__main__":
    test_messages = [
        {"role": "user", "content": "你好,请简单介绍一下你自己"}
    ]

    # ---- 用法 1：非流式 ----
    async def run_once():
        reply = await chat(test_messages)
        print("【非流式】", reply)

    asyncio.run(run_once())

    # ---- 用法 2：流式 ----
    async def run_stream():
        gen = await chat(test_messages, stream=True)
        print("【流式】", end="", flush=True)
        async for piece in gen:
            print(piece, end="", flush=True)
        print()

    asyncio.run(run_stream())
