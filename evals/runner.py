"""Eval runner: one factory task per case via the backend API, then scores in the task worktree."""

import datetime
import glob
import json
import os
import threading
import time
import uuid

import httpx
import yaml

from . import scoring as S
from .judge import get_judge

ROOT = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("FACTORY_API", "http://localhost:8787")


def cases_dir_for(project=None):
    """Bundled cases, or a repo's own cases (`eval_cases_dir` in <repo>/.factory/config.yml, default .factory/evals)."""
    if not project:
        return os.environ.get("FACTORY_EVAL_CASES_DIR") or os.path.join(ROOT, "cases")
    cfg_p = os.path.join(project, ".factory", "config.yml")
    cfg = {}
    if os.path.exists(cfg_p):
        with open(cfg_p) as fh:
            cfg = yaml.safe_load(fh) or {}
    return os.path.join(project, cfg.get("eval_cases_dir") or ".factory/evals")


def load_cases(only=None, project=None):
    cases = []
    for f in sorted(glob.glob(os.path.join(cases_dir_for(project), "*.yml"))):
        c = yaml.safe_load(open(f))
        c["_file"] = os.path.basename(f)
        if project:
            c.setdefault("project", os.path.realpath(project))
        if not only or c["id"] in only:
            cases.append(c)
    return cases


def _wait(client, tid, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = client.get(f"{API}/api/tasks/{tid}").json()
        # wait out the DoD gate phase too (status flips back to running while phase=gating)
        if t["status"] != "running" and not t.get("phase"):
            # brief settle so the API process releases any duckdb handle
            time.sleep(0.5)
            return t
        time.sleep(2)
    client.post(f"{API}/api/tasks/{tid}/cancel")
    return client.get(f"{API}/api/tasks/{tid}").json()


def run_case(case, engine, client, judge):
    t0 = time.time()
    r = None
    for attempt in range(3):  # task creation can be slow while other tasks run in-process dbt
        try:
            r = client.post(
                f"{API}/api/tasks",
                json={"prompt": case["request"], "engine": engine, "project": case.get("project")},
                timeout=180,
            ).json()
            break
        except httpx.TimeoutException:
            if attempt == 2:
                raise
            time.sleep(5)
    tid = r["id"]
    t = _wait(client, tid)
    secs = round(time.time() - t0, 1)
    ev = client.get(f"{API}/api/tasks/{tid}/events", timeout=120).text
    events = [json.loads(l[5:]) for l in ev.splitlines() if l.startswith("data:")]
    cost = sum((e.get("cost") or 0) for e in events if e.get("kind") == "result")
    turns = sum((e.get("turns") or 0) for e in events if e.get("kind") == "result")
    model = case.get("target_model") or t.get("preview_model")
    wt = t["worktree"]
    res = {
        "id": case["id"],
        "title": case.get("title"),
        "tags": case.get("tags", []),
        "task_id": tid,
        "status": t["status"],
        "model": model,
        "agent_model": t.get("preview_model"),
        "seconds": secs,
        "turns": turns,
        "cost_usd": cost,
        "gate": {k: (t.get("gate") or {}).get(k) for k in ("passed", "summary", "failed")},
    }
    if t["status"] != "succeeded":
        res.update(
            assertions=[],
            scores={"code": 0.0, "data": 0.0, "gates": 0.0, "overall": 0.0},
            passed=False,
            error="task did not succeed",
        )
        return res
    if t.get("preview_model") and t["preview_model"] != model:
        model = t["preview_model"]
        res["note"] = f"agent produced {model} instead of {case.get('target_model')}"
    code = S.code_assertions(case, model, wt)
    data = S.data_assertions(case, model, wt)
    gates = S.gate_rate(t.get("gate"))
    transcript = "\n".join(e.get("text") or "" for e in events if e.get("kind") == "text")
    j = judge.score(case, transcript)
    jscore = j.get("score") if isinstance(j, dict) else None
    cs, ds = S.frac(code), S.frac(data)
    res.update(
        assertions=code + data,
        judge=j,
        scores={"code": cs, "data": ds, "gates": gates, "judge": jscore, "overall": S.overall(cs, ds, gates, jscore)},
        passed=(ds == 1.0 and (cs or 0) >= 0.75),
    )
    return res


def aggregate(cases):
    done = [c for c in cases if "scores" in c]
    if not done:
        return {}

    def avg(k):
        return round(sum((c["scores"].get(k) or 0) for c in done) / len(done), 3)

    return {
        "cases": len(done),
        "passed": sum(c.get("passed") for c in done),
        "pass_rate": round(sum(c.get("passed") for c in done) / len(done), 3),
        "overall": avg("overall"),
        "code": avg("code"),
        "data": avg("data"),
        "gates": avg("gates"),
        "avg_turns": round(sum(c.get("turns", 0) for c in done) / len(done), 1),
        "total_cost_usd": round(sum(c.get("cost_usd", 0) for c in done), 4),
        "avg_seconds": round(sum(c.get("seconds", 0) for c in done) / len(done), 1),
    }


def run(engine="mock", only=None, run_id=None, parallel=1, label=None, project=None):
    run_id = run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    path = os.path.join(ROOT, "results", f"{run_id}.json")
    cases = load_cases(only, project)
    judge = get_judge()
    out = {
        "run_id": run_id,
        "label": label,
        "engine": engine,
        "judge": judge.name,
        "started": time.time(),
        "status": "running",
        "weights": S.WEIGHTS,
        "cases": [{"id": c["id"], "title": c.get("title"), "status": "pending"} for c in cases],
    }
    lock = threading.Lock()

    def save():
        with lock:
            out["aggregate"] = aggregate(out["cases"])
            json.dump(out, open(path, "w"), indent=2, default=str)

    save()

    def worker(i, case):
        with httpx.Client(timeout=60) as client:
            out["cases"][i] = {"id": case["id"], "title": case.get("title"), "status": "running"}
            save()
            try:
                res = run_case(case, engine, client, judge)
            except Exception as ex:
                res = {
                    "id": case["id"],
                    "title": case.get("title"),
                    "status": "error",
                    "error": f"{type(ex).__name__}: {ex}",
                    "passed": False,
                    "scores": {"code": 0, "data": 0, "gates": 0, "overall": 0},
                    "assertions": [],
                }
            out["cases"][i] = res
            save()

    sem = threading.Semaphore(parallel)
    threads = []
    for i, c in enumerate(cases):

        def go(i=i, c=c):
            with sem:
                worker(i, c)

        th = threading.Thread(target=go)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    out["status"] = "done"
    out["finished"] = time.time()
    save()
    return out
