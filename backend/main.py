import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import project_api as PAPI
import projects as PJ
from engine_config import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    ENGINES,
    MAX_TURNS,
    MCP_NAME,
    claude_auth,
    default_engine,
    mcp_tool_names,
    model,
    project_skills,
    write_mcp_config,
)
from factory_tools import dbt_tools as DT
from factory_tools import gates as GATES
from factory_tools import project_ctx as PJ_CTX
from factory_tools import review as REVIEW
from factory_tools import warehouse as WH
from factory_tools.gates import parse_waivers
from prompts import system_prompt
from style_api import style_caps
from task_locks import tlock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WT_ROOT = os.path.realpath(os.environ.get("FACTORY_WORKTREES_DIR") or f"{ROOT}/worktrees")
STATE = os.path.realpath(os.environ.get("FACTORY_STATE_DIR") or f"{ROOT}/state")
VENV_BIN = f"{ROOT}/.venv/bin"
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
os.makedirs(WT_ROOT, exist_ok=True)
os.makedirs(STATE, exist_ok=True)

# ---------------- projects (see project_api.py) ----------------
DEMO_PROJECT = PAPI.DEMO_PROJECT
DEFAULT_PROJECT = PAPI.DEFAULT_PROJECT
PROJECTS_FILE = PAPI.PROJECTS_FILE
EXCLUDE_PATHSPEC = PAPI.EXCLUDE_PATHSPEC


def mock_mode():
    return default_engine() == "mock"


def engine_of(t):
    return t.get("engine") or ("mock" if t.get("mock") else "cli")


TASKS: dict = {}


def save(t):
    json.dump({k: v for k, v in t.items() if k != "_lock"}, open(f"{STATE}/{t['id']}.json", "w"))


for f in os.listdir(STATE):
    if not f.endswith(".json") or f == os.path.basename(PROJECTS_FILE):
        continue
    t = json.load(open(f"{STATE}/{f}"))
    t.setdefault("turns", [{"prompt": t["prompt"], "status": t["status"]}])
    t.setdefault("cleaned", False)
    t.setdefault("engine", "mock" if t.get("mock") else "cli")
    if "git_root" not in t:  # tasks created before multi-project support ran on the demo project
        t["git_root"] = DEMO_PROJECT
        t["wt_root"] = t["worktree"]
        t["project_path"] = DEMO_PROJECT
        t["project_id"] = PJ.project_id(DEMO_PROJECT)
        t["project_name"] = os.path.basename(DEMO_PROJECT)
        t["mode"] = "dbt"
    if t["status"] == "running":
        t["status"] = "interrupted"
    TASKS[t["id"]] = t


def sh(argv: list[str], cwd, **kw):
    """Run a fixed program with an argv list (never a shell). Free text goes via stdin (`input=`), not argv."""
    if not isinstance(argv, list):
        raise TypeError("sh() takes an argv list")
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, **kw)
    except FileNotFoundError as e:  # optional tools (gh, claude) may be absent, e.g. in the container
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: not installed ({e.strerror})")


def emit(t, kind, **data):
    e = {"i": len(t["events"]), "ts": time.time(), "kind": kind, "turn": len(t.get("turns", [1])) - 1, **data}
    t["events"].append(e)
    if kind == "text":
        m = re.search(r"<plan>(.*?)</plan>", data.get("text", ""), re.S)
        if m:
            t["plan"] = m.group(1).strip()
        m = re.search(r"<preview_model>(.*?)</preview_model>", data.get("text", ""))
        if m:
            t["preview_model"] = m.group(1).strip()
    if kind == "tool_use":
        inp = data.get("input", {})
        fp = inp.get("file_path", "")
        if fp.endswith(".sql"):
            t["sql"][os.path.relpath(fp, t["worktree"]) if fp.startswith("/") else fp] = inp.get("content") or inp.get(
                "new_string", ""
            )


