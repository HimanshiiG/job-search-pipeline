"""Offline tests for scoring, the ledger, the reply loop and the newsletter.
Run: py -m unittest discover tests"""
import json, re, sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jobhunt import fetch, dedupe, newsletter, replies, stages, llm as llm_mod  # noqa: E402

NOW = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()


def job(i, **kw):
    base = dict(source="linkedin", company=f"Co{i}", title="Data Engineer", location="Bengaluru",
                remote=False, url=f"https://x/{i}", description="kafka snowflake " * 30, tags=[],
                created_at=None, country="IN", posted_at="2026-10-27", posted_precision="date")
    base.update(kw)
    return dedupe.dedupe([fetch._norm(**base)])[0]


class FakeLLM:
    """Scores job i as 10*i; batch number `fail` raises like a quota error."""
    def __init__(self, fail=None):
        self.calls, self.fail, self.stages = 0, fail, []

    def run_json(self, prompt, stage=None):
        self.calls += 1
        self.stages.append(stage)
        if self.calls == self.fail:
            raise RuntimeError("quota")
        jobs = json.loads(re.search(r'(\[\{"id".*?\}\])\s+#', prompt, re.S).group(1))
        return [{"id": j["id"], "score": 10 * int(j["company"][2:]), "fit_1line": "ok",
                 "biggest_gap": "dbt", "leaked_filter": "years" if j["company"] == "Co9" else None}
                for j in jobs]


class Tier1(unittest.TestCase):
    def test_threshold_leak_failed_batch_and_stage(self):
        jobs = [job(i) for i in range(1, 10)]
        fake = FakeLLM(fail=2)
        out = stages.tier1_score(fake, {}, jobs, batch_size=3, apply_threshold=50)
        self.assertEqual(len(out), 6)  # batch 2 (Co4-Co6) failed -> left out, retried next run
        tiers = {j["company"]: j["tier"] for j in out}
        self.assertEqual(tiers["Co7"], "apply")
        self.assertEqual(tiers["Co3"], "drop")
        self.assertEqual(tiers["Co9"], "drop")  # 90 but leaked a hard filter
        self.assertEqual(set(fake.stages), {"score"})  # routed to the scoring model


def scored_jobs():
    out = [job(i) for i in range(1, 9)]
    for j in out:
        j.update(score=40 + 5 * int(j["company"][2:]), fit_1line="fit", biggest_gap=None)
        j["tier"] = "apply" if j["score"] >= 50 else "drop"
    return out


