import os

os.environ["KINGUARD_SKIP_ENV_FILE"] = "1"  # tests never read real keys or switches from .env

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.correlator import Correlator
from core.fsm import transition_state
from core.guardrails import enforce_action_safety
from core.ingest import kept, read_records, safe_parse
from core.runtime import TriageRuntime
from domain.enums import ActionOutcome, ActionType, IncidentState, Relationship, ServiceDomain, SeverityLevel, ThreatDomain
from calibrate import sweep
from core.jev import system_one
from domain.extract import extract_signals, redact
from domain.gate import gate
from domain.investigate import investigate
from domain.language import write_person_message
from domain.intake import email_to_row
from domain.logic import parse_record, parse_timestamp, withhold
from domain.tools import WORLD, domain_age, identify_operator, merchant_registry
from domain.policy import ALLOWED_SERVICE_ACTIONS, FORBIDDEN_ACTIONS
from domain.schemas import ActionProposal, Assessment, RawInputReport
from evaluation import clustering, evaluate, load_jsonl
from runner import run
from main import app

ROOT = Path(__file__).resolve().parents[1]


def report(report_id: str, payload: str, timestamp: str = "2026-10-01T09:00:00", context: str = "") -> RawInputReport:
    return RawInputReport(report_id=report_id, source="sensor", payload=payload, timestamp=timestamp,
                          metadata={"context": context} if context else {})


def assessment(severity=SeverityLevel.LOW, confidence=0.9, state=IncidentState.INVESTIGATING, action=False, review=None):
    return Assessment(severity=severity, confidence=confidence, requested_state=state, rationale="test", review_reason=review,
                      proposed_action=ActionProposal(type=ActionType.RECORD_ONLY) if action else None)


class EngineTests(unittest.TestCase):
    def test_fsm_diverts_illegal_transition(self):
        self.assertEqual(transition_state(IncidentState.NEW, IncidentState.CLOSED), IncidentState.PENDING_REVIEW)

    def test_low_confidence_and_forbidden_actions_require_review(self):
        action = ActionProposal(type=ActionType.RECORD_ONLY)
        self.assertTrue(enforce_action_safety(action, 0.74).requires_review)
        FORBIDDEN_ACTIONS.add(ActionType.RECORD_ONLY)
        try:
            self.assertTrue(enforce_action_safety(action, 0.99).requires_review)
        finally:
            FORBIDDEN_ACTIONS.remove(ActionType.RECORD_ONLY)
        saved = dict(ALLOWED_SERVICE_ACTIONS)
        ALLOWED_SERVICE_ACTIONS.clear()
        try:
            self.assertTrue(enforce_action_safety(action, 0.99).requires_review)
        finally:
            ALLOWED_SERVICE_ACTIONS.update(saved)

    def test_duplicate_and_report_idempotency(self):
        runtime = TriageRuntime()
        first = runtime.process(report("R1", "same signal"))
        second = runtime.process(report("R2", "same signal"))
        self.assertEqual(first.incident_id, second.incident_id)
        self.assertEqual(second.relationship, Relationship.DUPLICATE)
        self.assertIsNone(second.proposed_action)
        self.assertEqual(runtime.process(report("R2", "same signal")), second)
        self.assertEqual(len(runtime.decisions), 2)

    def test_duplicate_suppresses_domain_action(self):
        runtime = TriageRuntime()
        runtime.process(report("R1", "same signal"))
        with patch("core.runtime.assess", return_value=assessment(action=True)):
            duplicate = runtime.process(report("R2", "same signal"))
        self.assertIsNone(duplicate.proposed_action)
        self.assertEqual(duplicate.action_outcome, ActionOutcome.SUPPRESSED_DUPLICATE)

    def test_runtime_queues_illegal_state(self):
        with patch("core.runtime.assess", return_value=assessment(SeverityLevel.HIGH, state=IncidentState.CLOSED)):
            runtime = TriageRuntime()
            decision = runtime.process(report("R1", "state request"))
        self.assertEqual(decision.status, IncidentState.PENDING_REVIEW)
        self.assertTrue(decision.requires_human_approval)
        self.assertIn(decision.review_id, runtime.reviews)

    def test_runner_preserves_order_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "in.jsonl", Path(directory) / "out.jsonl"
            source.write_text('{"report_id":"R2","payload":"alpha"}\n{"report_id":"R1","payload":"beta"}\n', encoding="utf-8")
            self.assertEqual(run(source, output), 2)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["report_id"] for row in rows], ["R2", "R1"])
            self.assertEqual(evaluate([{"report_id": "R2"}, {"report_id": "R1"}], rows)["coverage_percent"], 100)

    def test_same_origin_api_and_links(self):
        client = TestClient(app)
        client.post("/api/reset")
        response = client.post("/api/reports", json={"report_id": "API1", "payload": "example"})
        self.assertEqual(response.status_code, 201)
        incident_id = response.json()["incident_id"]
        detail = client.get(f"/api/incidents/{incident_id}").json()
        self.assertEqual(detail["reports"][0]["report_id"], "API1")
        self.assertEqual(detail["decisions"][0]["report_id"], "API1")
        self.assertEqual(client.get("/").status_code, 200)


