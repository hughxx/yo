"""测试 LLM tool call 真实返回，运行：python -m server.test_toolcall"""
import asyncio
import json
import httpx

from server.utils.settings import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_ID

TOOL = {
    "type": "function",
    "function": {
        "name": "save_result",
        "description": "保存一个结果",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "结果内容"}
            },
            "required": ["value"],
        },
    },
}

async def main():
    payload = {
        "model":       LLM_MODEL_ID,
        "messages":    [{"role": "user", "content": "请调用 save_result 工具，value 填写 'hello'"}],
        "temperature": 0.3,
        "tools":       [TOOL],
        "tool_choice": "auto",
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type":  "application/json",
    }
    url = f"{LLM_BASE_URL}/chat/completions"

    print(f"URL   : {url}")
    print(f"Model : {LLM_MODEL_ID}")
    print()

    async with httpx.AsyncClient(proxy=None, trust_env=False, verify=False) as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=60.0)

    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    print()
    print("Raw body:")
    print(resp.text)
    print()

    if resp.text.strip():
        try:
            data = json.loads(resp.text)
            print("Parsed JSON:")
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"JSON parse error: {e}")

asyncio.run(main())
