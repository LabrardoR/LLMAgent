"""
app/tools/calculator.py
"""
from langchain.tools import tool
import ast
import operator


@tool("calculator")
def calculator_tool(expression: str) -> str:
    """
    一个简单的计算器工具，可以执行数学表达式。
    例如: '2+3*4'
    支持: +, -, *, /, //, %, **
    """
    # 支持的安全操作符
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    def safe_eval(node):
        """安全地计算表达式节点"""
        if isinstance(node, ast.Num):  # 数字
            return node.n
        elif isinstance(node, ast.Constant):  # Python 3.8+ 常量
            return node.value
        elif isinstance(node, ast.BinOp):  # 二元操作符
            op_type = type(node.op)
            if op_type not in operators:
                raise ValueError(f"不支持的操作符: {op_type.__name__}")
            left = safe_eval(node.left)
            right = safe_eval(node.right)
            return operators[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):  # 一元操作符
            op_type = type(node.op)
            if op_type not in operators:
                raise ValueError(f"不支持的操作符: {op_type.__name__}")
            operand = safe_eval(node.operand)
            return operators[op_type](operand)
        else:
            raise ValueError(f"不支持的表达式类型: {type(node).__name__}")

    try:
        # 解析表达式为AST
        tree = ast.parse(expression, mode='eval')
        # 安全计算
        result = safe_eval(tree.body)
        return str(result)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as e:
        return f"计算错误: {e}"
    except Exception as e:
        return f"未知错误: {e}"