class MergeGuardTests(unittest.TestCase):
    def test_identical_text_in_a_different_context_stays_separate(self):
        runtime = TriageRuntime()
        first = runtime.process(report("R1", "same signal", context="Room A"))
        second = runtime.process(report("R2", "same signal", context="Room B"))
        self.assertNotEqual(first.incident_id, second.incident_id)
        self.assertEqual(second.relationship, Relationship.NEW)

    def test_identical_text_outside_the_window_is_a_new_occurrence(self):
        runtime = TriageRuntime()
        first = runtime.process(report("R1", "same signal"))
        second = runtime.process(report("R2", "same signal", timestamp="2026-10-05T09:00:00"))
        self.assertNotEqual(first.incident_id, second.incident_id)

    def test_identical_text_without_a_second_signal_keeps_its_action(self):
        runtime = TriageRuntime()
        runtime.process(report("R1", "same signal", timestamp=""))
        second = runtime.process(report("R2", "same signal", timestamp="garbled"))
        self.assertEqual(second.relationship, Relationship.RELATED)

    def test_resolver_failure_falls_back_and_is_traced(self):
        def broken(*_):
            raise RuntimeError("model down")
        runtime = TriageRuntime(Correlator(relation_resolver=broken))
        runtime.process(report("R1", "same signal"))
        second = runtime.process(report("R2", "same signal"))
        self.assertEqual(second.relationship, Relationship.DUPLICATE)
        self.assertIn("unavailable", second.trace[0])

    def test_malformed_timestamps_never_raise(self):
        for value in ("", "yesterday", "32/13/2026 25:61", None):
            self.assertIsNone(parse_timestamp(value))
        self.assertIsNotNone(parse_timestamp("2026-10-01 09:00"))


class ReviewAndActionTests(unittest.TestCase):
    def test_review_hold_is_sticky_until_risk_clears(self):
        runtime = TriageRuntime()
        with patch("core.runtime.assess", return_value=assessment(SeverityLevel.HIGH, state=IncidentState.TRIAGED, review="Conflicting evidence")):
            first = runtime.process(report("R1", "valve alarm on line 3"))
        runtime.decide_review(first.review_id, approved=True)
        with patch("core.runtime.assess", return_value=assessment(SeverityLevel.HIGH)):
            held = runtime.process(report("R2", "valve alarm on line 3 continues"))
        self.assertTrue(held.requires_human_approval)
        self.assertIsNone(held.review_id)
        self.assertEqual(len(runtime.reviews), 1)
        with patch("core.runtime.assess", return_value=assessment(SeverityLevel.LOW)):
            cleared = runtime.process(report("R3", "valve alarm on line 3 cleared"))
        self.assertFalse(cleared.requires_human_approval)

    def test_pending_review_is_not_duplicated(self):
        runtime = TriageRuntime()
        with patch("core.runtime.assess", return_value=assessment(state=IncidentState.TRIAGED, review="Conflicting evidence")):
            first = runtime.process(report("R1", "valve alarm on line 3"))
        with patch("core.runtime.assess", return_value=assessment(review="Conflicting evidence")):
            second = runtime.process(report("R2", "valve alarm on line 3 continues"))
        self.assertEqual(first.review_id, second.review_id)
        self.assertEqual(second.status, IncidentState.PENDING_REVIEW)

    def test_repeat_action_is_suppressed(self):
        runtime = TriageRuntime()
        with patch("core.runtime.assess", return_value=assessment(state=IncidentState.TRIAGED, action=True)):
            first = runtime.process(report("R1", "valve alarm on line 3"))
        with patch("core.runtime.assess", return_value=assessment(action=True)):
            second = runtime.process(report("R2", "valve alarm on line 3 continues"))
        self.assertEqual(first.action_outcome, ActionOutcome.PROPOSED)
        self.assertIsNone(second.proposed_action)
        self.assertEqual(second.action_outcome, ActionOutcome.SUPPRESSED_REPEAT)
        self.assertEqual(len(runtime.incidents[first.incident_id].actions), 2)


