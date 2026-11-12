"""Orchestrator: wires the stages together, all driven by config + profile.

Modes
  fetch-only  fetch, dedupe, filter, volume report. No LLM, no state change.
  score       fetch .. filter, fetch missing JDs, tier-1 score, add matches to the ledger.
  newsletter  read replies, pick top jobs from the ledger, tailor them, send the daily letter.
  full        score, then newsletter.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from email.utils import make_msgid

from .config import Config
import os, time
from datetime import timedelta
from . import fetch, dedupe, filters, stages, report, newsletter, replies, visa, documents
from .llm import LLM, usage_summary
from . import notify
from html import escape


def claude_alarm(since_runs: list[dict], newsletter_errors: list[str]) -> str | None:
    """A loud message when Claude failed: a run since the last letter scored nothing because every
    call failed, or the newsletter run's own calls all failed. None when all is well."""
    for r in reversed(since_runs):
        u = (r.get("usage") or {}).get("score") or {}
        if r.get("passed") and not r.get("scored") and u.get("calls") and u.get("failed") == u.get("calls"):
            return (f"Claude could not score any of the {r['passed']} jobs that passed the filters "
                    f"(all {u['calls']} calls failed). Reason: {r.get('llm_error') or 'unknown'}. "
                    "Usually the CLAUDE_CODE_OAUTH_TOKEN secret is missing or wrong, or the plan's limit is used up.")
    if newsletter_errors:
        return f"Claude failed while preparing this letter: {newsletter_errors[-1]}"
    return None

MODES = ("fetch-only", "score", "newsletter", "full")


def run(config_path: str | None = None, profile: str | None = None,
        limit_sources_to_file: str | None = None, fetch_only: bool = False,
        mode: str | None = None, reprocess_all: bool = False) -> dict:
    mode = mode or ("fetch-only" if fetch_only else "full")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    cfg = Config(config_path, profile)
    print(f"== JobHunt :: profile={cfg.profile_id} :: {mode} ==")
    result = {}
    if mode in ("fetch-only", "score", "full"):
        result.update(score(cfg, limit_sources_to_file, fetch_only=(mode == "fetch-only"),
                            reprocess_all=reprocess_all))
    if mode in ("newsletter", "full"):
        result.update(send_newsletter(cfg))
    print(f"== done. artifacts in {cfg.output_dir()} ==")
    return result


