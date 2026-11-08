# Phase 1 results: source testing (run 2026-10-26, Monday morning IST)

All tests run from the laptop with the scripts in `scripts/source_tests/`. Raw output lands in
`output/source_tests/` (gitignored). Caveat: the 36-hour window covered Sat–Mon, a quiet time for
new postings, so volumes are a floor.

## Scorecard

| Source | Volume (data-eng, fresh) | Freshness | Accuracy / quality | Verdict |
|---|---|---|---|---|
| **freehire: company job boards** (Greenhouse/Lever/Ashby/Workday) | Large; 92% of data-role titles at 24 test companies | **Excellent**: median 2 h after the company posts, p90 6 h | High; full descriptions, enrichment | **Use** |
| **freehire: job-board aggregators it ingests** (whatjobs, manatal, zohorecruit, teamtailor, keka, darwinbox, smartrecruiters…) | Large | **Unreliable**: whatjobs/manatal have **no real posting date** (posted = first seen). zohorecruit/teamtailor/keka/darwinbox are discovered **weeks–months late** (median 22–80 d) | Mixed | **Use only with a real posted_at ≤ window; drop undated sources** |
| **Adzuna** | ~1,300 data-engineer jobs in 2 days across 12 countries (excl. US 2,700). No Ireland, no Middle East | Good (`max_days_old`) | Relevant; est. **10–30% not found in freehire** after manual spot-check (raw 20–70% includes fuzzy-match misses) | **Worth £8/mo** if we want the extra; decision for user |
| **LinkedIn (JobSpy)** | 376 jobs / 36 h / 9 cities; 5 cities hit the 50 cap → more available. No blocking | Dates are day-level; some reposts (low job IDs) | ~47% of titles relevant (LinkedIn search is loose); our relevance filter cleans it | **Use**; pending user accuracy check |
| **Indeed (JobSpy)** | Near zero at 36 h; ~25 for Mumbai at 72 h, 100 at 7 d | Indeed's short windows are unreliable | OK | **Use with 72 h window** + our dedupe state |
| **Naukri (JobSpy)** | 104 jobs / 36 h / 4 cities (Mumbai only 6) | Some "today" posts are old (job code 29-07-26 dated 26-10) | Lots of 5–10 yr asks; filters will drop | **Use**; pending accuracy check |
| **Bayt (JobSpy)** | 13 jobs (UAE 1, SA 2, QA 10) | — | Small | Use, low priority. Middle East also from LinkedIn Dubai (11) + freehire AE/SA (~40) |

## freehire detail

- `open_within_days` = when **freehire** first saw a job, not when it was posted. Of 2,373 jobs
  freehire "first saw in the last 3 days" (21 countries): **14% verifiably posted ≤ 3 days ago,
  51% undated, 35% older than 3 days** (India worst: 220/300 old).
- Its `reality.class = fresh` does not catch late discovery (it reported age 0 on posts from September).
- **Rule for the pipeline:** keep a freehire job only if `posted_at` is within the window **and** its
  source is not an undated one (whatjobs-*, manatal, civilservicejobs, …). Rely on freehire's
  ATS-sourced rows for timeliness.
- Rate limit: 600 req/min, no key. Company slugs sometimes differ from ATS slugs (`creative-fabrica`).

## Adzuna detail

- Trial: 25 calls total; **14 used**, 11 left. Full plan £8/mo = 5,000 calls/mo (500/day).
- Countries: at, au, be, br, ca, ch, de, es, fr, gb, in, it, mx, nl, nz, pl, sg, us, za (no IE, no Gulf).
- At ~15 countries × 4 runs/day = 60 calls/day, comfortably inside 500/day.

## Open for the user

1. Check `output/source_tests/VERIFY_ME.csv` (20 LinkedIn + 5 Naukri) against the real sites.
2. Decide on Adzuna £8/mo.
3. Re-run `ats_vs_freehire.py` a few times over 2–3 days to confirm the 2 h lag on brand-new posts.

## Adzuna deep-dive (2026-10-26, 8 more trial calls; 3 left)

- **Real extra volume:** of 266 relevant Adzuna jobs, **33% (89)** were in neither freehire nor
  LinkedIn/Naukri (matched by company + fuzzy title). Highest in India (57%), Spain (45%),
  Switzerland (62%); lowest NL/GB/PL (~20%). Rough estimate: ~100 extra relevant jobs/day across
  12 countries before eligibility filters; many German/Polish/Spanish local-language ads will be
  dropped by the language filter.
- **Descriptions are capped at 500 characters.** Visa, remote-eligibility and years-required checks
  can't be run on Adzuna data alone; the full JD has to be fetched from the redirect page for jobs
  that survive the cheap filters.
- **US remote:** 1,961 "data engineer + remote" in 7 days, but in the sampled 100 none said
  India/worldwide and 12 explicitly said US-only. Adzuna US remote = remote inside the US.
- **Visa sponsorship:** keyword search returns GB 33, DE 3, NL 5, AU 12, CA 16, US 994 in 14 days,
  but no structured visa field and the 500-char snippet never shows the sponsorship sentence (the
  match is often "unable to sponsor"). Not usable as a visa source.
- **freehire is better for both:** remote data-eng jobs open to India: 40 / 7 days (+6 worldwide);
  stated visa sponsorship: US 39, NL 14, GB 10 / 14 days; jobs at **sponsor-register employers**:
  UK 107, NL 77, US H-1B 199, IE 7 / 14 days.
