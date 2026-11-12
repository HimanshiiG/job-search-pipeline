"""Deterministic hard filters (NO LLM, free, run in CI).

Stage 0 lesson, baked in: the source's visa_sponsorship flag is NOISY. The real
disqualifiers (visa / language / seniority) live in the JD BODY, so we parse it.
Knobs come from profile.hard_filters; the regex engine is here (code owns complex patterns).
"""
from __future__ import annotations
import re

# --- canonical patterns (validated against the 2026-10 Arbeitnow snapshot) ---
VISA_BLOCK = re.compile(
    r"(do not (currently )?sponsor|cannot sponsor|no visa sponsorship|"
    r"without (visa )?sponsorship|must (already )?have (the |an |a )?(existing )?right to work|"
    r"existing right to work|valid work permit|authori[sz]ed to work in)", re.I)

LANG_BLOCK = re.compile(
    r"((fluen\w*|proficien\w*|native|verhandlungssicher|flie[sß]end|C1|B2)"
    r".{0,40}(german|deutsch|french|fran[cç]ais)|"
    r"(german|deutsch|french|fran[cç]ais).{0,40}"
    r"(fluen\w*|proficien\w*|native|required|C1|B2|verhandlungssicher)|"
    r"gute.{0,20}deutschkenntnisse)", re.I)

# Eligibility gate (ai-job-search "Eligibility Gate"): a role the candidate cannot legally hold.
# Citizenship / permanent residency / security clearance, and Gulf nationals-only hiring.
# Not applied in the candidate's home country (eligibility.no_sponsorship_needed_in).
ELIGIBILITY_BLOCK = re.compile(
    r"(\b(must|need to|required to) (be|hold) (a |an )?(u\.?s\.?|american|uk|british|eu|european|australian|"
    r"canadian|singapore(an)?|german|dutch|irish|new zealand) (citizen|national)s?\b|"
    r"\b(citizenship|permanent residen(t|cy)|pr holders?|green card( holders?)?)\b.{0,40}"
    r"\b(required|only|must|mandatory)\b|"
    r"\b(only|exclusively) (open to|for|available to) (\w+ )?(citizens|nationals|permanent residents)\b|"
    r"\b(security clearance|sc clearance|dv clearance|ts/sci|top secret clearance|secret clearance|"
    r"baseline clearance|nv[12] clearance|active clearance|clearance (is )?required|"
    r"(eligible|able) to (obtain|hold) (a |an )?(security |government )?clearance)\b|"
    r"\b(emirati|saudi|qatari|omani|kuwaiti|bahraini) nationals?\b|\bemiratisation\b|\bsaudi[sz]ation\b|"
    r"\bnationals only\b)", re.I)

# Years of experience (career-ops jd-years idea): read every requirement, ignore preferred-only
# and non-requirement figures, and drop only when even the LOWEST stated requirement is out of
# reach. A wrong drop costs a real job; a wrong keep costs one scored row.
_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split())}
_N = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
YEARS = re.compile(
    rf"\b(?:at least|minimum(?: of)?|min\.?|over|more than)?\s*{_N}\s*(?:\(\d{{1,2}}\)\s*)?\+?\s*"
    rf"(?:(?:-|–|to|and)\s*{_N}\s*\+?\s*)?(?:or more\s+)?(years?|yrs?|months?)\b", re.I)
_PREFERRED = re.compile(r"\b(preferred|nice[- ]to[- ]have|ideally|a plus|is a bonus|desirable|advantageous|"
                        r"would be great|bonus points)\b", re.I)
_NOT_A_REQUIREMENT = re.compile(r"\b(founded|history|in business|for over|since \d{4}|clients|customers|"
                                r"we have been|our company|has been|celebrat|anniversary|warranty|contract of)\b", re.I)

DE_STOP = ["und", "oder", "mit", "deine", "wir", "unsere", "für", "bei", "das",
           "die", "der", "nicht", "werden"]
FR_STOP = ["le", "la", "les", "des", "une", "dans", "pour", "avec", "nous", "vous",
           "être", "votre", "afin", "au sein"]
# Dutch (2026-11-08: Dutch-only postings were reaching scoring; NL is a priority market)
NL_STOP = ["het", "een", "van", "voor", "wij", "jouw", "je", "bij", "zijn", "naar", "ook", "onze",
           "werkzaamheden", "ervaring", "functie"]


def _num(s: str) -> int:
    return int(s) if s.isdigit() else _NUM_WORDS[s.lower()]


def years_required(text: str) -> float | None:
    """The lowest years-of-experience figure the JD states as a requirement, or None.
    Ranges count by their lower bound ('3-5 years' asks for 3); months convert to years;
    sentences that mark the figure as preferred, or that are about the company, are skipped."""
    vals = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n|•|·", text or ""):
        if _PREFERRED.search(sentence) or _NOT_A_REQUIREMENT.search(sentence):
            continue
        for m in YEARS.finditer(sentence):
            n = _num(m.group(1))
            v = n / 12 if m.group(3).lower().startswith("month") else n
            if 0 < v <= 25:
                vals.append(v)
    return min(vals) if vals else None