class IngestAndHarnessTests(unittest.TestCase):
    def test_bad_rows_still_produce_a_review_decision(self):
        bad, error = safe_parse({"report_id": "", "payload": "no id"}, 4)
        self.assertEqual(bad.report_id, "ROW-00004")
        decision = TriageRuntime().process_safely(bad, error)
        self.assertTrue(decision.requires_human_approval)
        self.assertEqual(decision.status, IncidentState.PENDING_REVIEW)

    def test_processing_error_does_not_stop_the_run(self):
        runtime = TriageRuntime()
        with patch("core.runtime.assess", side_effect=RuntimeError("boom")):
            decision = runtime.process_safely(report("R1", "anything"))
        self.assertTrue(decision.requires_human_approval)
        self.assertIn("boom", decision.trace[0])

    def test_sample_run_scores_against_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.jsonl"
            self.assertEqual(run(ROOT / "samples" / "reports.jsonl", output), 10)
            result = evaluate([{}] * 10, load_jsonl(output), load_jsonl(ROOT / "samples" / "truth.jsonl"))
        self.assertEqual(result["clustering"]["f1"], 1.0)
        self.assertEqual(result["report_issues"], [])

    def test_pairwise_clustering_counts(self):
        truth = {"a": "E1", "b": "E1", "c": "E2", "d": "E3"}
        score = clustering(truth, {"a": "I1", "b": "I2", "c": "I2", "d": "I2"})
        self.assertEqual((score["tp"], score["fp"], score["fn"]), (0, 3, 1))

    def test_step_through_replay_over_api(self):
        client = TestClient(app)
        content = (ROOT / "samples" / "reports.jsonl").read_text(encoding="utf-8")
        loaded = client.post("/api/replay/load", json={"filename": "reports.jsonl", "content": content}).json()
        self.assertEqual(loaded["replay"], {"total": 10, "position": 0})
        stepped = client.post("/api/replay/step", json={"steps": 3}).json()
        self.assertEqual(stepped["replay"]["position"], 3)
        self.assertEqual([item["report_id"] for item in stepped["decisions"]], ["S01", "S02", "S03"])
        done = client.post("/api/replay/step", json={"steps": 100}).json()
        self.assertEqual(len(done["decisions"]), 10)
        csv_text = "report_id,timestamp,source,payload,zone\nC1,2026-10-01T09:00:00,sensor,hello,north\n"
        loaded = client.post("/api/replay/load", json={"filename": "in.csv", "content": csv_text}).json()
        self.assertEqual(loaded["replay"]["total"], 1)
        client.post("/api/reset")


def kinguard_rows() -> dict[str, dict]:
    return {row["report_id"]: row for row in kept(read_records(ROOT / "samples" / "kinguard.jsonl")) if "report_id" in row}


