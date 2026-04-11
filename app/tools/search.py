"""
app/tools/search.py
"""

from __future__ import annotations

from langchain.tools import tool
from duckduckgo_search import DDGS


@tool("search")
def search_tool(query: str) -> str:
    """
    一个网络搜索工具，用来补充实时信息。
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as exc:
        return f"Search error: {exc}"

    if not results:
        return "No search results found."

    lines = []
    for index, item in enumerate(results, 1):
        title = item.get("title", "")
        body = item.get("body", "")
        href = item.get("href", "")
        lines.append(f"[{index}] 标题: {title}\n摘要: {body}\n链接: {href}")
    return "\n\n".join(lines)
