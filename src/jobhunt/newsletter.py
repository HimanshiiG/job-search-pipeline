"""The daily newsletter: which jobs to apply to, across several days of runs.

Scoring runs (several a day) add every job that clears the apply threshold to a ledger
(state/ledger.json). Once a day the newsletter is built from the ledger:
  1. Top picks: best new jobs with a tailored resume (+ cover letter outside India)
  2. More new matches, grouped by region
  3. Waiting for your reply: jobs from earlier letters you haven't answered yet
  4. Follow up: applied 10+ days ago, no news (at most two nudges)
  5. Run stats, Claude usage, source health
  6. Application-form cheat sheet (profile.application_facts)
Every job carries a short code; the candidate replies with the codes they applied to (replies.py).
"""
from __future__ import annotations
import html, json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import replies

REGIONS = {
    "India": {"IN"},
    "Europe": {"DE", "NL", "GB", "IE", "AT", "CH", "SE", "DK", "NO", "FI", "IS", "PT", "ES", "FR", "BE",
               "LU", "IT", "PL", "CZ", "RO", "HU", "GR", "CY", "MT", "EE", "LV", "LT"},
    "Middle East": {"AE", "SA", "QA", "BH", "KW", "OM"},
    "Asia-Pacific": {"AU", "NZ", "SG", "JP", "HK", "MY"},
    "North America": {"US", "CA"},
}
REGION_ORDER = ["India", "Europe", "Middle East", "Asia-Pacific", "North America", "Other / remote"]
LEDGER_KEEP_DAYS = 21


def region_of(country: str | None) -> str:
    c = (country or "").upper()
    return next((r for r, cs in REGIONS.items() if c in cs), "Other / remote")


# ---------- ledger ----------
def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def add_scored(ledger: dict, scored: list[dict], now: datetime | None = None) -> int:
    """Add apply-tier jobs. Returns how many were new to the ledger."""
    now_s = (now or datetime.now(timezone.utc)).isoformat()
    added = 0
    for j in scored:
        if j.get("tier") != "apply" or j["hash"] in ledger:
            continue
        ledger[j["hash"]] = {
            k: j.get(k) for k in ("title", "company", "country", "location", "url", "board_url", "source",
                                  "also_on", "signals", "posted_at", "salary", "score", "fit_1line",
                                  "biggest_gap", "remote", "visa")}
        ledger[j["hash"]].update(hash=j["hash"], description=(j.get("description") or "")[:8000],
                                 first_scored=now_s, sent_on=None, top_pick=False, status="new")
        added += 1
    replies.ensure_codes(ledger)
    return added


def migrate(ledger: dict) -> None:
    """Entries from before the reply loop (no `status`): unsent ones are new; sent ones are closed
    as skipped, since there is no reply to attribute them to."""
    for e in ledger.values():
        if "status" not in e:
            e["status"] = "skipped" if e.get("sent_on") else "new"
            if e.get("sent_on"):
                e["legacy"] = True
    replies.ensure_codes(ledger)


KEEP = ("applied",)   # applied jobs are kept for good: follow-ups, outcomes, the posting text


def prune(ledger: dict, now: datetime | None = None) -> None:
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=LEDGER_KEEP_DAYS)).isoformat()
    for h in [h for h, e in ledger.items()
              if e.get("status") not in KEEP and (e.get("first_scored") or "") < cutoff]:
        del ledger[h]


def select(ledger: dict, top_n: int | None = None, now: datetime | None = None) -> tuple[list, list, list, list]:
    """(applications, pool, awaiting_reply, follow_up_due). New jobs ranked by score, then freshest.
    applications: new jobs that have documents (every match >= docs_threshold); pool: the rest.
    top_n (legacy) caps the applications list when given and no job has documents yet.
    awaiting_reply: sent in an earlier letter that has had no reply yet (nothing is skipped
    without a reply). follow_up_due: applied, no outcome, 10+ days quiet, at most two nudges."""
    now = now or datetime.now(timezone.utc)
    new = [e for e in ledger.values() if e.get("status", "new") == "new"]
    new.sort(key=lambda e: (e.get("score") or 0, str(e.get("posted_at") or "")), reverse=True)
    if any(e.get("doc") for e in new) or top_n is None:
        top, rest = [e for e in new if e.get("doc")], [e for e in new if not e.get("doc")]
    else:
        top, rest = new[:top_n], new[top_n:]
    awaiting = sorted((e for e in ledger.values() if e.get("status") == "sent"),
                      key=lambda e: (e.get("top_pick"), e.get("score") or 0), reverse=True)
    due = []
    for e in ledger.values():
        if e.get("status") != "applied" or e.get("outcome") or e.get("followups", 0) >= FOLLOWUP_MAX:
            continue
        since = e.get("last_followup") or e.get("applied_on")
        if since and (now.date() - datetime.fromisoformat(since[:10]).date()).days >= FOLLOWUP_DAYS:
            due.append(e)
    return top, rest, awaiting, due


