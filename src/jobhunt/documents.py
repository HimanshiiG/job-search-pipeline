"""Application documents for every match at or above `run.docs_threshold` (2026-11-08: 60%).

One Markdown file per job: tailored resume, and outside India (or when the JD asks) the cover
letter + outreach to one named person from the same research call; a recruiter note; LinkedIn
people-search links; warm intros from the candidate's LinkedIn connections export; and the fact
check's warnings. Stored in the ledger so the evening run's documents reach the morning letter.

Budget guard: jobs are done highest score first; if Claude reports a usage/rate limit the step
stops and the remaining jobs wait for the next run. Nothing is lost, it just arrives later.
"""
from __future__ import annotations
import csv, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from . import stages, factcheck, fetch, visa
from .config import ROOT
from .llm import LLM, fill

LIMIT_HINT = re.compile(r"(usage limit|rate limit|limit reached|quota|too many requests|overloaded|credit)", re.I)
MAX_ATTEMPTS = 2


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (s or "").lower()).strip("-")[:30]


def people_links(e: dict) -> str:
    """LinkedIn people-search links for the user to open (ai-job-search referral links). Never
    fetched or scraped by the pipeline."""
    base = "https://www.linkedin.com/search/results/people/?keywords="
    role = re.sub(r"\(.*?\)|[-|,].*$", "", e.get("title") or "").strip()
    return (f"- Recruiters: {base}{quote_plus(e['company'] + ' recruiter')}\n"
            f"- Team / hiring manager: {base}{quote_plus(e['company'] + ' ' + (role or 'data engineering'))}")