# ---------------------------------------------------------------- score
def score(cfg: Config, offline_file: str | None = None, fetch_only: bool = False,
          reprocess_all: bool = False) -> dict:
    out = cfg.output_dir()

    # 1. FETCH (each source filtered to its own max_age_hours on the real posting date)
    print("[1] fetch")
    health: dict = {}
    if offline_file:  # offline testing: load a saved Arbeitnow json instead of hitting net
        raw = json.loads(Path(offline_file).read_text(encoding="utf-8"))
        jobs = [fetch._norm("offline", j.get("company_name"), j.get("title"), j.get("location"),
                            j.get("remote"), j.get("url"), j.get("description"), j.get("tags"),
                            j.get("created_at")) for j in raw.get("data", [])]
        health["offline"] = {"fetched": len(jobs), "fresh": len(jobs), "error": None, "seconds": 0}
    else:
        jobs = fetch.fetch_all(cfg.sources, health)

    # 2. DEDUPE across sources (+ only-new across runs)
    print("[2] dedupe")
    unique = dedupe.dedupe(jobs)
    report.add_relocation_signal(unique, report.load_company_list(cfg.relocation_list_path()))
    registers = visa.load_registers(cfg.registers_path()) if cfg.run.get("sponsor_registers", True) else {}
    visa.add_labels(unique, cfg.profile, registers)
    state = dedupe.load_state(cfg.state_path())
    fresh = unique if reprocess_all else dedupe.filter_new(unique, state)
    print(f"  {len(jobs)} fetched -> {len(unique)} unique, {len(fresh)} "
          f"{'to re-evaluate (--all)' if reprocess_all else 'new since last run'}")

    # 3. HARD FILTERS (deterministic, free)
    print("[3] hard filters")
    passed, dropped = filters.apply(fresh, cfg.profile)
    print(f"  {len(passed)} passed, {len(dropped)} dropped")

    # 3b. NO TITLE-ONLY SCORING (2026-11-08). Card-only jobs (LinkedIn) get their JD fetched, then
    #     the filters run again on the real text. A job whose JD can't be fetched this run is NOT
    #     marked seen, so the next run tries again; a closed posting is dropped for good.
    deferred: list[dict] = []
    if not fetch_only:
        cards = [j for j in passed if not fetch.has_description(j)]
        if cards:
            jd = cfg.run.get("jd_fetch", {})
            counts = fetch.enrich_descriptions(cards, max_fetch=int(jd.get("max_per_run", 400)),
                                               pause=float(jd.get("pause_sec", 1.5)))
            print(f"  [3b] JD fetch for {len(cards)} card-only jobs: {counts}")
            health["jd-fetch"] = {"fetched": len(cards), "fresh": counts["ok"], "error": None,
                                  "seconds": 0, **{k: v for k, v in counts.items()}}
            closed = [j for j in cards if j.get("jd_status") == "closed"]
            for j in closed:
                j["filter_fails"] = ["CLOSED"]
            deferred = [j for j in passed if not fetch.has_description(j) and j.get("jd_status") != "closed"]
            refilter = [j for j in cards if j.get("jd_status") == "ok"]
            ok2, drop2 = filters.apply(refilter, cfg.profile)
            keep = {id(j) for j in ok2}
            passed = [j for j in passed if fetch.has_description(j) and
                      (j.get("jd_status") != "ok" or id(j) in keep)]
            dropped += drop2 + closed
            visa.add_labels(passed, cfg.profile, registers)  # JDs fetched just now may state sponsorship
            print(f"  after JD: {len(passed)} passed, {len(drop2)} dropped on the real text, "
                  f"{len(closed)} closed, {len(deferred)} deferred to next run (no JD yet)")

    _dump(out / "dropped.json", [{**_brief(j), "fails": j["filter_fails"]} for j in dropped])
    _dump(out / "passed.json", [_brief(j) for j in passed])
    rep = report.fetch_report(health, unique, fresh, passed, dropped)
    (out / "fetch_report.md").write_text(rep, encoding="utf-8")
    print(f"  report -> {out / 'fetch_report.md'}")

    if fetch_only:  # look, don't touch: no LLM, no state update, so a real run still sees these
        print(rep)
        return {"unique": len(unique), "new": len(fresh), "passed": len(passed)}

    # 4. TIER-1 SCORE (batched claude -p), freshest first, capped to protect Pro limits.
    #    Jobs over the cap, or in a failed batch, are NOT marked seen: the next run scores them.
    cap = int(cfg.llm.get("tier1_max_jobs", 250))
    passed.sort(key=lambda j: fetch.age_hours(j) if fetch.age_hours(j) is not None else 1e9)
    to_score = passed[:cap]
    print(f"[4] tier-1 score: {len(to_score)} jobs (cap {cap}; {len(passed) - len(to_score)} wait for next run)")
    llm = LLM(cfg.llm)
    scored = stages.tier1_score(llm, cfg.profile, to_score,
                                batch_size=int(cfg.llm.get("tier1_batch_size", 30)),
                                apply_threshold=int(cfg.run.get("apply_threshold", 50))) if to_score else []
    _dump(out / "scored.json", [{**_brief(j), "score": j["score"], "tier": j["tier"],
                                 "fit": j["fit_1line"], "gap": j["biggest_gap"]} for j in scored])

    ledger = newsletter.load(cfg.ledger_path())
    newsletter.migrate(ledger)
    added = newsletter.add_scored(ledger, scored)
    newsletter.prune(ledger)
    newsletter.save(cfg.ledger_path(), ledger)
    matched = sum(1 for j in scored if j["tier"] == "apply")

    # 5. DOCUMENTS for every match >= docs_threshold, in every run (best first, budget-guarded)
    print(f"[5] documents (matches >= {cfg.run.get('docs_threshold', 60)}%)")
    docstats = documents.make_documents(cfg, ledger, llm, documents.load_connections(cfg.connections_path()))
    newsletter.save(cfg.ledger_path(), ledger)
    print(f"  {docstats}")
    usage = usage_summary(llm.calls)
    print(f"  {len(scored)} scored, {matched} matched (>= threshold), {added} new in ledger | usage {usage}")

    dedupe.save_state(cfg.state_path(), state, dropped + scored)
    _log_run(cfg, {"at": _now(), "fetched": len(jobs), "passed": len(passed), "scored": len(scored),
                   "matched": matched, "deferred": len(deferred), "health": health, "docs": docstats,
                   "usage": _jsonable(usage), "llm_error": llm.errors[-1] if llm.errors else None})
    return {"passed": len(passed), "scored": len(scored), "matched": matched, "deferred": len(deferred)}


