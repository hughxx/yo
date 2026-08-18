#!/usr/bin/env python3
"""测试环境草稿接口集成验证。

执行顺序：
1. POST 新建唯一草稿；
2. 使用相同 doc_id 再次 POST，验证幂等返回；
3. PUT 更新同一草稿，验证更新接口。

脚本会在测试环境留下 1 条 pending 草稿，不会操作已有记录。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime

import requests
import urllib3


DEFAULT_BASE_URL = "https://coreinsight-beta.rnd.huawei.com/chat"


def parse_args():
    parser = argparse.ArgumentParser(description="验证测试环境草稿新建和更新接口")
    parser.add_argument("--user-id", default="w00899061", help="草稿所属用户")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="测试环境接口前缀")
    parser.add_argument("--verify-tls", action="store_true",
                        help="校验 HTTPS 证书；默认与 LocalToolkit 一致不校验")
    return parser.parse_args()


def request_json(session: requests.Session, method: str, url: str,
                 payload: dict, verify_tls: bool) -> dict:
    print(f"\n{method} {url}")
    print("请求：")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    try:
        response = session.request(
            method, url, json=payload, timeout=60, verify=verify_tls)
    except requests.RequestException as exc:
        raise AssertionError(f"请求失败：{exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"HTTP {response.status_code}，响应不是 JSON：{response.text[:500]}") from exc

    print(f"响应：HTTP {response.status_code}")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if response.status_code >= 400:
        raise AssertionError(
            f"HTTP 状态异常：{response.status_code}，{body.get('msg', '')}")
    # 当前平台统一信封使用 code=200；兼容草稿接口早期的 code=0。
    if not isinstance(body, dict) or body.get("code") not in (0, 200):
        raise AssertionError(f"业务响应失败：{body}")
    if not isinstance(body.get("data"), dict) or not body["data"].get("id"):
        raise AssertionError(f"响应缺少 data.id：{body}")
    return body


def main() -> int:
    args = parse_args()
    if not args.verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base_url = args.base_url.rstrip("/")
    doc_id = uuid.uuid4().hex
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    create_url = f"{base_url}/experience/draft/create"
    update_url = f"{base_url}/experience/draft/{doc_id}"

    create_payload = {
        "doc_id": doc_id,
        "user_id": args.user_id,
        "scene": "LocalToolkit草稿接口联调",
        "scene_id": "251",
        "title": f"[测试] 草稿接口联调 {stamp}",
        "summary": "这是草稿新建接口的测试正文。用于验证测试环境写入链路。",
        "experience": (
            "# 测试经验\n\n"
            "## 背景\n验证 LocalToolkit 草稿创建接口。\n\n"
            "## 操作\n创建草稿后，再调用更新接口覆盖完整内容。"
        ),
    }
    update_payload = {
        "user_id": args.user_id,
        "title": f"[测试-已更新] 草稿接口联调 {stamp}",
        "summary": "这是更新后的完整正文。若平台待确认经验中显示此内容，说明更新成功。",
        "experience": (
            "# 测试经验（已更新）\n\n"
            "## 背景\n验证 LocalToolkit 草稿更新接口。\n\n"
            "## 结果\n新建、幂等重试和更新接口均已通过。"
        ),
    }

    session = requests.Session()
    try:
        created = request_json(
            session, "POST", create_url, create_payload, args.verify_tls)
        if created["data"]["id"] != doc_id:
            raise AssertionError("新建接口返回的 data.id 与请求 doc_id 不一致")
        if created["data"].get("idempotent") is not False:
            raise AssertionError("首次创建应返回 idempotent=false")

        retried = request_json(
            session, "POST", create_url, create_payload, args.verify_tls)
        if retried["data"]["id"] != doc_id:
            raise AssertionError("幂等重试返回的 data.id 不一致")
        if retried["data"].get("idempotent") is not True:
            raise AssertionError("重复创建应返回 idempotent=true")

        updated = request_json(
            session, "PUT", update_url, update_payload, args.verify_tls)
        if updated["data"]["id"] != doc_id:
            raise AssertionError("更新接口返回的 data.id 与路径 doc_id 不一致")
    finally:
        session.close()

    print("\nPASS：草稿新建、幂等重试和更新接口均验证成功。")
    print(f"测试草稿 ID：{doc_id}")
    print("请使用对应测试用户在 beta 环境的待确认经验中检查最终内容。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAIL：{exc}", file=sys.stderr)
        raise SystemExit(1)