def normalize(t, raw):
    try:
        o = json.loads(raw)
    except Exception:
        return emit(t, "log", text=raw)
    ty = o.get("type")
    if ty in ("system", "result") and o.get("session_id") and o.get("session_id") != "mock":
        t["session_id"] = o["session_id"]
    if ty == "system" and o.get("subtype") == "init":
        caps = t.setdefault("capabilities", {})
        if o.get("tools"):
            caps["tools"] = o["tools"]
            caps["mcp_tools"] = [x for x in o["tools"] if x.startswith("mcp__")] or caps.get("mcp_tools", [])
        if o.get("mcp_servers"):
            caps["mcp_servers"] = o["mcp_servers"]
        if o.get("skills"):
            caps["skills_init"] = o["skills"]
        if o.get("slash_commands"):
            caps["slash_commands"] = o["slash_commands"]
        caps["source"] = "init event"
    if ty == "system":
        emit(t, "system", text=f"session {o.get('session_id')} model={o.get('model')}")
    elif ty in ("assistant", "user"):
        for c in o.get("message", {}).get("content", []):
            if c.get("type") == "text":
                emit(t, "text", text=c["text"])
            elif c.get("type") == "tool_use":
                emit(t, "tool_use", id=c.get("id"), name=c.get("name"), input=c.get("input", {}))
            elif c.get("type") == "tool_result":
                cont = c.get("content")
                if isinstance(cont, list):
                    cont = "\n".join(x.get("text", "") for x in cont if isinstance(x, dict))
                emit(
                    t, "tool_result", id=c.get("tool_use_id"), text=str(cont)[:12000], is_error=c.get("is_error", False)
                )
    elif ty == "result":
        emit(
            t,
            "result",
            text=o.get("result") or "",
            cost=o.get("total_cost_usd"),
            turns=o.get("num_turns"),
            is_error=o.get("is_error"),
        )
        if t["status"] == "running":
            t["phase"] = "finishing"  # engine reported its result; process exit + DoD gate still to come
            t["status"] = "failed" if o.get("is_error") else "succeeded"


def _needs_bootstrap(t):
    """duckdb (or `bootstrap: full`) projects get seed+run into the private dev target once per task."""
    if t.get("mode", "dbt") != "dbt" or PJ_CTX.load(t["worktree"]).get("bootstrap", "full") != "full":
        return False
    return not os.path.exists(os.path.join(t["worktree"], ".factory", "dev.duckdb"))


def _bootstrap(t):
    """Seed + run the base project into the task's private dev target so `model+` builds have parents."""
    if not _needs_bootstrap(t):
        return
    emit(t, "log", text="bootstrapping dev target: dbt seed + dbt run (base project)")
    from factory_tools.warehouse import run_dbt

    for args in (["seed", "--quiet"], ["run", "--quiet"]):
        p0 = run_dbt(args, cwd=t["worktree"], timeout=300)
        if p0.returncode:
            emit(t, "log", text=f"bootstrap dbt {args[0]} failed: {(p0.stdout + p0.stderr)[-400:]}")


