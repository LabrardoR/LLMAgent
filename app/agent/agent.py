"""
Agent 组装模块。

职责：
1) 管理用户可选模型；
2) 管理内置工具与扩展工具；
3) 根据用户设置动态构建 LangChain Agent；
4) 为 Agent 注入系统级决策提示词。
"""

from langchain_community.chat_models import ChatTongyi
from langchain_core.tools import Tool, BaseTool
from langchain_core.messages import SystemMessage
from pathlib import Path
import importlib.util
import os

from app.tools.calculator import calculator_tool
from app.tools.search import search_tool
from app.tools.database import database_tool


AVAILABLE_MODELS = [
    {"model_name": "qwen-turbo", "provider": "dashscope"},
    {"model_name": "qwen-plus", "provider": "dashscope"},
    {"model_name": "qwen-max", "provider": "dashscope"},
]

_extension_tools: dict[str, BaseTool] = {}


def _load_extension_tools() -> None:
    """
    扫描并加载扩展工具目录中的工具。

    约定：
    - 每个扩展文件位于 app/tools/extensions/*.py；
    - 文件内提供 register_tool()，返回 BaseTool 实例；
    - 以 "_" 开头的文件视为内部文件，不参与加载。
    """
    _extension_tools.clear()
    ext_dir = Path("app/tools/extensions")
    if not ext_dir.exists():
        return
    for file in ext_dir.glob("*.py"):
        if file.name.startswith("_"):
            continue
        module_name = f"app.tools.extensions.{file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file)
        if spec is None or spec.loader is None:
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register_tool"):
                tool = module.register_tool()
                if isinstance(tool, BaseTool):
                    _extension_tools[tool.name] = tool
        except Exception:
            continue


def reload_extension_tools() -> list[dict]:
    """重新加载扩展工具并返回最新工具列表。"""
    _load_extension_tools()
    return get_available_tools()


def _builtin_tools(user_id: str | None = None) -> dict[str, BaseTool]:
    """
    构建内置工具集合。

    database 工具需要绑定 user_id，确保工具查询仅作用于当前用户数据。
    """
    tools: dict[str, BaseTool] = {
        "calculator": calculator_tool,
        "search": search_tool,
    }
    if user_id:
        tools["database"] = Tool(
            name="database",
            func=lambda query: database_tool.func(query, user_id=user_id),
            description=database_tool.description,
            coroutine=lambda query: database_tool.coroutine(query, user_id=user_id),
        )
    return tools


def get_available_tools() -> list[dict]:
    """返回当前系统可用工具元信息（内置 + 扩展）。"""
    _load_extension_tools()
    merged = {
        **_builtin_tools("placeholder"),
        **_extension_tools,
    }
    return [{"name": t.name, "description": t.description} for t in merged.values()]


async def get_selected_model(user_id: str) -> str:
    """获取用户当前选择模型，未设置时返回默认模型。"""
    from app.models.user_config import UserConfig
    from app.models.user import User

    try:
        user = await User.get_or_none(user_id=user_id)
        if not user:
            return "qwen-turbo"

        config = await UserConfig.get_or_none(user=user)
        if config and config.selected_model:
            return config.selected_model
    except Exception:
        pass

    return "qwen-turbo"


async def set_selected_model(user_id: str, model_name: str) -> None:
    """设置用户模型，并校验模型名是否合法。"""
    from app.models.user_config import UserConfig
    from app.models.user import User

    allowed = {m["model_name"] for m in AVAILABLE_MODELS}
    if model_name not in allowed:
        raise ValueError("model_not_supported")

    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise ValueError("user_not_found")

    config = await UserConfig.get_or_none(user=user)
    if config:
        config.selected_model = model_name
        await config.save()
    else:
        await UserConfig.create(user=user, selected_model=model_name)


async def get_tools_enabled(user_id: str) -> dict[str, bool]:
    """
    获取用户工具启用状态。

    若用户首次访问，则按当前可用工具初始化为全启用。
    新增工具时会自动补齐默认状态，避免旧用户缺失开关字段。
    """
    from app.models.user_config import UserConfig
    from app.models.user import User

    available_names = [item["name"] for item in get_available_tools()]

    try:
        user = await User.get_or_none(user_id=user_id)
        if not user:
            return {name: True for name in available_names}

        config = await UserConfig.get_or_none(user=user)
        if config and config.enabled_tools:
            enabled = config.enabled_tools
            # 补齐新增工具
            for name in available_names:
                enabled.setdefault(name, True)
            return enabled
    except Exception:
        pass

    return {name: True for name in available_names}


