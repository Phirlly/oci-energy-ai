"""Native Messages adapter for this demo's text and local function tools only."""

import json

from agents import FunctionTool, Model, ModelResponse, Usage
from anthropic import transform_schema
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


def to_messages(items):
    """Translate the stateless transcript, preserving adjacent tool-use/result IDs."""
    if isinstance(items, str):
        return [{"role": "user", "content": [{"type": "text", "text": items}]}]
    messages = []
    for item in items:
        kind = item.get("type", "message")
        if kind == "function_call":
            if item.get("namespace"):
                raise ValueError("Namespaced tools are unsupported.")
            arguments = json.loads(item["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("Tool input must be an object.")
            role, content = "assistant", [{"type": "tool_use", "id": item["call_id"],
                                          "name": item["name"], "input": arguments}]
        elif kind == "function_call_output":
            if not isinstance(item["output"], str):
                raise ValueError("Only text tool results are supported.")
            role, content = "user", [{"type": "tool_result", "tool_use_id": item["call_id"],
                                     "content": item["output"]}]
        elif kind == "message" and item["role"] in {"user", "assistant"}:
            role = item["role"]
            if isinstance(item["content"], str):
                content = [{"type": "text", "text": item["content"]}]
            else:
                content = []
                for block in item["content"]:
                    if block["type"] not in {"input_text", "output_text"}:
                        raise ValueError("Only text messages are supported.")
                    content.append({"type": "text", "text": block["text"]})
        else:
            raise ValueError("Unsupported conversation item.")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": content})
    seen = set()
    pending = set()
    for message in messages:
        blocks = message["content"]
        calls = [block["id"] for block in blocks if block["type"] == "tool_use"]
        results = [block["tool_use_id"] for block in blocks if block["type"] == "tool_result"]
        if results or pending:
            if (message["role"] != "user" or set(results) != pending
                    or len(results) != len(pending)
                    or any(block["type"] != "tool_result" for block in blocks[:len(results)])):
                raise ValueError("Tool results must immediately follow their calls.")
            pending = set()
        if calls:
            if any(not value or value in seen for value in calls) or len(set(calls)) != len(calls):
                raise ValueError("Tool call IDs must be unique.")
            seen.update(calls)
            pending = set(calls)
    if pending or not messages or messages[-1]["role"] != "user":
        raise ValueError("Messages must end with a complete user turn.")
    return messages


class AnthropicMessagesModel(Model):
    def __init__(self, client, model):
        self.client = client
        self.model = model

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, *, previous_response_id,
                           conversation_id, prompt):
        if handoffs or previous_response_id or conversation_id or prompt:
            raise ValueError("Handoffs and remote state are unsupported.")
        allowed = {"max_tokens", "timeout", "store", "tool_choice", "parallel_tool_calls"}
        if any(value is not None for name, value in model_settings.to_json_dict().items() if name not in allowed):
            raise ValueError("Unsupported Anthropic model setting.")
        if model_settings.store:
            raise ValueError("Remote response storage is unsupported.")
        if model_settings.tool_choice not in {None, "auto", "required", "none"}:
            raise ValueError("Unsupported tool choice.")
        definitions = []
        for tool in tools:
            if not isinstance(tool, FunctionTool):
                raise ValueError("Only local function tools are supported.")
            definitions.append({"name": tool.name, "description": tool.description,
                                "input_schema": tool.params_json_schema})
        choice = {"type": {"required": "any", "none": "none"}.get(model_settings.tool_choice, "auto")}
        if choice["type"] != "none":
            choice["disable_parallel_tool_use"] = True
        output_config = {"effort": "low"}
        if output_schema is not None and not output_schema.is_plain_text():
            output_config["format"] = {"type": "json_schema", "schema": transform_schema(output_schema.json_schema())}
        response = await self.client.messages.create(
            model=self.model, messages=to_messages(input), system=system_instructions or "",
            **({"tools": definitions, "tool_choice": choice} if definitions else {}),
            max_tokens=model_settings.max_tokens or 2048,
            thinking={"type": "disabled"}, output_config=output_config,
            timeout=model_settings.timeout or 60,
        )
        if response.stop_reason not in {"end_turn", "tool_use"}:
            raise ValueError("Provider did not complete its response.")
        output = []
        for index, block in enumerate(response.content):
            if block.type == "text":
                output.append(ResponseOutputMessage(
                    id=f"{response.id}-{index}", role="assistant", type="message", status="completed",
                    content=[ResponseOutputText(type="output_text", text=block.text, annotations=[])],
                ))
            elif block.type == "tool_use":
                if not block.id or not isinstance(block.input, dict):
                    raise ValueError("Invalid tool request.")
                output.append(ResponseFunctionToolCall(type="function_call", call_id=block.id,
                                                      name=block.name, arguments=json.dumps(block.input)))
            else:
                raise ValueError("Unsupported provider content.")
        calls = [item.call_id for item in output if item.type == "function_call"]
        if (len(set(calls)) != len(calls) or not output
                or (response.stop_reason == "tool_use") != bool(calls)):
            raise ValueError("Provider stop reason and tool calls disagree.")
        usage = response.usage
        return ModelResponse(output=output, response_id=None, usage=Usage(
            requests=1, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens,
        ))

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Streaming is not supported by this demo adapter.")
