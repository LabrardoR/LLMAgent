import os
from http import HTTPStatus
import dashscope


def call_with_messages(messages):
    """调用阿里百炼模型"""
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
    if not dashscope.api_key:
        raise ValueError("请设置 DASHSCOPE_API_KEY 环境变量")

    response = dashscope.Generation.call(  # type: ignore[union-attr]
        dashscope.Generation.Models.qwen_turbo,
        messages=messages,
        result_format='message',
    )

    if response.status_code == HTTPStatus.OK:  # type: ignore[union-attr]
        return response.output.choices[0].message.content # type: ignore
    else:
        return f"Request id: {response.request_id}, Status code: {response.status_code}, error code: {response.code}, error message: {response.message}" # type: ignore