class KinGuardTests(unittest.TestCase):
    def setUp(self):
        self.runtime = TriageRuntime()
        self.rows = kinguard_rows()

    def send(self, report_id: str):
        return self.runtime.process(parse_record(self.rows[report_id]))

    def test_one_time_codes_are_withheld_and_account_numbers_masked(self):
        self.assertNotIn("K03", self.rows)
        self.assertIsNotNone(withhold({"payload": "Your OTP is 123456"}))
        debit = parse_record(self.rows["K04"])
        self.assertNotIn("1234567890", debit.payload)
        self.assertEqual(debit.metadata["signals"]["merchant"], "techcare")
        self.assertEqual(debit.metadata["signals"]["amount"], 349.0)
        self.assertEqual(redact("call 0105550142"), "call 0105550142")

    def test_email_parsing_finds_the_deceptive_link_and_failed_authentication(self):
        report = parse_record(email_to_row((ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")))
        signals = report.metadata["signals"]
        self.assertTrue(signals["link_mismatch"])
        self.assertTrue(signals["auth_fail"])
        self.assertNotIn("yourbank.example", signals["domains"])
        self.assertEqual(signals["reply_to_domain"], "pc-care-services.example")

    def test_scam_lure_is_contained_and_its_duplicate_is_not_acted_on_twice(self):
        first, second = self.send("K01"), self.send("K02")
        self.assertEqual(first.action_outcome, ActionOutcome.EXECUTED)
        self.assertIn("techcare-help.example", WORLD.flagged)
        self.assertEqual(second.action_outcome, ActionOutcome.SUPPRESSED_DUPLICATE)
        self.assertEqual(len(WORLD.outbox), 1)

    def test_ambiguous_merchant_is_resolved_with_the_reference(self):
        decision = self.send("K04")
        self.assertEqual(decision.labels["reg_no"], "2026/118822/07")
        self.assertFalse(merchant_registry("techcare").ok)
        self.assertTrue(merchant_registry("techcare", "TCS8841").ok)

    def test_dispute_needs_the_caregiver_and_runs_only_when_approved(self):
        self.send("K01")
        decision = self.send("K04")
        self.assertEqual(decision.incident_id, "I0001")
        self.assertEqual(decision.action_outcome, ActionOutcome.HELD_FOR_REVIEW)
        self.assertEqual(WORLD.disputes, {})
        self.runtime.decide_review(decision.review_id, approved=True)
        self.assertIn("2026/118822/07", WORLD.disputes)
        self.assertEqual(self.runtime.incidents["I0001"].status, IncidentState.CONTAINED)

    def test_rejected_dispute_never_runs(self):
        decision = self.send("K04")
        self.runtime.decide_review(decision.review_id, approved=False)
        self.assertEqual(WORLD.disputes, {})

    def test_operator_returning_under_a_new_name_escalates(self):
        self.send("K01")
        dispute = self.send("K04")
        self.runtime.decide_review(dispute.review_id, approved=True)
        returned = self.send("K07")
        self.assertEqual(returned.incident_id, dispute.incident_id)
        self.assertEqual(returned.proposed_action.type, ActionType.BLOCK_OPERATOR)
        self.assertEqual(returned.action_outcome, ActionOutcome.HELD_FOR_REVIEW)
        self.assertIn("did not stop this operator", returned.trace[1])
        self.runtime.decide_review(returned.review_id, approved=True)
        self.assertEqual(WORLD.blocked, {"D-7781"})

    def test_shared_provider_sender_is_flagged_by_address_not_domain(self):
        decision = self.send("K06")
        self.assertEqual(decision.action_outcome, ActionOutcome.EXECUTED)
        self.assertEqual(WORLD.flagged, {"winner.claims@gmail.com"})

    def test_tool_refuses_a_domain_wide_block_and_the_agent_narrows_it(self):
        report = parse_record(self.rows["K06"])
        proposal = assessment(SeverityLevel.MEDIUM, state=IncidentState.CONTAINED)
        proposal.proposed_action = ActionProposal(type=ActionType.FLAG_SENDER, service=ServiceDomain.MAIL_FILTER, details={"target": "gmail.com"})
        with patch("core.runtime.assess", return_value=proposal):
            decision = self.runtime.process(report)
        incident = self.runtime.incidents[decision.incident_id]
        self.assertEqual([record.outcome for record in incident.actions], [ActionOutcome.FAILED, ActionOutcome.EXECUTED])
        self.assertEqual(WORLD.flagged, {"winner.claims@gmail.com"})

    def test_a_second_address_from_the_same_scammer_is_flagged_too(self):
        self.send("K06")
        again = dict(self.rows["K06"], report_id="K06b", timestamp="2026-10-09T10:00:00",
                     metadata={"sender": "prize.desk@gmail.com", "sender_name": ""})
        again["payload"] += " Call 010 555 0199."
        first = dict(self.rows["K06"], report_id="K06a", timestamp="2026-10-08T10:00:00")
        first["payload"] += " Call 010 555 0199."
        self.runtime.process(parse_record(first))
        decision = self.runtime.process(parse_record(again))
        self.assertEqual(decision.action_outcome, ActionOutcome.EXECUTED)
        self.assertIn("prize.desk@gmail.com", WORLD.flagged)

    def test_instructions_inside_a_message_do_not_change_the_outcome(self):
        decision = self.send("K06")
        self.assertNotEqual(decision.labels["threat"], "BENIGN")
        self.assertEqual(decision.action_outcome, ActionOutcome.EXECUTED)

    def test_known_subscription_is_benign_and_a_price_jump_is_not(self):
        first, jump = self.send("K05"), self.send("K08")
        self.assertIsNone(first.proposed_action)
        self.assertEqual(jump.incident_id, first.incident_id)
        self.assertEqual(jump.proposed_action.type, ActionType.DRAFT_DISPUTE)
        self.assertTrue(jump.requires_human_approval)

    def feedback(self, incident_id: str):
        return self.runtime.process(RawInputReport(report_id=f"F-{incident_id}", source="person", payload="legitimate",
                                                   metadata={"incident_id": incident_id, "feedback": "legitimate"}))

    def test_person_confirming_a_charge_rolls_the_agent_back(self):
        self.send("K05")
        jump = self.send("K08")
        answer = self.feedback(jump.incident_id)
        self.assertEqual(answer.action_outcome, ActionOutcome.EXECUTED)
        self.assertEqual(answer.status, IncidentState.RESOLVED)
        self.assertFalse(answer.requires_human_approval)
        self.assertEqual(self.runtime.reviews[jump.review_id].status, "SUPERSEDED")
        self.assertIn("streambox", WORLD.trusted)

    def test_confirming_a_high_risk_sender_is_not_taken_at_face_value(self):
        lure = self.send("K01")
        answer = self.feedback(lure.incident_id)
        self.assertEqual(answer.action_outcome, ActionOutcome.HELD_FOR_REVIEW)
        self.assertIn("techcare-help.example", WORLD.flagged)
        self.assertNotIn("techcare support", WORLD.trusted)

    def test_scenario_scores_cleanly_and_intake_api_works(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.jsonl"
            self.assertEqual(run(ROOT / "samples" / "kinguard.jsonl", output), 8)
            result = evaluate(list(read_records(ROOT / "samples" / "kinguard.jsonl")), load_jsonl(output),
                              load_jsonl(ROOT / "samples" / "kinguard_truth.jsonl"))
        self.assertEqual(result["coverage_percent"], 100)
        self.assertEqual(result["report_issues"], [])
        client = TestClient(app)
        client.post("/api/reset")
        withheld = client.post("/api/intake/share", json={"text": "Your OTP is 123456"}).json()
        self.assertEqual(withheld["status"], "withheld")
        email = client.post("/api/intake/email", json={"content": (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")}).json()
        self.assertEqual(email["action_outcome"], "EXECUTED")
        answer = client.post(f"/api/incidents/{email['incident_id']}/feedback", json={"legitimate": True}).json()
        self.assertTrue(answer["requires_human_approval"])
        client.post("/api/reset")


def model_answers(urgency=0.0, credentials=0.0, payment=0.0, subscription=0.0, threat="BENIGN", confidence=0.9):
    answers = {key: {"type": "noul", "noul": value} for key, value in
               {"urgency": urgency, "credentials": credentials, "payment": payment, "subscription": subscription}.items()}
    answers["threat"] = {"type": "choice", "choice": threat, "confidence": confidence}
    return lambda text: answers


class ModelAndToolTests(unittest.TestCase):
    def test_decision_model_adds_what_the_rules_missed(self):
        text = "Kindly settle the outstanding amount before noon or your account closes. Buy iTunes codes."
        signals = extract_signals(text, {})
        self.assertEqual(gate(text, signals).score, 0)
        verdict = gate(text, signals, model_answers(urgency=0.92, payment=0.88, threat="UNKNOWN"))
        self.assertEqual(verdict.score, 0.6)
        self.assertEqual(len(verdict.reasons), 2)
        self.assertIn("decision model", verdict.reasons[0])

    def test_decision_model_cannot_lower_a_rule_finding_or_count_twice(self):
        text = "Urgent: send a gift card today."
        signals = extract_signals(text, {})
        rules_only = gate(text, signals)
        with_model = gate(text, signals, model_answers(urgency=0.99, payment=0.01, threat="BENIGN"))
        self.assertEqual(with_model.score, rules_only.score)
        self.assertNotEqual(with_model.threat, ThreatDomain.BENIGN)

    def test_gate_survives_a_model_failure(self):
        def broken(text):
            raise TimeoutError("no answer")
        text = "Urgent: send a gift card today."
        verdict = gate(text, extract_signals(text, {}), broken)
        self.assertEqual(verdict.score, 0.6)
        self.assertIn("unavailable", verdict.notes[0])

    def test_jev_client_sends_the_documented_request(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"answers": {"q": {"type": "noul", "noul": 0.9}}}'
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"}), patch("urllib.request.urlopen", return_value=Reply()) as call:
            answers = system_one({"message": "hello"}, {"q": {"type": "noul", "instructions": "Is this a greeting?"}})
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual((body["model"], body["state"]), ("jev-latest", {"message": "hello"}))
        self.assertEqual(answers["q"]["noul"], 0.9)
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(RuntimeError):
            system_one("x", {})

    def test_live_domain_lookup_falls_back_to_the_fixture_when_it_fails(self):
        when = parse_timestamp("2026-10-01T09:00:00")
        with patch.dict("os.environ", {"KINGUARD_LIVE_LOOKUPS": "1"}), patch("urllib.request.urlopen", side_effect=OSError("offline")):
            known = domain_age("techcare-help.example", when)
            unknown = domain_age("nowhere.example", when)
        self.assertTrue(known.ok)
        self.assertIn("fixture", known.detail)
        self.assertEqual(known.data["age_days"], 4)
        self.assertFalse(unknown.ok)

    def test_two_company_names_with_one_director_are_one_operator(self):
        self.assertEqual(identify_operator("techcare", "TCS8841"), "D-7781")
        self.assertEqual(identify_operator("pc care services", ""), "D-7781")
        self.assertEqual(identify_operator("techcare", ""), "")
        self.assertNotEqual(identify_operator("streambox", ""), "D-7781")

    def test_calibration_sweep_counts_right_and_wrong_calls(self):
        rows = [("Urgent: send a gift card today.", {}, True), ("See you at lunch tomorrow.", {}, False),
                ("Your subscription renews soon.", {}, False)]
        table = {line["threshold"]: line for line in sweep(rows)}
        self.assertEqual((table[0.1]["caught"], table[0.1]["false_alarms"]), (1, 1))
        self.assertEqual((table[0.3]["caught"], table[0.3]["false_alarms"]), (1, 0))
        self.assertEqual(table[0.9]["missed"], 1)

    def test_language_model_resolves_a_garbled_merchant_only_when_the_registry_confirms(self):
        when = parse_timestamp("2026-10-02T06:00:00")
        signals = extract_signals("Debit order of R349.00 to TECHCRE SUP ref TCS8841 on 02 Oct.", {})
        _, unresolved = investigate(signals, when)
        self.assertIsNone(unresolved)
        findings, company = investigate(signals, when, lambda name: ["StreamBox", "TechCare Support"])
        self.assertEqual(company["reg_no"], "2026/118822/07")
        self.assertTrue(any("confirmed by the reference" in finding.note for finding in findings))
        _, wrong = investigate(signals, when, lambda name: ["StreamBox", "TechCare Solutions"])
        self.assertIsNone(wrong)
        def broken(name):
            raise TimeoutError("no answer")
        findings, company = investigate(signals, when, broken)
        self.assertIsNone(company)
        self.assertTrue(any("unavailable" in finding.note for finding in findings))

    def test_generated_warning_is_rejected_if_it_contains_a_number_or_link(self):
        class Reply:
            def __init__(self, message): self.message = message
        with patch("domain.language.call_agent_structured", return_value=Reply("Nothing to worry about. We blocked it for you.")):
            self.assertEqual(write_person_message({"fact": "x"}), "Nothing to worry about. We blocked it for you.")
        for bad in ("Please call 010 555 0142 to confirm.", "Visit www.claim.example now.", ""):
            with patch("domain.language.call_agent_structured", return_value=Reply(bad)), self.assertRaises(ValueError):
                write_person_message({"fact": "x"})

    def test_warning_falls_back_to_standard_wording_when_the_model_fails(self):
        runtime = TriageRuntime()
        row = kinguard_rows()["K01"]
        with patch.dict("os.environ", {"ENABLE_GEMINI": "1"}), patch("domain.language.call_agent_structured", side_effect=RuntimeError("no key")):
            decision = runtime.process(parse_record(row))
        self.assertEqual(decision.action_outcome, ActionOutcome.EXECUTED)
        self.assertIn("looks like a scam", WORLD.outbox[0]["message"])


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/reset")
        self.lure = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        self.debit = "YourBank: Debit order of R349.00 to TECHCARE ref TCS8841 from acc 1234567890 on 02 Oct."

    def tearDown(self):
        self.client.post("/api/reset")

    def test_person_and_caregiver_views(self):
        email = self.client.post("/api/intake/email", json={"content": self.lure}).json()
        sms = self.client.post("/api/intake/share", json={"text": self.debit, "sender": "YourBank"}).json()
        self.assertEqual(sms["incident_id"], email["incident_id"])
        self.assertEqual(len(self.client.get("/api/outbox").json()), 1)
        self.assertEqual([item["incident_id"] for item in self.client.get("/api/incidents").json()], [email["incident_id"]])
        self.assertEqual(self.client.get(f"/api/decisions/{sms['report_id']}").json()["action_outcome"], "HELD_FOR_REVIEW")
        self.assertEqual(self.client.get("/api/decisions/nope").status_code, 404)
        pending = self.client.get("/api/reviews", params={"status": "PENDING"}).json()
        self.assertEqual([item["review_id"] for item in pending], [sms["review_id"]])
        approved = self.client.post(f"/api/reviews/{sms['review_id']}/decision", json={"approved": True}).json()
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(self.client.get("/api/reviews", params={"status": "PENDING"}).json(), [])
        self.assertEqual(self.client.post(f"/api/reviews/{sms['review_id']}/decision", json={"approved": True}).status_code, 409)
        self.assertEqual(self.client.get("/api/incidents").json()[0]["status"], "CONTAINED")

    def test_documentation_lists_every_route_and_bad_input_is_rejected(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in ("/api/intake/email", "/api/intake/share", "/api/outbox", "/api/incidents", "/api/reviews",
                     "/api/reviews/{review_id}/decision", "/api/incidents/{incident_id}/feedback", "/api/state"):
            self.assertIn(path, paths)
        self.assertEqual(self.client.post("/api/intake/share", json={"text": ""}).status_code, 422)
        self.assertEqual(self.client.post("/api/incidents/I9999/feedback", json={"legitimate": True}).status_code, 404)

    def test_cross_origin_requests_are_refused_unless_configured(self):
        response = self.client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
