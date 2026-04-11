"""
Agent 组装模块。

职责：
1. 管理用户可选模型；
2. 管理内置工具和扩展工具；
3. 构建支持工具调用的简单 Agent；
4. 记录模型与工具使用日志，便于前端展示与排查问题。
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, Tool

from app.tools.calculator import calculator_tool
from app.tools.database import database_tool
from app.tools.search import search_tool

AVAILABLE_MODELS = [
    {"model_name": "auto", "provider": "system", "description": "根据问题复杂度自动选择模型"},
    {"model_name": "qwen-turbo", "provider": "dashscope", "description": "响应速度快，适合日常问答"},
    {"model_name": "qwen-plus", "provider": "dashscope", "description": "综合能力更强，适合复杂任务"},
    {"model_name": "qwen-max", "provider": "dashscope", "description": "适合复杂推理和长文本场景"},
]

_extension_tools: dict[str, BaseTool] = {}


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _load_extension_tools() -> None:
    """扫描扩展工具目录并动态加载工具。"""
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


def reload_extension_tools() -> list[dict[str, Any]]:
    _load_extension_tools()
    merged = _build_tool_catalog()
    return [item for item in merged.values()]


def _build_database_tool(user_id: str) -> BaseTool:
    return Tool(
        name="database",
        func=lambda query: database_tool.func(query, user_id=user_id),
        coroutine=lambda query: database_tool.coroutine(query, user_id=user_id),
        description=database_tool.description,
    )


def _build_tool_catalog(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    _load_extension_tools()

    tools: dict[str, BaseTool] = {
        "calculator": calculator_tool,
        "search": search_tool,
    }
    if user_id:
        tools["database"] = _build_database_tool(user_id)
    else:
        tools["database"] = database_tool

    tools.update(_extension_tools)

    return {
        name: {
            "name": tool.name,
            "description": tool.description,
            "builtin": name in {"calculator", "search", "database"},
            "extension": name not in {"calculator", "search", "database"},
        }
        for name, tool in tools.items()
    }


async def get_available_tools(user_id: str | None = None) -> list[dict[str, Any]]:
    """
    返回当前可用工具。

    如果传入 user_id，会同时返回工具开关状态。
    """
    catalog = _build_tool_catalog(user_id)
    if not user_id:
        return list(catalog.values())

    enabled = await get_tools_enabled(user_id)
    items: list[dict[str, Any]] = []
    for name, item in catalog.items():
        tool_item = dict(item)
        tool_item["enabled"] = bool(enabled.get(name, True))
        items.append(tool_item)
    return items


async def get_selected_model(user_id: str) -> str:
    from app.models.user import User
    from app.models.user_config import UserConfig

    user = await User.get_or_none(user_id=user_id)
    if not user:
        return "qwen-turbo"

    config = await UserConfig.get_or_none(user=user)
    if config and config.selected_model:
        return config.selected_model
    return "qwen-turbo"


async def set_selected_model(user_id: str, model_name: str) -> None:
    from app.models.user import User
    from app.models.user_config import UserConfig

    allowed = {item["model_name"] for item in AVAILABLE_MODELS}
    if model_name not in allowed:
        raise ValueError("model_not_supported")

    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise ValueError("user_not_found")

    config = await UserConfig.get_or_none(user=user)
    if config:
        config.selected_model = model_name
        await config.save()
        return

    await UserConfig.create(user=user, selected_model=model_name)


async def get_tools_enabled(user_id: str) -> dict[str, bool]:
    from app.models.user import User
    from app.models.user_config import UserConfig

    available_names = list(_build_tool_catalog(user_id).keys())
    user = await User.get_or_none(user_id=user_id)
    if not user:
        return {name: True for name in available_names}

    config = await UserConfig.get_or_none(user=user)
    if not config:
        return {name: True for name in available_names}

    enabled_tools = config.enabled_tools or {}
    changed = False
    for name in available_names:
        if name not in enabled_tools:
            enabled_tools[name] = True
            changed = True

    if changed:
        config.enabled_tools = enabled_tools
        await config.save()

    return enabled_tools


async def set_tool_enabled(user_id: str, tool_name: str, enabled: bool) -> None:
    from app.models.user import User
    from app.models.user_config import UserConfig

    allowed = set(_build_tool_catalog(user_id).keys())
    if tool_name not in allowed:
        raise ValueError("tool_not_supported")

    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise ValueError("user_not_found")

    config = await UserConfig.get_or_none(user=user)
    if not config:
        await UserConfig.create(user=user, enabled_tools={tool_name: bool(enabled)})
        return

    enabled_tools = config.enabled_tools or {}
    enabled_tools[tool_name] = bool(enabled)
    config.enabled_tools = enabled_tools
    await config.save()


def _resolve_model_name(selected_model: str, user_input: str, context_prompt: str) -> str:
    """
    简单的模型路由策略。

    auto 模式下优先保证稳定性和可理解性，因此只使用少量明确规则。
    """
    if selected_model != "auto":
        return selected_model

    text_size = len(user_input) + len(context_prompt)
    complex_keywords = ("总结", "分析", "对比", "规划", "方案", "代码", "调试", "设计", "RAG", "Agent")
    if text_size > 2500:
        return "qwen-max"
    if text_size > 1200 or any(word in user_input for word in complex_keywords):
        return "qwen-plus"
    return "qwen-turbo"


async def _log_tool_call(
    user_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
    tool_name: str,
    input_text: str,
    output_text: str,
    success: bool,
    latency_ms: int,
) -> None:
    if not user_id:
        return

    try:
        from app.models.tool_call_log import ToolCallLog

        await ToolCallLog.create(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            tool_name=tool_name,
            input_text=input_text[:4000],
            output_text=output_text[:4000],
            success=success,
            latency_ms=latency_ms,
        )
    except Exception:
        return


async def _log_chat_run(
    user_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
    selected_model: str,
    resolved_model: str,
    input_text: str,
    output_text: str,
    tool_count: int,
    reference_count: int,
    duration_ms: int,
) -> None:
    if not user_id:
        return

    try:
        from app.models.chat_run_log import ChatRunLog

        await ChatRunLog.create(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            selected_model=selected_model,
            resolved_model=resolved_model,
            input_chars=len(input_text),
            output_chars=len(output_text),
            tool_count=tool_count,
            reference_count=reference_count,
            duration_ms=duration_ms,
        )
    except Exception:
        return


async def _invoke_tool(tool: BaseTool, args: Any) -> str:
    try:
        result = await tool.ainvoke(args)
    except Exception:
        result = tool.invoke(args)

    if isinstance(result, str):
        return result
    return str(result)


async def get_agent(
    user_id: str | None = None,
    context_prompt: str = "",
    conversation_id: str | None = None,
    message_id: str | None = None,
    reference_count: int = 0,
):
    """
    返回一个支持 ainvoke 和 astream_events 的简单 Agent。

    这个 Agent 使用“模型 -> 工具执行 -> 模型”的循环，直到模型返回最终文本。
    """
    selected_model = "qwen-turbo"
    enabled = {name: True for name in _build_tool_catalog(user_id).keys()}
    if user_id:
        selected_model = await get_selected_model(user_id)
        enabled = await get_tools_enabled(user_id)

    resolved_model = _resolve_model_name(selected_model, "", context_prompt)
    available_tools: dict[str, BaseTool] = {
        "calculator": calculator_tool,
        "search": search_tool,
    }
    if user_id:
        available_tools["database"] = _build_database_tool(user_id)
    else:
        available_tools["database"] = database_tool
    _load_extension_tools()
    available_tools.update(_extension_tools)

    tool_map = {
        name: tool
        for name, tool in available_tools.items()
        if enabled.get(name, True)
    }
    tools = list(tool_map.values())

    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "")

    def _create_llm(model_name: str) -> ChatTongyi:
        return ChatTongyi(
            model=model_name,
            dashscope_api_key=dashscope_api_key,
            streaming=False,
        )

    base_prompt = (
        "你是一个可调用工具的智能助手。\n"
        "请优先基于已知上下文回答，在确有必要时再调用工具。\n"
        "如果给出了知识库内容，请尽量引用其中有帮助的部分。\n"
        "如果存在长期记忆，请自然地利用它来提升回答质量。\n"
        "当工具结果不足以支撑结论时，要明确说明不确定。"
    )
    system_prompt = f"{base_prompt}\n\n{context_prompt}".strip() if context_prompt else base_prompt

    class SimpleAgent:
        def __init__(self) -> None:
            self.system_prompt = system_prompt
            self.selected_model = selected_model
            self.reference_count = reference_count
            self.conversation_id = conversation_id
            self.message_id = message_id
            self.user_id = user_id
            self.tool_map = tool_map

        def _build_messages(self, inputs: dict[str, Any]) -> list[Any]:
            messages: list[Any] = []
            if self.system_prompt:
                messages.append(SystemMessage(content=self.system_prompt))

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

            messages.append(HumanMessage(content=inputs.get("input", "")))
            return messages

        async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
            started_at = time.perf_counter()
            user_input = inputs.get("input", "")
            resolved = _resolve_model_name(self.selected_model, user_input, self.system_prompt)
            llm = _create_llm(resolved)
            llm_with_tools = llm.bind_tools(tools) if tools else llm
            messages = self._build_messages(inputs)
            tool_logs: list[dict[str, Any]] = []
            final_output = ""

            for _ in range(6):
                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)

                tool_calls = getattr(response, "tool_calls", None) or []
                if not tool_calls:
                    final_output = _stringify_content(getattr(response, "content", ""))
                    break

                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool = self.tool_map.get(tool_name)
                    tool_input = tool_call.get("args", {})
                    if not tool:
                        tool_result = f"工具不存在: {tool_name}"
                        success = False
                        latency_ms = 0
                    else:
                        tool_started_at = time.perf_counter()
                        try:
                            tool_result = await _invoke_tool(tool, tool_input)
                            success = True
                        except Exception as exc:
                            tool_result = f"工具执行失败: {exc}"
                            success = False
                        latency_ms = int((time.perf_counter() - tool_started_at) * 1000)

                    tool_logs.append(
                        {
                            "tool_name": tool_name,
                            "input": tool_input,
                            "output": tool_result,
                            "success": success,
                            "latency_ms": latency_ms,
                        }
                    )
                    await _log_tool_call(
                        user_id=self.user_id,
                        conversation_id=self.conversation_id,
                        message_id=self.message_id,
                        tool_name=tool_name,
                        input_text=str(tool_input),
                        output_text=str(tool_result),
                        success=success,
                        latency_ms=latency_ms,
                    )
                    messages.append(
                        ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_call.get("id", ""),
                            name=tool_name,
                        )
                    )

            if not final_output:
                final_output = "我暂时没有生成有效内容，请稍后重试。"

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            await _log_chat_run(
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                message_id=self.message_id,
                selected_model=self.selected_model,
                resolved_model=resolved,
                input_text=user_input,
                output_text=final_output,
                tool_count=len(tool_logs),
                reference_count=self.reference_count,
                duration_ms=duration_ms,
            )

            return {
                "output": final_output,
                "selected_model": self.selected_model,
                "resolved_model": resolved,
                "tool_calls": tool_logs,
                "duration_ms": duration_ms,
            }

        async def astream_events(self, inputs: dict[str, Any], version: str = "v2"):
            """
            为了保证工具调用流程稳定，这里先完整执行，再按小块返回内容。

            这样虽然不是底层 token 级流式，但前端接口保持不变，行为也更稳定。
            """
            result = await self.ainvoke(inputs)
            content = str(result.get("output", ""))
            if not content:
                return

            chunk_size = 24
            for index in range(0, len(content), chunk_size):
                chunk_text = content[index:index + chunk_size]
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": AIMessage(content=chunk_text)},
                }
            yield {
                "event": "on_chat_model_end",
                "data": {"result": result},
            }

    return SimpleAgent()
