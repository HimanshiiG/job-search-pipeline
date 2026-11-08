"""Signals that need local data, and the fetch/volume report (no LLM).

The report answers "is the volume good?" per run: jobs per source and country at each stage,
which filters dropped what, posting age, and which sources look broken.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path

from .dedupe import norm_company
from .fetch import age_hours


def load_company_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {norm_company(l) for l in lines if l.strip() and not l.lstrip().startswith("#")}


def add_relocation_signal(jobs: list[dict], companies: set[str]) -> None:
    for j in jobs:
        if norm_company(j["company"]) in companies and "relocation-list" not in j["signals"]:
            j["signals"].append("relocation-list")


def _table(title: str, counter: Counter, header=("", "jobs")) -> list[str]:
    rows = [f"### {title}", "", f"| {header[0]} | {header[1]} |", "|---|---:|"]
    rows += [f"| {k or '(unknown)'} | {v} |" for k, v in counter.most_common()]
    return rows + [""]


def fetch_report(health: dict, unique: list[dict], new: list[dict], passed: list[dict],
                 dropped: list[dict]) -> str:
    L = ["# Fetch report", ""]
    L += ["## Sources", "", "| source | fetched | fresh | time | status |", "|---|---:|---:|---:|---|"]
    for name, h in health.items():
        status = "ERROR: " + h["error"] if h["error"] else ("**0 jobs: possibly blocked**" if h["fresh"] == 0 else "ok")
        L.append(f"| {name} | {h['fetched']} | {h['fresh']} | {h['seconds']}s | {status} |")
    L += ["", f"**{len(unique)} unique jobs** after cross-source dedupe, **{len(new)} new** since last "
          f"run, **{len(passed)} passed** hard filters.", ""]
    L += _table("Passed, by country", Counter(j.get("country") for j in passed), ("country", "jobs"))
    L += _table("Passed, by source (winning copy)", Counter(j["source"] for j in passed), ("source", "jobs"))
    multi = sum(1 for j in unique if j.get("also_on"))
    L += [f"Jobs found on more than one source: {multi} of {len(unique)}.", ""]
    reasons = Counter(f for j in dropped for f in j["filter_fails"])
    L += _table("Dropped, by reason (a job can fail several)", reasons, ("reason", "jobs"))
    L += _table("Signals on passed jobs", Counter(s for j in passed for s in j.get("signals", [])),
                ("signal", "jobs"))
    ages = [a for a in (age_hours(j) for j in passed) if a is not None]
    buckets = Counter("<12h" if a < 12 else "12-24h" if a < 24 else "24-48h" if a < 48 else "48-72h"
                      if a < 72 else ">72h" for a in ages)
    L += _table("Passed, by posting age", buckets, ("age", "jobs"))
    return "\n".join(L)