def run_task(t, prompt, followup=False):
    if not followup:
        _bootstrap(t)
    wt = t["worktree"]
    env = {
        **os.environ,
        "PATH": f"{VENV_BIN}:{os.path.dirname(CLAUDE)}:{os.environ['PATH']}",
        "DBT_PROFILES_DIR": f"{wt}/.factory",
        "FACTORY_MODE": t.get("mode", "dbt"),
        "CLAUDE_CODE_MAX_RETRIES": os.environ.get("CLAUDE_CODE_MAX_RETRIES", "2"),
    }
    try:
        eng = engine_of(t)
        if eng == "mock":
            cmd = [sys.executable, f"{ROOT}/backend/mock.py", "followup" if followup else "first", prompt]
        elif eng == "sdk":
            cmd = [
                f"{VENV_BIN}/python",
                f"{ROOT}/backend/sdk_runner.py",
                prompt,
                (t.get("session_id") or "") if followup else "",
            ]
            env["CLAUDE_CLI_PATH"] = CLAUDE
        else:
            cmd = [
                CLAUDE,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--append-system-prompt",
                system_prompt(t.get("mode", "dbt"), wt),
                "--allowedTools",
                ",".join(ALLOWED_TOOLS),
                "--disallowedTools",
                ",".join(DISALLOWED_TOOLS),
                "--mcp-config",
                write_mcp_config(wt),
                "--setting-sources",
                "project",
                "--permission-mode",
                "acceptEdits",
                "--max-turns",
                str(MAX_TURNS),
            ] + (["--model", model()] if model() else [])
            if followup and t.get("session_id"):
                cmd += ["--resume", t["session_id"]]
        p = subprocess.Popen(
            cmd,
            cwd=wt,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        PROCS[t["id"]] = p
        t["pid"] = p.pid
        for line in p.stdout:
            if line.strip():
                normalize(t, line.strip())
        p.wait()
        if t["status"] == "running":
            t["phase"] = "finishing"  # set before the status flips so pollers never see a half-finished turn
            t["status"] = "succeeded" if p.returncode == 0 else "failed"
            if p.returncode:
                emit(t, "log", text=f"engine exited {p.returncode}")
    except Exception as ex:
        if t["status"] == "running":
            t["status"] = "failed"
        emit(t, "log", text=f"error: {ex}")
    PROCS.pop(t["id"], None)
    t["pid"] = None
    if t["status"] != "succeeded":
        t["phase"] = None
    t["turns"][-1]["status"] = t["status"]
    # Definition of Done: run gates on the preview model (or last changed) when the turn succeeded
    if t["status"] == "succeeded":
        # keep the task "running" (phase=gating) until DoD finishes so clients don't race the warehouse lock
        t["status"] = "running"
        t["phase"] = "gating"
        save(t)
        try:
            with tlock(t["id"]):
                _run_post_turn_gate(t)
        except Exception as ex:
            emit(t, "log", text=f"gate error: {ex}")
        finally:
            try:
                from factory_tools.warehouse import _release_duckdb

                _release_duckdb()
            except Exception:
                pass
            t["status"] = "succeeded"
            t["phase"] = None
            save(t)
    emit(t, "done", status=t["status"])
    save(t)


def _compute_gate(t, model=None):
    wt = t["worktree"]
    if t.get("mode") == "sql":
        return GATES.sql_gates(wt, t.get("base") or "HEAD")
    model = model or t.get("preview_model")
    if not model:
        models, _ = REVIEW.changed_models(wt, t.get("base") or "HEAD")
        model = models[0] if models else None
    if not model:
        return None
    text = "\n".join(e.get("text") or "" for e in t["events"] if e.get("kind") == "text")
    return GATES.run_gates(model, waivers=parse_waivers(text), cwd=wt)


def _run_post_turn_gate(t):
    gate = _compute_gate(t)
    if not gate:
        emit(t, "log", text="gate skipped: no model to score")
        return
    t["gate"] = gate
    t["turns"][-1]["gate"] = {k: gate[k] for k in ("passed", "summary", "failed")}
    checks = [{k: c.get(k) for k in ("id", "status", "detail", "group")} for c in gate["checks"]]
    emit(
        t,
        "gate",
        model=gate["model"],
        passed=gate["passed"],
        summary=gate["summary"],
        failed=gate["failed"],
        checks=checks,
    )


PROCS: dict = {}

app = FastAPI(title="dbt-factory")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(PAPI.router)
PAPI.has_running_tasks = lambda pid: any(
    t.get("project_id") == pid and t["status"] == "running" for t in TASKS.values()
)


class TaskIn(BaseModel):
    prompt: str
    mock: bool | None = None
    engine: str | None = None
    project_id: str | None = None
    project: str | None = None  # a local path; registered on the fly (used by evals)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mock_mode": mock_mode(),
        "engine": default_engine(),
        "engines": list(ENGINES),
        "model": model(),
        "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
        "claude": CLAUDE if os.path.exists(CLAUDE) else None,
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "auth": claude_auth(),
        "adapter": (PAPI.DETECT_CACHE.get(PAPI.default_project_id() or "") or {}).get("adapter"),
        "project": DEFAULT_PROJECT,
        "default_project_id": PAPI.default_project_id(),
        "gh_authed": sh(["gh", "auth", "status"], ROOT).returncode == 0,
    }


TASK_LIST_KEYS = [
    "id",
    "prompt",
    "status",
    "branch",
    "created",
    "mock",
    "cleaned",
    "engine",
    "gate",
    "project_id",
    "project_name",
    "mode",
]


