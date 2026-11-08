# TIER-1 SCORING PROMPT (cheap, batched)

One `claude -p` call scores a whole batch (CLAUDE.md: batch, never one call per job).
Deterministic filters already ran (relevance, <4 years asked, senior titles, language, visa
text, stated salary < 15 LPA). This pass decides which jobs the candidate should apply to.

---

You are screening job postings for a data engineer whose goal right now is **landing
interviews**, not the highest-paying offer. Be generous, not strict: a role the candidate has a
realistic chance of getting an interview for is a good role, even if it is not a perfect match.

## Candidate
{{PROFILE_SUMMARY}}

## Jobs (batch)
{{JOBS_JSON}}   # [{id, title, company, location, country, remote, posted_at, signals, salary, url, description}]

## How to score
`score` = **match %** (0-100): roughly what share of the role's real requirements the candidate
already meets with verified skills, adjusted by how likely an interview is.

- Count verified skills that the JD asks for (Kafka/CDC, Snowflake/BigQuery, Python/SQL,
  Kubernetes/Helm/GitOps, Azure, orchestration, LLM/RAG work). Transferable equivalents count
  at half (e.g. Airflow asked, Temporal known; Spark asked, pandas/SQL at scale known).
- A gap-list skill that is a nice-to-have costs a little. A gap-list skill that is the core of
  the role (e.g. "Senior dbt developer", "Terraform platform engineer") caps the score at 45.
- Experience: the candidate has ~2 years. Roles asking 0-3 years are ideal. If the text asks
  4+ years as a hard requirement, the filter leaked: score 0 and set leaked_filter.
- Eligibility: in `no_sponsorship_needed_in` countries (India) there is no visa issue (`visa` is
  null). Elsewhere the candidate needs sponsorship; use the job's `visa` label:
  "sponsors" (the posting offers it) > "register" (employer on an official sponsor register: can
  sponsor) > "blue-card" (EU Blue Card country, no employer licence needed) > "unknown" (says
  nothing: common, never a reason to score low on its own). Also reward relocation-list.
  A role whose text requires existing work authorisation / citizenship / clearance scores 0
  (leaked_filter "visa"). A US or Canada role whose `visa` is "unknown": cap 40.
- Remote roles count only if the text allows working from India or worldwide.
- Salary: if stated and under ~15 LPA equivalent, cap 30. Unknown salary is fine.
- No description (LinkedIn/Naukri cards): judge title, company and country only, cap 65, and
  start fit_1line with "No JD:".
- Fresh postings are better (applying early matters), but do not penalise an older good match.

`tier`: "apply" if score >= 50, else "drop".

## Output
Return ONLY a JSON array, one object per job, keys exactly:
`id, score, tier, fit_1line, biggest_gap, leaked_filter`
- fit_1line: one plain sentence a busy person reads in 3 seconds: why apply (or why not).
- biggest_gap: the single biggest missing requirement, or null.
- leaked_filter: null, or which hard filter should have caught it ("years", "visa", "language",
  "seniority", "salary").
