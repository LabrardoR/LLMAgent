from langchain.tools import tool


@tool
def calculator_tool(expression: str) -> str:
    """
    一个简单的计算器工具，可以执行数学表达式。
    例如: '2+3*4'
    """
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"