@app.get("/api/tasks")
def list_tasks():
    return sorted(
        [{k: t.get(k) for k in TASK_LIST_KEYS} for t in TASKS.values()],
        key=lambda x: -x["created"],
    )


@app.post("/api/tasks")
def create_task(body: TaskIn):
    eng = body.engine or ("mock" if body.mock else default_engine())
    if eng not in ENGINES:
        raise HTTPException(400, f"engine must be one of {ENGINES}")
    det = PAPI.resolve_project(body.project, body.project_id)
    tid = uuid.uuid4().hex[:8]
    branch = f"factory/{tid}"
    wt_root, wt = PAPI.prepare_worktree(det, tid, branch, WT_ROOT)
    write_mcp_config(wt)
    base = sh(["git", "rev-parse", "HEAD"], det["git_root"]).stdout.strip()
    t = {
        "id": tid,
        "base": base,
        "prompt": body.prompt,
        "status": "running",
        "branch": branch,
        "worktree": wt,
        "wt_root": wt_root,
        "git_root": det["git_root"],
        "project_id": det["id"],
        "project_name": det["name"],
        "project_path": det["path"],
        "mode": det["mode"],
        "adapter": det.get("adapter"),
        "created": time.time(),
        "engine": eng,
        "mock": eng == "mock",
        "events": [],
        "turns": [{"prompt": body.prompt, "started": time.time(), "status": "running"}],
        "session_id": None,
        "capabilities": {
            "skills": project_skills(wt),
            "mcp_server": MCP_NAME,
            "mcp_tools": mcp_tool_names(),
            "source": "static scan",
        },
        "plan": None,
        "sql": {},
        "preview_model": None,
        "pr": None,
    }
    TASKS[tid] = t
    save(t)
    threading.Thread(target=run_task, args=(t, body.prompt), daemon=True).start()
    return {"id": tid}


def get(tid):
    if tid not in TASKS:
        raise HTTPException(404)
    return TASKS[tid]


@app.get("/api/tasks/{tid}")
def task(tid: str):
    t = get(tid)
    return {k: v for k, v in t.items() if k != "events"}


@app.get("/api/tasks/{tid}/events")
async def events(tid: str, since: int = 0):
    t = get(tid)

    async def gen():
        i = since
        while True:
            while i < len(t["events"]):
                yield f"data: {json.dumps(t['events'][i])}\n\n"
                i += 1
            if t["status"] != "running" and i >= len(t["events"]):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/tasks/{tid}/diff")
def diff(tid: str):
    t = get(tid)
    wt = t["worktree"]
    if t.get("cleaned"):
        return {
            "diff": sh(["git", "diff", t.get("base") or "HEAD", t["branch"]], t["git_root"]).stdout,
            "stat": "(worktree cleaned; diff of branch vs main)",
        }
    sh(["git", "add", "-A", "-N", "--", ".", *EXCLUDE_PATHSPEC], wt)
    base = t.get("base") or "HEAD"
    return {
        "diff": sh(["git", "diff", base, "--", ".", *EXCLUDE_PATHSPEC], wt).stdout,
        "stat": sh(["git", "diff", base, "--stat", "--", ".", *EXCLUDE_PATHSPEC], wt).stdout,
    }


PREVIEW_CACHE: dict = {}


def _models(wt):
    try:
        return [r["name"] for r in DT.list_resources(resource_type="model", cwd=wt)["resources"]]
    except Exception:
        return []


@app.get("/api/tasks/{tid}/preview")
def preview(tid: str, relation: str | None = None, limit: int = 20):
    """Data preview through the dbt target (dbt show) - never reads warehouse files directly."""
    t = get(tid)
    wt = t["worktree"]
    if t.get("cleaned"):
        raise HTTPException(410, "worktree cleaned up")
    if t.get("mode") == "sql":
        raise HTTPException(409, "plain SQL mode: no dbt target to preview through")
    rel = relation or t.get("preview_model")
    rr = f"{wt}/target/run_results.json"
    key = (tid, rel, limit, os.path.getmtime(rr) if os.path.exists(rr) else 0)
    if key in PREVIEW_CACHE:
        return PREVIEW_CACHE[key]
    if t["status"] == "running" and PJ_CTX.load(wt).get("single_writer", True):
        raise HTTPException(409, "preview runs when the droid is idle (single-writer warehouse)")
    if not rel:
        return {"relations": _models(wt), "columns": [], "rows": []}
    try:
        out = {
            "relation": rel,
            "via": f"dbt show ({PJ_CTX.load(wt).get('adapter') or 'dbt'} target dev)",
            **WH.sample(rel, limit, cwd=wt),
        }
    except WH.QueryError as ex:
        raise HTTPException(409, str(ex))
    PREVIEW_CACHE[key] = out
    return out


