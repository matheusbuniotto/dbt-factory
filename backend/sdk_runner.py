"""Agent-SDK engine. Runs claude_agent_sdk.query() and prints each message as a
Claude-Code stream-json line, so the backend's normaliser / cancel path is shared with the CLI engine.
Usage: python sdk_runner.py <prompt> [resume_session_id]   (cwd = task worktree)"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine_config import ALLOWED_TOOLS, DISALLOWED_TOOLS, MAX_TURNS, claude_auth, mcp_servers, model
from prompts import system_prompt


def _block(b):
    from claude_agent_sdk import TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock

    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        return {"type": "tool_result", "tool_use_id": b.tool_use_id, "content": b.content, "is_error": bool(b.is_error)}
    if isinstance(b, ThinkingBlock):
        return None
    return None


def to_stream_json(m):
    """Convert one SDK message object into a CLI stream-json dict (or None to skip)."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, UserMessage

    if isinstance(m, SystemMessage):
        d = m.data or {}
        return (
            {**d, "type": "system", "subtype": "init", "session_id": d.get("session_id"), "model": d.get("model")}
            if m.subtype == "init"
            else None
        )
    if isinstance(m, (AssistantMessage, UserMessage)):
        content = m.content if isinstance(m.content, list) else [{"type": "text", "text": m.content}]
        blocks = [x if isinstance(x, dict) else _block(x) for x in content]
        blocks = [b for b in blocks if b]
        if isinstance(m, AssistantMessage) and getattr(m, "error", None):
            blocks.append({"type": "text", "text": f"API error: {m.error}"})
        return (
            {"type": "assistant" if isinstance(m, AssistantMessage) else "user", "message": {"content": blocks}}
            if blocks
            else None
        )
    if isinstance(m, ResultMessage):
        text = m.result or ""
        if m.is_error:
            extra = "; ".join(str(e) for e in (getattr(m, "errors", None) or []))
            text = text or extra or f"{m.subtype} (api status {getattr(m, 'api_error_status', None)})"
        return {
            "type": "result",
            "subtype": m.subtype,
            "is_error": m.is_error,
            "num_turns": m.num_turns,
            "total_cost_usd": m.total_cost_usd,
            "session_id": m.session_id,
            "result": text,
        }
    return None


def out(o):
    print(json.dumps(o, default=str), flush=True)


async def main(prompt, resume=None):
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, query

    stderr_tail = []
    opts = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": system_prompt(os.getcwd())},
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=DISALLOWED_TOOLS,
        mcp_servers=mcp_servers(os.getcwd()),
        permission_mode="acceptEdits",
        max_turns=MAX_TURNS,
        cwd=os.getcwd(),
        model=model(),
        resume=resume,
        env=dict(os.environ),
        cli_path=os.environ.get("CLAUDE_CLI_PATH") or None,
        setting_sources=["project"],
        stderr=lambda l: stderr_tail.append(l) or stderr_tail[-30:] and None,
    )
    out(
        {
            "type": "system",
            "subtype": "engine",
            "session_id": None,
            "model": f"agent-sdk:{model() or 'default'} auth={claude_auth() or 'none'} base={os.environ.get('ANTHROPIC_BASE_URL', 'anthropic')}",
        }
    )
    got_result = False
    try:
        async for m in query(prompt=prompt, options=opts):
            o = to_stream_json(m)
            if o:
                got_result |= o["type"] == "result"
                out(o)
    except ClaudeSDKError as ex:
        hint = (
            ""
            if claude_auth()
            else " No credentials found: set ANTHROPIC_API_KEY, or ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN for an external gateway, or run `claude login`."
        )
        tail = "\n".join(stderr_tail[-8:])
        if got_result:  # CLI already reported the error as a result; just add the hint
            if hint:
                out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Engine hint:" + hint}]}})
            return 1
        out(
            {
                "type": "result",
                "subtype": "error_sdk",
                "is_error": True,
                "num_turns": 0,
                "total_cost_usd": None,
                "result": f"Agent SDK error: {type(ex).__name__}: {ex}.{hint}" + (f"\n{tail}" if tail else ""),
            }
        )
        return 1
    if not got_result:
        out(
            {
                "type": "result",
                "subtype": "error_no_result",
                "is_error": True,
                "result": "Agent SDK ended without a result message",
            }
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)))
