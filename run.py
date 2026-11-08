#!/usr/bin/env python
"""Entrypoint.  py run.py [--mode score|newsletter|full|fetch-only] [--profile <id>] [--config FILE]

--mode score      : fetch, filter, score new jobs, add matches to the ledger (several times/day)
--mode newsletter : research + tailor the top picks and send the daily newsletter
--mode full       : both (default)

--fetch-only   : fetch, dedupe and filter, then print the volume report. No claude -p calls and
                 no state update, so it's safe to run as often as you like.

--offline FILE : skip the network and load a saved Arbeitnow job-board JSON (for testing the
                 fetch->dedupe->filter path without hitting the APIs).
"""
import sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from jobhunt import pipeline  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Config-driven European job-hunt pipeline.")
    ap.add_argument("--profile", default=None, help="profile id (overrides config run.profile)")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--offline", default=None, help="path to a saved Arbeitnow JSON (no network)")
    ap.add_argument("--fetch-only", action="store_true",
                    help="fetch + dedupe + filter + volume report; no LLM, no state update")
    ap.add_argument("--mode", choices=pipeline.MODES, default=None,
                    help="score (several times a day) | newsletter (daily) | full | fetch-only")
    ap.add_argument("--all", action="store_true",
                    help="re-evaluate every unique job, ignoring the dedupe memory")
    args = ap.parse_args()
    result = pipeline.run(args.config, args.profile, args.offline, fetch_only=args.fetch_only,
                          mode=args.mode, reprocess_all=args.all)
    print(result)


if __name__ == "__main__":
    main()
