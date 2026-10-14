"""Pluggable LLM-as-judge for plan/explanation quality. Skipped unless configured + credentials exist.
FACTORY_JUDGE=claude uses `claude -p` (works with claude login, API key or a LiteLLM gateway)."""
import os, json, shutil, subprocess

RUBRIC = """Score 0-1 for each: plan_clarity (plan is concrete and ordered), explains_grain (states grain),
explains_delta (explains changes vs prod / reconciliation), honest_waivers (waivers are justified, not hiding failures).
Return ONLY JSON: {"plan_clarity":x,"explains_grain":x,"explains_delta":x,"honest_waivers":x,"rationale":"..."}"""

class NoJudge:
    name = "none"
    def score(self, case, transcript): return None

class ClaudeCLIJudge:
    name = "claude-cli"
    def score(self, case, transcript):
        exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        prompt = f"{RUBRIC}\n\nRequest: {case['request']}\n\nAgent transcript (text only):\n{transcript[:12000]}"
        p = subprocess.run([exe, "-p", prompt, "--output-format", "json", "--max-turns", "1"], capture_output=True, text=True, timeout=180)
        try:
            res = json.loads(json.loads(p.stdout)["result"])
            keys = ["plan_clarity", "explains_grain", "explains_delta", "honest_waivers"]
            return {"score": round(sum(float(res[k]) for k in keys) / len(keys), 3), **res}
        except Exception as ex:
            return {"score": None, "error": f"judge failed: {ex}", "raw": (p.stdout or p.stderr)[-300:]}

def get_judge():
    kind = os.environ.get("FACTORY_JUDGE", "none")
    if kind == "claude":
        has = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.path.exists(os.path.expanduser("~/.claude/.credentials.json"))
        if has: return ClaudeCLIJudge()
    return NoJudge()
