"""Chat agent helper functions — message formatting, error classification, serialization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage


def _find_safe_split(messages: list[ModelMessage], keep_recent: int) -> int:
    """Find a split index that won't orphan tool_result messages.

    Returns the index where 'recent' should start. The recent portion
    messages[split:] will begin with a user prompt, never an orphaned tool result.
    """
    from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart

    if not messages:
        return 0

    target = max(len(messages) - keep_recent, 0)

    for i in range(target, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            has_user = any(isinstance(p, UserPromptPart) for p in msg.parts)
            has_tool_return = any(isinstance(p, ToolReturnPart) for p in msg.parts)
            if has_user and not has_tool_return:
                return i

    return 0


def format_conversation_export(
    message_history: list[ModelMessage],
    model_alias: str = "balanced",
) -> str:
    """Format conversation history as a markdown document for export."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    lines: list[str] = []
    lines.append("# Chat Export")
    lines.append("")
    lines.append(f"- **Model**: {model_alias}")
    lines.append(f"- **Exported**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"- **Messages**: {len(message_history)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in message_history:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    lines.append("### You")
                    lines.append("")
                    for line in str(part.content).split("\n"):
                        lines.append(f"> {line}")
                    lines.append("")
                elif isinstance(part, ToolReturnPart):
                    lines.append(f"*Tool result ({part.tool_name}):*")
                    content = str(part.content)
                    if len(content) > 500:
                        content = content[:500] + "..."
                    lines.append(f"```\n{content}\n```")
                    lines.append("")
        elif isinstance(msg, ModelResponse):
            text_parts = []
            tool_parts = []
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content:
                    text_parts.append(part.content)
                elif isinstance(part, ToolCallPart):
                    tool_parts.append(part)
            for tp in tool_parts:
                args_str = ""
                if tp.args and isinstance(tp.args, dict):
                    args_str = " ".join(f"{k}={v!r}" for k, v in tp.args.items())
                lines.append(f"*Tool call: `{tp.tool_name}`{' ' + args_str if args_str else ''}*")
                lines.append("")
            if text_parts:
                lines.append("### Assistant")
                lines.append("")
                lines.append("\n".join(text_parts))
                lines.append("")

    return "\n".join(lines)


def _serialize_messages_for_summary(messages: list[ModelMessage]) -> str:
    """Convert messages to plain text for summarization."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    lines.append(f"User: {part.content}")
                elif isinstance(part, ToolReturnPart):
                    content = str(part.content)
                    if len(content) > 500:
                        content = content[:500] + "..."
                    lines.append(f"Tool result ({part.tool_name}): {content}")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    lines.append(f"Assistant: {part.content}")
                elif isinstance(part, ToolCallPart):
                    lines.append(f"Tool call: {part.tool_name}")
    return "\n".join(lines)


# ── Error classification ────────────────────────────────────────────────────


def _truncate_error(raw: str, limit: int) -> str:
    """Truncate an error message, extracting the meaningful part if possible."""
    msg = raw
    for marker in ("AnthropicError:", "BadRequestError:", "HTTPStatusError:"):
        idx = raw.find(marker)
        if idx != -1:
            msg = raw[idx : idx + limit]
            break
    else:
        msg = raw[:limit]
    if len(msg) < len(raw):
        msg += "..."
    return msg


def classify_chat_error(e: Exception) -> tuple[str, str]:
    """Classify a chat error into (short_message, category).

    Categories: "history_corrupt", "rate_limit", "context_length",
    "provider_down", "unknown".
    """
    err = str(e).lower()
    raw = str(e)

    if "tool_result" in err or "tool_use_id" in err:
        return (
            "Message history corrupted (orphaned tool_result). Auto-repair attempted.",
            "history_corrupt",
        )

    if "rate limit" in err or "429" in err or "rate_limit" in err:
        return _truncate_error(raw, 150), "rate_limit"

    if "context length" in err or "max tokens" in err or "too many tokens" in err:
        return "Context length exceeded.", "context_length"

    if any(
        kw in err
        for kw in (
            "connection refused",
            "connect timeout",
            "timed out",
            "503",
            "502",
            "server error",
        )
    ):
        return _truncate_error(raw, 150), "provider_down"

    return _truncate_error(raw, 200), "unknown"
