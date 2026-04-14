from __future__ import annotations

import re

from langchain.tools import tool


@tool("text_inspector")
def text_inspector_tool(text: str) -> str:
    """分析文本的长度、段落、链接、邮箱和数字信息，适合快速检查输入内容。"""
    normalized = text or ""
    lines = [line for line in normalized.splitlines() if line.strip()]
    urls = re.findall(r"https?://[^\s]+", normalized)
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", normalized)
    numbers = re.findall(r"\d+(?:\.\d+)?", normalized)

    return (
        f"字符数: {len(normalized)}\n"
        f"非空行数: {len(lines)}\n"
        f"URL 数量: {len(urls)}\n"
        f"邮箱数量: {len(emails)}\n"
        f"数字数量: {len(numbers)}\n"
        f"前 3 个 URL: {urls[:3]}\n"
        f"前 3 个邮箱: {emails[:3]}"
    )


def register_tool():
    return text_inspector_tool