@app.get("/api/tasks/{tid}/capabilities")
def capabilities(tid: str):
    t = get(tid)
    caps = dict(t.get("capabilities") or {})
    if not t.get("cleaned"):
        caps["skills"] = project_skills(t["worktree"])
    caps["sql_style"] = style_caps(None if t.get("cleaned") else t["worktree"], t.get("project_id"))
    return caps


@app.post("/api/tasks/{tid}/pr")
def pr(tid: str):
    t = get(tid)
    wt = t["worktree"]
    if t["status"] == "running" or t.get("cleaned"):
        raise HTTPException(409, "task running or cleaned")
    sh(["git", "add", "-A", "--", ".", *EXCLUDE_PATHSPEC], wt)
    c = sh(
        [
            "git",
            "-c",
            "user.name=dbt-factory",
            "-c",
            "user.email=factory@localhost",
            "commit",
            "-F",
            "-",
        ],
        wt,
        # user text goes through stdin, never argv; the PR title/body are filled from this message
        input=f"dbt-factory: {t['prompt'][:72]}\n\n{t.get('plan') or t['prompt']}\n",
    )
    out = {
        "committed": c.returncode == 0,
        "commit_log": (c.stdout + c.stderr)[-1000:],
        "branch": t["branch"],
        "pr_url": None,
    }
    if sh(["gh", "auth", "status"], wt).returncode == 0:
        p = sh(
            [
                "gh",
                "pr",
                "create",
                "--head",
                t["branch"],
                "--fill-first",
            ],
            wt,
        )
        out["pr_url"] = p.stdout.strip() or None
        out["gh"] = p.stderr[-500:]
    else:
        out["gh"] = "gh not authenticated: skipped PR creation (commit is on local branch)"
    t["pr"] = out
    save(t)
    return out


class MsgIn(BaseModel):
    content: str


@app.post("/api/tasks/{tid}/messages")
def message(tid: str, body: MsgIn):
    t = get(tid)
    if t["status"] == "running":
        raise HTTPException(409, "task is running")
    if t.get("cleaned"):
        raise HTTPException(409, "worktree cleaned up")
    if engine_of(t) != "mock" and not t.get("session_id"):
        raise HTTPException(409, "no session_id to resume")
    t["turns"].append({"prompt": body.content, "started": time.time(), "status": "running"})
    t["status"] = "running"
    t["pr"] = None
    emit(t, "user", text=body.content)
    save(t)
    threading.Thread(target=run_task, args=(t, body.content, True), daemon=True).start()
    return {"turn": len(t["turns"]) - 1, "since": len(t["events"]) - 1}


@app.post("/api/tasks/{tid}/cancel")
def cancel(tid: str):
    t = get(tid)
    if t["status"] != "running":
        raise HTTPException(409, f"task is {t['status']}")
    t["status"] = "cancelled"
    p = PROCS.get(tid)
    if p:
        try:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    emit(t, "cancel", text="cancelled by user")
    save(t)
    return {"status": "cancelled"}


@app.post("/api/tasks/{tid}/cleanup")
def cleanup(tid: str, delete_branch: bool = False):
    t = get(tid)
    if t["status"] == "running":
        raise HTTPException(409, "cancel first")
    wt = t.get("wt_root") or t["worktree"]
    if not wt.startswith(WT_ROOT + "/"):
        raise HTTPException(400)
    root = t["git_root"]
    r = sh(["git", "worktree", "remove", "--force", wt], root)
    if os.path.isdir(wt):
        shutil.rmtree(wt)
    sh(["git", "worktree", "prune"], root)
    out = {"worktree_removed": not os.path.exists(wt), "git": r.stderr.strip()}
    if delete_branch:
        out["branch_deleted"] = sh(["git", "branch", "-D", t["branch"]], root).returncode == 0
    t["cleaned"] = True
    save(t)
    return out


