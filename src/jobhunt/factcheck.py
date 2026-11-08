"""Fact check for generated documents (career-ops verify-cv-facts, ai-job-search grounding audit).

Rules 2 and 4 are in the prompts; this checks them in code, and FLAGS (never blocks) so the
candidate fixes the draft before sending:
  - every number in a resume / letter / outreach note must appear in the sources (base resume +
    profile), allowing for formatting ("300x" ~ "300×", "2.1M" ~ "2.1 million");
  - money amounts and the profile's confidential figures (e.g. internal reconciliation amounts)
    must not appear at all: describe the structure, not the figure;
  - a gap-list skill appearing in the resume is a claim (the letter may NAME a gap, so letters
    are not checked for this).
"""
from __future__ import annotations
import re

NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(%|x|×|k|m|bn|tb|gb|mb|million|billion|\+)?(?![\w])", re.I)
MONEY = re.compile(r"([$€£₹]\s?\d[\d,.]*\s?(k|m|bn|million|billion|cr|crore|lakh)?|\b\d[\d,.]*\s?(million|billion|crore|lakh)"
                   r"\s+(dollars|usd|eur|euros|inr|rupees)\b)", re.I)
_TRIVIAL = {str(n) for n in range(0, 13)} | {"2024", "2025", "2026", "2027"}


def _norm_num(v: str) -> str:
    return v.replace(",", "").rstrip("0").rstrip(".") if "." in v else v.replace(",", "")


def _numbers(text: str) -> set[str]:
    return {_norm_num(m.group(1)) for m in NUMBER.finditer(text or "")}


def check(doc: str, sources: str, gaps: list[str], kind: str = "resume",
          confidential: list[str] | None = None) -> list[str]:
    """Return human-readable warnings for one generated document."""
    warnings = []
    known = _numbers(sources)
    for n in sorted(_numbers(doc) - known):
        if n in _TRIVIAL or len(n) == 4 and n.startswith("19"):
            continue
        warnings.append(f"number {n} is not in your resume/profile: confirm it or remove it")
    for m in MONEY.finditer(doc or ""):
        warnings.append(f"money figure '{m.group(0).strip()}': describe the structure instead (Rule 4)")
    for c in confidential or []:
        if c and c.lower() in (doc or "").lower():
            warnings.append(f"confidential detail '{c}' appears: remove it (Rule 4)")
    if kind == "resume":
        low = (doc or "").lower()
        for g in gaps or []:
            term = re.split(r"[(/]", str(g))[0].strip()
            if len(term) > 2 and re.search(r"\b" + re.escape(term.lower()) + r"\b", low):
                warnings.append(f"gap-list skill '{term}' appears in the resume: never claim it (Rule 2)")
    return list(dict.fromkeys(warnings))
