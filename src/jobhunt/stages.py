"""The LLM stages: tier-1 scoring, research + cover letter (one call), resume tailoring.

Each loads its prompt template from prompts/ and calls claude -p via llm.LLM.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from .llm import LLM, fill

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "prompts"


def _prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def _profile_summary(profile: dict) -> str:
    """Compact profile for the cheap tier-1 pass."""
    e = profile.get("eligibility", {})
    return json.dumps({
        "verified_skills": profile.get("skills_verified", {}),
        "gaps_never_claim": profile.get("skills_gaps", []),
        "needs_sponsorship": e.get("needs_sponsorship"),
        "languages": e.get("languages", {}),
        "markets_priority": e.get("markets", {}).get("priority"),
        "markets_acceptable": e.get("markets", {}).get("acceptable"),
        "no_sponsorship_needed_in": e.get("no_sponsorship_needed_in", []),
        "experience_years": profile.get("experience_years"),
    }, ensure_ascii=False)


def _job_brief(job: dict, desc_chars: int = 1800) -> dict:
    return {"id": job["hash"], "title": job["title"], "company": job["company"],
            "location": job["location"], "country": job.get("country"), "remote": job["remote"],
            "posted_at": job.get("posted_at"), "signals": job.get("signals", []),
            "salary": job.get("salary"), "visa": job.get("visa"), "url": job["url"],
            "description": job["description"][:desc_chars]}


# ---------- TIER 1 ----------
def tier1_score(llm: LLM, profile: dict, jobs: list[dict], batch_size: int = 30,
                apply_threshold: int = 50) -> list[dict]:
    """Returns only the jobs that got a score. A batch whose call fails is left out, so those
    jobs are not marked seen and get scored on the next run instead of being lost."""
    tmpl = _prompt("tier1_score.md")
    results, failed = {}, set()
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        prompt = fill(tmpl,
                      PROFILE_SUMMARY=_profile_summary(profile),
                      JOBS_JSON=json.dumps([_job_brief(j) for j in batch], ensure_ascii=False))
        try:
            scored = llm.run_json(prompt, stage="score")
        except Exception as e:  # quota / timeout / bad JSON: retry these next run
            print(f"  ! tier-1 batch {i // batch_size + 1} failed ({e.__class__.__name__}: {str(e)[:120]})")
            failed |= {j["hash"] for j in batch}
            continue
        for s in (scored if isinstance(scored, list) else []):
            results[s.get("id")] = s
    out = []
    for j in jobs:
        if j["hash"] in failed:
            continue
        s = results.get(j["hash"], {"score": 0, "fit_1line": "no score returned",
                                    "biggest_gap": None, "leaked_filter": None})
        try:
            j["score"] = int(float(s.get("score") or 0))
        except (TypeError, ValueError):
            j["score"] = 0
        j["tier"] = "apply" if j["score"] >= apply_threshold and not s.get("leaked_filter") else "drop"
        j["fit_1line"] = s.get("fit_1line", "")
        j["biggest_gap"] = s.get("biggest_gap")
        j["leaked_filter"] = s.get("leaked_filter")
        out.append(j)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ---------- TIER 2: research + cover letter (one call) ----------
# India postings rarely ask for a cover letter: unless the JD mentions one, India top picks get a
# tailored resume only (2026-11-08). Everywhere else gets research + letter + resume.
LETTER_ASKED = re.compile(r"\b(cover(ing)?[- ]letter|motivation(al)? letter|letter of motivation|"
                          r"statement of purpose)\b", re.I)


def needs_cover_letter(job: dict, profile: dict) -> bool:
    skip_in = [c.upper() for c in (profile.get("eligibility", {}).get("cover_letter_only_if_asked_in")
                                   or profile.get("cover_letter_only_if_asked_in") or ["IN"])]
    if (job.get("country") or "").upper() not in skip_in:
        return True
    return bool(LETTER_ASKED.search(job.get("description") or ""))


def research_and_letter(llm: LLM, profile: dict, job: dict,
                        tools: list[str] | None = None) -> dict:
    """One call: {research, letter, outreach, reviewer}."""
    prompt = fill(_prompt("research_letter.md"),
                  PROFILE_FULL=json.dumps(profile, ensure_ascii=False),
                  JOB=json.dumps(_job_brief(job, desc_chars=6000), ensure_ascii=False))
    p = sections(llm.run(prompt, stage="research_letter", tools=tools),
                 ("RESEARCH NOTES", "COVER LETTER", "OUTREACH", "REVIEWER NOTES"), main="COVER LETTER")
    return {"research": p["RESEARCH NOTES"], "letter": p["COVER LETTER"], "outreach": p["OUTREACH"],
            "reviewer": p["REVIEWER NOTES"]}


def sections(text: str, names: tuple[str, ...], main: str) -> dict:
    """Split '=== NAME ===' sections. If the model ignored the headings, everything is `main`."""
    parts = {}
    for name in names:
        m = re.search(rf"===\s*{name}\s*===\s*(.*?)(?====\s*[A-Z ]+\s*===|\Z)", text, re.S)
        parts[name] = m.group(1).strip() if m else ""
    if not parts[main]:
        parts[main] = text.strip()
    return parts


def split_sections(text: str) -> tuple[str, str, str]:
    p = sections(text, ("RESEARCH NOTES", "COVER LETTER", "REVIEWER NOTES"), main="COVER LETTER")
    return p["RESEARCH NOTES"], p["COVER LETTER"], p["REVIEWER NOTES"]


# ---------- RESUME SELECTION ----------
def select_base_resume(profile: dict, job: dict) -> tuple[str, str]:
    """Pick the best-matching base-resume variant for this job. Returns (label, text)."""
    resumes = profile.get("resumes") or []
    if not resumes:
        return ("", "")
    hay = (job["title"] + " " + job["description"]).lower()
    best, best_score = None, -1
    for r in resumes:
        score = sum(1 for kw in (r.get("match") or []) if kw.lower() in hay)
        if score > best_score:
            best, best_score = r, score
    if best_score <= 0:  # nothing matched -> fall back to the configured default
        default = profile.get("default_resume")
        best = next((r for r in resumes if r.get("label") == default), resumes[0])
    text = (ROOT / best["path"]).read_text(encoding="utf-8") if (ROOT / best["path"]).exists() else ""
    return (best.get("label", ""), text)


# ---------- TAILOR ----------
def tailor_resume(llm: LLM, profile: dict, base_resume: str, research_notes: str, job: dict,
                  location_line: str = "", ats_terms: list[str] | None = None) -> dict:
    """{resume, diff, recruiter_note}."""
    tmpl = _prompt("resume_tailor.md")
    prompt = fill(tmpl, PROFILE_FULL=json.dumps(profile, ensure_ascii=False),
                  BASE_RESUME=base_resume,
                  RESEARCH_NOTES=research_notes or "(no research for this job: tailor from the JD)",
                  LOCATION_LINE=location_line or "Mumbai, India",
                  ATS_TERMS=", ".join(ats_terms or []) or "(none beyond what the base resume already says)",
                  JOB=json.dumps(_job_brief(job, 4000), ensure_ascii=False))
    p = sections(llm.run(prompt, stage="resume"), ("RESUME", "DIFF NOTE", "RECRUITER NOTE"), main="RESUME")
    return {"resume": p["RESUME"], "diff": p["DIFF NOTE"], "recruiter_note": p["RECRUITER NOTE"]}
