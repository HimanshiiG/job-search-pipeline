"""Phase-1 test: is Adzuna worth GBP 8/month? (trial = 25 calls total, so this spends 1/country)

Per country: one search for "data engineer" posted in the last 2 days (50 results). Then, for a
sample of those jobs, look the same company+title up in freehire to see how many Adzuna adds
that we would not otherwise have.

Credentials from .env: app_id, app_key (never printed).
Usage:  py scripts/source_tests/adzuna_test.py [--countries in,de,nl,...] [--sample 20]
"""
from __future__ import annotations
import argparse, json, re, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "source_tests"
UA = {"User-Agent": "jobhunt-pipeline/0.1 (personal job search; polite)"}
DEFAULT = "in,de,nl,gb,ie,at,ch,pl,es,fr,au,sg,us,ca"


def env():
    vals = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def in_freehire(title, company):
    words = " ".join(norm(title).split()[:6])
    r = requests.get("https://freehire.me/api/v1/jobs/search", headers=UA, timeout=30,
                     params=dict(q=f"{words} {norm(company)}", limit=20)).json()
    c = norm(company)
    return any(c and (c in norm(j["company"]) or norm(j["company"]) in c) and
               norm(title)[:25] == norm(j["title"])[:25] for j in r.get("data", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default=DEFAULT)
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()
    e = env()
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    allrows = []
    print(f"{'cty':5}{'total 2d':>9}{'got':>5}{'<=36h':>7}{'sampled':>9}{'NOT in freehire':>17}")
    for c in a.countries.split(","):
        r = requests.get(f"https://api.adzuna.com/v1/api/jobs/{c}/search/1", headers=UA, timeout=30,
                         params=dict(app_id=e["app_id"], app_key=e["app_key"], what_phrase="data engineer",
                                     max_days_old=2, results_per_page=50, sort_by="date"))
        if r.status_code != 200:
            print(f"{c:5}  HTTP {r.status_code}: {r.text[:120]}")
            continue
        body = r.json()
        res = body.get("results", [])
        fresh = [j for j in res if (now - datetime.fromisoformat(j["created"].replace("Z", "+00:00")))
                 .total_seconds() <= 36 * 3600]
        uniq = 0
        sample = res[: a.sample]
        for j in sample:
            j["_in_freehire"] = in_freehire(j.get("title", ""), (j.get("company") or {}).get("display_name", ""))
            uniq += not j["_in_freehire"]
            time.sleep(0.15)
        for j in res:
            j["_country"] = c
        allrows += res
        print(f"{c:5}{body.get('count', 0):>9}{len(res):>5}{len(fresh):>7}{len(sample):>9}"
              f"{uniq:>10} ({100*uniq/max(len(sample),1):.0f}%)")
        time.sleep(1)
    (OUT / "adzuna_test.json").write_text(json.dumps(allrows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"raw -> {OUT / 'adzuna_test.json'}")


if __name__ == "__main__":
    main()