@app.get("/api/tasks/{tid}/gate")
def get_gate(tid: str, refresh: bool = False):
    t = get(tid)
    if t.get("cleaned"):
        raise HTTPException(410, "worktree cleaned up")
    if refresh or not t.get("gate"):
        with tlock(tid):
            model = t.get("preview_model")
            gate = _compute_gate(t, model)
            if not gate:
                raise HTTPException(404, "no model")
            t["gate"] = gate
            save(t)
    return t["gate"]


@app.get("/api/tasks/{tid}/review")
def get_review(tid: str, refresh: bool = False):
    t = get(tid)
    if t.get("cleaned"):
        raise HTTPException(410, "worktree cleaned up")
    if refresh or not t.get("review"):
        with tlock(tid):
            kw = {"base": t.get("base") or "HEAD", "run_data": t["status"] != "running"}
            t["review"] = REVIEW.build_review(t["worktree"], model=t.get("preview_model"), **kw)
            save(t)
    rev = dict(t["review"])
    rev["comments"] = t.get("comments") or []
    rev["verdict"] = t.get("verdict")
    return rev


class CommentIn(BaseModel):
    body: str
    path: str | None = None
    line: int | None = None
    line_hint: str | None = None
    finding_id: str | None = None


@app.get("/api/tasks/{tid}/comments")
def list_comments(tid: str):
    return get(tid).get("comments") or []


@app.post("/api/tasks/{tid}/comments")
def add_comment(tid: str, body: CommentIn):
    t = get(tid)
    import uuid as _u

    c = {
        "id": _u.uuid4().hex[:8],
        "body": body.body,
        "path": body.path,
        "line": body.line,
        "line_hint": body.line_hint,
        "finding_id": body.finding_id,
        "resolved": False,
        "ts": time.time(),
        "author": "reviewer",
    }
    t.setdefault("comments", []).append(c)
    save(t)
    return c


@app.post("/api/tasks/{tid}/comments/{cid}/resolve")
def resolve_comment(tid: str, cid: str, resolved: bool = True):
    t = get(tid)
    for c in t.get("comments") or []:
        if c["id"] == cid:
            c["resolved"] = resolved
            save(t)
            return c
    raise HTTPException(404)


@app.post("/api/tasks/{tid}/comments/send-to-agent")
def comments_to_agent(tid: str, only_unresolved: bool = True):
    """Package open review comments as a follow-up turn for the droid."""
    t = get(tid)
    if t["status"] == "running":
        raise HTTPException(409, "task is running")
    open_c = [c for c in (t.get("comments") or []) if not (only_unresolved and c.get("resolved"))]
    if not open_c:
        raise HTTPException(400, "no comments to send")
    parts = ["Please address these review comments:"]
    for c in open_c:
        loc = (
            f"{c['path']}"
            + (f":{c['line']}" if c.get("line") else "")
            + (f" ({c['line_hint']})" if c.get("line_hint") else "")
        )
        parts.append(f"- [{c['id']}] {loc}: {c['body']}")
    body = MsgIn(content="\n".join(parts))
    return message(tid, body)


class VerdictIn(BaseModel):
    verdict: str  # approve | request_changes | comment
    body: str = ""
    post_to_github: bool = False


def _review_body(t, body) -> str:
    """Markdown review body: verdict text, inline comments, review summary and risk."""
    comments = t.get("comments") or []
    review_body = body.body or f"dbt-factory review: {body.verdict}"
    if comments:
        review_body += "\n\n### Comments\n" + "\n".join(
            f"- `{c.get('path') or 'general'}`: {c['body']}" + (" (resolved)" if c.get("resolved") else "")
            for c in comments
        )
    rev = t.get("review") or {}
    if rev.get("summary"):
        review_body += f"\n\n### Summary\n{rev['summary']}"
    if rev.get("risk"):
        review_body += f"\n\nRisk: **{rev['risk']}**"
    return review_body


