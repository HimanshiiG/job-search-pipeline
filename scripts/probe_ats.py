"""Find which public ATS board each watchlist company uses, and how many India roles it has.

Usage:  py scripts/probe_ats.py              # probe the built-in watchlist
        py scripts/probe_ats.py stripe cred  # probe specific slugs

Tries Greenhouse, Lever, Ashby and SmartRecruiters for each slug. Prints a ready-to-paste
config.yaml `sources:` entry for every hit. Slugs are guesses; a miss may just mean a
different slug (check the company's careers page apply link).
"""
from __future__ import annotations
import sys, time
import requests

UA = {"User-Agent": "jobhunt-pipeline/0.1 (personal job search; polite)"}
INDIA = ("india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "gurgaon",
         "gurugram", "noida", "chennai", "delhi")

WATCHLIST = [
    # US big tech / data-infra / SaaS
    "databricks", "confluent", "snowflake", "atlassian", "rubrik", "nutanix", "stripe", "uber",
    "rippling", "samsara", "roku", "twilio", "okta", "cloudflare", "mongodb", "elastic",
    "postman", "browserstack",
    # HFT / quant / buy-side
    "towerresearchcapital", "graviton", "quadeye", "deshaw", "optiver", "squarepoint",
    "alphagrep", "arcesium",
    # Indian product / fintech
    "cred", "razorpay", "zepto", "phonepe", "groww", "swiggy", "meesho", "dream11",
    "zerodha", "atlan", "sharechat", "rapido", "slice", "upstox", "inmobi",
]


def _titles_locs_greenhouse(slug):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", headers=UA, timeout=20)
    r.raise_for_status()
    return [(j["title"], (j.get("location") or {}).get("name", "")) for j in r.json()["jobs"]]


def _titles_locs_lever(slug):
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", headers=UA, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError("not a board")
    return [(j["text"], (j.get("categories") or {}).get("location", "")) for j in data]


def _titles_locs_ashby(slug):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", headers=UA, timeout=20)
    r.raise_for_status()
    return [(j["title"], j.get("location", "")) for j in r.json()["jobs"]]


def _titles_locs_smartrecruiters(slug):
    r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", headers=UA, timeout=20)
    r.raise_for_status()
    rows = r.json().get("content", [])
    if not rows:
        raise ValueError("empty")
    return [(j["name"], (j.get("location") or {}).get("city", "")) for j in rows]


PROBES = {
    "greenhouse": (_titles_locs_greenhouse, "token"),
    "lever": (_titles_locs_lever, "company"),
    "ashby": (_titles_locs_ashby, "company"),
    "smartrecruiters": (_titles_locs_smartrecruiters, "company"),
}


def probe(slug):
    hits = []
    for ats, (fn, key) in PROBES.items():
        try:
            jobs = fn(slug)
        except Exception:
            continue
        india = [t for t, loc in jobs if any(k in (loc or "").lower() for k in INDIA)]
        data = [t for t in india if "data" in t.lower()]
        hits.append((ats, key, len(jobs), len(india), data[:3]))
        time.sleep(0.3)  # polite
    return hits


def main():
    slugs = sys.argv[1:] or WATCHLIST
    found = []
    for slug in slugs:
        hits = probe(slug)
        if not hits:
            print(f"  -  {slug}: no public board found")
        for ats, key, total, india, data in hits:
            print(f"  +  {slug}: {ats}  total={total}  india={india}  data-roles={data}")
            found.append((slug, ats, key))
    if found:
        print("\n# paste into config/config.yaml `sources:`")
        for slug, ats, key in found:
            print(f"  - name: {slug}-{ats}\n    type: {ats}\n    enabled: true\n    {key}: {slug}")


if __name__ == "__main__":
    main()
