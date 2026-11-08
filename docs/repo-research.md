# Research: ai-job-search, career-ops, JobSpy (2026-11-08)

Cloned at their latest commits and read the code and docs. None of their code was run. No
integration decisions here; this is what each project is and does.

| | ai-job-search | career-ops | JobSpy |
|---|---|---|---|
| Repo | ai-job-search-dev/ai-job-search | career-ops-hq/career-ops | speedyapply/JobSpy |
| What it is | Claude Code workflow (slash commands + skills) for one person's search | Large Claude Code / multi-CLI system for the whole search lifecycle | Python library that scrapes job boards |
| Size / activity | 315 files, 437 commits since Mar 2026, last commit 2026-11-07 | 3,280 files, ~3,970 commits since Apr 2026, last commit 2026-11-07 | 48 files, 393 commits, last commit 2026-10-27, v1.4.1 (2026-10-23) |
| Language | Markdown prompts + Python tools + Bun/TypeScript portal CLIs | Node.js (~250 scripts), Go TUI, web UI | Python |
| Licence | MIT | MIT | MIT |
| Runs | Interactively inside Claude Code | Interactively in Claude Code, Codex, Gemini, OpenCode etc.; headless batch with `claude -p` | Library, CLI (`jobspy`), MCP server (`mcp-jobspy`) |
| Evidence it works | Author: 69 tailored applications → 20 first interviews → 1 job | "Hired wall" with 22 public self-reported hires | Widely used library |

---

## 1. ai-job-search

A fork-and-fill framework. You give it your documents, it builds a profile, then six core
commands carry you from search to outcome. Built for the Danish market, with LinkedIn and
freehire as country-agnostic portals.

**Commands:** `/setup` (profile from CV / LinkedIn export / interview), `/scrape`, `/rank`,
`/apply`, `/interview`, `/outcome`, plus `/gmail-sync`, `/notion-sync`, `/html-report`,
`/expand`, `/upskill`, `/add-template`, `/add-portal`, `/reset`.

