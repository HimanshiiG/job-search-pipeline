# India job sources (≥ 30 LPA)

Research for extending the pipeline to India. Target: Data Engineer / Data Platform roles
paying **at least 30 LPA total**, for the candidate profile (~2 years experience).

> **Verification status.** The cloud session that wrote this could not reach the ATS hosts
> (DNS blocked), so nothing below was tested live except where marked ✅ (seen in search results).
> Run `py scripts/probe_ats.py` locally to confirm which company boards actually respond.

---

## 1. The core problem: Indian postings rarely state salary

Most Indian JDs hide the CTC ("best in industry"). A salary regex alone would drop almost
everything or keep almost everything. So the ≥30 LPA rule has to work in three layers:

| Layer | How | Cost |
|---|---|---|
| **a. Company tier (main filter)** | Only poll / keep companies known to pay ≥30 LPA at ~2 YOE (watchlist below, based on levels.fyi). | Free, deterministic |
| **b. Stated salary** | Where a source gives a number (Adzuna `salary_min`, Hirist/Cutshort "xx LPA", JD text), drop if the top of the range is < 30 LPA. | Free, deterministic |
| **c. LLM estimate** | Tier-1 scoring gets one extra field: "likely CTC band for this role at this company". Flags unknowns, doesn't drop them. | Already-batched call |

**Reality check.** 30 LPA is about the **75th percentile** for Indian data engineers on
levels.fyi (median ~20 LPA). At ~2 YOE it is reachable mainly at: US big-tech / SaaS India
offices, HFT & quant firms, top fintech/consumer startups, and investment banks' tech arms.
Services companies (Infosys, HashedIn, Searce, etc.) median 9–12 LPA at that level, so they
should never be polled.

---

## 2. Sources, ranked

### Tier A — build these first

| Source | Access | Salary data? | Notes |
|---|---|---|---|
| **ATS polling (Greenhouse / Lever / Ashby / SmartRecruiters)** for a watchlist of ≥30 LPA payers | Public JSON, no key. Same adapters the pipeline already has, plus filter `location` to India. | Rarely (Ashby sometimes, with `includeCompensation=true`) | Highest value, as in Europe: roles at hour zero. ✅ Databricks, Roku, Samsara post Bengaluru roles on Greenhouse. |
| **Adzuna API, India** | `GET https://api.adzuna.com/v1/api/jobs/in/search/{page}?app_id=…&app_key=…&what=data engineer&salary_min=3000000` — free key from developer.adzuna.com | Yes, annual INR. **Check `salary_is_predicted`**: if `1`, Adzuna guessed it. | Free tier reportedly ~250 calls/day. Only aggregator with a real salary filter + free official API. |

### Tier B — worth adding

