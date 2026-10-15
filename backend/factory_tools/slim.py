"""Slim, CI-style dbt execution: build only what changed, defer everything else to prod.

State lives in the task dir (never in the user's repo):
  .factory/prod-state/manifest.json   prod manifest (`dbt parse --target prod` of the task's base commit),
                                      cached per project + base sha in <factory state>/prod_state/
  .factory/turn-state/manifest.json   manifest of the last build in this task (follow-ups build only what
                                      changed since then)
  .factory/built.json                 {"ok": {unique_id: checksum}, "failed": [unique_id]} from past builds

Default selection: `state:modified+<depth>` against the last build (or prod on the first build), plus models
that changed vs prod but never built successfully, plus last build's failures. Every dev build/compile/show
gets `--defer --defer-state <prod-state>` so unselected parents resolve to prod relations.
A full/unselected build is refused unless explicitly confirmed (FULL_BUILD_CONFIRM)."""

import json
import os
import shutil
import subprocess
import tempfile

from . import project_ctx as P

PROD_STATE = ".factory/prod-state"
TURN_STATE = ".factory/turn-state"
BUILT = ".factory/built.json"
FULL_BUILD_CONFIRM = "build everything"
FULL_SELECTORS = {"*", "+*", "*+", "fqn:*", "path:.", "path:./", "path:models", "path:models/", "resource_type:model"}
STATE_ROOT = os.path.realpath(
    os.environ.get("FACTORY_STATE_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "state")
)


class FullBuildRefused(Exception):
    pass


def config(cwd) -> dict:
    """slim settings from .factory/config.yml `slim:` (via project.json): depth ('' = all children, or int)."""
    s = P.load(cwd).get("slim") or {}
    return {
        "depth": s.get("depth", ""),
        "favor_state": bool(s.get("favor_state", False)),
    }


def _p(cwd, rel):
    return os.path.join(cwd, rel)


def has_prod_state(cwd) -> bool:
    return os.path.exists(_p(cwd, PROD_STATE + "/manifest.json"))


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _cache_dir(cwd, sha):
    pid = P.load(cwd).get("project_id") or "default"
    rel = os.path.relpath(cwd, P.load(cwd).get("worktree_root") or cwd)
    return os.path.join(STATE_ROOT, "prod_state", pid, sha, rel.replace(os.sep, "__"))


def ensure_prod_state(cwd, base="HEAD", refresh=False):
    """Prod manifest for the task's base commit: from the per-project cache, else `dbt parse --target prod`
    in a throwaway checkout of `base` (the task's own edits never leak into prod state)."""
    from .warehouse import run_dbt

    dst = _p(cwd, PROD_STATE)
    if has_prod_state(cwd) and not refresh:
        return dst
    sha = _git(cwd, "rev-parse", base).stdout.strip() or "unknown"
    cache = _cache_dir(cwd, sha)
    if refresh or not os.path.exists(os.path.join(cache, "manifest.json")):
        top = _git(cwd, "rev-parse", "--show-toplevel").stdout.strip() or cwd
        rel = os.path.relpath(cwd, top)
        tmp = tempfile.mkdtemp(prefix="factory-prod-")
        try:
            _git(cwd, "worktree", "add", "--detach", tmp, sha)
            sub = os.path.join(tmp, rel)
            os.makedirs(os.path.join(sub, ".factory"), exist_ok=True)
            shutil.copy(_p(cwd, ".factory/profiles.yml"), os.path.join(sub, ".factory", "profiles.yml"))
            p = run_dbt(["parse", "--target", "prod", "--quiet"], cwd=sub, tools_target=False)
            if p.returncode != 0:
                raise RuntimeError("prod parse failed: " + (p.stdout + p.stderr)[-400:])
            os.makedirs(cache, exist_ok=True)
            shutil.copy(os.path.join(sub, "target", "manifest.json"), os.path.join(cache, "manifest.json"))
        finally:
            _git(cwd, "worktree", "remove", "--force", tmp)
            shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    shutil.copy(os.path.join(cache, "manifest.json"), os.path.join(dst, "manifest.json"))
    return dst


def refresh_project_cache(project_id):
    """Drop a project's cached prod manifests (rebuilt lazily on the next task/build)."""
    d = os.path.join(STATE_ROOT, "prod_state", project_id)
    shutil.rmtree(d, ignore_errors=True)
    return d


def defer_args(cwd, target=None):
    """--defer flags for dev runs (never for prod reads)."""
    if target not in (None, "dev") or not has_prod_state(cwd):
        return []
    args = ["--defer", "--defer-state", _p(cwd, PROD_STATE)]
    return args + (["--favor-state"] if config(cwd)["favor_state"] else [])


def _built(cwd) -> dict:
    try:
        with open(_p(cwd, BUILT)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ok": {}, "failed": []}


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _checksums(manifest) -> dict:
    return {
        uid: (n.get("checksum") or {}).get("checksum")
        for uid, n in (manifest or {}).get("nodes", {}).items()
        if n.get("resource_type") in ("model", "seed", "snapshot")
    }


def pending(cwd, current_manifest) -> list[str]:
    """Models changed vs prod that never built successfully at their current version, + last failures."""
    prod = _checksums(_load(_p(cwd, PROD_STATE + "/manifest.json")))
    cur = _checksums(current_manifest)
    b = _built(cwd)
    changed = [u for u, c in cur.items() if prod.get(u) != c]
    out = [u for u in changed if b["ok"].get(u) != cur[u]] + [u for u in b["failed"] if u in cur]
    return list(dict.fromkeys(out))


def _name(manifest, uid):
    n = manifest["nodes"].get(uid) or {}
    return n.get("name") or uid.split(".")[-1]


def default_selection(cwd, current_manifest) -> tuple[str, str | None]:
    """(selector, state dir) for an unselected build."""
    depth = config(cwd)["depth"]
    plus = f"+{depth}" if depth != "" else "+"
    if os.path.exists(_p(cwd, TURN_STATE + "/manifest.json")):
        extra = [_name(current_manifest, u) + plus for u in pending(cwd, current_manifest)]
        return " ".join([f"state:modified{plus}", *extra]), TURN_STATE
    if has_prod_state(cwd):
        return f"state:modified{plus}", PROD_STATE
    return "", None


def guard(select, full_build=False, confirm=None):
    """Refuse an unselected / whole-project build unless explicitly confirmed."""
    s = (select or "").strip()
    if s and s not in FULL_SELECTORS:
        return
    if full_build and (confirm or "").strip().lower() == FULL_BUILD_CONFIRM:
        return
    raise FullBuildRefused(
        "refusing a full-project build: pass a --select (default: state:modified+), "
        f"or full_build=true with confirm='{FULL_BUILD_CONFIRM}' if the user explicitly asked for it"
    )


def record(cwd, results):
    """After a build: snapshot the manifest as turn state and remember what built / failed."""
    man = _load(_p(cwd, "target/manifest.json"))
    if not man:
        return
    os.makedirs(_p(cwd, TURN_STATE), exist_ok=True)
    shutil.copy(_p(cwd, "target/manifest.json"), _p(cwd, TURN_STATE + "/manifest.json"))
    sums = _checksums(man)
    b = _built(cwd)
    ok = dict(b["ok"])
    failed = set(b["failed"])
    for r in results:
        uid = r["unique_id"]
        if r["status"] == "success" and uid in sums:
            ok[uid] = sums[uid]
            failed.discard(uid)
        elif r["status"] in ("error", "fail", "skipped") and uid in sums:
            failed.add(uid)
    with open(_p(cwd, BUILT), "w") as f:
        json.dump({"ok": ok, "failed": sorted(failed)}, f)


def model_count(manifest) -> int:
    return sum(1 for n in (manifest or {}).get("nodes", {}).values() if n.get("resource_type") == "model")