**`/apply`, the core (drafter–reviewer loop):**
1. Fetch the posting (portal CLI first, then WebFetch, then a browser-header retry that obeys
   robots.txt, then the employer's own careers page). Prefers the employer's posting over
   LinkedIn/Indeed copies because aggregators drop grade/seniority and requisition IDs.
2. **Posting integrity gate** (`tools/posting_guard.py`): strips hidden HTML, invisible and
   Unicode-tag characters, and flags instruction-shaped lines (prompt injection in job ads).
3. **Source host check**: posting from an installed portal, a known ATS domain
   (Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Workable), or flagged "unverified".
4. **Fit evaluation**: eligibility gate (citizenship/clearance = hard stop; "silence is not
   permission"), language gate (FAIL / FLAG / PASS), then 5 dimensions: technical 30%,
   experience 25%, behavioural 15%, career alignment 30%, location pass/fail. Bands:
   Strong 75+, Good 60–74, Moderate 45–59, Weak 30–44.
5. Draft a tailored **CV (LaTeX moderncv, exactly 2 pages)** and **cover letter (1 page)**.
   Every stated requirement must be addressed: matched, or an honest bridge for a gap.
6. A separate **reviewer agent** (fresh context, read-only) researches the company and
   returns exact-text edits plus narrative critique; the drafter applies them. A **grounding
   audit** checks every date, title and number against three source files.
7. **Compile and inspect the PDFs**: page count, layout holes, orphaned headings, then
   extract the PDF text layer and check it the way an ATS reads it (contact details as text,
   reading order, ASCII date ranges) plus a keyword-coverage table (covered / synonym /
   missing-have-it / missing-gap; never keyword-stuff).
8. Record a tracker row (`job_search_tracker.csv`) and archive the posting text.

**Writing rules** (`03-writing-style.md`): no em-dashes, no clichés ("passionate about",
"leverage"), no unverified company claims, no apologetic language; "interview backtrack
test" for every reframed bullet; cover letter is forward-looking (which of their problems you
solve), motivation section first, headline = specialty + posting keyword.

**Search side:** portal CLIs with one contract (`search` / `detail`, JSON output, `enabled`
flag), auto-discovered. `linkedin-search` uses LinkedIn's public `jobs-guest` endpoints with
backoff on 429, supports posted-within-N-minutes, and its `detail` returns `isActive`
(detects "No longer accepting applications", since dead LinkedIn URLs redirect to other
jobs). `/scrape` also does mass-posting detection, a per-portal health check (catches a
parser silently returning empty fields), and dedup against seen jobs and the tracker.
`/rank` scores in parallel agents and marks postings `expired` / `unreachable`,
deadline urgency (🔥 within 7 days), and a staleness flag for posts over 30 days old.

**Outreach:** light. `/scrape` builds two **LinkedIn people-search links** per good match
(recruiters at the company; people with the role title at the company) for you to open
yourself. Never scrapes people. `/outcome followup` drafts a 60–120-word follow-up after 10
quiet days (max two), using only claims already in what you sent; shaped for email or
LinkedIn message. `/interview` builds a prep pack and runs a mock interview.

**Needs:** Claude Code, Python, Bun, a LaTeX install (lualatex + xelatex).

---

## 2. career-ops

Much bigger and more opinionated: "apply better to fewer". Paste a job, it checks the job is
live, scores it 1–5 against your CV, writes a report, tailors a CV PDF, and logs it. Around 50
modes and ~250 scripts.

**Evaluation (`oferta`, blocks A–H):** liveness gate first; blacklist and dealbreaker gates;
agency/recruiter detection; then A role summary (+ geo-mismatch and **work-authorisation
check**, ⛔ only on explicit "no sponsorship"), B requirement-by-requirement CV match with
importance bands and evidence tiers, C level strategy, D comp and demand research, E
customisation plan, F interview plan with STAR stories, G **posting legitimacy** (ghost-job
signals), H draft application answers (only at high scores). Global score 1–5:
4.5+ apply now, 4.0–4.4 worth applying, below 4.0 it recommends against (you can override).
Evidence confidence (high/medium/low) per evaluation. `calibrate` checks whether scores
predict real outcomes.

**Outreach (`contacto` mode), the most relevant feature for networking:**
- Checks your saved-contacts phonebook (`data/contacts.tsv`) first for a warm lead.
- Otherwise finds **one** person by web search, in order: hiring manager, assigned
  recruiter, a team peer, an interviewer. Hard cap of 3 searches; never guesses a name; no
  login, no LinkedIn scraping.
- Writes a **3-sentence message per persona**:
  - Recruiter: fit / proof that pre-answers screening questions / "happy to share my CV".
  - Hiring manager: a specific challenge their team faces (from JD/blog/news) / your best
    quantified result on that problem / "would love to hear how your team approaches X".
  - Peer: genuine reference to their work / your related work / their take on a topic.
    **Does not ask for a job.**
  - Interviewer (pre-interview) and Internal referral (only with a real prior relationship,
    then asks directly).
- Respects LinkedIn's connection-note limit: **200 characters on a free account, 300 on
  Premium**. Never shares a phone number. Optional save to contacts, vCard export.
- `email` mode: application, **referral-request** and **cold** emails with subject line and
  attachment checklist, plus recovery emails (process stuck, interviewer no-show). Draft-only;
  there is no mail-sending code anywhere in the repo.
- `followup` + `followup-cadence.mjs`: overdue detection and drafts; `reply-watch`
  classifies employer replies into tracker updates.

**Documents:** CV rendered from HTML through headless Chromium (Playwright) to **PDF**, with a
fact check (numbers/facts in the PDF must exist in `cv.md`), newest-first ordering guard,
page budget, A4/Letter by country, optional ATS-parseable second render, ATS lint/score,
LaTeX/Overleaf export. Cover letter: four angle prompts (why / problems / approach / tone),
keyword mirroring, PDF through the same pipeline. "Voice DNA" file to write in your voice.

**Search side (zero-LLM scanner):** `scan.mjs` over `portals.yml` with title/location
filters, scan history, `--since`, cross-listing and repost detection, optional Playwright
liveness check. **55+ provider modules**, including: Greenhouse, Lever, Ashby, Workday,
SmartRecruiters, Workable, Recruitee, Personio, Teamtailor, BambooHR, SuccessFactors, Taleo,
Oracle Recruiting Cloud (JPMorgan, BNY, Amex), iCIMS, Phenom, Eightfold, **Darwinbox and Keka
(common in India)**, Zoho Recruit, Arbeitnow, Arbeitsagentur, Himalayas, Remotive, RemoteOK,
Jobicy, We Work Remotely, Welcome to the Jungle, Landing.jobs, The Hub, GermanTechJobs,
JustJoin.it, **SEEK/Jobstreet (Australia)**, **MyCareersFuture (Singapore)**, Platsbanken,
Job Bank Canada, Hacker News "Who is hiring", public Telegram channels, Amazon, Apple, Google,
IBM, Atlassian. Not supported: LinkedIn scanning (only pasting LinkedIn alert emails via
`linkedin-import.mjs`), Naukri, Indeed, Glassdoor (rejected: needs stealth scraping).
`discover-ats.mjs` resolves a company name to its live ATS board; `discover-new-companies`
feeds companies seen in scans back into that.

**Other:** UK sponsor-register check (`sponsor-check.mjs`, "not found means unconfirmed,
never doesn't sponsor"), H-1B sponsor plugin, Gmail/Notion/Apify plugins (off by default),
funded-company discovery, years-of-experience parser (`jd-years.mjs`: drops only when even
the lowest reading of a clear requirement is out of reach), interview suite, offer/contract
reading, negotiation scripts, rejection-pattern analysis, Go terminal dashboard. Headless
batch runs `claude -p --dangerously-skip-permissions`, 3 workers in parallel.

---

## 3. JobSpy (already used by our pipeline, v1.4.1 = latest)

Python library; one `scrape_jobs()` across LinkedIn, Indeed, Glassdoor, Google (broken),
ZipRecruiter, Bayt, Naukri, BDJobs, HelloWork. Now also a `jobspy` CLI and an MCP server
(`claude mcp add jobspy -- uvx mcp-jobspy@latest`, tools `search_jobs`, `get_job_details`).

**How each board is read (from the code):**
- **LinkedIn:** public `jobs-guest` search endpoint, 10 cards per page, **random 3–7 s sleep
  between pages** (why our LinkedIn step takes ~22 min). Stops on a page that looks blocked.
  `is_remote` and `job_type` are ignored for LinkedIn. `fetch_description` loads each
  `/jobs/view/<id>` page (one extra request per job). Posted date is day-precision.
- **Indeed:** Indeed's GraphQL API (`apis.indeed.com/graphql`), fast; returns the employer's
  direct apply URL when there is one.
- **Naukri:** Naukri's internal `jobapi/v3/search` with a per-request `nkparam` signature,
  3–7 s between pages; job page fetch adds description and company details.
- **Bayt:** HTML pages, 2–5 s delay (got 403s from GitHub's servers in our run).

**Recent history:** a burst of fixes in Oct 2026 restored Naukri, ZipRecruiter and BDJobs
searches and fixed paging, salaries, `hours_old` and remote flags on every board. Results
now carry `attrs["errors"]` / `attrs["warnings"]` saying which boards failed or changed the
search (our pipeline doesn't read these yet).