def _max_years_required(text: str) -> int | None:
    """Kept for callers/tests: the requirement used for the years filter, as an int."""
    v = years_required(text)
    return None if v is None else int(v) if v == int(v) else round(v, 1)


PERIODS_PER_YEAR = {"year": 1, "yearly": 1, "annual": 1, "month": 12, "monthly": 12,
                    "week": 52, "weekly": 52, "day": 260, "daily": 260, "hour": 2080, "hourly": 2080}


def annual_salary_inr(salary: dict | None, fx_to_inr: dict) -> float | None:
    """Top of the stated range, annualised and converted to INR. None if unknown/unconvertible."""
    if not salary:
        return None
    amount = salary.get("max") or salary.get("min")
    rate = fx_to_inr.get((salary.get("currency") or "").upper())
    per_year = PERIODS_PER_YEAR.get((salary.get("period") or "year").lower())
    if not amount or not rate or not per_year:
        return None
    return float(amount) * per_year * float(rate)


def _looks_non_english(text: str, threshold: int, extra: list[str]) -> bool:
    low = text.lower()
    words = DE_STOP + FR_STOP + NL_STOP + [w.lower() for w in (extra or [])]
    hits = sum(len(re.findall(r"\b" + re.escape(w) + r"\b", low)) for w in words)
    return hits >= threshold


def evaluate(job: dict, profile: dict) -> list[str]:
    """Return a list of failed-filter tags. Empty list == passes."""
    hf = profile.get("hard_filters", {})
    elig = profile.get("eligibility", {})
    title = job["title"]
    body = job["description"]
    fails = []

    # relevance: must match the profile's relevance regex somewhere
    rel = profile.get("relevance_regex")
    if rel:
        # collapse any whitespace/newlines from the YAML folded scalar; do NOT use re.X
        # (VERBOSE would drop the spaces inside multi-word terms like "analytics engineer").
        # also drop the space the fold leaves after a line-ending "|", or "| big data" would need
        # a word before it and miss titles that start with the term.
        rx = re.compile(re.sub(r"\s*\|\s*", "|", re.sub(r"\s+", " ", rel)).strip(), re.I)
        if not (rx.search(title) or rx.search(body)):
            fails.append("IRRELEVANT")

    # visa: only matters if the candidate needs sponsorship in this job's country
    home = [c.upper() for c in elig.get("no_sponsorship_needed_in", [])]
    needs_visa = elig.get("needs_sponsorship") and (job.get("country") or "").upper() not in home
    if hf.get("block_visa_body", True) and needs_visa and VISA_BLOCK.search(body):
        fails.append("NO-SPONSOR")

    # eligibility: citizenship / PR / clearance / nationals-only (never in the home country)
    if hf.get("block_eligibility", True) and needs_visa and ELIGIBILITY_BLOCK.search(f"{title} {body}"):
        fails.append("CITIZEN/CLEARANCE")

    # language requirement in an otherwise-English JD
    if hf.get("block_language_required", True) and LANG_BLOCK.search(body):
        fails.append("LANG-REQ")

    # whole JD not in English
    if hf.get("require_english_jd", True) and _looks_non_english(
            body, int(hf.get("non_english_jd_threshold", 8)), hf.get("extra_stopwords", [])):
        fails.append("JD-NON-EN")

    # seniority by title
    # Dual-level titles keep their reachable end (Sonnet audit 2026-11-12): "Senior/Staff Data
    # Engineer", "Senior / Principal ...", and entry staff grades like "Staff Engineer I" go to scoring.
    titles = [t.lower() for t in hf.get("drop_senior_titles", [])]
    dual_level = re.search(r"\bsenior\b[^/]{0,40}/[^/]{0,10}\b(staff|principal|lead)\b|"
                           r"\b(staff|principal|lead)\b[^/]{0,40}/[^/]{0,10}\bsenior\b|"
                           r"\bstaff (software |data )?engineer (i|1)\b", title, re.I)
    if not dual_level and any(re.search(r"\b" + re.escape(t) + r"\b", title.lower()) for t in titles):
        fails.append("SR-TITLE")

    # years of experience
    maxy = hf.get("max_years_required")
    if maxy is not None:
        # a structured minimum (Naukri experience range, freehire enrichment) beats the regex
        req = job.get("years_min") if job.get("years_min") is not None else _max_years_required(body)
        if req is not None and req > int(maxy):
            fails.append(f"{int(req)}+YRS")

    # salary floor: only when the source states a salary (most don't; unknown passes)
    floor = hf.get("salary_floor_inr")
    if floor:
        inr = annual_salary_inr(job.get("salary"), hf.get("fx_to_inr", {}))
        if inr is not None and inr < float(floor):
            fails.append("LOW-SALARY")

    return fails


def apply(jobs: list[dict], profile: dict) -> tuple[list[dict], list[dict]]:
    """Split into (passed, dropped). Each job gets job['filter_fails']."""
    passed, dropped = [], []
    for j in jobs:
        fails = evaluate(j, profile)
        j["filter_fails"] = fails
        (dropped if fails else passed).append(j)
    return passed, dropped
