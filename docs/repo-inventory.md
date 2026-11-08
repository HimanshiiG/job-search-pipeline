# Feature inventory: ai-job-search + career-ops (+ JobSpy) vs our pipeline (2026-11-08)

Every command, mode and script in both repos, each marked:
**HAVE** (we already do it) · **ADOPT** (take the idea as is) · **ADAPT** (rework for a scheduled,
headless pipeline) · **LATER** (useful at a later stage of the search) · **NO** (not relevant, reason given).

"Decided" items are being built now (your answers of 2026-11-08). Everything marked ADOPT/ADAPT
without "decided" waits for your OK.

## Our pipeline today, for reference

Fetch (freehire, LinkedIn/Indeed/Naukri/Bayt via JobSpy, Arbeitnow) → freshness on real posting
date → cross-source dedupe → deterministic filters (relevance, years, senior titles, language,
non-English JD, visa text, salary floor) → batched `claude -p` scoring → ledger → daily
newsletter: top 5 with research + tailored resume + cover letter, more matches by region,
cheat sheet. GitHub Actions twice a day. Measured over 10.5 days: ~650 unique jobs/day pass
the filters; 38% were scored; ~60 matched/day.

---

## Summary: what to take, ranked by value to you

| # | What | From | Mark | Why it matters for us |
|---|---|---|---|---|
| 1 | Score more, on Haiku; no title-only scoring (fetch the JD first, with liveness) | ai-job-search linkedin-search `detail`/`isActive`, career-ops `fetch-jd`, `liveness-api` | ADAPT, **decided** | 62% of passing jobs were never scored; 67% of matches had no JD |
| 2 | Reply-based feedback loop: applied codes, follow-ups after 10 quiet days (max 2), keep applied jobs forever | ai-job-search `/outcome followup`, career-ops `followup-cadence`, `followup-seed` | ADAPT, **decided** | You want a feedback loop at minimal effort |
| 3 | One call for research + cover letter; India: resume only unless the JD asks for a letter | career-ops `cover` (research is baked into the letter step) | ADAPT, **decided** | Fewer calls, letter written by the call that did the research |
| 4 | Outreach: one named contact per top pick, 3-sentence persona message within 200 chars, referral/cold email; warm intros from your LinkedIn connections export | career-ops `contacto`, `email`, `linkedin-join`, `contact-lookup` | ADAPT | Your stated next need. Discussed separately |
| 5 | Writing rules for resume + letter (see §A) | ai-job-search `03-writing-style`, `06-cover-letter-templates`; career-ops `heuristics/recruiter-side`, `cover` language rules | ADOPT | Prompt-only change, no cost; directly raises letter quality |
| 6 | Fact check on generated documents: every number/metric in the tailored resume or letter must exist in your source resume/profile; block employer-internal figures | career-ops `verify-cv-facts`, ai-job-search grounding audit | ADAPT | Your Rule 2 and Rule 4 enforced in code, not just in the prompt |
| 7 | Hidden-text / prompt-injection cleaning of JDs before Claude (our research call has web access) | ai-job-search `posting_guard.py`, career-ops `clean-markers` | ADOPT | Real risk once web tools are on |
| 8 | Hard eligibility gate: citizenship / permanent residency / security clearance → drop | ai-job-search `04-job-evaluation` Eligibility Gate | ADOPT | Cheap regex, removes impossible roles before scoring |
| 9 | Better years parser: spelled-out numbers, "at least N", months, required vs preferred, drop only when even the lowest reading is out of reach | career-ops `jd-years` | ADAPT | Fewer wrong drops and wrong keeps |
| 10 | Validate Haiku before switching: score the same ~60 jobs with Haiku and Sonnet once, compare agreement | career-ops `eval-golden` | ADAPT | Turns the model choice into a measured decision |
| 11 | Per-company "already applied here" flag + one-job-per-company cap in top picks | career-ops `precheck-duplicate`, ai-job-search mass-posting consolidation | ADOPT | Avoids double applications and 4 picks from one company |
| 12 | Application-form answer kit: self-intro paragraph per role type (data-platform / data-engineer), 60/150-word project entries, ≤140-char pitch | ai-job-search `08-application-forms` | ADOPT | Many Indian and large-company portals ask for these; write once, reuse |
| 13 | Staffing-agency flag ("our client", consultancy reposts) | career-ops agency gate, `fingerprint-core` (SimHash JD dedup) | ADAPT | Naukri/LinkedIn are full of agency reposts of the same role |
| 14 | Weekly "skills you keep missing" line from the ledger's biggest_gap field | career-ops `skip-blockers`, `upskill`; ai-job-search `/upskill` | ADOPT | Zero-cost; feeds your Terraform/Airflow backlog with evidence |
| 15 | Calibration: do higher scores actually get more interviews? | career-ops `calibrate`, ai-job-search `/setup` calibration | LATER | Needs ~2-4 weeks of applied → interview data from the reply loop |
| 16 | Auto-detect interview invites / rejections from the inbox | career-ops `reply-watch`, `invite-match`, ai-job-search `/gmail-sync` | LATER | Removes the `interview`/`rejected` reply lines; same IMAP access |
| 17 | More sources: SEEK/Jobstreet (AU), MyCareersFuture (SG), Darwinbox/Keka/Zoho direct (India; freehire sees them weeks late), Workday/Oracle direct (banks), Welcome to the Jungle, HN Who's hiring, Landing.jobs, The Hub, GermanTechJobs, JustJoin.it, public Telegram channels; company→ATS resolver | career-ops providers, `discover-ats`, `scan-hn` | LATER | Volume isn't the bottleneck now; scoring is |
| 18 | Adjacent job titles to widen search (analytics engineer, ML data engineer, ...) | career-ops `titles`, ai-job-search `/setup --section search` | LATER | Same reason |
| 19 | Keyword audit: which relevance terms catch jobs nothing else catches | career-ops `filter-audit`, `coverage-check` | LATER | Tune the relevance regex from evidence |
| 20 | Interview prep: stage-specific pack, STAR story bank, mock interview, debrief, red-flag check, role-clarity questions | ai-job-search `/interview`, career-ops `interview-prep`, `interview/*`, `match-star`, `role-clarity`, `interview-redflag` | LATER | When interviews start |
| 21 | Offer stage: contract reading, negotiation scripts, salary gap | career-ops `offer-prep`, `negotiation-roi`, `salary-gap` | LATER | When offers start |
| 22 | Form auto-fill for Greenhouse/Lever/Ashby, stops before Submit | career-ops `prepare-application`, `apply` | LATER | Saves typing; runs a local browser, not the cloud pipeline. Respects Rule 1 |
| 23 | Europe calibration addendum (permit, language, salary threshold checks per country, "main reviewer doubts") | career-ops `regional/eu-swe` | ADOPT into the research+letter prompt | Germany/NL are your priority markets |