async def set_tool_enabled(user_id: str, tool_name: str, enabled: bool) -> None:
    """设置指定工具开关状态。"""
    from app.models.user_config import UserConfig
    from app.models.user import User

    allowed = {t["name"] for t in get_available_tools()}
    if tool_name not in allowed:
        raise ValueError("tool_not_supported")

    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise ValueError("user_not_found")

    config = await UserConfig.get_or_none(user=user)
    if config:
        if not config.enabled_tools:
            config.enabled_tools = {}
        config.enabled_tools[tool_name] = bool(enabled)
        await config.save()
    else:
        await UserConfig.create(
            user=user,
            enabled_tools={tool_name: bool(enabled)}
        )


async def get_agent(user_id: str | None = None, context_prompt: str = ""):
    """
    组装可执行的 Agent 实例。

    参数：
    - user_id: 用于读取用户模型与工具配置；
    - context_prompt: 由上层拼装的上下文（RAG/记忆等），注入 system prompt。

    返回一个支持 ainvoke 和 astream_events 的可调用对象。
    """
    tools = []
    available = _builtin_tools(user_id)
    _load_extension_tools()
    available.update(_extension_tools)
    enabled = {name: True for name in available.keys()}
    model_name = "qwen-turbo"
    if user_id:
        enabled = await get_tools_enabled(user_id)
        model_name = await get_selected_model(user_id)
    for name, tool in available.items():
        if enabled.get(name, True):
            tools.append(tool)

    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "")
    llm = ChatTongyi(
        model=model_name,
        dashscope_api_key=dashscope_api_key,
        streaming=True,
    )

    base_prompt = (
        "你是一个可调用工具的智能助手。\n"
        "你拥有以下能力：\n"
        "1. 短期记忆：你可以记住本次对话中的所有内容，用户不需要重复之前说过的话。\n"
        "2. 长期记忆：系统会为你提供用户的个人信息和偏好，这些信息可能来自之前的对话。\n"
        "3. 知识库：系统会为你提供相关的文档内容作为参考。\n"
        "4. 工具调用：在需要时，你可以调用工具来完成任务（如计算、搜索、查询数据库）。\n\n"
        "重要提示：\n"
        "- 如果长期记忆中有用户的个人信息，请在回答中自然地使用它们，表明你记得用户。\n"
        "- 优先使用已知信息给出准确答案，避免不必要的工具调用。\n"
        "- 如果外部上下文与用户问题冲突，请说明冲突并给出你的判断依据。\n"
        "- 当用户问及之前的对话内容时，请参考短期记忆中的对话历史来回答。"
    )
    system_prompt = f"{base_prompt}\n\n{context_prompt}".strip() if context_prompt else base_prompt

    # 使用简单的绑定工具方式
    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm

    # 返回一个包装对象，兼容 ainvoke 和 astream_events
    class SimpleAgent:
        def __init__(self, llm, system_prompt):
            self.llm = llm
            self.system_prompt = system_prompt

        async def ainvoke(self, inputs: dict):
            """同步调用接口"""
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = []
            if self.system_prompt:
                messages.append(SystemMessage(content=self.system_prompt))

            # 添加历史消息
            chat_history = inputs.get("chat_history", [])
            for msg in chat_history:
                if isinstance(msg, dict):
                    from langchain_core.messages import HumanMessage, AIMessage
                    role = msg.get("role")
                    content = msg.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
                else:
                    messages.append(msg)

            # 添加当前输入
            user_input = inputs.get("input", "")
            messages.append(HumanMessage(content=user_input))

            # 调用LLM
            response = await self.llm.ainvoke(messages)
            return {"output": response.content}

        async def astream_events(self, inputs: dict, version: str = "v2"):
            """流式调用接口"""
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

            messages = []
            if self.system_prompt:
                messages.append(SystemMessage(content=self.system_prompt))

            # 添加历史消息
            chat_history = inputs.get("chat_history", [])
            for msg in chat_history:
                if isinstance(msg, dict):
                    role = msg.get("role")
                    content = msg.get("content", "")
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
                else:
                    messages.append(msg)

            # 添加当前输入
            user_input = inputs.get("input", "")
            messages.append(HumanMessage(content=user_input))

            # 流式调用
            async for chunk in self.llm.astream(messages):
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": chunk}
                }

    return SimpleAgent(llm_with_tools, system_prompt)


AVAILABLE_TOOLS = get_available_tools()
