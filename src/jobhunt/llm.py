"""Thin wrapper around `claude -p` (Claude Pro via Claude Code).

CLAUDE.md rules enforced here:
  - NEVER pass --bare (would demand ANTHROPIC_API_KEY / bill API).
  - ANTHROPIC_API_KEY is stripped from the child env so it bills the plan, not the API.
  - Prompts go in on stdin (no arg-length limits for big batched prompts).

Every call runs with --output-format json so its usage (tokens, API-equivalent cost) can be
recorded in `self.calls`; the pipeline logs that per run and shows it in the newsletter.
Models are chosen per stage: `models: {score: haiku, research_letter: sonnet, resume: sonnet}`.
"""
from __future__ import annotations
import os, re, json, subprocess, time


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: dict):
        self.command = cfg.get("command", "claude")
        self.extra_args = list(cfg.get("extra_args", ["-p"]))
        self.model = cfg.get("model")                  # fallback for stages not in `models`
        self.models = dict(cfg.get("models") or {})
        self.timeout = int(cfg.get("timeout_sec", 300))
        self.dry_run = bool(cfg.get("dry_run", False))
        # lean: replace Claude Code's ~40k-token default system prompt + tool definitions with a
        # one-line system prompt and only the tools a stage needs (measured: 41.7k -> ~1k tokens
        # of overhead per call, ~10x cheaper on the plan's limits).
        self.lean = bool(cfg.get("lean", True))
        self.system_prompt = cfg.get("system_prompt") or (
            "You help a data engineer with their job search: you screen postings, research companies "
            "and draft application documents. Follow the user's instructions and output format exactly.")
        self.calls: list[dict] = []                    # one usage record per call
        self.errors: list[str] = []                    # the reason text of each failed call

    def _env(self) -> dict:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)  # bill the plan, not the API
        return env

    def model_for(self, stage: str | None) -> str | None:
        return self.models.get(stage) or self.model

    def run(self, prompt: str, stage: str | None = None, tools: list[str] | None = None) -> str:
        """Returns the model's text reply. tools: extra tools to allow (print mode denies anything
        not pre-approved), e.g. ["WebSearch", "WebFetch"] for the research step."""
        if self.dry_run:
            return "[dry_run] no LLM call made."
        args = [self.command, *self.extra_args, "--output-format", "json"]
        if "--bare" in args:
            raise LLMError("Refusing to run with --bare (see CLAUDE.md).")
        model = self.model_for(stage)
        if model:
            args += ["--model", model]
        if self.lean:
            args += ["--tools", ",".join(tools or []), "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence", "--system-prompt", self.system_prompt]
        if tools:
            args += ["--allowedTools", *tools]
        t0 = time.time()
        try:
            proc = subprocess.run(args, input=prompt, env=self._env(), capture_output=True,
                                  text=True, encoding="utf-8", timeout=self.timeout)
        except FileNotFoundError:
            raise LLMError(f"'{self.command}' not found on PATH.")
        except subprocess.TimeoutExpired:
            self._record(stage, model, t0, None, error="timeout")
            raise LLMError(f"claude -p timed out after {self.timeout}s.")
        envelope = _parse_envelope(proc.stdout)
        self._record(stage, model, t0, envelope,
                     error=None if proc.returncode == 0 else f"exit {proc.returncode}")
        if proc.returncode != 0 or (envelope or {}).get("is_error"):
            # the reason is in the envelope's `result` (e.g. "Invalid API key", "usage limit reached")
            reason = str((envelope or {}).get("result") or proc.stderr or proc.stdout or "").strip()[:300]
            self.errors.append(reason or f"exit {proc.returncode}")
            raise LLMError(f"claude -p failed (exit {proc.returncode}): {reason}")
        if envelope is None:
            return proc.stdout.strip()
        return str(envelope.get("result") or "").strip()

    def run_json(self, prompt: str, stage: str | None = None):
        """Run and return parsed JSON from the reply. Tolerates stray prose around it."""
        if self.dry_run:  # stub a 60% match for every job id in the batch, to exercise the newsletter
            ids = dict.fromkeys(re.findall(r'"id": "([0-9a-f]{16})"', prompt))
            return [{"id": i, "score": 60, "fit_1line": "[dry_run] stub score", "biggest_gap": None,
                     "leaked_filter": None} for i in ids]
        return _extract_json(self.run(prompt, stage=stage))

    def _record(self, stage, model, t0, envelope, error=None) -> None:
        env = envelope or {}
        u = env.get("usage") or {}
        self.calls.append({
            "stage": stage, "model": model or "default",
            "seconds": round(time.time() - t0, 1),
            "input_tokens": int(u.get("input_tokens") or 0),
            "cache_read_tokens": int(u.get("cache_read_input_tokens") or 0),
            "cache_write_tokens": int(u.get("cache_creation_input_tokens") or 0),
            "output_tokens": int(u.get("output_tokens") or 0),
            "cost_usd": float(env.get("total_cost_usd") or 0.0),
            "models_used": sorted((env.get("modelUsage") or {}).keys()),
            "error": error,
        })


def usage_summary(calls: list[dict]) -> dict:
    """Totals per stage, for the run log and the newsletter's usage line."""
    out: dict = {}
    for c in calls:
        s = out.setdefault(c.get("stage") or "other", {"calls": 0, "failed": 0, "tokens": 0, "cost_usd": 0.0,
                                                        "models": set()})
        s["calls"] += 1
        s["failed"] += bool(c.get("error"))
        s["tokens"] += (c["input_tokens"] + c["cache_read_tokens"] + c["cache_write_tokens"]
                        + c["output_tokens"])
        s["cost_usd"] = round(s["cost_usd"] + c["cost_usd"], 4)
        s["models"] |= set(c.get("models_used") or [c.get("model")])
    for s in out.values():
        s["models"] = sorted(m for m in s["models"] if m)
    return out


def _parse_envelope(stdout: str) -> dict | None:
    try:
        env = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(env, list):  # some CLI versions print a list of events; the last is the result
        env = next((e for e in reversed(env) if isinstance(e, dict) and e.get("type") == "result"), None)
    return env if isinstance(env, dict) else None


def _extract_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # pull the first {...} or [...] block
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = text.find(open_c), text.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Could not parse JSON from LLM output: {text[:300]}")


def fill(template: str, **vars) -> str:
    """Replace {{VAR}} placeholders in a prompt template."""
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return out