### §A. Writing rules to put into the resume and cover-letter prompts (item 5)
- No em-dashes; no clichés ("passionate about", "leverage", "hit the ground running", "excited",
  "data-driven", "stakeholder alignment"); no apologetic hedging ("I think I could").
- **Interview backtrack test**: every reframed bullet must be explainable in an interview without
  "what I actually meant was...".
- **Every stated JD requirement is addressed**: matched, or an honest bridge for a gap; never
  silently omitted. Use the JD's own term where truthfully applicable.
- Cover letter is **forward-looking**: which of their problems you solve and how; motivation
  ("why this company") early; 1-2 past examples as proof; 350-420 words; one page.
- **Six-second clarity gate**: the top third of the resume and the letter's opening make target
  role, strongest matching stack and one production outcome impossible to miss.
- **Business-value bullets**: Action + system/scope + tool + outcome + proof; avoid "helped",
  "responsible for", "worked on" when stronger ownership is true.
- **Recruiter risk map** (internal, not printed): stack doubt, seniority doubt, domain doubt,
  logistics doubt, genericness, each with the evidence that answers it.
- Headline formula: specialty + a keyword from the posting.
- Every company claim in the letter must be verified from a fetched page, not a search snippet.

---

## ai-job-search: every command, skill and tool

| Item | What it does | Mark | Note |
|---|---|---|---|
| `/setup` | Profile from documents / CV / interview; search config | HAVE | `profiles/<id>.yaml` + resumes |
| `/scrape` | Portal search, dedupe, quick fit, referral links, health check | HAVE / ADOPT parts | Health check HAVE (source health in newsletter); referral search links → item 4; mass-posting → item 11 |
| `/rank` | Parallel scoring, expired/unreachable status, deadline urgency, staleness flag | HAVE / ADAPT | Liveness → item 1; deadlines rarely present in our sources (NO) |
| `/apply` | Drafter → reviewer → revise → PDF compile → ATS text-layer check → tracker | ADAPT parts | Grounding audit → item 6; writing rules → item 5; reviewer second pass: optional later (costs a call per pick); PDFs: NO (you make PDFs yourself) |
| `/interview` | Prep pack + mock interview | LATER | item 20 |
| `/outcome` | Record result, archive posting, follow-ups (10 days, max 2), stale sweep | ADAPT, decided | item 2 |
| `/gmail-sync` | Status updates proposed from Gmail | LATER | item 16 |
| `/notion-sync` | Pipeline view in Notion | NO | Newsletter is your view |
| `/html-report` | Offline dashboard | NO | Same |
| `/expand` | Competencies from GitHub/portfolio | NO for now | Your GitHub is empty (backlog item) |
| `/upskill` | Skill-gap heatmap + learning plan | ADOPT light | item 14 (count, no LLM) |
| `/add-template` | Custom CV/letter template | NO | You make PDFs yourself |
| `/add-portal` | Generate a new job-board scraper | NO | We add sources as Python adapters |
| `/reset` | Wipe profile | NO | |
| skill `01`–`02` profile, behavioural | Candidate profile, PI/DISC | HAVE / NO | Behavioural profile not used by us |
| skill `03` writing style | Rules | ADOPT | §A |
| skill `04` job evaluation | Eligibility + language gates, 5 weighted dimensions | ADOPT gates (item 8); HAVE scoring | |
| skill `05`/`06` CV and letter templates | LaTeX structure + tailoring rules | ADOPT rules; NO LaTeX | |
| skill `07` interview prep | STAR examples | LATER | |
| skill `08` application forms | Self-intro, project entries, char-limited pitch | ADOPT | item 12 |
| skill `09` web research | 403 escalation, robots.txt-respecting retry, trust boundary | ADOPT trust rules (item 7); HAVE retry need (item 1) | |
| agents posting-fetcher / scorer / reviewer | Read-only sub-agents | ADAPT idea | Research call already isolated; keep posting text as data |
| tools `posting_guard`, `page_decode` | Hidden text / injection scan | ADOPT | item 7 |
| tools `fetch_page`, `robots_check` | Browser-header GET that obeys robots.txt | ADOPT if needed | For employer pages in research |
| tools `job_key`, `scrape_state`, `rank_state` | Canonical keys, dedup state, expiry sweep | HAVE | `dedupe.py`, ledger |
| tools `verify_pdf`, `verify_layout` | PDF page/layout checks | NO | No PDFs in pipeline |
| tools `salary_lookup`, `convert_salary_excel` | BYO salary benchmark | NO | Salary not a goal now |
| tools `security_guards`, `lint_skills`, `check_framework_version`, `check_upstream_updates`, `upstream_triage`, `install_portal_clis` | Their repo's CI and fork maintenance | NO | Repo plumbing |
| portals jobindex/jobnet/jobbank/jobdanmark | Danish boards | NO | Not your market |
| portals linkedin-search, freehire-search | LinkedIn guest API, freehire API | HAVE | JobSpy + our freehire adapter; `isActive` → item 1 |

