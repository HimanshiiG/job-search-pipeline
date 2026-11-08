"""Phase-1 test: JobSpy volume + accuracy (LinkedIn / Indeed / Naukri / Bayt), 36-hour window.

Writes a CSV the user checks by hand against the real sites (does the job exist, is the
posted time right, is it still open). No descriptions fetched: card data only, to stay polite.

Usage:  py scripts/source_tests/jobspy_test.py [--sites linkedin,indeed,naukri,bayt] [--hours 36]
Output: output/source_tests/jobspy_<site>.csv + a summary table.
"""
from __future__ import annotations
import argparse, time
from pathlib import Path

import pandas as pd
from jobspy import scrape_jobs

OUT = Path(__file__).resolve().parents[2] / "output" / "source_tests"
TERM = '"data engineer"'

# (label, location, indeed country). LinkedIn uses `location`; Indeed needs country_indeed.
SEARCHES = [
    ("Mumbai", "Mumbai, India", "india"), ("Bengaluru", "Bengaluru, India", "india"),
    ("Berlin", "Berlin, Germany", "germany"), ("Amsterdam", "Amsterdam, Netherlands", "netherlands"),
    ("London", "London, United Kingdom", "uk"), ("Dubai", "Dubai, United Arab Emirates", "united arab emirates"),
    ("Sydney", "Sydney, Australia", "australia"), ("Singapore", "Singapore", "singapore"),
    ("New York", "New York, NY", "usa"),
]
NAUKRI = ["Mumbai", "Bengaluru", "Pune", "Hyderabad"]
BAYT = ["United Arab Emirates", "Saudi Arabia", "Qatar"]
COLS = ["site", "search", "title", "company", "location", "date_posted", "is_remote", "job_url"]


def run(site, label, **kw):
    t0 = time.time()
    try:
        df = scrape_jobs(site_name=[site], search_term=TERM, verbose=0, **kw)
        err = ""
    except Exception as e:
        df, err = pd.DataFrame(), f"{e.__class__.__name__}: {str(e)[:80]}"
    df = df if df is not None else pd.DataFrame()
    df["search"] = label
    print(f"  {site:9}{label:12}{len(df):>5} jobs  {time.time()-t0:5.0f}s  {err}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default="linkedin,indeed,naukri,bayt")
    ap.add_argument("--hours", type=int, default=36)
    ap.add_argument("--per-search", type=int, default=50)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    common = dict(hours_old=a.hours, results_wanted=a.per_search)
    for site in a.sites.split(","):
        frames = []
        if site in ("linkedin", "indeed", "glassdoor"):
            for label, loc, cty in SEARCHES:
                frames.append(run(site, label, location=loc, country_indeed=cty, **common))
                time.sleep(8 if site == "linkedin" else 2)
        elif site == "naukri":
            for city in NAUKRI:
                frames.append(run(site, city, location=city, **common))
                time.sleep(3)
        elif site == "bayt":
            for cty in BAYT:
                frames.append(run(site, cty, location=cty, **common))
                time.sleep(3)
        df = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame(columns=COLS)
        for c in COLS:
            if c not in df.columns:
                df[c] = None
        df = df.drop_duplicates(subset=["job_url"])
        df[COLS].to_csv(OUT / f"jobspy_{site}.csv", index=False, encoding="utf-8-sig")
        print(f"== {site}: {len(df)} unique jobs -> {OUT / f'jobspy_{site}.csv'}\n")


if __name__ == "__main__":
    main()
