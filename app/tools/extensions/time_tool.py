from datetime import datetime

from langchain.tools import tool


@tool
def time_tool(query: str = "") -> str:
    """返回当前本地时间字符串，格式为 YYYY-MM-DD HH:MM:SS。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_tool():
    return time_tool