# ---------------------------------------------------------------- newsletter
def send_newsletter(cfg: Config) -> dict:
    out = cfg.output_dir()
    ledger = newsletter.load(cfg.ledger_path())
    newsletter.migrate(ledger)
    runs = _load_runs(cfg)

    # 5a. READ REPLIES: codes applied -> applied; the rest of that letter (and older) -> skipped
    reply_result = read_replies(cfg, ledger, runs)

    # 5b. any documents still owed (newsletter-only runs, or a limit hit earlier)
    llm = LLM(cfg.llm)
    documents.make_documents(cfg, ledger, llm, documents.load_connections(cfg.connections_path()))
    top, rest, awaiting, due = newsletter.select(ledger)
    print(f"[5] newsletter: {len(top)} applications with documents, {len(rest)} more matches, "
          f"{len(awaiting)} awaiting reply, {len(due)} follow-ups due")
    docs = {e["hash"]: [e["doc"]["file"]] for e in top}
    attachments = []
    for e in top:   # the application notes (.md) + the tailored resume as LaTeX (open in Overleaf -> PDF)
        attachments.append((e["doc"]["file"], e["doc"]["content"]))
        if e["doc"].get("tex"):
            attachments.append((e["doc"]["tex_file"], e["doc"]["tex"]))
    try:  # weekly reusable answers for application forms
        kit = documents.answers_kit(cfg, llm, cfg.answers_kit_path())
        if kit:
            attachments.append(("application_answers_kit.md", kit))
    except Exception as ex:
        print(f"  ! answers kit failed: {ex.__class__.__name__}: {str(ex)[:120]}")
    for i, e in enumerate(top, 1):
        _save_pack(out, i, e, e["doc"].get("research", ""), e["doc"]["content"], "")

    since = runs.get("since_letter", [])
    stats = {k: sum(r.get(k, 0) for r in since) for k in ("fetched", "passed", "scored", "matched")}
    stats["runs"] = len(since)
    health = since[-1]["health"] if since else {}
    usage = _merge_usage([r.get("usage") or {} for r in since] + [_jsonable(usage_summary(llm.calls))])
    subject, text, html = newsletter.build(cfg.profile, top, rest, awaiting, due, docs, stats, health,
                                           usage=usage, reply_result=reply_result)
    alarm = claude_alarm(since, llm.errors)
    if alarm:   # never send a quiet empty letter when Claude itself failed
        print(f"  ! {alarm}")
        subject = "CLAUDE FAILED: " + subject
        text = f"*** {alarm} ***\n\n" + text
        html = f"<p style='background:#fdd;padding:8px'><b>{escape(alarm)}</b></p>" + html
    _wait_until_send_time(cfg)
    msgid = make_msgid(domain="jobhunt.local")
    try:
        status = notify.deliver(cfg.email, subject, text, html, attachments, out, cfg.smtp_password(),
                                message_id=msgid)
    except Exception as e:  # a mail failure must not lose the run's artifacts or the ledger
        status = f"email NOT sent: FAILED ({type(e).__name__}); newsletter is in {out / 'email'}"
    print(f"  {status}")

    if "NOT sent" not in status or cfg.run.get("mark_sent_on_dry_run", False):
        today = datetime.now(timezone.utc).date().isoformat()
        threshold = int(cfg.run.get("docs_threshold", 60))
        owed = [e for e in rest if (e.get("score") or 0) >= threshold
                and e.get("doc_attempts", 0) < documents.MAX_ATTEMPTS]   # docs still coming: keep new
        newsletter.mark_sent(ledger, top + [e for e in rest if e not in owed], today, {e["hash"] for e in top})
        newsletter.mark_followups(ledger, due, today)
        runs.setdefault("letters", []).append({"date": today, "msgid": msgid,
                                               "codes": [e.get("code") for e in top + rest]})
        runs["letters"] = runs["letters"][-60:]
        runs["since_letter"], runs["last_letter"] = [], _now()
    _save_runs(cfg, runs)
    newsletter.save(cfg.ledger_path(), ledger)
    return {"top_picks": len(top), "more": len(rest), "awaiting": len(awaiting), "followups": len(due),
            "email": status}


