"""Score the same jobs with two models and report agreement (career-ops eval-golden idea).

Fetches fresh data-engineering jobs with full descriptions from freehire (India + Europe), runs
the real filters, then scores the first N survivors with both models using the real tier-1
prompt. Reports: score difference, how often both put a job on the same side of the apply
threshold, and the disagreements to eyeball.

Usage:  py scripts/compare_models.py [--n 60] [--a haiku] [--b sonnet]
Costs about 2 x ceil(N/30) lean claude -p calls on your plan.
"""
from __future__ import annotations
import argparse, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jobhunt import dedupe, fetch, filters, stages  # noqa: E402
from jobhunt.config import Config  # noqa: E402
from jobhunt.llm import LLM, usage_summary  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--a", default="haiku")
    ap.add_argument("--b", default="sonnet")
    args = ap.parse_args()
    cfg = Config()
    thr = int(cfg.run.get("apply_threshold", 50))
    src = {"name": "freehire", "category": "data_engineering", "max_age_hours": 72, "max_per_group": 200,
           "undated_sources": ["whatjobs", "manatal", "civilservicejobs"],
           "groups": [{"countries": ["IN"]}, {"regions": ["eu", "uk"]}]}
    jobs = [j for j in fetch.fetch_freehire(src) if fetch.has_description(j)]
    passed, _ = filters.apply(dedupe.dedupe(jobs), cfg.profile)
    sample = passed[: args.n]
    print(f"{len(jobs)} fetched with JD, {len(passed)} passed filters, comparing {len(sample)}")

    results = {}
    for model in (args.a, args.b):
        llm = LLM({**cfg.llm, "models": {"score": model}})
        scored = stages.tier1_score(llm, cfg.profile, [dict(j) for j in sample],
                                    batch_size=int(cfg.llm.get("tier1_batch_size", 30)), apply_threshold=thr)
        results[model] = {j["hash"]: j for j in scored}
        print(f"  {model}: {len(scored)} scored | usage {usage_summary(llm.calls)}")

    a, b = results[args.a], results[args.b]
    common = [h for h in a if h in b]
    diffs = [abs(a[h]["score"] - b[h]["score"]) for h in common]
    same_side = sum((a[h]["score"] >= thr) == (b[h]["score"] >= thr) for h in common)
    print(f"\n{len(common)} jobs scored by both")
    print(f"  mean |score difference|: {statistics.mean(diffs):.1f} points (median {statistics.median(diffs):.0f})")
    print(f"  same apply/skip decision at {thr}%: {same_side}/{len(common)} ({100 * same_side / len(common):.0f}%)")
    print(f"  {args.a} applies to {sum(a[h]['score'] >= thr for h in common)}, "
          f"{args.b} to {sum(b[h]['score'] >= thr for h in common)}")
    worst = sorted(common, key=lambda h: -abs(a[h]["score"] - b[h]["score"]))[:8]
    print("\nbiggest disagreements:")
    for h in worst:
        print(f"  {a[h]['score']:>3} vs {b[h]['score']:>3} | {a[h]['title'][:45]} — {a[h]['company'][:25]}")
        print(f"      {args.a}: {a[h]['fit_1line'][:110]}")
        print(f"      {args.b}: {b[h]['fit_1line'][:110]}")


if __name__ == "__main__":
    main()