| Source | Access | Notes |
|---|---|---|
| **JSearch (Google for Jobs via RapidAPI / OpenWeb Ninja)** | API key, free plan with small monthly quota | Covers LinkedIn, Naukri, Indeed postings that Google indexes, legally, via one API. Use 1–2 batched queries/day (`query=data engineer in Bengaluru`, `country=in`). Best way to get Naukri/LinkedIn coverage without scraping. |
| **Careerjet publisher API** | Free publisher key; needs user IP + UA per call | India site exists (careerjet.co.in). Aggregator, lower signal. |
| **Jooble API** | Free key on request | India supported; aggregator, lower signal. |
| **YC Work at a Startup** (filter: India) | No official API; page is public | Small but high-quality; YC India startups often pay 30+ for strong DEs. Weekly manual check or light polite fetch. |
| **Company careers on Workday** (banks, big GCCs) | Undocumented but public JSON: `https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (POST) | Goldman, Morgan Stanley, JPMC, Walmart, etc. Needs a Workday adapter; verify ToS per company. |

### Tier C — manual / alerts only (no API, ToS forbids scraping)

| Source | Why manual |
|---|---|
| **Naukri** | No public API; ToS forbids automated access. Third-party scrapers exist but break CLAUDE.md Rule 6. Use its email alerts with a **30–50 LPA salary filter** (Naukri has one) and/or reach it through JSearch. |
| **LinkedIn** | No job-search API; scraping violates ToS. Use saved-search alerts. |
| **Instahyre** | No public API; curated, recruiters reach out. Keep profile updated, set expected CTC ≥30. |
| **Hirist / iimjobs** (same group) | Show salary in LPA when disclosed; no API. Email alerts. |
| **Cutshort** | Has an API, but it's for **recruiters** (search candidates), not job seekers. Use as a profile/alerts site. |
| **Wellfound (India)** | No public API. Shows salary ranges on most posts, which is useful for checking the ≥30 LPA rule by hand. |
| **Foundit (Monster India)** | No public API. Low tech signal; skip. |

### Not worth it
EURES-style government portals (NCS – National Career Service): low tech signal, no API.

---

## 3. Watchlist seed (≥30 LPA at ~2 YOE, India offices)

ATS is **unverified** unless marked ✅; `scripts/probe_ats.py` tries every slug against
Greenhouse, Lever, Ashby and SmartRecruiters and reports which respond.

**US big tech / data-infra / SaaS (best fit for the Kafka/Snowflake/K8s profile):**
Databricks ✅GH · Confluent · Snowflake · Atlassian · Rubrik · Nutanix · Stripe · Uber ·
Rippling · Samsara ✅GH · Roku ✅GH · Twilio · Intuit · Adobe · Salesforce · Microsoft ·
Google · Amazon · LinkedIn · Walmart Global Tech · Target · Visa · PayPal · ServiceNow ·
Okta · Cloudflare · MongoDB · Elastic · Postman · BrowserStack

**HFT / quant / buy-side (highest pay; a finance-industry background is a direct plus):**
Tower Research · Graviton · Quadeye · D. E. Shaw India · Optiver · Squarepoint · AlphaGrep ·
Millennium · Citadel/Citadel Securities (Gurgaon) · Goldman Sachs · Morgan Stanley
(levels.fyi L4 ~28.6 LPA) · JPMorgan · BlackRock · Arcesium · KKR / Blackstone tech centres

**Indian product / fintech / consumer (pay varies by team, check levels.fyi per company):**
CRED · Razorpay · Zepto · PhonePe · Groww · Flipkart · Swiggy · Meesho · Dream11 ·
Zerodha · Atlan · ShareChat · Rapido · Slice · Upstox · InMobi/Glance

---

## 4. How this plugs into the existing pipeline

All config, little code:

1. **`profiles/<id>.yaml`** — add `markets.india: [Bengaluru, Mumbai, Pune, Hyderabad,
   Gurugram, Noida, Chennai, Remote-India]` and `salary_floor_inr: 3000000`.
2. **`filters.py`** — for India jobs: skip visa/language filters (not relevant), apply
   `salary_floor_inr` only when a salary is stated (layer b). Unknown salary → keep only if the
   company is on the watchlist (layer a).
3. **`fetch.py`** — new adapters: `adzuna` (needs key in env `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`),
   `ashby`, `smartrecruiters`; later `jsearch`, `workday`. Add a location filter to the ATS
   adapters so a global company board returns only its India roles.
4. **`prompts/tier1_score.md`** — ask for `est_ctc_band_lpa` per job (layer c).

Suggested order: probe the watchlist → Ashby + location filter → Adzuna → JSearch.

---

## Sources
- Adzuna India endpoint and `salary_is_predicted`: [jobspipe.dev guide](https://jobspipe.dev/answers/how-to-use-adzuna-api), [adzuna-job-search-mcp](https://glama.ai/mcp/servers/@folathecoder/adzuna-job-search-mcp/blob/2a1dccf28f89db8e9b261456bd103b5108fd6ded/README.md), [adzuna-sdk README (rate limits)](https://cdn.jsdelivr.net/npm/adzuna-sdk@0.1.2/README.md)
- Naukri has no public API: [Apify Naukri scraper listing](https://apify.com/bovi/naukri-jobs-scraper)
- JSearch free plan: [jobspipe.dev](https://jobspipe.dev/answers/is-jsearch-api-free)
- Careerjet / Jooble APIs: [jobspipe.dev Careerjet](https://jobspipe.dev/blog/careerjet-api), [public-api.org Jooble](https://public-api.org/api/858/jooble)
- Cutshort API is recruiter-side: [cutshort.io](https://cutshort.io/how-to-source-talent-using-claude)
- Zoho Recruit public pages: [jobspipe.dev Zoho Recruit](https://jobspipe.dev/sources/zoho-recruit)
- Greenhouse India postings: [Databricks](https://job-boards.greenhouse.io/databricks/jobs/8604579002), [Roku Bengaluru](https://job-boards.greenhouse.io/roku/jobs/7975750), [Samsara](https://job-boards.greenhouse.io/samsara/jobs/7974089)
- Salary benchmarks: [levels.fyi Morgan Stanley DE](https://www.levels.fyi/en-gb/companies/morgan-stanley/salaries/software-engineer/title/data-engineer), [levels.fyi HashedIn DE](https://www.levels.fyi/companies/hashedin/salaries/software-engineer/title/data-engineer), [datavidhya (median / P75)](https://datavidhya.com/blog/data-engineer-salary/)
- India job boards overview: [100hires](https://100hires.com/best-job-posting-sites-in-india.html), [Hirist scraper listing](https://apify.com/data_daemon/hirist-jobs-scraper)
