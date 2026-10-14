import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FACTORY_ENGINE", "mock")
import main
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from sdk_runner import to_stream_json


def mk(**kw):
    return {
        "id": "t",
        "worktree": "/wt",
        "status": "running",
        "events": [],
        "turns": [{"prompt": "p"}],
        "sql": {},
        "plan": None,
        "preview_model": None,
        "session_id": None,
        **kw,
    }


SESSION = [
    SystemMessage(subtype="init", data={"session_id": "sess-123", "model": "gpt-4o"}),
    AssistantMessage(
        content=[
            ThinkingBlock(thinking="hmm", signature="x"),
            TextBlock(text="<plan>\n- read project\n- add model\n</plan>"),
        ],
        model="gpt-4o",
    ),
    AssistantMessage(
        content=[ToolUseBlock(id="tu1", name="Write", input={"file_path": "/wt/models/m.sql", "content": "select 1"})],
        model="gpt-4o",
    ),
    UserMessage(content=[ToolResultBlock(tool_use_id="tu1", content="File created", is_error=False)]),
    AssistantMessage(content=[ToolUseBlock(id="tu2", name="Bash", input={"command": "dbt build"})], model="gpt-4o"),
    UserMessage(
        content=[
            ToolResultBlock(
                tool_use_id="tu2", content=[{"type": "text", "text": "Done. PASS=3 WARN=0 ERROR=0"}], is_error=False
            )
        ]
    ),
    AssistantMessage(content=[TextBlock(text="<preview_model>m</preview_model> done")], model="gpt-4o"),
    ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=4,
        session_id="sess-123",
        total_cost_usd=0.0123,
        result="Built m",
    ),
]


def run(msgs, t):
    for m in msgs:
        o = to_stream_json(m)
        if o:
            main.normalize(t, json.dumps(o, default=str))
    return t


def test_full_session_maps_to_ui_events():
    t = run(SESSION, mk())
    kinds = [e["kind"] for e in t["events"]]
    assert kinds == ["system", "text", "tool_use", "tool_result", "tool_use", "tool_result", "text", "result"]
    assert t["session_id"] == "sess-123"
    assert t["plan"] == "- read project\n- add model"
    assert t["preview_model"] == "m"
    assert t["sql"] == {"models/m.sql": "select 1"}
    assert "PASS=3" in t["events"][5]["text"]
    r = t["events"][-1]
    assert r["cost"] == 0.0123 and r["turns"] == 4 and not r["is_error"]
    assert t["status"] == "succeeded"


def test_thinking_only_message_is_skipped():
    assert to_stream_json(AssistantMessage(content=[ThinkingBlock(thinking="x", signature="s")], model="m")) is None


def test_error_result_marks_failed_with_message():
    t = run(
        [
            ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=0,
                is_error=True,
                num_turns=0,
                session_id="s",
                total_cost_usd=None,
                result=None,
                errors=["Invalid API key"],
            )
        ],
        mk(),
    )
    assert t["status"] == "failed" and "Invalid API key" in t["events"][-1]["text"]


def test_session_id_from_result_when_no_init():
    t = run(
        [
            ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=0,
                is_error=False,
                num_turns=1,
                session_id="only-in-result",
                total_cost_usd=0,
                result="ok",
            )
        ],
        mk(),
    )
    assert t["session_id"] == "only-in-result"


def test_cancelled_status_not_overwritten():
    t = mk(status="cancelled")
    run(SESSION[-1:], t)
    assert t["status"] == "cancelled"