@app.post("/api/tasks/{tid}/verdict")
def post_verdict(tid: str, body: VerdictIn):
    t = get(tid)
    if body.verdict not in ("approve", "request_changes", "comment"):
        raise HTTPException(400, "verdict must be approve|request_changes|comment")
    out = {
        "verdict": body.verdict,
        "body": body.body,
        "ts": time.time(),
        "gh": None,
        "pr_url": (t.get("pr") or {}).get("pr_url"),
    }
    if body.post_to_github:
        pr = (t.get("pr") or {}).get("pr_url") or (t.get("pr") or {}).get("url")
        if not pr and sh(["gh", "auth", "status"], t["worktree"]).returncode == 0:
            # try to find PR for branch
            p = sh(["gh", "pr", "view", t["branch"], "--json", "url", "-q", ".url"], t["worktree"])
            pr = p.stdout.strip() or None
        if not pr:
            out["gh"] = "no PR URL; commit & open PR first (or pass post_to_github after creating one)"
        elif sh(["gh", "auth", "status"], t["worktree"]).returncode != 0:
            out["gh"] = "gh not authenticated"
        else:
            event = {"approve": "APPROVE", "request_changes": "REQUEST_CHANGES", "comment": "COMMENT"}[body.verdict]
            review_body = _review_body(t, body)
            if not re.fullmatch(r"https://[\w.-]+/[\w.-]+/[\w.-]+/pull/\d+", pr):
                raise HTTPException(400, "unexpected PR URL")
            p = sh(["gh", "pr", "review", pr, "--event", event, "--body-file", "-"], t["worktree"], input=review_body)
            out["gh"] = "posted" if p.returncode == 0 else (p.stderr or p.stdout)[-500:]
            out["pr_url"] = pr
    t["verdict"] = out
    save(t)
    return out


# ---------------- Evals ----------------
EVALS_DIR = f"{ROOT}/evals"
EVAL_PROCS: dict = {}


@app.get("/api/evals/cases")
def eval_cases():
    import glob

    import yaml

    return [yaml.safe_load(open(f)) for f in sorted(glob.glob(f"{EVALS_DIR}/cases/*.yml"))]


@app.get("/api/evals/runs")
def eval_runs():
    import glob

    out = []
    for f in glob.glob(f"{EVALS_DIR}/results/*.json"):
        try:
            r = json.load(open(f))
        except Exception:
            continue
        out.append(
            {k: r.get(k) for k in ("run_id", "label", "engine", "judge", "started", "finished", "status", "aggregate")}
            | {"n_cases": len(r.get("cases", []))}
        )
    return sorted(out, key=lambda r: r.get("started") or 0, reverse=True)


@app.get("/api/evals/runs/{run_id}")
def eval_run(run_id: str):
    if not re.fullmatch(r"[\w.-]+", run_id):
        raise HTTPException(400)
    # resolve against the files that actually exist, so no request-derived path reaches open()
    runs = {e.name[:-5]: e.path for e in os.scandir(f"{EVALS_DIR}/results") if e.name.endswith(".json")}
    p = runs.get(run_id)
    if not p:
        raise HTTPException(404)
    return json.load(open(p))


class EvalIn(BaseModel):
    engine: str = "mock"
    cases: list[str] | None = None
    label: str | None = None


@app.post("/api/evals/run")
def eval_start(body: EvalIn):
    if body.engine not in ENGINES:
        raise HTTPException(400)
    import datetime as _dt

    rid = _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    known = {c["id"]: c["id"] for c in eval_cases()}
    if any(c not in known for c in body.cases or []):
        raise HTTPException(400, "unknown eval case")
    engine = {e: e for e in ENGINES}[body.engine]
    cmd = [f"{VENV_BIN}/python", "-m", "evals", "run", "--engine", engine, "--run-id", rid]
    for c in body.cases or []:
        cmd += ["--case", known[c]]  # value taken from the allow-list, not from the request
    log = open(f"{EVALS_DIR}/results/{rid}.log", "w")
    EVAL_PROCS[rid] = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        # free-text label travels via the environment, never argv
        env={**os.environ, "PATH": f"{VENV_BIN}:{os.environ['PATH']}", "FACTORY_EVAL_LABEL": (body.label or "")[:200]},
    )
    return {"run_id": rid}