FOLLOWUP_DAYS, FOLLOWUP_MAX = 10, 2


def mark_sent(ledger: dict, entries: list[dict], today: str, top_hashes: set[str]) -> None:
    for e in entries:
        ledger[e["hash"]].update(sent_on=today, status="sent")
        if e["hash"] in top_hashes:
            ledger[e["hash"]]["top_pick"] = True


def mark_followups(ledger: dict, entries: list[dict], today: str) -> None:
    for e in entries:
        x = ledger[e["hash"]]
        x["followups"] = x.get("followups", 0) + 1
        x["last_followup"] = today


# ---------- rendering ----------
def _age(e: dict, now: datetime) -> str:
    p = e.get("posted_at")
    if not p:
        return "?"
    try:
        dt = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
    except ValueError:
        return str(p)[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = (now - dt).total_seconds() / 3600
    return "today" if h < 24 else f"{int(h // 24)}d ago"


def _salary(e: dict) -> str:
    s = e.get("salary") or {}
    if not (s.get("min") or s.get("max")):
        return ""
    lo, hi = s.get("min"), s.get("max")
    rng = f"{lo:,.0f}–{hi:,.0f}" if lo and hi else f"{(lo or hi):,.0f}"
    return f"{s.get('currency') or ''} {rng}/{s.get('period') or 'year'}".strip()


def _where(e: dict) -> str:
    return e.get("location") or e.get("country") or "?"


def _tags(e: dict) -> str:
    nice = {"visa-sponsorship-stated": "visa sponsored", "relocation-supported": "relocation",
            "relocation-list": "known to relocate", "uk-skilled-worker-sponsor": "UK sponsor",
            "nl-recognised-sponsor": "NL sponsor", "us-h1b-sponsor": "H-1B sponsor",
            "ie-permit-employer": "IE permit employer", "ca-lmia-employer": "CA LMIA",
            "dk-fast-track-company": "DK fast-track"}
    t = [nice.get(s, s) for s in e.get("signals") or [] if s not in ("uk-register", "nl-register", "posting-flagged")]
    v = {"sponsors": "visa: sponsors", "register": "visa: on sponsor register", "blue-card": "visa: EU Blue Card",
         "unknown": "visa: unknown"}.get(e.get("visa") or "")
    if v:
        t.insert(0, v)
    if e.get("remote"):
        t.append("remote")
    return ", ".join(t)


def _usage_line(usage: dict) -> str:
    if not usage:
        return ""
    parts = []
    for stage, u in sorted(usage.items()):
        models = "/".join(m.replace("claude-", "") for m in u.get("models") or []) or "default"
        parts.append(f"{stage}: {u['calls']} calls ({models}), {u['tokens'] / 1e6:.2f}M tokens"
                     + (f", {u['failed']} failed" if u.get("failed") else ""))
    total = sum(u.get("cost_usd", 0) for u in usage.values())
    return " · ".join(parts) + f" · API-equivalent ${total:.2f}"


def build(profile: dict, top: list, rest: list, awaiting: list, due: list, docs: dict, stats: dict,
          health: dict, usage: dict | None = None, reply_result: dict | None = None,
          now: datetime | None = None) -> tuple[str, str, str]:
    """Returns (subject, text, html). docs: {hash: [attachment filenames]}."""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%a %d %b")
    subject = f"Apply today: {len(top)} applications ready + {len(rest)} more matches ({day})"
    T, H = [], []

    def h(s):
        return html.escape(str(s or ""))

    def code(e):
        return f"[{e.get('code') or '----'}]"

    T += [f"JobHunt newsletter — {day}", "",
          "REPLY with the codes of the jobs you applied to, e.g.:  K7QX M2XA",
          "Everything else in this letter counts as skipped. No reply = nothing changes.",
          "Later, optional:  interview K7QX  /  rejected M2XA  /  offer P9DB", ""]
    H += [f"<h2 style='margin:0'>JobHunt — {h(day)}</h2>",
          f"<p style='color:#555'>{len(top)} applications ready (documents attached), {len(rest)} more matches"
          f"{f', {len(awaiting)} waiting for your reply' if awaiting else ''}. "
          "Nothing was submitted; you apply.</p>",
          "<p style='background:#f4f8ff;border:1px solid #cfe0ff;border-radius:6px;padding:8px 12px'>"
          "<b>Reply</b> with the codes of the jobs you applied to, e.g. <code>K7QX M2XA</code>. "
          "Everything else in this letter counts as skipped; no reply means nothing changes.<br>"
          "<small>Later, optional: <code>interview K7QX</code> · <code>rejected M2XA</code> · "
          "<code>offer P9DB</code></small></p>"]
    rr = reply_result or {}
    if rr.get("applied") or rr.get("outcomes") or rr.get("unknown") or rr.get("skipped"):
        line = (f"Got your reply: {rr.get('applied', 0)} applied, {rr.get('skipped', 0)} skipped, "
                f"{rr.get('outcomes', 0)} outcomes"
                + (f"; unknown codes ignored: {' '.join(rr['unknown'])}" if rr.get("unknown") else ""))
        T += [line, ""]
        H += [f"<p style='color:#2a6'>{h(line)}</p>"]

    if top:
        T += ["== TODAY'S APPLICATIONS (one document per job attached) ==", ""]
        H += ["<h3>Today's applications — one document per job attached</h3>"]
        for e in top:
            att = ", ".join(docs.get(e["hash"], [])) or "no documents (generation failed)"
            doc = e.get("doc") or {}
            extras = []
            if doc.get("warnings"):
                extras.append(f"⚠ {len(doc['warnings'])} thing(s) to check before sending (top of the document)")
            if doc.get("contact"):
                extras.append("contact + outreach note inside")
            T += [f"{code(e)} {e['title']} — {e['company']} ({_where(e)})",
                  f"   Match {e.get('score')}% · posted {_age(e, now)} · {_tags(e) or '-'} {_salary(e)}",
                  f"   Why: {e.get('fit_1line')}",
                  f"   Biggest gap: {e.get('biggest_gap') or '-'}",
                  f"   Apply: {e['url']}", f"   Attached: {att}"] + [f"   {x}" for x in extras] + [""]
            H += [f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin:10px 0'>"
                  f"<code style='font-size:14px'>{h(code(e))}</code> "
                  f"<b><a href='{h(e['url'])}'>{h(e['title'])}</a></b> — {h(e['company'])} "
                  f"<span style='color:#666'>({h(_where(e))})</span><br>"
                  f"<b>Match {h(e.get('score'))}%</b> · posted {h(_age(e, now))}"
                  f"{' · ' + h(_tags(e)) if _tags(e) else ''}{' · ' + h(_salary(e)) if _salary(e) else ''}<br>"
                  f"{h(e.get('fit_1line'))}<br>"
                  f"<span style='color:#a33'>Gap to name: {h(e.get('biggest_gap') or '-')}</span><br>"
                  f"<span style='color:#666'>Attached: {h(att)}</span>"
                  + "".join(f"<br><span style='color:#a60'>{h(x)}</span>" for x in extras) + "</div>"]

    def table(title, rows):
        T.append(f"-- {title} ({len(rows)}) --")
        H.append(f"<h4 style='margin-bottom:4px'>{h(title)} ({len(rows)})</h4>"
                 "<table cellpadding='4' style='border-collapse:collapse;font-size:13px'>"
                 "<tr style='background:#f3f3f3'><th>Code</th><th>Match</th><th>Role</th><th>Company</th>"
                 "<th>Where</th><th>Posted</th><th>Why</th></tr>")
        for e in rows:
            T.append(f"  {code(e)} {e.get('score')}% | {e['title']} | {e['company']} | {_where(e)} | "
                     f"{_age(e, now)}{' | ' + _tags(e) if _tags(e) else ''} | {e.get('fit_1line')} | {e['url']}")
            H.append(f"<tr style='border-top:1px solid #eee'><td><code>{h(e.get('code'))}</code></td>"
                     f"<td>{h(e.get('score'))}%</td><td><a href='{h(e['url'])}'>{h(e['title'])}</a>"
                     f"{'<br><small>' + h(_tags(e)) + '</small>' if _tags(e) else ''}</td>"
                     f"<td>{h(e['company'])}</td><td>{h(_where(e))}</td><td>{h(_age(e, now))}</td>"
                     f"<td>{h(e.get('fit_1line'))}</td></tr>")
        T.append("")
        H.append("</table>")

    if rest:
        T += ["== ALSO MATCHED (below the documents bar, or documents still being written) ==", ""]
        H.append("<h3>Also matched</h3><p style='color:#666'>Below the documents bar, or documents "
                 "still being written (they arrive in a later letter).</p>")
        for region in REGION_ORDER:
            rows = [e for e in rest if region_of(e.get("country")) == region]
            if rows:
                table(region, rows)

    if awaiting:
        dates = ", ".join(sorted({e.get("sent_on") for e in awaiting if e.get("sent_on")}))
        T += [f"== WAITING FOR YOUR REPLY (letters of {dates}) ==",
              "  Your next reply covers these too: list any you applied to.", ""]
        H.append(f"<h3>Waiting for your reply</h3><p style='color:#666'>From the letters of {h(dates)}. "
                 "Your next reply covers these too: list any you applied to.</p>")
        table("Not yet answered", awaiting)

    if due:
        T.append("== FOLLOW UP (applied 10+ days ago, no news) ==")
        H.append("<h3>Follow up</h3><p style='color:#666'>Applied 10+ days ago with no news. A short "
                 "note to the recruiter or hiring manager is worth it (at most twice).</p><ul>")
        for e in due:
            n = e.get("followups", 0) + 1
            T.append(f"  {code(e)} {e['title']} — {e['company']}, applied {e.get('applied_on')} "
                     f"(nudge {n} of 2): {e['url']}")
            H.append(f"<li><code>{h(e.get('code'))}</code> <a href='{h(e['url'])}'>{h(e['title'])}</a> — "
                     f"{h(e['company'])}, applied {h(e.get('applied_on'))} (nudge {n} of 2)</li>")
        T.append("")
        H.append("</ul>")

    T += ["== SINCE THE LAST LETTER ==",
          f"  runs {stats.get('runs', 0)} · fetched {stats.get('fetched', 0)} · passed filters "
          f"{stats.get('passed', 0)} · scored {stats.get('scored', 0)} · matched {stats.get('matched', 0)}"]
    H += ["<h3>Since the last letter</h3>",
          f"<p>{stats.get('runs', 0)} runs · {stats.get('fetched', 0)} jobs fetched · "
          f"{stats.get('passed', 0)} passed filters · {stats.get('scored', 0)} scored · "
          f"{stats.get('matched', 0)} matched (≥ threshold)</p>"]
    if usage:
        T.append(f"  Claude usage: {_usage_line(usage)}")
        H.append(f"<p style='color:#666;font-size:12px'>Claude usage: {h(_usage_line(usage))}</p>")
    bad = [f"{n}: {x.get('error') or '0 jobs, possibly blocked'}" for n, x in (health or {}).items()
           if x.get("error") or x.get("fresh") == 0]
    if bad:
        T += [f"  WARNING {b}" for b in bad]
        H.append("<p style='color:#a33'>" + "<br>".join("⚠ " + h(b) for b in bad) + "</p>")
    T.append("")

    facts = profile.get("application_facts") or {}
    if facts:
        T.append("== APPLICATION CHEAT SHEET ==")
        H.append("<h3>Application cheat sheet</h3><table cellpadding='3' style='font-size:13px'>")
        for k, v in facts.items():
            label = k.replace("_", " ").capitalize()
            T.append(f"  {label}: {v if v is not None else '(fill in profiles/<id>.yaml)'}")
            H.append(f"<tr><td style='color:#666'>{h(label)}</td><td>"
                     f"{h(v) if v is not None else '<i>(fill in profile)</i>'}</td></tr>")
        H.append("</table>")
    T += ["", "Drafts only. Nothing was submitted (Rule #1). Edit, then send yourself."]
    H.append("<p style='color:#888;font-size:12px'>Drafts only. Nothing was submitted. "
             "Edit the documents, then apply yourself.</p>")
    body = ("<div style='font-family:Segoe UI,Arial,sans-serif;max-width:900px;color:#222'>"
            + "\n".join(H) + "</div>")
    return subject, "\n".join(T), body
