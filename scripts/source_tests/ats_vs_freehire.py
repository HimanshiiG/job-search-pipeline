"""Phase-1 test: does freehire really cover company ATS boards, and how late?

For each company, read its Greenhouse / Lever / Ashby board directly (the ground truth), then
read everything freehire holds for that company_slug, and match postings by their ATS job id.
  coverage = share of the board's open jobs that freehire has
  lag      = freehire created_at - ATS publish date, for jobs the ATS published in the last 7 days

Usage:  py scripts/source_tests/ats_vs_freehire.py
Re-run every few hours for 2-3 days: brand-new postings show the real discovery delay.
Appends a snapshot to output/source_tests/ats_vs_freehire.jsonl.
"""
from __future__ import annotations
import json, re, statistics, time
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = {"User-Agent": "jobhunt-pipeline/0.1 (personal job search; polite)"}
FH = "https://freehire.me/api/v1"
OUT = Path(__file__).resolve().parents[2] / "output" / "source_tests"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# (ats, board slug). Mix of India / EU / US / APAC employers with data roles.
COMPANIES = [
    ("greenhouse", "databricks"), ("greenhouse", "stripe"), ("greenhouse", "samsara"),
    ("greenhouse", "roku"), ("greenhouse", "cloudflare"), ("greenhouse", "datadog"),
    ("greenhouse", "mongodb"), ("greenhouse", "gitlab"), ("greenhouse", "figma"),
    ("greenhouse", "twilio"), ("greenhouse", "okta"), ("greenhouse", "elastic"),
    ("greenhouse", "n26"), ("greenhouse", "hellofresh"), ("greenhouse", "celonis"),
    ("greenhouse", "getyourguide"), ("greenhouse", "contentful"), ("greenhouse", "phonepe"),
    ("greenhouse", "groww"), ("greenhouse", "canva"), ("greenhouse", "airwallex"),
    ("greenhouse", "wallapop"), ("greenhouse", "creativefabrica"),
    ("lever", "qonto"), ("lever", "palantir"), ("lever", "spotify"), ("lever", "cred"),
    ("lever", "zeta"), ("lever", "meesho"), ("lever", "intropic"), ("lever", "mujininc"),
    ("ashby", "wayve"), ("ashby", "notion"), ("ashby", "ramp"), ("ashby", "deel"),
    ("ashby", "posthog"), ("ashby", "supabase"), ("ashby", "cohere"), ("ashby", "stream"),
    ("ashby", "zepto"), ("ashby", "atlan"),
]


def _ts(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s / 1000, timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def board(ats, slug):
    """Return {ats_job_id: publish_datetime} from the company's own board."""
    if ats == "greenhouse":
        js = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                          headers=UA, timeout=30).json().get("jobs", [])
        return {str(j["id"]): _ts(j.get("first_published") or j.get("updated_at")) for j in js}
    if ats == "lever":
        js = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json",
                          headers=UA, timeout=30).json()
        if not isinstance(js, list):
            return {}
        return {j["id"]: _ts(j.get("createdAt")) for j in js}
    js = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                      headers=UA, timeout=30).json().get("jobs", [])
    return {j["id"]: _ts(j.get("publishedAt")) for j in js}


def fh_ids(slug):
    """Return {ats_job_id: freehire created_at} for everything freehire holds for the company."""
    out, offset = {}, 0
    while offset < 2000:
        r = requests.get(f"{FH}/jobs/search", headers=UA, timeout=30,
                         params=dict(company_slug=slug, limit=100, offset=offset)).json()
        for j in r.get("data", []):
            url = j.get("url") or ""
            m = re.search(r"gh_jid=(\d+)|/jobs/(\d+)", url) or UUID.search(url)
            key = next((g for g in m.groups() if g), None) if m and m.groups() else (m.group(0) if m else None)
            if key:
                out[key] = _ts(j.get("created_at"))
            if j.get("external_id"):
                out.setdefault(str(j["external_id"]), _ts(j.get("created_at")))
        if len(r.get("data", [])) < 100:
            break
        offset += 100
        time.sleep(0.2)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    tot_b = tot_hit = 0
    lags, missing_new = [], 0
    snap = {"at": now.isoformat(), "companies": []}
    print(f"{'company':24}{'board':>6}{'in freehire':>12}{'cov':>6}{'new<7d':>8}{'median lag':>12}")
    for ats, slug in COMPANIES:
        try:
            b = board(ats, slug)
        except Exception as e:
            print(f"{ats+':'+slug:24}  board error: {e.__class__.__name__}")
            continue
        if not b:
            print(f"{ats+':'+slug:24}  no public board under this slug")
            continue
        f = fh_ids(slug)
        hit = [k for k in b if k in f]
        new = [k for k, t in b.items() if t and (now - t).days < 7]
        clag = [(f[k] - b[k]).total_seconds() / 3600 for k in new if k in f and f[k] and b[k]]
        missing_new += sum(1 for k in new if k not in f)
        lags += clag
        tot_b += len(b)
        tot_hit += len(hit)
        med = f"{statistics.median(clag):.0f}h" if clag else "-"
        print(f"{ats+':'+slug:24}{len(b):>6}{len(hit):>12}{100*len(hit)/len(b):>5.0f}%"
              f"{len(new):>8}{med:>12}")
        snap["companies"].append(dict(ats=ats, slug=slug, board=len(b), hit=len(hit),
                                      new=len(new), missing_new=sum(1 for k in new if k not in f),
                                      lags_h=clag))
        time.sleep(0.3)

    print(f"\nTOTAL coverage: {tot_hit}/{tot_b} = {100*tot_hit/max(tot_b,1):.0f}%")
    if lags:
        q = statistics.quantiles(lags, n=10) if len(lags) >= 10 else lags
        print(f"jobs published <7d ago: {len(lags)} found in freehire, {missing_new} NOT yet in freehire")
        print(f"discovery lag (hours): median {statistics.median(lags):.0f}, "
              f"p90 {q[-1]:.0f}, max {max(lags):.0f}")
    with open(OUT / "ats_vs_freehire.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")


if __name__ == "__main__":
    main()
