"""Visa label per job (2026-11-08): no single source is reliable, so several are combined.

  sponsors   the posting says so ("visa sponsorship available", "we sponsor", relocation package)
  register   the employer is on an official sponsor register: UK Home Office licensed sponsors
             (Skilled Worker route), NL IND recognised sponsors, or freehire's register tags
             (UK, NL, US H-1B, IE, CA, DK). Says the company CAN sponsor, not that this role will.
  blue-card  an EU Blue Card country: no employer licence is needed (Germany is the clearest case),
             the salary threshold is the gate
  unknown    nothing either way. Never a reason to drop: most postings say nothing.
Postings that refuse sponsorship are already dropped by the filters (NO-SPONSOR). Home-country
jobs (India) get no label. Registers are downloaded at most weekly and cached in state/.
"""
from __future__ import annotations
import csv, io, json, re, time
from pathlib import Path

import requests

UK_REGISTER_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
NL_REGISTER_PAGE = ("https://ind.nl/en/public-register-recognised-sponsors/"
                    "public-register-regular-labour-and-highly-skilled-migrants")
UA = {"User-Agent": "Mozilla/5.0 (jobhunt-pipeline; personal job search)", "Accept-Encoding": "identity"}
BLUE_CARD = {"DE", "NL", "AT", "BE", "FR", "ES", "PT", "IT", "PL", "SE", "FI", "CZ", "LU", "LT", "LV", "EE",
             "SK", "SI", "HU", "RO", "BG", "HR", "GR", "CY", "MT"}
REGISTER_SIGNALS = {"uk-skilled-worker-sponsor", "nl-recognised-sponsor", "us-h1b-sponsor",
                    "ie-permit-employer", "ca-lmia-employer", "dk-fast-track-company", "uk-register", "nl-register"}
POSITIVE = re.compile(
    r"(visa sponsorship (is )?(available|provided|offered|possible|supported)|"
    r"\b(we|will|can|happy to|able to) (provide |offer )?(visa )?sponsor(ship)?\b(?! is not)|"
    r"sponsorship (is )?available|relocation (support|package|assistance|bonus)|"
    r"help (you )?with (your )?(visa|relocation|work permit)|blue card (support|sponsorship))", re.I)
_SUFFIX = re.compile(r"\b(ltd|limited|plc|llp|llc|inc|corp|corporation|co|company|gmbh|ag|se|bv|b v|nv|n v|"
                     r"holding|holdings|group|uk|international|the)\b")
_STATUS_TAGS = ("register", "sponsors", "blue-card", "unknown")


def tokens(name: str) -> tuple[str, ...]:
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    return tuple(t for t in _SUFFIX.sub(" ", s).split() if t)


class Register:
    """Company-name lookup: exact token match, or the register name starting with the job's
    company tokens ("Wise" ~ "Wise Payments Limited") when that prefix is specific enough."""
    def __init__(self, names: list[str]):
        self.by_first: dict[str, set[tuple[str, ...]]] = {}
        for n in names:
            t = tokens(n)
            if t:
                self.by_first.setdefault(t[0], set()).add(t)

    def __contains__(self, company: str) -> bool:
        jt = tokens(company)
        if not jt:
            return False
        for rt in self.by_first.get(jt[0], ()):
            if rt == jt or (rt[:len(jt)] == jt and (len(jt) >= 2 or len(jt[0]) >= 5)):
                return True
        return False


def _download_uk() -> list[str]:
    page = requests.get(UK_REGISTER_PAGE, headers=UA, timeout=60).text
    url = re.search(r"https://assets\.publishing\.service\.gov\.uk/[^\"]+\.csv", page).group(0)
    text = requests.get(url, headers=UA, timeout=180).content.decode("utf-8-sig", "replace")
    rows = csv.DictReader(io.StringIO(text))
    return sorted({r["Organisation Name"].strip() for r in rows
                   if "skilled worker" in (r.get("Route") or "").lower() and r.get("Organisation Name")})


def _download_nl() -> list[str]:
    for attempt in range(3):
        try:
            page = requests.get(NL_REGISTER_PAGE, headers=UA, timeout=120).text
            break
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(5)
    cells = re.findall(r"<tr[^>]*>\s*<t[dh][^>]*>(.*?)</t[dh]>", page, re.S)
    return sorted({re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip().strip('"') for c in cells[1:]} - {""})


def load_registers(cache: Path, max_age_days: int = 7) -> dict[str, Register]:
    """{'GB': Register, 'NL': Register}; refreshed at most weekly, stale cache kept on failure."""
    data = {}
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if time.time() - data.get("fetched_at", 0) > max_age_days * 86400:
        fresh = dict(data)
        for key, fn in (("GB", _download_uk), ("NL", _download_nl)):
            try:
                fresh[key] = fn()
            except Exception as e:  # keep last week's list rather than none
                print(f"  ! sponsor register {key} refresh failed: {e.__class__.__name__}")
        if fresh.get("GB") or fresh.get("NL"):
            fresh["fetched_at"] = time.time()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(fresh), encoding="utf-8")
            data = fresh
    return {k: Register(v) for k, v in data.items() if k in ("GB", "NL") and v}


def label(job: dict, profile: dict, registers: dict[str, Register]) -> str | None:
    home = {c.upper() for c in profile.get("eligibility", {}).get("no_sponsorship_needed_in", [])}
    country = (job.get("country") or "").upper()
    if country in home:
        return None
    signals = set(job.get("signals") or [])
    if "visa-sponsorship-stated" in signals or "relocation-supported" in signals or POSITIVE.search(job.get("description") or ""):
        return "sponsors"
    reg = registers.get(country)
    if reg is not None and job.get("company") in reg:
        job.setdefault("signals", []).append(f"{country.lower().replace('gb', 'uk')}-register")
        return "register"
    if signals & REGISTER_SIGNALS:
        return "register"
    if country in BLUE_CARD:
        return "blue-card"
    return "unknown"


def add_labels(jobs: list[dict], profile: dict, registers: dict[str, Register]) -> None:
    for j in jobs:
        j["visa"] = label(j, profile, registers)