# ---------- warm intros (career-ops linkedin-join) ----------
def load_connections(path: Path) -> list[dict]:
    """LinkedIn → Settings → Data privacy → Get a copy of your data → Connections. The export
    starts with a free-text preamble; the header row is found by content."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("first name")), None)
    if start is None:
        return []
    return [r for r in csv.DictReader(lines[start:]) if r.get("Company")]


def warm_intros(company: str, connections: list[dict], limit: int = 3) -> list[str]:
    if not connections:
        return []
    reg = visa.Register([company])
    out = [f"{r.get('First Name', '')} {r.get('Last Name', '')} ({r.get('Position', '')})".strip()
           for r in connections if r["Company"] in reg or company in visa.Register([r["Company"]])]
    return out[:limit]


# ---------- one job ----------
def _sources_text(profile: dict, base_resume: str) -> str:
    return base_resume + "\n" + json.dumps(profile, ensure_ascii=False)


def build(cfg, llm: LLM, e: dict, connections: list[dict]) -> dict:
    """Make the documents for one ledger entry. Raises on a model failure (caller decides)."""
    profile = cfg.profile
    if fetch.fill_description(e) == "ok":
        pass  # description now present for research + tailoring
    letter_needed = stages.needs_cover_letter(e, profile)
    rl = {"research": "", "letter": "", "outreach": "", "reviewer": ""}
    if letter_needed:
        rl = stages.research_and_letter(llm, profile, e, tools=cfg.llm.get("research_tools", ["WebSearch", "WebFetch"]))
    label, base_resume = stages.select_base_resume(profile, e)
    res = stages.tailor_resume(llm, profile, base_resume, rl["research"], e) if base_resume else {
        "resume": "", "diff": "", "recruiter_note": ""}

    sources = _sources_text(profile, base_resume)
    gaps = profile.get("skills_gaps") or []
    confidential = (profile.get("confidentiality") or {}).get("never_mention") or []
    warnings = [f"resume: {w}" for w in factcheck.check(res["resume"], sources, gaps, "resume", confidential)]
    warnings += [f"letter: {w}" for w in factcheck.check(rl["letter"], sources, gaps, "letter", confidential)]
    warnings += [f"outreach: {w}" for w in factcheck.check(rl["outreach"] + res["recruiter_note"], sources, gaps,
                                                          "letter", confidential)]
    if "posting-flagged" in (e.get("signals") or []):
        warnings.append("the posting contained text aimed at an AI; it was removed before drafting, "
                        "but read the original posting yourself")

    known = warm_intros(e["company"], connections)
    parts = [f"# {e['title']} — {e['company']}  [{e.get('code')}]",
             f"Match {e.get('score')}% · {e.get('location') or e.get('country')} · visa: {e.get('visa') or 'n/a (India)'}",
             f"Apply: {e['url']}", ""]
    if warnings:
        parts += ["## ⚠ Check before sending"] + [f"- {w}" for w in warnings] + [""]
    parts += [f"## Resume (tailored from your {label or 'base'} resume)", res["resume"] or "(not generated)", ""]
    if rl["letter"]:
        parts += ["## Cover letter", rl["letter"], ""]
    parts += ["## People to contact"]
    if known:
        parts += ["You already know (warm intro first):"] + [f"- {k}" for k in known]
    if rl["outreach"]:
        parts += [rl["outreach"]]
    if res["recruiter_note"]:
        parts += ["", f"Recruiter note (<=200 chars): {res['recruiter_note']}"]
    parts += ["", "Search LinkedIn yourself:", people_links(e), ""]
    if res["diff"] or rl["reviewer"]:
        parts += ["## Notes for you (not part of the application)", res["diff"], rl["reviewer"], ""]
    return {"file": f"{e.get('code')}_{_slug(e['company'])}.md", "content": "\n".join(p for p in parts if p is not None),
            "warnings": warnings, "letter": bool(rl["letter"]), "contact": bool(rl["outreach"]) or bool(known),
            "research": rl["research"], "made_at": datetime.now(timezone.utc).isoformat()}


def make_documents(cfg, ledger: dict, llm: LLM, connections: list[dict] | None = None) -> dict:
    """Documents for every unsent match >= threshold that has none yet, best first."""
    threshold = int(cfg.run.get("docs_threshold", 60))
    cap = int(cfg.run.get("docs_max_per_run", 80))
    todo = [e for e in ledger.values()
            if e.get("status", "new") == "new" and (e.get("score") or 0) >= threshold
            and not e.get("doc") and e.get("doc_attempts", 0) < MAX_ATTEMPTS]
    todo.sort(key=lambda e: e.get("score") or 0, reverse=True)
    stats = {"pending": len(todo), "made": 0, "failed": 0, "stopped_on_limit": False}
    connections = connections or []
    for e in todo[:cap]:
        try:
            e["doc"] = build(cfg, llm, e, connections)
            stats["made"] += 1
            print(f"  + docs {e.get('code')} {e['company'][:30]} — {e['title'][:40]}"
                  f"{' (letter)' if e['doc']['letter'] else ''}{' ⚠' if e['doc']['warnings'] else ''}")
        except Exception as ex:
            e["doc_attempts"] = e.get("doc_attempts", 0) + 1
            stats["failed"] += 1
            print(f"  ! docs failed for {e['company'][:30]}: {ex.__class__.__name__}: {str(ex)[:120]}")
            if LIMIT_HINT.search(str(ex)):
                e["doc_attempts"] -= 1  # not this job's fault: retry it next run
                stats["stopped_on_limit"] = True
                print("  ! Claude limit reached: remaining documents wait for the next run")
                break
    return stats


# ---------- weekly application-answers kit (ai-job-search 08-application-forms) ----------
def answers_kit(cfg, llm: LLM, state_path: Path) -> str | None:
    """Reusable answers for portal forms, regenerated weekly or when the profile changes."""
    profile_hash = hashlib.sha1(json.dumps(cfg.profile, sort_keys=True, default=str).encode()).hexdigest()[:12]
    cached = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["at"])).days if cached.get("at") else 999
    if cached.get("profile_hash") == profile_hash and age_days < 7:
        return None  # already sent this week
    resumes = "\n\n".join((ROOT / r["path"]).read_text(encoding="utf-8")
                          for r in cfg.profile.get("resumes", []) if (ROOT / r["path"]).exists())
    prompt = fill((ROOT / "prompts" / "answers_kit.md").read_text(encoding="utf-8"),
                  PROFILE_FULL=json.dumps(cfg.profile, ensure_ascii=False), RESUMES=resumes)
    kit = llm.run(prompt, stage="resume")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "profile_hash": profile_hash,
                                      "kit": kit}), encoding="utf-8")
    return kit
