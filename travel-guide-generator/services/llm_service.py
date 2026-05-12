"""Unified LLM client layer supporting OpenAI, Anthropic, and OpenAI-compatible APIs."""
import json
from abc import ABC, abstractmethod
from typing import Generator, Optional

import anthropic
import openai
from openai import OpenAI

from config import LLMConfig


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> str | Generator[str, None, None]:
        """Send chat completion request."""
        pass

    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        available_functions: dict,
    ) -> str:
        """Chat with automatic tool calling loop."""
        pass


class OpenAIClient(LLMClient):
    """Client for OpenAI and OpenAI-compatible APIs (DeepSeek, Qwen, etc.)."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not config.api_key:
            raise ValueError("API Key 不能为空，请先在配置页面填写 LLM API Key")
        kwargs = {"api_key": config.api_key}
        if config.api_base:
            kwargs["base_url"] = config.api_base
        self.client = OpenAI(**kwargs)

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> str | Generator[str, None, None]:
        params = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        # DeepSeek V4 thinking mode control via extra_body
        provider = self.config.provider.lower()
        if provider in ("deepseek",) and self.config.thinking_enabled:
            params["reasoning_effort"] = self.config.reasoning_effort
            params["extra_body"] = {"thinking": {"type": "enabled"}}

        if stream:
            return self._stream_chat(params)

        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content or ""

    def _stream_chat(self, params: dict) -> Generator[str, None, None]:
        """Stream chat response.

        Yields JSON strings with fields:
            - type: "reasoning" | "content" | "done"
            - text: the actual text chunk
        """
        import traceback

        try:
            response = self.client.chat.completions.create(**params)
        except Exception as e:
            print(f"[LLM] API call failed: {e}")
            traceback.print_exc()
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            return

        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Debug: log all delta attributes
            delta_dict = delta.__dict__ if hasattr(delta, "__dict__") else {}
            if delta_dict:
                print(f"[LLM] delta fields: {delta_dict}")

            # DeepSeek reasoning_content (thinking process)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning is not None and reasoning != "":
                print(f"[LLM] reasoning chunk: {reasoning[:80]}...")
                yield json.dumps(
                    {"type": "reasoning", "text": reasoning},
                    ensure_ascii=False,
                )

            # Normal content
            content = getattr(delta, "content", None)
            if content is not None and content != "":
                yield json.dumps(
                    {"type": "content", "text": content},
                    ensure_ascii=False,
                )

        yield json.dumps({"type": "done"}, ensure_ascii=False)

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        available_functions: dict,
    ) -> str:
        """Multi-turn tool calling loop."""
        max_iterations = 3
        current_messages = list(messages)

        for _ in range(max_iterations):
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=current_messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            message = response.choices[0].message

            # No tool calls, return final answer
            if not message.tool_calls:
                return message.content or ""

            # Add assistant message with tool_calls
            # DeepSeek thinking mode requires reasoning_content to be passed back
            assistant_msg = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            current_messages.append(assistant_msg)

            # Execute each tool call
            for tool_call in message.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                if function_name in available_functions:
                    result = available_functions[function_name](**arguments)
                else:
                    result = {"error": f"Function {function_name} not found"}

                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # Fallback if max iterations reached
        return "[Error: Too many tool call iterations]"


class AnthropicClient(LLMClient):
    """Client for Anthropic Claude models."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        kwargs = {"api_key": config.api_key}
        if config.api_base:
            kwargs["base_url"] = config.api_base
        self.client = anthropic.Anthropic(**kwargs)

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> str | Generator[str, None, None]:
        # Convert messages to Anthropic format
        system_message = ""
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        params = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system_message,
            "stream": stream,
        }
        if tools:
            params["tools"] = tools

        if stream:
            return self._stream_chat(params)

        response = self.client.messages.create(**params)
        return response.content[0].text if response.content else ""

    def _stream_chat(self, params: dict) -> Generator[str, None, None]:
        """Stream chat response."""
        with self.client.messages.stream(**params) as stream:
            for text in stream.text_stream:
                yield text

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        available_functions: dict,
    ) -> str:
        # Claude tool use is similar to OpenAI
        return self.chat(messages, tools=tools)


class LLMFactory:
    """Factory to create LLM clients based on configuration."""

    @staticmethod
    def create(config: LLMConfig) -> LLMClient:
        provider = config.provider.lower()
        if provider in ("openai", "openai-compatible", "deepseek", "qwen", "zhipu"):
            return OpenAIClient(config)
        elif provider == "anthropic":
            return AnthropicClient(config)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
