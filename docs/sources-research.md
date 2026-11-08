# Worldwide job sources: research (Oct 2026)

Goal: high **volume** of Data Engineer / Data Platform Engineer jobs from India, Australia,
Europe, US and elsewhere, polled several times a day, then matched to the resume.

Supersedes the salary-floor idea in `india-sources.md` (dropped: no salary filter).

> Verification: this cloud session can't reach most job hosts (freehire.me, dev.to and the ATS
> APIs are DNS-blocked here). Facts below come from the projects' GitHub READMEs. Live calls must
> be tested from a laptop.

---

## Verdict per link reviewed

| Link | What it is | Use it? |
|---|---|---|
| **freehire** (freehire.me, github.com/strelov1/freehire) | Open-source job search engine. **3.37M open postings from 477k companies** (snapshot 2026-10-20), crawled straight from company ATSs (Workday, Greenhouse, Lever, Ashby, iCIMS + ~120 more), plus aggregators (Adzuna, Himalayas, 97 Telegram channels) and big-company career sites (Amazon, Apple, Google). Reposts deduplicated. **Public, keyless** API: `GET https://freehire.me/api/v1/jobs`. MIT licence, 3.1k stars, very active. | **Yes, as the backbone.** One source replaces most of the ATS/watchlist/Firecrawl work. |
| **JobSpy** (github.com/speedyapply/JobSpy, `pip install python-jobspy`) | Python library that scrapes LinkedIn, Indeed, Glassdoor, Naukri, ZipRecruiter, Bayt, BDJobs, HelloWork. **No login.** | **Yes**, for LinkedIn / Indeed / Naukri, which freehire doesn't cover. |
| **joeyism/linkedin_scraper** | Playwright scraper for LinkedIn profiles, companies and jobs. **Requires logging in with your LinkedIn account.** | **No.** Puts the account you apply with at risk of restriction. JobSpy gets LinkedIn jobs without login. |
| **remoteintech/remote-jobs** | Directory of remote-friendly tech companies, one markdown file per company (`src/companies/*.md`) with `careers_url`, `region` (worldwide / europe / asia-pacific…), `remote_policy`, `technologies`. | **Minor.** Freehire already crawls most of these companies' ATSs. Could be used as a "remote-friendly" boost. |
| **AndrewStetsenko/tech-jobs-with-relocation** | Guide + table of **87 companies that hire internationally with relocation** (mostly DE 21, NL 16, UK 9, JP 7, DK 6, PT 5), plus curated relocation job boards, agencies and visa tools. | **Yes, as a signal, not a feed.** 87 companies is small volume, but "known to relocate foreigners" is the strongest signal we have for the visa problem. Use it to **boost** matching jobs in scoring and to seed the high-priority list. Its resource list gives more sources (below). |

---

## 1. freehire: the backbone

- **API:** `GET https://freehire.me/api/v1/jobs` (no key). Responses are `{"data": [...], "meta": {...}}`.
  Exact query-parameter names aren't in the README; the full reference is at freehire.me/docs/api.
  **TODO on a laptop:** confirm parameter names (keyword, country, posted-since, pagination).
- **Filters it supports** (from the MCP/CLI docs): `remote`, `region` (e.g. `eu`), `country`
  (ISO, e.g. `IN`, `AU`, `DE`, `NL`, `GB`, `US`), `city`, `company`, `category`, `role`,
  `seniority`, `employment_type`, `english_level`, `exclude_skill`, `salary_min`, **`visa`**,
  `skills`, plus a generic facet like `source=greenhouse`. Valid values come from the `facets`
  endpoint/tool, not guesses.
- **MCP server for Claude Code** (github.com/strelov1/freehire-mcp): hosted, read-only, no key:
  `/plugin install freehire --marketplace strelov1/freehire-mcp`. Useful for one-off interactive
  searches. The scheduled pipeline should call the REST API directly (no LLM needed).
- **CLI:** `freehire --json search "data engineer" --country IN --limit 50`.
- **Rules:** freehire's MCP also has `apply` / `submit` / `cv_tailor` tools. **Never use apply or
  submit** (CLAUDE.md Rule 1). Read-only search only.
- **Risks:** a single community project; rate limits aren't published (cache, poll politely); the
  hosted service could change. It's MIT and self-hostable as a fallback.
- **Gap:** it doesn't include LinkedIn, Indeed or Naukri. That's what JobSpy is for.

## 2. JobSpy: LinkedIn, Indeed, Naukri

