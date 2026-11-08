"""Offline tests for the Phase-2 fetch/dedupe/filter changes. Run: py -m unittest discover tests"""
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jobhunt import fetch, dedupe, filters, report  # noqa: E402

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def job(**kw):
    base = dict(source="s", company="Acme", title="Data Engineer", location="Berlin", remote=False,
                url="u", description="", tags=[], created_at=None, country="DE",
                posted_at=iso(1), posted_precision="time", years_min=None, signals=[], origin=None)
    base.update(kw)
    return fetch._norm(**base)


PROFILE = yaml.safe_load("""
eligibility: {needs_sponsorship: true, no_sponsorship_needed_in: [IN]}
hard_filters: {max_years_required: 4, drop_senior_titles: [staff, lead]}
relevance_regex: >-
  \\b(data engineer|platform engineer|
   big data|databricks)\\b
""")


class Freshness(unittest.TestCase):
    def test_timestamp_window(self):
        self.assertTrue(fetch.fresh_enough(job(posted_at=iso(30)), 36, NOW))
        self.assertFalse(fetch.fresh_enough(job(posted_at=iso(40)), 36, NOW))

    def test_date_precision_gets_a_day_of_slack(self):
        j = job(posted_at="2026-10-24", posted_precision="date")  # 60h before NOW
        self.assertTrue(fetch.fresh_enough(j, 36, NOW))
        self.assertFalse(fetch.fresh_enough(j, 12, NOW))

    def test_undated_is_dropped(self):
        self.assertFalse(fetch.fresh_enough(job(posted_at=None), 36, NOW))


class Freehire(unittest.TestCase):
    ROW = {"source": "greenhouse", "company": "Databricks", "title": "Data Engineer", "location": "Bengaluru",
           "url": "https://x/1", "description": "d", "countries": ["IN"], "work_mode": "onsite",
           "posted_at": "2026-10-26T08:00:00Z", "created_at": "2026-10-26T10:00:00Z",
           "collections": ["uk-skilled-worker-sponsor", "yc"],
           "enrichment": {"visa_sponsorship": True, "relocation": "supported", "experience_years_min": 3}}

    def test_undated_detection(self):
        self.assertTrue(fetch._freehire_undated({"source": "whatjobs-uk"}, ["whatjobs"]))
        same = {"source": "personio", "posted_at": "2026-10-26T02:20:57Z", "created_at": "2026-10-26T02:20:59Z"}
        self.assertTrue(fetch._freehire_undated(same, []))
        self.assertFalse(fetch._freehire_undated(self.ROW, ["whatjobs"]))

    def test_normalise_signals_and_fields(self):
        j = fetch._freehire_job({"name": "freehire"}, self.ROW)
        self.assertEqual(j["country"], "IN")
        self.assertEqual(j["years_min"], 3)
        self.assertEqual(j["origin"], "freehire/greenhouse")
        self.assertEqual(set(j["signals"]), {"uk-skilled-worker-sponsor", "visa-sponsorship-stated",
                                             "relocation-supported"})

    def test_midnight_date_is_day_precision(self):
        j = fetch._freehire_job({"name": "freehire"}, {**self.ROW, "posted_at": "2026-10-09T00:00:00Z"})
        self.assertEqual(j["posted_precision"], "date")

    def test_fetch_drops_undated_and_builds_query(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"data": [self.ROW, {**self.ROW, "source": "whatjobs-in"}]}
        with mock.patch.object(fetch.requests, "get", return_value=resp) as get:
            got = fetch.fetch_freehire({"name": "freehire", "max_age_hours": 36,
                                        "undated_sources": ["whatjobs"],
                                        "seniority_exclude": ["lead", "staff"],
                                        "groups": [{"countries": ["IN"]},
                                                   {"regions": ["global"], "work_mode": "remote"}]})
        self.assertEqual(len(got), 2)  # one kept per group; whatjobs dropped in both
        p0, p1 = get.call_args_list[0].kwargs["params"], get.call_args_list[1].kwargs["params"]
        self.assertEqual(p0["countries"], "IN")
        self.assertEqual(p0["seniority_exclude"], "lead,staff")
        self.assertEqual((p1["regions"], p1["work_mode"]), ("global", "remote"))
        self.assertNotIn("countries", p1)  # geography ORs in freehire: never mix within a group