class Ledger(unittest.TestCase):
    def test_codes_are_unique_stable_and_readable(self):
        led = {}
        newsletter.add_scored(led, scored_jobs(), NOW)
        codes = [e["code"] for e in led.values()]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(re.fullmatch(r"[A-HJ-NP-Z2-9]{4}", c) for c in codes))
        again = {}
        newsletter.add_scored(again, scored_jobs(), NOW)
        self.assertEqual(sorted(codes), sorted(e["code"] for e in again.values()))

    def test_select_reply_skip_and_followup_flow(self):
        led = {}
        self.assertEqual(newsletter.add_scored(led, scored_jobs(), NOW), 7)  # Co1 (45) not added
        top, rest, awaiting, due = newsletter.select(led, top_n=3, now=NOW)
        self.assertEqual([e["company"] for e in top], ["Co8", "Co7", "Co6"])
        self.assertEqual((len(rest), awaiting, due), (4, [], []))
        newsletter.mark_sent(led, top + rest, TODAY, {e["hash"] for e in top})

        # no reply yet: next day the jobs are waiting, nothing is skipped
        _, _, awaiting, _ = newsletter.select(led, top_n=3, now=NOW + timedelta(days=1))
        self.assertEqual(len(awaiting), 7)
        self.assertEqual(awaiting[0]["company"], "Co8")  # top picks first

        # reply: two applied, the rest of that letter skipped
        a, b = top[0]["code"], rest[0]["code"]
        applied, outcomes = replies.parse_reply(f"{a} {b.lower()}\n\nOn Wed, JobHunt wrote:\n> {top[1]['code']}")
        self.assertEqual(applied, [a, b])  # the quoted letter below the reply is ignored
        res = replies.apply_reply(led, TODAY, applied, outcomes, TODAY)
        self.assertEqual((res["applied"], res["skipped"]), (2, 5))
        _, _, awaiting, due = newsletter.select(led, top_n=3, now=NOW + timedelta(days=1))
        self.assertEqual((awaiting, due), ([], []))

        # 10 quiet days later: follow-up due, at most twice
        _, _, _, due = newsletter.select(led, top_n=3, now=NOW + timedelta(days=10))
        self.assertEqual({e["code"] for e in due}, {a, b})
        newsletter.mark_followups(led, due, (NOW + timedelta(days=10)).date().isoformat())
        _, _, _, due = newsletter.select(led, top_n=3, now=NOW + timedelta(days=15))
        self.assertEqual(due, [])
        newsletter.mark_followups(led, newsletter.select(led, 3, now=NOW + timedelta(days=20))[3],
                                  (NOW + timedelta(days=20)).date().isoformat())
        self.assertEqual(newsletter.select(led, 3, now=NOW + timedelta(days=40))[3], [])

        # outcome stops follow-ups; applied jobs survive pruning, skipped ones don't
        replies.apply_reply(led, TODAY, [], {a: "interview"}, TODAY)
        newsletter.prune(led, NOW + timedelta(days=60))
        self.assertEqual({e["code"] for e in led.values()}, {a, b})
        self.assertEqual(next(e for e in led.values() if e["code"] == a)["outcome"], "interview")

    def test_parse_reply_outcomes_comments_and_unknown(self):
        applied, outcomes = replies.parse_reply("K7QX m2xa  # done today\ninterview P9DB\nrejected: T4RB")
        self.assertEqual(applied, ["K7QX", "M2XA"])
        self.assertEqual(outcomes, {"P9DB": "interview", "T4RB": "rejected"})
        led = {}
        newsletter.add_scored(led, scored_jobs(), NOW)
        res = replies.apply_reply(led, TODAY, ["ZZZZ"], {}, TODAY)
        self.assertEqual(res["unknown"], ["ZZZZ"])

    def test_letter_for_reply(self):
        letters = [{"date": "2026-10-27", "msgid": "<a@j>"}, {"date": "2026-10-28", "msgid": "<b@j>"}]
        self.assertEqual(replies.letter_for({"date": "2026-10-29", "in_reply_to": "<a@j>"}, letters), "2026-10-27")
        self.assertEqual(replies.letter_for({"date": "2026-10-29", "in_reply_to": ""}, letters), "2026-10-28")

    def test_migrate_legacy_entries(self):
        led = {"h1": {"hash": "h1", "sent_on": "2026-11-01"}, "h2": {"hash": "h2", "sent_on": None}}
        newsletter.migrate(led)
        self.assertEqual((led["h1"]["status"], led["h2"]["status"]), ("skipped", "new"))
        self.assertTrue(led["h1"]["code"] and led["h2"]["code"])

    def test_build_renders_everything(self):
        led = {}
        newsletter.add_scored(led, scored_jobs(), NOW)
        top, rest, awaiting, due = newsletter.select(led, top_n=2, now=NOW)
        rest[0]["country"] = "DE"
        rest[0]["signals"] = ["nl-recognised-sponsor"]
        usage = {"score": {"calls": 9, "failed": 0, "tokens": 400000, "cost_usd": 0.4, "models": ["claude-haiku-5-5"]}}
        subj, text, html = newsletter.build(
            {"application_facts": {"notice_period": "60 days", "phone": None}}, top, rest, rest[:1], rest[:1],
            {top[0]["hash"]: ["X_resume.md"]}, {"runs": 3, "fetched": 900, "matched": 7},
            {"linkedin": {"fetched": 0, "fresh": 0, "error": None}}, usage=usage,
            reply_result={"applied": 2, "skipped": 5, "outcomes": 0, "unknown": []}, now=NOW)
        self.assertIn("2 applications ready + 5 more", subj)
        for needle in ("REPLY with the codes", f"[{top[0]['code']}]", "X_resume.md", "Europe (1)", "India (4)",
                       "NL sponsor", "WAITING FOR YOUR REPLY", "FOLLOW UP", "nudge 1 of 2",
                       "Got your reply: 2 applied, 5 skipped", "haiku-5-5", "Notice period: 60 days",
                       "(fill in profiles/<id>.yaml)", "WARNING linkedin", "1d ago"):
            self.assertIn(needle, text)
        self.assertIn("<table", html)
        self.assertNotIn("<script", html)