`scrape_jobs(site_name=[...], search_term=..., location=..., country_indeed=..., hours_old=...,
results_wanted=..., fetch_description=...)`. Python ≥ 3.10.

| Site | Coverage | Behaviour |
|---|---|---|
| `indeed` | ~60 countries via `country_indeed` incl. **India, Australia, Germany, Netherlands, UK, Ireland, USA**, Austria, Switzerland, Spain, Portugal, Nordics, Poland, Singapore, UAE | Best one: README says no rate limiting. Search also matches descriptions, so use quotes: `'"data engineer"'`. |
| `linkedin` | Global, `location` string | HTTP 429 on bursts (clears in ~1 min). Keep requests small, add sleeps; proxies only if needed. |
| `naukri` | India, `location` = city (Mumbai, Bengaluru, Pune…) | The main local Indian volume. |
| `glassdoor` | ~22 countries incl. India, Australia, DE, NL, UK, US | Rate-limits above ~2 req/s. |
| `google` | — | Currently broken per README (returns nothing). Skip. |

- `hours_old` filters to fresh jobs. Run every few hours with `hours_old=6`–`12` so each run sees
  only new posts. That fixes the "posted 2w ago" problem.
- Most boards cap at ~1,000 results per search; that's fine with fresh-only windows.
- **ToS:** this scrapes public pages without login. That breaks those sites' terms (CLAUDE.md Rule 6);
  the user accepted that trade-off on 2026-10-26. Keep it polite: few queries, sleeps, no proxies
  unless blocked. Your personal accounts are never involved.

## 3. Relocation signal (boost, not feed)

Jobs from these employers get a scoring boost and a "relocation-friendly" tag in the digest:
- **Stetsenko list:** 87 companies (above). Several are directly on public ATSs, e.g.
  Wayve and Stream (Ashby), Intropic and Mujin (Lever), PayPay, Lightspeed, Creative Fabrica and
  Wallapop (Greenhouse), Seldon, SmartNews and Elements (Workable), Gnosis (Personio).
- **Australia visa sponsors:** github.com/geshan/au-companies-providing-work-visa-sponsorship
  (linked from the guide).
- **UK and NL sponsor registers:** already planned in CLAUDE.md.
- **US:** h1bgrader.com (H-1B sponsor history), also linked from the guide.

## 4. Extra sources from the relocation guide

| Source | Notes |
|---|---|
| **HN "Who is hiring?"** | Monthly thread; official free Algolia HN API (`hn.algolia.com/api/v1`). Many posts say "VISA" / "relocation". Cheap to add. |
| **Relocate.me** | Relocation-only board (+ Telegram channel t.me/relocateme). Check whether freehire already covers it before adding. |
| **Landing.Jobs** | `visa_support=true` filter; Portugal + EU. |
| **SwissDevJobs, TokyoDev, Japan Dev** | Country-specific relocation boards. |
| **Recruitment agencies** | Global {M}, Toughbyte, Zero to One Search: place international candidates. Manual, not automated. |

---

## Final source stack

| # | Source | Covers | Cost | Polling |
|---|---|---|---|---|
| 1 | **freehire API** | ~3.4M jobs, worldwide company ATSs + Adzuna + Himalayas + Telegram | Free, keyless | Every few hours |
| 2 | **JobSpy** | LinkedIn, Indeed (IN/AU/EU/US), Naukri, Glassdoor | Free (scraping) | Every few hours, `hours_old` window |
| 3 | **Arbeitnow** (existing) | EU, visa flag | Free | Keep |
| 4 | **HN Who's Hiring** | Startups, visa/relocation tags | Free official API | Daily |
| — | Relocation lists | Boost/tag in scoring | Free | Refresh monthly |

**Dropped:** Firecrawl / Alexandria (paid, mostly duplicates freehire), joeyism/linkedin_scraper
(needs login), building our own 10k-company slug list (freehire already has 477k companies),
salary filter.

## Sources
- freehire: [GitHub](https://github.com/strelov1/freehire), [MCP server](https://github.com/strelov1/freehire-mcp), [CLI](https://github.com/strelov1/freehire-cli), [API docs](https://freehire.me/docs/api), [live numbers](https://freehire.me/open)
- [JobSpy](https://github.com/speedyapply/JobSpy)
- [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper)
- [remoteintech/remote-jobs](https://github.com/remoteintech/remote-jobs) and its [CONTRIBUTING.md](https://github.com/remoteintech/remote-jobs/blob/main/CONTRIBUTING.md)
- [AndrewStetsenko/tech-jobs-with-relocation](https://github.com/AndrewStetsenko/tech-jobs-with-relocation)