def _wait_until_send_time(cfg: Config) -> None:
    """Hold the letter until email.send_at (IST, e.g. "08:00") when JOBHUNT_WAIT_FOR_SEND is set
    (the scheduled morning run starts early so big days still finish in time). Late runs send at once."""
    at = cfg.email.get("send_at")
    if not at or not os.environ.get("JOBHUNT_WAIT_FOR_SEND"):
        return
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    hh, mm = (int(x) for x in str(at).split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if 0 < wait < 6 * 3600:
        print(f"  waiting {wait / 60:.0f} min to send at {at} IST")
        time.sleep(wait)


def read_replies(cfg: Config, ledger: dict, runs: dict) -> dict:
    """Apply every unprocessed reply to the ledger. Silent no-op without IMAP credentials."""
    letters = runs.get("letters", [])
    password = cfg.smtp_password()
    if not letters or not password or not cfg.email.get("read_replies", True):
        return {}
    processed = set(runs.get("replies_processed", []))
    since = min(lt["date"] for lt in letters[-30:])
    try:
        found = replies.fetch_replies(cfg.email, password, since, processed)
    except Exception as e:  # IMAP off / auth failure: report, never block the newsletter
        print(f"  ! could not read replies ({e.__class__.__name__}: {str(e)[:120]})")
        return {"error": str(e)[:120]}
    total = {"applied": 0, "skipped": 0, "outcomes": 0, "unknown": []}
    for r in sorted(found, key=lambda r: r["date"]):
        letter_date = replies.letter_for(r, letters)
        if not letter_date:
            continue
        applied, outcomes = replies.parse_reply(r["text"])
        res = replies.apply_reply(ledger, letter_date, applied, outcomes, r["date"])
        for k in ("applied", "skipped", "outcomes"):
            total[k] += res[k]
        total["unknown"] += [c for c in res["unknown"] if c not in total["unknown"]]
        processed.add(r["msgid"])
    runs["replies_processed"] = sorted(processed)[-500:]
    print(f"[5a] replies: {len(found)} new, {total}")
    return total


# ---------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(usage: dict) -> dict:
    return {k: {**v, "models": list(v.get("models") or [])} for k, v in usage.items()}


def _merge_usage(parts: list[dict]) -> dict:
    out: dict = {}
    for part in parts:
        for stage, u in (part or {}).items():
            m = out.setdefault(stage, {"calls": 0, "failed": 0, "tokens": 0, "cost_usd": 0.0, "models": []})
            for k in ("calls", "failed", "tokens"):
                m[k] += u.get(k, 0)
            m["cost_usd"] = round(m["cost_usd"] + u.get("cost_usd", 0.0), 4)
            m["models"] = sorted(set(m["models"]) | set(u.get("models") or []))
    return out


def _load_runs(cfg: Config) -> dict:
    return newsletter.load(cfg.runs_path())


def _save_runs(cfg: Config, runs: dict) -> None:
    newsletter.save(cfg.runs_path(), runs)


def _log_run(cfg: Config, entry: dict) -> None:
    runs = _load_runs(cfg)
    runs.setdefault("since_letter", []).append(entry)
    runs["since_letter"] = runs["since_letter"][-30:]
    _save_runs(cfg, runs)


def _brief(j: dict) -> dict:
    return {"title": j["title"], "company": j["company"], "country": j.get("country"),
            "location": j["location"], "posted_at": j.get("posted_at"), "source": j["source"],
            "also_on": j.get("also_on", []), "signals": j.get("signals", []),
            "salary": j.get("salary"), "url": j["url"]}


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_pack(out: Path, i: int, job: dict, notes: str, resume: str, letter: str) -> None:
    """Everything for one top pick, kept in the run's artifacts (research notes included there)."""
    d = out / f"{i:02d}_{_slug(job['company'])}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, body in (("research_notes.md", notes), ("resume.md", resume), ("cover_letter.md", letter)):
        if body:
            (d / name).write_text(body, encoding="utf-8")


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (s or "").lower()).strip("-")[:40]
