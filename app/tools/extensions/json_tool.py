from __future__ import annotations

import json

from langchain.tools import tool


@tool("json_helper")
def json_helper_tool(json_text: str) -> str:
    """校验并格式化 JSON 文本，适合处理接口参数、配置片段和调试输入。"""
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return f"JSON 解析失败: line={exc.lineno}, column={exc.colno}, msg={exc.msg}"

    pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"JSON 有效。\n类型: {type(payload).__name__}\n格式化结果:\n{pretty}"


def register_tool():
    return json_helper_tool
