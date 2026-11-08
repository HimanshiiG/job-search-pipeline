"""Dedupe across sources and remember across runs.

Key = company + normalised title + country. Location strings differ per source ("Bangalore" vs
"Bengaluru, Karnataka, India"), so country is the stable part. When several sources carry the
same job, the copy with the longest description wins and the others are kept in `also_on`.
"""
from __future__ import annotations
import json, hashlib, re, time
from pathlib import Path

_COMPANY_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llc|gmbh|ag|se|bv|b\.v|plc|pty|corp|corporation|co)\b\.?")
_TITLE_NOISE = re.compile(
    r"\((?:[mwfdx]\s*/\s*)+[mwfdx]\)|\b(?:all genders|f/m/d|m/f/d|m/w/d|w/m/d|h/f|f/h)\b|"
    r"\s[-–|]\s*(?:remote|hybrid|on-?site).*$", re.I)
# freehire sometimes names a company by its ATS subdomain ("chalhoubgroup.teamtailor")
_ATS_HOST = re.compile(r"\.(teamtailor|greenhouse|lever|workable|recruitee|personio|ashbyhq|"
                       r"bamboohr|smartrecruiters|zohorecruit|myworkdayjobs)\b.*$")


def norm_company(s: str) -> str:
    s = _ATS_HOST.sub("", (s or "").lower().strip())
    s = _COMPANY_SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s)  # no spaces: "Chalhoub Group" == "chalhoubgroup"


def norm_title(s: str) -> str:
    s = _TITLE_NOISE.sub(" ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def job_hash(job: dict) -> str:
    country = (job.get("country") or (job.get("location") or "")).lower()
    key = f"{norm_company(job['company'])}|{norm_title(job['title'])}|{country}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def dedupe(jobs: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for j in jobs:
        h = job_hash(j)
        j["hash"] = h
        cur = best.get(h)
        if cur is None:
            j["also_on"] = []
            best[h] = j
            continue
        winner, loser = (j, cur) if len(j["description"]) > len(cur["description"]) else (cur, j)
        winner["also_on"] = sorted({*cur.get("also_on", []), loser["source"]} - {winner["source"]})
        winner["signals"] = sorted({*winner.get("signals", []), *loser.get("signals", [])})
        if winner.get("years_min") is None:
            winner["years_min"] = loser.get("years_min")
        best[h] = winner
    return list(best.values())


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def filter_new(jobs: list[dict], state: dict) -> list[dict]:
    """Keep only jobs not seen in a previous run (timeliness: act on fresh postings)."""
    return [j for j in jobs if j["hash"] not in state]


def save_state(path: Path, state: dict, jobs: list[dict]) -> None:
    now = int(time.time())
    for j in jobs:
        state.setdefault(j["hash"], now)
    path.write_text(json.dumps(state), encoding="utf-8")
