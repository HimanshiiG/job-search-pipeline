"""Phase-1 test: how fresh are freehire's "new" data-engineering jobs?

For every job freehire first recorded in the last N days (open_within_days), compare the date
the SOURCE says it was posted (posted_at) with when freehire first saw it (created_at).
lag = created_at - posted_at. A big lag means freehire discovered an already-old posting.

Usage:  py scripts/source_tests/freehire_freshness.py [--days 3] [--per-country 300]
Writes the raw rows to output/source_tests/freehire_freshness.json.
"""
from __future__ import annotations
import argparse, json, statistics, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://freehire.me/api/v1"
UA = {"User-Agent": "jobhunt-pipeline/0.1 (personal job search; polite)"}
COUNTRIES = ["IN", "DE", "NL", "GB", "IE", "AT", "CH", "PL", "ES", "PT", "FR", "SE", "DK",
             "AE", "SA", "QA", "AU", "SG", "JP", "US", "CA"]
OUT = Path(__file__).resolve().parents[2] / "output" / "source_tests"


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def fetch_country(country, days, cap):
    rows, offset = [], 0
    while offset < cap:
        r = requests.get(f"{BASE}/jobs/search", headers=UA, timeout=30, params=dict(
            category="data_engineering", countries=country, open_within_days=days,
            sort="created_at", order="desc", limit=100, offset=offset))
        r.raise_for_status()
        body = r.json()
        rows += body["data"]
        if len(body["data"]) < 100 or len(rows) >= body["meta"]["total"]:
            break
        offset += 100
        time.sleep(0.2)
    return rows[:cap]


def bucket(lag_days):
    if lag_days is None:
        return "no posted_at"
    for lim, name in [(1, "<1d"), (3, "1-3d"), (7, "3-7d"), (30, "7-30d")]:
        if lag_days < lim:
            return name
    return ">30d"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--per-country", type=int, default=300)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    all_rows, by_src = [], defaultdict(list)
    order = ["<1d", "1-3d", "3-7d", "7-30d", ">30d", "no posted_at"]
    print(f"{'country':8}{'jobs':>6}  " + "".join(f"{b:>13}" for b in order))
    for c in COUNTRIES:
        rows = fetch_country(c, a.days, a.per_country)
        cnt = Counter()
        for j in rows:
            p, cr = _ts(j.get("posted_at")), _ts(j.get("created_at"))
            lag = (cr - p).total_seconds() / 86400 if p and cr else None
            j["_lag_days"] = lag
            j["_country_q"] = c
            cnt[bucket(lag)] += 1
            by_src[j.get("source")].append(lag)
        all_rows += rows
        n = len(rows) or 1
        print(f"{c:8}{len(rows):>6}  " + "".join(
            f"{cnt[b]:>6} ({100*cnt[b]/n:>3.0f}%)" for b in order))

    print("\nby source (lag = days between source posting date and freehire first seeing it)")
    print(f"{'source':22}{'jobs':>6}{'median lag':>12}{'<=3d %':>9}")
    for s, lags in sorted(by_src.items(), key=lambda kv: -len(kv[1]))[:25]:
        known = [x for x in lags if x is not None]
        med = f"{statistics.median(known):.1f}d" if known else "-"
        ok = 100 * sum(1 for x in known if x <= 3) / len(known) if known else 0
        print(f"{str(s):22}{len(lags):>6}{med:>12}{ok:>8.0f}%")

    (OUT / "freehire_freshness.json").write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nraw rows -> {OUT / 'freehire_freshness.json'}")


if __name__ == "__main__":
    main()
