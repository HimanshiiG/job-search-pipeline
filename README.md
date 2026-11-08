# JobHunt — config-driven European job-search pipeline

Searches European job sources, hard-filters for eligibility, scores fit with an LLM, deeply
researches the top roles, tailors a resume + cover letter to each, and emails you an application
pack (link + docs). **It never submits** — you review and apply (CLAUDE.md Rule #1).

```
fetch (job APIs) → dedupe → hard-filter → tier-1 score → tier-2 research/dossier
     → tailor resume + cover letter → email you the link + docs
```

The deterministic 90% (fetch/dedupe/filter) uses no LLM and is free to run in CI. The LLM 10%
(score/research/tailor) runs locally via `claude -p` on the Claude Pro plan.

## Quick start
```bash
pip install -r requirements.txt            # PyYAML + requests (rest is stdlib)
py run.py --offline sample/arbeitnow.json  # full run, no network, no LLM (set llm.dry_run)
py run.py --profile <id>                  # live run
```
On this machine use `py` (Python 3.12 launcher). Artifacts land in `output/<profile>/`.

## Configure everything
- **`config/config.yaml`** — job sources (add/remove/re-type freely), LLM settings, email/SMTP,
  how many roles get deep research (`run.tier2_top_n`).
- **`profiles/<id>.yaml`** — one candidate = one config: eligibility (visa/language/salary),
  hard-filter knobs, verified skills, the gap list (never claimed), signature achievements.
  A second person (the spouse profile) is just another file here — no code changes.
- **`profiles/<id>.resume.md`** — base resume the tailor stage reorders (never invents). Replace
  the placeholder with the real resume, or point `resume_file:` elsewhere.
- **`prompts/*.md`** — the LLM prompt chain (tier-1 score, tier-2 dossier, resume tailor, letter).

## Sources supported
`freehire`, `jobspy` (LinkedIn / Indeed / Naukri / Bayt), `arbeitnow`, `lever`, `greenhouse` adapters (see `src/jobhunt/fetch.py`; why these: `docs/phase1-results.md`). Add an adapter
by writing one function returning normalised dicts and registering it in `ADAPTERS`.

## Email / secrets
SMTP password comes from env `JOBHUNT_SMTP_PASS` (never committed). With `email.dry_run: true`
(default) the pipeline writes the email + attachments to `output/<profile>/email/` instead of
sending — so it runs end-to-end with no creds.

## Claude Pro invocation (CLAUDE.md)
`claude -p` only; **never `--bare`**; `ANTHROPIC_API_KEY` is stripped from the child env so it
bills the plan. Tier-1 scoring is batched (one call per ~30 jobs). `llm.dry_run: true` stubs all
LLM calls for offline testing.

## Status
Stage 1 skeleton complete and config-driven. Stage 0 validation (filters vs real data, the
unreliable Arbeitnow visa flag) is in `pilot/stage0/`. Next: expand the ATS watchlist (Qonto=Lever
confirmed), wire GitHub Actions cron for fetch/filter, add the spouse profile.

## Volume check (no LLM)
```bash
py run.py --fetch-only        # fetch + dedupe + filters, prints output/<profile>/fetch_report.md
py -m unittest discover tests # offline tests
```

## Schedule (GitHub Actions)
`.github/workflows/jobhunt.yml` runs at 04:30 IST (fetch, score, documents; the newsletter is sent
at 08:00 IST) and 18:00 IST (fetch, score, documents; nothing sent), and on demand from the
Actions tab. Secrets: `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`), `JOBHUNT_SMTP_PASS`,
`JOBHUNT_VAULT_KEY`.

## Private data in a public repo
Everything personal is encrypted with one key (`scripts/vault.py`):
- `vault/private.bin`: the profile and resumes (`profiles/`), `config/private.yaml` (profile id,
  email addresses), the project brief and past letters. Edit the plain files locally, then
  `py scripts/vault.py seal` and commit the new `vault/private.bin`.
- The pipeline's state (seen jobs, ledger, replies, run logs) is encrypted on the bot-only
  `jobhunt-state` branch. Run output never goes to the public Actions log, and no artifacts are
  uploaded.

## How the search works
See `docs/job-search-practice.md` (the practice), `docs/phase1-results.md` (why these sources),
`docs/repo-inventory.md` (what was taken from ai-job-search and career-ops).