## career-ops: every mode

| Mode | What it does | Mark | Note |
|---|---|---|---|
| auto-pipeline, oferta | Full A–H evaluation report per job | ADAPT parts | Too heavy per job for 500 jobs/day; take gates (blacklist, dealbreaker, agency, work-auth) and legitimacy signals |
| ofertas | Compare several offers | LATER | |
| triage | Fast go/no-go | HAVE | Our tier-1 |
| scan, pipeline, batch | Portal scan, inbox, headless batch | HAVE | Our fetch + scoring |
| discover | Company → ATS board | LATER | item 17 |
| titles | Adjacent titles | LATER | item 18 |
| deep | 6-axis research prompt (AI strategy, recent moves, eng culture, likely challenges, competitors, candidate angle) | ADOPT into research+letter prompt | Better research structure for free |
| regional/eu-swe | Europe calibration | ADOPT | item 23 |
| cover | Research-backed letter, keyword mirroring, 4 angles, banned words, 350-420 words | ADOPT rules | §A; the "ask 4 angle questions" step is interactive: NO |
| pdf, latex, latex-tex, text, ats | CV render paths and ATS scoring | NO / HAVE | You make PDFs; we produce text (`text` = what we do) |
| heuristics/recruiter-side | Risk map, 6-second gate, bullet formula | ADOPT | §A |
| pdf/hm-audit | Adversarial hiring-manager read of the CV | LATER | Optional second pass, costs a call |
| email | Application / referral / cold / process-stuck / no-show emails | ADAPT | item 4 |
| contacto | One contact, persona 3-sentence note, 200/300-char limit | ADAPT | item 4 |
| apply | Playwright form fill, stops before Submit | LATER | item 22 |
| tracker, outcome, followup | Status, archive, follow-up cadence | ADAPT, decided | item 2 |
| reply-watch | Classify employer replies | LATER | item 16 |
| patterns, calibrate, upskill, retro | Rejection patterns, score calibration, gap analysis, learned rules | LATER / ADOPT light | items 14-15 |
| interview, intake, master-profile, add, expand | Profile building | HAVE / NO | Profile exists |
| interview-prep, interview/plan, practice, debrief, interview-redflag | Interview suite | LATER | item 20 |
| offer-prep | Contract reading | LATER | item 21 |
| training, project | Evaluate a course / portfolio project | LATER | Could help pick the GitHub portfolio project in your backlog |
| agent-inbox, update | Their session queue, self-updater | NO | Repo plumbing |
| oferta-signals/*, `_shared`, `_writing`, `_profile`/`_custom`/`_brief` templates, i18n mode folders | Shared prompt pieces, translations | ADOPT pieces already listed; NO translations | |

## career-ops: every script, by group

| Group | Scripts | Mark | Reason |
|---|---|---|---|
| Scanning + providers | scan, scan-ats-full, scan-hn, scan-seek, scan-dayforce, scan-interamt, scan-local-lib, providers/* (55+), branded-successfactors, history-ats-seeds, dead-boards, provider-id-cache, ats-vendor, discover-ats, discover-new-companies, company-funded, himalayas-posting, coverage-check, filter-audit, title-keywords, classify-tier, audit-portals, verify-portals, validate-portals, fix-slugs, portal-health-lock, pipeline-lock, migrate-scan-runs | HAVE core / LATER extras | items 17-19; `classify-tier` duplicates our senior-title filter |
| JD fetching + liveness | fetch-jd, browser-extract, liveness-api, liveness-browser, liveness-core, check-liveness, robots-check, archive-posting, jd-capture, check-jd-archive | ADAPT | item 1; archive: we keep JD text in the ledger for applied jobs (item 2) |
| JD analysis (zero-LLM) | jd-years, jd-skill-gap, skill-extract, role-clarity, jd-similarity, fingerprint-core, listing-fingerprint, url-key, detect-reposts | ADAPT jd-years (9), fingerprint (13); LATER role-clarity, reposts; HAVE url/dedupe keys | |
| Eligibility | sponsor-check, plugins/h1b-sponsor | HAVE | freehire sponsor collections (UK, NL, US H-1B, IE, CA, DK); their rule "not found = unconfirmed" matches ours (signal, never a penalty) |
| Evaluation runners | gemini-eval, ollama-eval, openai-eval, openai-tailor, openrouter-runner, batch-evaluate-gemini, batch-tailor, rank-pipeline, evaluation-cache, persist-evaluation-report, reserve-report-num, reeval-candidates, eval-golden | NO (other providers) / ADAPT eval-golden (10) | We use `claude -p` |
| CV + letter building | build-cv-html, build-cv-latex, generate-pdf, generate-cover-letter, generate-latex, extract-latex-content, patch-latex-content, install-latex-engine, cv-templates, cv-sections-core, cv-experience-order, cv-title-check, cv-voice, theme-style, img-to-pdf, verify-ats, ats-payload, keyword-match | NO (PDF) / ADAPT checks | You make PDFs; keep the *checks*: title consistency, newest-first order, keyword coverage → item 6 |
| Fact checks | verify-cv-facts, verify-cv-structure, story-provenance-check, clean-markers | ADOPT | items 6-7 |
| Outreach | contacto (mode), contact-lookup, contacts, contact-extract, linkedin-join | ADAPT | item 4 |
| Tracker + outcomes | tracker, tracker-parse, tracker-utils, tracker-links, tracker-sync-check, set-status, add-entry, merge-tracker, dedup-tracker, normalize-statuses, reconcile-pipeline, sync-batch-input, sync-pdf-flags, mark-pdf-ready, fix-report-links, verify-pipeline, verify-tracker-url-match, import-tracker, find, outcome, precheck-duplicate, close-stale, closing-soon, followup-cadence, followup-seed, application-artifacts, application-answers, apply-scope | ADAPT ideas (items 2, 11) / NO plumbing | Their markdown-table tracker plumbing; we use the ledger |
| Replies + inbox | reply-watch, reply-matcher, paste-reply, invite-match, ics-interview, panelist-roles, debrief-sync, assessment-log | LATER | item 16 |
| Analytics | analyze-patterns, stats, funnel-stages, funnel-velocity, calibrate, skip-blockers, upskill, discard-analytics, company-history, process-quality, rejection-latency, weekly-digest | LATER / ADOPT light (14) | Need outcome data first |
| Interview + offer | match-star, salary-gap, negotiation-roi | LATER | items 20-21 |
| Form filling | prepare-application | LATER | item 22 |
| Profile | career-profile, intake, onboard-write, validate-profile, learn, profile-language, github-evidence | NO | Profile exists |
| Repo / app plumbing | doctor, test-all, update-system, updater-migration-tests, upgrade-tests, seed-fixture, plugins, plugin-audit, plugin-install, validate-plugin-registry, validate-system-paths-coverage, validate-untrusted-content-coverage, check-table-freshness, i18n-drift, privacy-status, session-activity, remember-cli, path-resolver, user-agent, jsonc-parse, build-dashboard, agent-inbox, hired-share, hired-wall-build, manifesto, playwright.cv.config, web/, dashboard/ | NO | Their own install, update, UI and community tooling |

## JobSpy

| Item | Mark | Note |
|---|---|---|
| `scrape_jobs` (LinkedIn, Indeed, Naukri, Bayt) | HAVE | v1.4.1, current |
| `attrs["errors"]` / `attrs["warnings"]` per board | ADOPT | Show real board failures in source health |
| `fetch_description` | ADAPT | Fetch JDs only for jobs that pass our filters, not for every card (item 1) |
| Glassdoor, ZipRecruiter, Google, BDJobs, HelloWork | NO | US-only, broken, or not your market |
| CLI, MCP server | NO | The pipeline calls the library directly |
| Bayt | drop | 0 jobs in 7 of 11 runs from GitHub (403s) |