class Dedupe(unittest.TestCase):
    def test_cross_source_same_job_merges(self):
        a = job(source="linkedin", company="Acme GmbH", title="Data Engineer (m/w/d)", location="Berlin, DE")
        b = job(source="freehire", company="ACME", title="Data Engineer", location="Berlin, Germany",
                description="long description", signals=["nl-recognised-sponsor"])
        c = job(source="indeed", company="Acme", title="Data Engineer - Remote", location="Munich", years_min=2)
        out = dedupe.dedupe([a, b, c])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "freehire")  # longest description wins
        self.assertEqual(out[0]["also_on"], ["indeed", "linkedin"])
        self.assertEqual(out[0]["years_min"], 2)

    def test_ats_subdomain_company_name_merges(self):
        a = job(company="Chalhoub Group", country="in", description="x")
        b = job(company="chalhoubgroup.teamtailor", country="IN")
        out = dedupe.dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["country"], "IN")

    def test_same_title_different_country_kept(self):
        self.assertEqual(len(dedupe.dedupe([job(country="DE"), job(country="IN")])), 2)


class Filters(unittest.TestCase):
    NOSPON = "Great team. We do not sponsor visas for this role."

    def test_india_skips_visa_filter(self):
        self.assertNotIn("NO-SPONSOR", filters.evaluate(job(country="IN", description=self.NOSPON), PROFILE))
        self.assertIn("NO-SPONSOR", filters.evaluate(job(country="DE", description=self.NOSPON), PROFILE))

    def test_structured_years_beat_regex(self):
        self.assertIn("6+YRS", filters.evaluate(job(years_min=6), PROFILE))
        self.assertEqual(filters.evaluate(job(years_min=3, description="ideally 7 years"), PROFILE), [])

    def test_relevance_term_at_folded_line_start(self):
        self.assertEqual(filters.evaluate(job(title="Big Data Developer"), PROFILE), [])
        self.assertIn("IRRELEVANT", filters.evaluate(job(title="Power BI Developer"), PROFILE))

    def test_senior_title(self):
        self.assertIn("SR-TITLE", filters.evaluate(job(title="Lead Data Engineer"), PROFILE))


class Report(unittest.TestCase):
    def test_relocation_signal_and_report(self):
        jobs = dedupe.dedupe([job(company="Wise Ltd"), job(company="Other", country="IN")])
        report.add_relocation_signal(jobs, {"wise"})
        self.assertIn("relocation-list", jobs[0]["signals"])
        passed, dropped = filters.apply(jobs, PROFILE)
        md = report.fetch_report({"freehire": {"fetched": 5, "fresh": 2, "error": None, "seconds": 1},
                                  "linkedin": {"fetched": 0, "fresh": 0, "error": None, "seconds": 1}},
                                 jobs, jobs, passed, dropped)
        self.assertIn("possibly blocked", md)
        self.assertIn("| DE | 1 |", md)



if __name__ == "__main__":
    unittest.main()


class ExperienceAndSalary(unittest.TestCase):
    P = {**PROFILE, "hard_filters": {**PROFILE["hard_filters"], "max_years_required": 3,
                                     "salary_floor_inr": 1500000,
                                     "fx_to_inr": {"INR": 1, "EUR": 100, "USD": 88}}}

    def test_range_counts_by_lower_bound(self):
        self.assertEqual(filters.evaluate(job(description="3-5 years of experience"), self.P), [])
        self.assertEqual(filters.evaluate(job(description="2 to 4 yrs in data"), self.P), [])
        self.assertIn("4+YRS", filters.evaluate(job(description="4+ years Python"), self.P))
        self.assertIn("5+YRS", filters.evaluate(job(years_min=5), self.P))

    def test_salary_floor_only_when_stated(self):
        low = {"min": 600000, "max": 1200000, "currency": "INR", "period": "yearly"}
        ok = {"min": 1200000, "max": 2200000, "currency": "INR", "period": "year"}
        eur_month = {"min": 4000, "max": None, "currency": "EUR", "period": "month"}
        self.assertIn("LOW-SALARY", filters.evaluate(job(salary=low), self.P))
        self.assertEqual(filters.evaluate(job(salary=ok), self.P), [])
        self.assertEqual(filters.evaluate(job(salary=eur_month), self.P), [])
        self.assertEqual(filters.evaluate(job(salary=None), self.P), [])
        self.assertEqual(filters.evaluate(job(salary={"max": 5, "currency": "XYZ"}), self.P), [])
