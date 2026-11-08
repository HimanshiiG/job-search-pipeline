"""Fetch + normalise jobs from configured sources. Adapter per source `type`.

Every adapter returns a list of normalised dicts:
  {id, source, company, title, location, remote, url, description, tags, created_at,
   country, posted_at, posted_precision, years_min, signals, origin}

Freshness is enforced here for every source that sets `max_age_hours` (Phase-1 finding: a
source's "new" flag is not the posting date, so we filter on posted_at ourselves).
"""
from __future__ import annotations
import re, html, json, os, time
from datetime import datetime, timezone
import requests

from . import sanitize

UA = {"User-Agent": "jobhunt-pipeline/0.1 (personal job search; polite)"}
TIMEOUT = 30


def _clean_flag(text: str) -> tuple[str, bool]:
    """HTML -> plain text, with hidden elements, invisible characters and instruction-shaped
    lines removed (sanitize.py). Returns (text, flagged)."""
    text = sanitize.strip_hidden_html(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text, removed = sanitize.clean_text(text)
    return re.sub(r"\s+", " ", text).strip(), bool(removed)


def _clean(text: str) -> str:
    return _clean_flag(text)[0]


def _norm(source, company, title, location, remote, url, description, tags, created_at,
          country=None, posted_at=None, posted_precision="time", years_min=None,
          signals=None, origin=None, salary=None, board_url=None) -> dict:
    """salary: {min, max, currency, period} when the source states one (period: year/month/...)."""
    description, flagged = _clean_flag(description)
    signals = list(signals or []) + (["posting-flagged"] if flagged else [])
    return {
        "id": f"{source}:{url}",
        "source": source,
        "company": (company or "").strip(),
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "remote": bool(remote),
        "url": url,
        "description": description,
        "tags": tags or [],
        "created_at": created_at,
        "country": country.upper() if country else guess_country(location),
        "posted_at": posted_at,
        "posted_precision": posted_precision,
        "years_min": years_min,
        "signals": signals or [],
        "origin": origin or source,
        "salary": salary if salary and (salary.get("min") or salary.get("max")) else None,
        "board_url": board_url or url,   # the job board's own page (LinkedIn view URL etc.)
    }


_COUNTRY_WORDS = {
    "DE": "germany deutschland berlin munich münchen hamburg frankfurt cologne köln stuttgart düsseldorf leipzig",
    "NL": "netherlands nederland amsterdam rotterdam utrecht eindhoven hague",
    "GB": "united kingdom uk england london manchester edinburgh glasgow cambridge oxford bristol",
    "IE": "ireland dublin cork", "AT": "austria österreich vienna wien graz", "CH": "switzerland zurich zürich geneva basel",
    "FR": "france paris lyon", "ES": "spain barcelona madrid", "PT": "portugal lisbon lisboa porto",
    "PL": "poland warsaw kraków krakow wrocław", "SE": "sweden stockholm", "DK": "denmark copenhagen",
    "BE": "belgium brussels antwerp", "IN": "india bengaluru bangalore mumbai pune hyderabad gurugram chennai",
}
_COUNTRY_LOOKUP = {w: c for c, ws in _COUNTRY_WORDS.items() for w in ws.split()}


def guess_country(location: str) -> str | None:
    """Country code from free-text location ("Berlin, Germany" -> DE), for sources that send none."""
    for w in re.findall(r"[a-zà-ÿ]+", (location or "").lower()):
        if w in _COUNTRY_LOOKUP:
            return _COUNTRY_LOOKUP[w]
    return None


def _get(url, params=None):
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _iso(ts) -> str | None:
    if ts in (None, ""):
        return None
    if isinstance(ts, (int, float)):
        ts = ts / 1000 if ts > 1e11 else ts  # ms vs s epoch
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    return str(ts)


def age_hours(job: dict, now: datetime | None = None) -> float | None:
    p = job.get("posted_at")
    if not p:
        return None
    try:
        dt = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() / 3600


def fresh_enough(job: dict, max_age_hours: float, now: datetime | None = None) -> bool:
    """Undated jobs fail. Day-precision dates get 24h of slack (the post could be late that day)."""
    a = age_hours(job, now)
    if a is None:
        return False
    slack = 24 if job.get("posted_precision") == "date" else 0
    return a <= max_age_hours + slack


# ---------- adapters ----------
def fetch_arbeitnow(src: dict) -> list[dict]:
    out, url = [], src["url"]
    params = dict(src.get("params", {}))
    for page in range(1, int(src.get("max_pages", 1)) + 1):
        params["page"] = page
        data = _get(url, params).json()
        rows = data.get("data", [])
        if not rows:
            break
        for j in rows:
            out.append(_norm(src["name"], j.get("company_name"), j.get("title"),
                             j.get("location"), j.get("remote"), j.get("url"),
                             j.get("description"), j.get("tags"), j.get("created_at"),
                             posted_at=_iso(j.get("created_at"))))
        time.sleep(0.5)  # polite
    return out


def fetch_lever(src: dict) -> list[dict]:
    company = src["company"]
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    out = []
    for j in _get(url).json():
        cats = j.get("categories", {}) or {}
        out.append(_norm(src["name"], company, j.get("text"), cats.get("location"),
                         (cats.get("commitment") or "").lower() == "remote",
                         j.get("hostedUrl"),
                         j.get("descriptionPlain") or j.get("description"),
                         [cats.get("team"), cats.get("department")], j.get("createdAt"),
                         posted_at=_iso(j.get("createdAt"))))
    return out


def fetch_greenhouse(src: dict) -> list[dict]:
    token = src["token"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    out = []
    for j in _get(url).json().get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        out.append(_norm(src["name"], token, j.get("title"), loc, False,
                         j.get("absolute_url"), j.get("content"), [], j.get("updated_at"),
                         posted_at=j.get("first_published") or j.get("updated_at")))
    return out


FREEHIRE = "https://freehire.me/api/v1/agent/jobs/search"
# freehire collections that mean "this employer is on an official sponsor register"
SPONSOR_COLLECTIONS = {"uk-skilled-worker-sponsor", "nl-recognised-sponsor", "us-h1b-sponsor",
                       "ca-lmia-employer", "ie-permit-employer", "dk-fast-track-company"}


def _freehire_undated(j: dict, undated_prefixes: list[str]) -> bool:
    """Phase-1: whatjobs/manatal/... carry no real posting date (posted_at == first seen)."""
    if any((j.get("source") or "").startswith(p) for p in undated_prefixes):
        return True
    p, c = j.get("posted_at"), j.get("created_at")
    return bool(p and c and p[:16] == c[:16])


def _freehire_job(src: dict, j: dict) -> dict:
    e = j.get("enrichment") or {}
    signals = sorted(SPONSOR_COLLECTIONS & set(j.get("collections") or []))
    if e.get("visa_sponsorship"):
        signals.append("visa-sponsorship-stated")
    if e.get("relocation") in ("supported", "required"):
        signals.append("relocation-supported")
    posted = j.get("posted_at")
    precision = "date" if posted and posted[11:19] == "00:00:00" else "time"
    countries = j.get("countries") or []
    return _norm(src["name"], j.get("company"), j.get("title"), j.get("location"),
                 j.get("work_mode") == "remote", j.get("url"), j.get("description"),
                 j.get("skills"), j.get("created_at"),
                 country=countries[0] if len(countries) == 1 else (countries[0] if countries else None),
                 posted_at=posted, posted_precision=precision,
                 years_min=e.get("experience_years_min"), signals=signals,
                 origin=f"freehire/{j.get('source')}",
                 salary={"min": e.get("salary_min"), "max": e.get("salary_max"),
                         "currency": e.get("salary_currency"), "period": e.get("salary_period")})


def fetch_freehire(src: dict) -> list[dict]:
    """One search per geography group (geography facets OR together, so each group is separate
    to stop one big region from eating the page budget). Filters on the source's posting date."""
    days = int(src.get("max_age_hours", 36) // 24) + 2
    cap = int(src.get("max_per_group", 300))
    undated = src.get("undated_sources", [])
    out = []
    for g in src.get("groups", []):
        params = {"category": src.get("category", "data_engineering"),
                  "posted_within_days": days, "sort": "posted_at", "order": "desc",
                  "description_format": "text", "limit": 100}
        for key in ("countries", "regions", "work_mode"):
            if g.get(key):
                params[key] = ",".join(g[key]) if isinstance(g[key], list) else g[key]
        if src.get("seniority_exclude"):
            params["seniority_exclude"] = ",".join(src["seniority_exclude"])
        got = 0
        for offset in range(0, cap, 100):
            params["offset"] = offset
            r = requests.get(FREEHIRE, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
                r = requests.get(FREEHIRE, params=params, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            rows = r.json().get("data", [])
            for j in rows:
                if not _freehire_undated(j, undated):
                    out.append(_freehire_job(src, j))
            got += len(rows)
            if len(rows) < 100:
                break
            time.sleep(0.2)
    return out


def _years_from_range(s) -> int | None:
    m = re.match(r"\s*(\d{1,2})", str(s or ""))
    return int(m.group(1)) if m else None


def run_slot() -> str:
    """'morning' or 'evening': from JOBHUNT_SLOT, else from the UTC hour (IST mornings are
    late-night UTC)."""
    slot = os.environ.get("JOBHUNT_SLOT")
    if slot:
        return slot
    h = datetime.now(timezone.utc).hour
    return "morning" if (h >= 20 or h < 6) else "evening"


def search_terms(src: dict) -> list[str]:
    """`search_terms_by_slot: {morning: [...], evening: [...]}` splits slow sources' terms across
    the two daily runs (each term still runs once a day); otherwise `search_terms`."""
    by_slot = src.get("search_terms_by_slot")
    if by_slot:
        return list(by_slot.get(run_slot()) or [])
    return list(src.get("search_terms", ["data engineer"]))


def fetch_jobspy(src: dict) -> list[dict]:
    """LinkedIn / Indeed / Naukri / Bayt via python-jobspy (scrapes public pages, no login).
    One search per (term, search entry). Card data only unless fetch_description is set."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print(f"  ! {src['name']}: python-jobspy not installed (py -m pip install python-jobspy)")
        return []
    import pandas as pd
    site = src["site"]
    out = []
    for term in search_terms(src):
        for s in src.get("searches", []):
            kw = dict(site_name=[site], search_term=term, hours_old=src.get("hours_old", 36),
                      results_wanted=src.get("results_wanted", 50), verbose=0,
                      fetch_description=bool(src.get("fetch_description", False)))
            for key in ("location", "country_indeed", "is_remote"):
                if key in s:
                    kw[key] = s[key]
            where = s.get('location') or s.get('country_indeed')
            try:
                df = scrape_jobs(**kw)
            except Exception as e:  # one blocked search must not sink the source
                print(f"  ! {src['name']} {term!r} @ {where}: {e.__class__.__name__}: {str(e)[:80]}")
                src.setdefault("_errors", []).append(f"{where}: {e.__class__.__name__}")
                df = None
            # JobSpy >= 1.4 reports per-board failures here instead of raising
            for err in ((getattr(df, "attrs", None) or {}).get("errors") or []) if df is not None else []:
                src.setdefault("_errors", []).append(f"{where}: {str(err)[:80]}")
            for r in ([] if df is None else df.to_dict("records")):
                val = lambda k: None if k not in r or pd.isna(r[k]) else r[k]  # noqa: E731
                posted = val("date_posted")
                out.append(_norm(src["name"], val("company"), val("title"), val("location"),
                                 bool(val("is_remote")), val("job_url_direct") or val("job_url"),
                                 val("description"), [], None,
                                 country=s.get("country"),
                                 posted_at=str(posted) if posted is not None else None,
                                 posted_precision="date",
                                 years_min=_years_from_range(val("experience_range")),
                                 origin=f"jobspy/{site}",
                                 salary={"min": val("min_amount"), "max": val("max_amount"),
                                         "currency": val("currency"), "period": val("interval")},
                                 board_url=val("job_url")))
            time.sleep(float(src.get("sleep_sec", 3)))
    return out


_LI_ID = re.compile(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})")


HAS_JD = 300   # characters: below this a job is treated as a card without a description
_LI_CLOSED = re.compile(r"closed-job__flavor|no longer accepting applications", re.I)


def has_description(job: dict) -> bool:
    return len(job.get("description") or "") >= HAS_JD


def fill_description(job: dict, tries: int = 3, backoff: float = 4.0) -> str:
    """Fetch the JD for a card-only LinkedIn job (2026-11-08: no job is scored on its title alone).
    Returns 'ok' (description filled), 'closed' (posting shows LinkedIn's closed banner),
    'failed' (throttled / unreachable after retries: try again next run) or 'skip' (not a
    LinkedIn job, or it already has a JD). Retries 429/5xx with exponential backoff: on GitHub's
    servers LinkedIn throttles right after the search burst."""
    if has_description(job):
        return "skip"
    m = _LI_ID.search(job.get("board_url") or job.get("url") or "")
    if not m:
        return "skip"
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            if _LI_CLOSED.search(r.text):
                return "closed"
            body = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', r.text, re.S)
            text, flagged = _clean_flag(body.group(1)) if body else ("", False)
            if len(text) >= HAS_JD:
                job["description"] = text
                if flagged and "posting-flagged" not in job.setdefault("signals", []):
                    job["signals"].append("posting-flagged")
                return "ok"
            return "failed"
        if r is not None and r.status_code in (404, 410):
            return "closed"
        time.sleep(backoff * (2 ** attempt))
    return "failed"


def enrich_descriptions(jobs: list[dict], max_fetch: int = 400, pause: float = 1.5) -> dict:
    """fill_description over every card-only job, politely. Sets job['jd_status']; returns counts."""
    counts = {"ok": 0, "closed": 0, "failed": 0, "skip": 0, "over_cap": 0}
    done = 0
    for j in jobs:
        if has_description(j):
            j["jd_status"] = "skip"
            counts["skip"] += 1
            continue
        if done >= max_fetch:
            j["jd_status"] = "failed"
            counts["over_cap"] += 1
            continue
        status = fill_description(j)
        j["jd_status"] = status
        counts[status] += 1
        if status != "skip":
            done += 1
            time.sleep(pause)
    return counts


def _get_retry(method, url, tries=3, **kw):
    """Some hosts (WTTJ, ind.nl) cut long responses mid-stream on this route; retry those."""
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("headers", UA)
    for attempt in range(tries):
        try:
            r = requests.request(method, url, **kw)
            r.raise_for_status()
            return r
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError):
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_wttj(src: dict) -> list[dict]:
    """Welcome to the Jungle (EU tech, FR-heavy): the public Algolia search the site itself uses
    (career-ops providers/wttj.mjs). English postings only, posted within the window. The hit
    carries summary / key missions / profile, which together make the description."""
    env = _get_retry("GET", "https://www.welcometothejungle.com/api/env").text
    app = re.search(r'"PUBLIC_ALGOLIA_APPLICATION_ID":"([^"]+)"', env).group(1)
    key = re.search(r'"PUBLIC_ALGOLIA_API_KEY_CLIENT":"([^"]+)"', env).group(1)
    since = int(time.time() - float(src.get("max_age_hours", 48)) * 3600 - 86400)
    headers = {"x-algolia-application-id": app, "x-algolia-api-key": key,
               "referer": "https://www.welcometothejungle.com/", "content-type": "application/json"}
    filters = f"published_at_timestamp>{since}" + (f" AND {src['filters']}" if src.get("filters") else "")
    out, seen = [], set()
    for q in src.get("search_terms", ["data engineer"]):
        params = f"query={requests.utils.quote(q)}&hitsPerPage=200&filters={requests.utils.quote(filters)}"
        hits = _get_retry("POST", f"https://{app}-dsn.algolia.net/1/indexes/wttj_jobs_production_en/query",
                          headers=headers, data=json.dumps({"params": params})).json().get("hits", [])
        for h in hits:
            if h.get("slug") in seen or (src.get("languages") and h.get("language") not in src["languages"]):
                continue
            seen.add(h.get("slug"))
            org = h.get("organization") or {}
            off = (h.get("offices") or [{}])[0]
            desc = " ".join(str(h.get(k) or "") for k in ("summary", "key_missions", "profile"))
            out.append(_norm(src["name"], org.get("name"), h.get("name"),
                             ", ".join(x for x in (off.get("city"), off.get("country")) if x),
                             h.get("remote") in ("fulltime", "full"),
                             f"https://www.welcometothejungle.com/en/companies/{org.get('slug')}/jobs/{h.get('slug')}",
                             desc, [], None, country=off.get("country_code"),
                             posted_at=_iso(h.get("published_at_timestamp")),
                             salary={"min": h.get("salary_minimum"), "max": h.get("salary_maximum"),
                                     "currency": h.get("salary_currency"), "period": h.get("salary_period")},
                             origin="wttj"))
        time.sleep(1)
    return out


def fetch_mycareersfuture(src: dict) -> list[dict]:
    """MyCareersFuture: Singapore's national job bank, public search API + per-job detail API
    (career-ops providers/mycareersfuture.mjs). Detail is fetched only for fresh jobs."""
    cutoff = time.time() - float(src.get("max_age_hours", 48)) * 3600 - 86400
    out, seen = [], set()
    for q in src.get("search_terms", ["data engineer"]):
        for page in range(int(src.get("max_pages", 2))):
            res = _get_retry("POST", f"https://api.mycareersfuture.gov.sg/v2/search?limit=100&page={page}",
                             headers={**UA, "content-type": "application/json"},
                             data=json.dumps({"search": q, "sortBy": ["new_posting_date"], "page": page})).json()
            rows = res.get("results", [])
            stop = False
            for r in rows:
                posted = (r.get("metadata") or {}).get("newPostingDate")
                if posted and datetime.fromisoformat(posted).replace(tzinfo=timezone.utc).timestamp() < cutoff:
                    stop = True
                    continue
                if r.get("uuid") in seen:
                    continue
                seen.add(r.get("uuid"))
                try:
                    d = _get_retry("GET", f"https://api.mycareersfuture.gov.sg/v2/jobs/{r['uuid']}").json()
                except requests.RequestException:
                    d = {}
                comp = (d.get("hiringCompany") or d.get("postedCompany") or r.get("hiringCompany")
                        or r.get("postedCompany") or {})
                sal = d.get("salary") or {}
                out.append(_norm(src["name"], comp.get("name"), r.get("title"), "Singapore", False,
                                 ((d.get("metadata") or {}).get("jobDetailsUrl")
                                  or f"https://www.mycareersfuture.gov.sg/job/{r['uuid']}"),
                                 d.get("description") or "", [], None, country="SG",
                                 posted_at=posted, posted_precision="date",
                                 years_min=d.get("minimumYearsExperience"),
                                 salary={"min": sal.get("minimum"), "max": sal.get("maximum"), "currency": "SGD",
                                         "period": ((sal.get("type") or {}).get("salaryType") or "month").lower()},
                                 origin="mycareersfuture"))
                time.sleep(0.3)
            if stop or len(rows) < 100:
                break
    return out


def fetch_hn(src: dict) -> list[dict]:
    """Hacker News "Ask HN: Who is hiring?" (official Algolia HN API; career-ops scan-hn). Each
    top-level comment is one posting; first line is usually "Company | Role | Location | ...".
    Many say VISA / REMOTE explicitly. Only comments posted within the window are kept."""
    story = requests.get("https://hn.algolia.com/api/v1/search_by_date", headers=UA, timeout=TIMEOUT,
                         params={"query": "Ask HN: Who is hiring?", "tags": "story,author_whoishiring"}).json()["hits"][0]
    since = int(time.time() - float(src.get("max_age_hours", 48)) * 3600)
    hits = requests.get("https://hn.algolia.com/api/v1/search_by_date", headers=UA, timeout=TIMEOUT,
                        params={"tags": f"comment,story_{story['objectID']}", "hitsPerPage": 1000,
                                "numericFilters": f"created_at_i>{since}"}).json().get("hits", [])
    out = []
    for h in hits:
        if str(h.get("parent_id")) != str(story["objectID"]):
            continue  # replies to postings, not postings
        text = html.unescape(re.sub(r"<p>", "\n", h.get("comment_text") or ""))
        first = re.sub(r"<[^>]+>", " ", text.split("\n", 1)[0])
        parts = [p.strip() for p in first.split("|")]
        company = parts[0][:80] if parts else "HN"
        title = next((p for p in parts[1:] if re.search(r"engineer|developer|data|scientist|analyst", p, re.I)),
                     parts[1] if len(parts) > 1 else first[:80])
        remote = bool(re.search(r"\bremote\b", first, re.I))
        signals = ["visa-sponsorship-stated"] if re.search(r"\bvisa\b(?! not)", first, re.I) else []
        out.append(_norm(src["name"], company, title[:120], " | ".join(parts[2:4])[:120], remote,
                         f"https://news.ycombinator.com/item?id={h['objectID']}", text, [], None,
                         posted_at=_iso(h.get("created_at_i")), signals=signals, origin="hn"))
    return out


ADAPTERS = {
    "arbeitnow": fetch_arbeitnow,
    "lever": fetch_lever,
    "greenhouse": fetch_greenhouse,
    "freehire": fetch_freehire,
    "jobspy": fetch_jobspy,
    "wttj": fetch_wttj,
    "mycareersfuture": fetch_mycareersfuture,
    "hn": fetch_hn,
}


def fetch_all(sources: list[dict], health: dict | None = None) -> list[dict]:
    """health (optional) is filled with per-source {fetched, fresh, error} for the report/email."""
    jobs = []
    health = health if health is not None else {}
    for src in sources:
        adapter = ADAPTERS.get(src["type"])
        if not adapter:
            print(f"  ! no adapter for source type '{src['type']}' ({src['name']}) — skipping")
            continue
        t0 = time.time()
        try:
            got = adapter(src)
            err = None
        except Exception as e:  # one bad source must not sink the run
            got, err = [], f"{e.__class__.__name__}: {str(e)[:120]}"
        n = len(got)
        board_errors = src.pop("_errors", [])
        if board_errors and not err:
            err = f"{len(board_errors)} search(es) failed, e.g. {board_errors[0]}" if not got else None
        if src.get("max_age_hours") is not None:
            got = [j for j in got if fresh_enough(j, float(src["max_age_hours"]))]
        health[src["name"]] = {"fetched": n, "fresh": len(got), "error": err,
                               "failed_searches": len(board_errors),
                               "seconds": round(time.time() - t0)}
        print(f"  {'!' if err else '+'} {src['name']}: {n} fetched, {len(got)} fresh"
              + (f"  ({err})" if err else ""))
        jobs.extend(got)
    return jobs