class Documents(unittest.TestCase):
    def test_cover_letter_rule(self):
        prof = {"eligibility": {"cover_letter_only_if_asked_in": ["IN"]}}
        self.assertTrue(stages.needs_cover_letter({"country": "DE", "description": ""}, prof))
        self.assertFalse(stages.needs_cover_letter({"country": "IN", "description": "Python, Kafka"}, prof))
        self.assertTrue(stages.needs_cover_letter({"country": "IN", "description": "Send a cover letter"}, prof))

    def test_split_sections(self):
        n, l, r = stages.split_sections("=== RESEARCH NOTES ===\nhook\n=== COVER LETTER ===\nDear X\n"
                                        "=== REVIEWER NOTES ===\ncheck")
        self.assertEqual((n, l, r), ("hook", "Dear X", "check"))
        self.assertEqual(stages.split_sections("just a letter")[1], "just a letter")


class DescriptionFetch(unittest.TestCase):
    def resp(self, code, text=""):
        r = mock.Mock(status_code=code)
        r.text = text
        return r

    def test_ok_closed_retry_and_skip(self):
        body = '<div class="show-more-less-html__markup">' + "real job text " * 40 + "</div>"
        li = lambda: {"description": "", "board_url": "https://www.linkedin.com/jobs/view/4481423085"}  # noqa: E731
        with mock.patch.object(fetch.requests, "get", return_value=self.resp(200, body)), \
             mock.patch.object(fetch.time, "sleep"):
            j = li()
            self.assertEqual(fetch.fill_description(j), "ok")
            self.assertTrue(fetch.has_description(j))
        with mock.patch.object(fetch.requests, "get", return_value=self.resp(200, "No longer accepting applications")):
            self.assertEqual(fetch.fill_description(li()), "closed")
        seq = [self.resp(429), self.resp(429), self.resp(200, body)]
        with mock.patch.object(fetch.requests, "get", side_effect=seq), mock.patch.object(fetch.time, "sleep") as sl:
            self.assertEqual(fetch.fill_description(li()), "ok")
            self.assertEqual(sl.call_count, 2)  # backed off twice, then got it
        with mock.patch.object(fetch.requests, "get", return_value=self.resp(429)), \
             mock.patch.object(fetch.time, "sleep"):
            self.assertEqual(fetch.fill_description(li()), "failed")
        self.assertEqual(fetch.fill_description({"description": "", "url": "https://naukri.com/x"}), "skip")

    def test_enrich_respects_cap(self):
        jobs = [{"description": "", "board_url": f"https://www.linkedin.com/jobs/view/{4481423085 + i}"} for i in range(3)]
        with mock.patch.object(fetch, "fill_description", return_value="ok") as fd, \
             mock.patch.object(fetch.time, "sleep"):
            counts = fetch.enrich_descriptions(jobs, max_fetch=2, pause=0)
        self.assertEqual((fd.call_count, counts["over_cap"]), (2, 1))


class LLMWrapper(unittest.TestCase):
    ENVELOPE = json.dumps({"type": "result", "is_error": False, "result": "[]", "total_cost_usd": 0.01,
                           "usage": {"input_tokens": 10, "cache_read_input_tokens": 100,
                                     "cache_creation_input_tokens": 1000, "output_tokens": 5},
                           "modelUsage": {"claude-haiku-5-5": {}}})

    def test_lean_args_model_per_stage_and_usage(self):
        L = llm_mod.LLM({"models": {"score": "haiku", "resume": "sonnet"}})
        with mock.patch.object(llm_mod.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=self.ENVELOPE, stderr="")) as run:
            self.assertEqual(L.run_json("x", stage="score"), [])
            L.run("y", stage="research_letter", tools=["WebSearch", "WebFetch"])
        a1, a2 = run.call_args_list[0].args[0], run.call_args_list[1].args[0]
        self.assertNotIn("--bare", a1)
        self.assertEqual(a1[a1.index("--model") + 1], "haiku")
        self.assertEqual(a1[a1.index("--tools") + 1], "")          # scoring: no tools at all
        self.assertIn("--system-prompt", a1)
        self.assertNotIn("--model", a2)                             # no model set for this stage
        self.assertEqual(a2[a2.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertIn("--allowedTools", a2)
        u = llm_mod.usage_summary(L.calls)
        self.assertEqual((u["score"]["calls"], u["score"]["tokens"]), (1, 1115))
        self.assertEqual(u["score"]["models"], ["claude-haiku-5-5"])


if __name__ == "__main__":
    unittest.main()
