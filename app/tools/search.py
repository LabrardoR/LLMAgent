"""
app/tools/search.py
"""
from langchain.tools import tool
from duckduckgo_search import DDGS


@tool
def search_tool(query: str) -> str:
    """
    一个网络搜索引擎工具，可以用来查找实时信息。
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            return "\n".join([str(r) for r in results])
    except Exception as e:
        return f"Error: {e}"
