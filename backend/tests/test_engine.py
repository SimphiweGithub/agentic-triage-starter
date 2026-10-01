import os

os.environ["KINGUARD_SKIP_ENV_FILE"] = "1"  # tests never read real keys or switches from .env
os.environ["KINGUARD_STATE_FILE"] = ""        # and never write the real saved state
os.environ["KINGUARD_DB"] = ":memory:"      # and never touch the real database
os.environ["KINGUARD_DEV_OPEN"] = "1"      # the older tests call routes without a session; AccessTests turn this off

import base64
from datetime import datetime, timedelta, timezone
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
from calibrate import load_labelled, sweep
from collect_sms import collect, looks_personal, mask_for_labelling
from core.jev import system_one
from domain.extract import extract_signals, redact
from domain.gate import TEXT_RULES, gate
from domain.investigate import investigate
from domain.language import write_person_message
from domain.intake import email_to_row
from domain.logic import parse_record, parse_timestamp, withhold
from domain.tools import WORLD, World, default_world, domain_age, identify_operator, merchant_registry, reset_world
from domain.policy import ALLOWED_SERVICE_ACTIONS, FORBIDDEN_ACTIONS
from domain.schemas import ActionProposal, Assessment, RawInputReport
from evaluation import clustering, evaluate, load_jsonl
from runner import run
import api.gmail as gmail
from api import auth, people, pool, scanner
from api.mailbox import poll_once, start_polling
from api.routes import take_in_email
from api.store import Store, get_store
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

    def test_person_confirming_a_charge_rolls_the_agent_back_only_when_the_caregiver_agrees(self):
        self.send("K05")
        jump = self.send("K08")
        answer = self.feedback(jump.incident_id)
        self.assertEqual(answer.action_outcome, ActionOutcome.HELD_FOR_REVIEW)  # the person has no decision power
        self.assertEqual(self.runtime.reviews[answer.review_id].audience, "CAREGIVER")
        self.assertNotIn("streambox", WORLD.trusted)
        self.runtime.decide_review(answer.review_id, approved=True)
        self.assertIn("streambox", WORLD.trusted)

    def test_with_no_guardian_a_low_risk_answer_is_taken_at_once(self):
        WORLD.guardian = False
        self.send("K05")
        jump = self.send("K08")
        answer = self.feedback(jump.incident_id)
        self.assertEqual(answer.action_outcome, ActionOutcome.EXECUTED)
        self.assertEqual(answer.status, IncidentState.RESOLVED)
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

    def test_garbled_merchant_is_resolved_by_creditor_code_and_name_similarity(self):
        when = parse_timestamp("2026-10-02T06:00:00")
        signals = extract_signals("Debit order of R349.00 to TECHCRE SUP ref TCS8841 on 02 Oct.", {})
        findings, company = investigate(signals, when)
        self.assertEqual(company["reg_no"], "2026/118822/07")
        self.assertTrue(any("retrying with reference" in finding.note for finding in findings))
        self.assertEqual(identify_operator("techcre sup", "TCS8841"), "D-7781")
        self.assertFalse(merchant_registry("techcre sup").ok)
        self.assertFalse(merchant_registry("acme loans", "TCS8841").ok)
        self.assertFalse(merchant_registry("techcre sup", "SBX1001").ok)

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

    def test_live_mailbox_takes_in_each_unread_email_once(self):
        lure = self.lure.encode("utf-8")

        class FakeMailbox:
            def __init__(self): self.unread, self.closed = [b"1"], False
            def select(self, name): return "OK", [b"1"]
            def search(self, charset, criterion): return "OK", [b" ".join(self.unread)]
            def fetch(self, number, parts):
                self.unread.remove(number)
                return "OK", [(b"1 (RFC822 {%d}" % len(lure), lure), b")"]
            def logout(self): self.closed = True

        mailbox = FakeMailbox()
        self.assertEqual(poll_once(lambda: mailbox, take_in_email), 1)
        self.assertTrue(mailbox.closed)
        self.assertEqual(poll_once(lambda: mailbox, take_in_email), 0)
        incidents = self.client.get("/api/incidents").json()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "CONTAINED")
        self.assertIsNone(start_polling(take_in_email))
        self.assertFalse(self.client.get("/api/health").json()["mailbox"])

    def test_documentation_lists_every_route_and_bad_input_is_rejected(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in ("/api/people/{person_id}/intake/email", "/api/people/{person_id}/intake/share", "/api/people/{person_id}/outbox",
                     "/api/people/{person_id}/incidents", "/api/people/{person_id}/reviews", "/api/people/{person_id}/reviews/{review_id}/decision",
                     "/api/people/{person_id}/incidents/{incident_id}/feedback", "/api/people/{person_id}/state", "/api/people/summary", "/api/me"):
            self.assertIn(path, paths)
        self.assertEqual(self.client.post("/api/intake/share", json={"text": ""}).status_code, 422)
        self.assertEqual(self.client.post("/api/incidents/I9999/feedback", json={"legitimate": True}).status_code, 404)

    def test_cross_origin_requests_are_refused_unless_configured(self):
        response = self.client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertNotIn("access-control-allow-origin", response.headers)


SAFE_EMAIL = ("From: Woolworths <noreply@woolworths.co.za>\nTo: person@example.com\nSubject: Your receipt\nMessage-ID: <a1@x>\n"
              "Date: Mon, 02 Nov 2026 10:05:00 +0000\n\nThank you for shopping with us. Your receipt total is R212.40.")
CODE_EMAIL = ("From: YourBank <alerts@yourbank.example>\nSubject: Code\nMessage-ID: <a2@x>\n"
              "Date: Mon, 02 Nov 2026 10:05:00 +0000\n\nYour one-time PIN is 482913. Do not share it.")


class AccessTests(unittest.TestCase):
    """Who may call what, and that one person's data never reaches another. Clerk is replaced by an override naming the caller."""

    def setUp(self):
        self.env = patch.dict(os.environ, {"KINGUARD_DEV_OPEN": "0", "CLERK_SECRET_KEY": "sk_test_fake"})
        self.env.start()
        get_store().reset()
        pool.forget_everyone()
        self.client = TestClient(app)
        self.user = "caregiver_1"
        app.dependency_overrides[auth.who] = lambda: self.user
        self.sent_roles = []
        self.role_patch = patch.object(people, "set_clerk_role", lambda user_id, role: self.sent_roles.append((user_id, role)))
        self.role_patch.start()
        self.lure = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")

    def tearDown(self):
        self.role_patch.stop()
        app.dependency_overrides.clear()
        self.env.stop()
        get_store().reset()
        pool.forget_everyone()

    def add_person(self, name="Thandi", relation="Gran", as_user=None) -> str:
        if as_user:
            self.user = as_user
        created = self.client.post("/api/people", json={"name": name, "relation": relation})
        self.assertEqual(created.status_code, 201)
        return created.json()["people"][-1]["id"]

    def invite_and_accept(self, person_id: str, as_user: str = "person_1") -> str:
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        caregiver = self.user
        self.user = as_user
        with patch.object(people, "google_token", return_value="google-token"):
            self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 200)
        self.user = caregiver
        return token

    def test_health_is_open_but_every_other_route_needs_a_session(self):
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/people/Pabc/state").status_code, 401)
        with patch.dict(os.environ, {"CLERK_SECRET_KEY": ""}):
            self.assertEqual(self.client.get("/api/people/Pabc/state").status_code, 503)

    def test_routes_must_name_the_person_outside_development_mode(self):
        self.add_person()
        self.assertEqual(self.client.get("/api/state").status_code, 404)        # the unprefixed routes are for the plain console only

    def test_someone_who_is_not_linked_sees_nothing_but_can_start_looking_after_someone(self):
        self.assertEqual(self.client.get("/api/people/Pabc/state").status_code, 403)
        me = self.client.get("/api/me").json()
        self.assertEqual((me["role"], me["people"], me["can_add_person"]), (None, [], True))

    def test_a_caregiver_can_look_after_several_people(self):
        first = self.add_person("Thandi", "Gran")
        second = self.add_person("Sipho", "Uncle")
        me = self.client.get("/api/me").json()
        self.assertEqual([item["name"] for item in me["people"]], ["Thandi", "Sipho"])
        self.assertEqual(me["role"], "caregiver")
        self.assertEqual(self.sent_roles, [("caregiver_1", "caregiver")])      # the Clerk role is set once, not per person
        for person_id in (first, second):
            self.assertEqual(self.client.get(f"/api/people/{person_id}/state").status_code, 200)

    def test_one_caregivers_people_are_invisible_to_another_caregiver(self):
        mine = self.add_person("Thandi", as_user="caregiver_1")
        theirs = self.add_person("Sipho", as_user="caregiver_2")
        self.user = "caregiver_1"
        self.assertEqual(self.client.get(f"/api/people/{theirs}/state").status_code, 404)
        self.assertEqual(self.client.get(f"/api/people/{theirs}/mailboxes").status_code, 404)
        self.assertEqual(self.client.post(f"/api/people/{theirs}/invites").status_code, 404)
        self.assertEqual(self.client.post(f"/api/people/{theirs}/intake/share", json={"text": "hello"}).status_code, 404)
        self.assertEqual([item["name"] for item in self.client.get("/api/people/summary").json()], ["Thandi"])
        self.user = "caregiver_2"
        self.assertEqual(self.client.get(f"/api/people/{mine}/state").status_code, 404)

    def test_each_person_has_their_own_incidents_reviews_and_world(self):
        first = self.add_person("Thandi")
        second = self.add_person("Sipho")
        self.assertEqual(self.client.post(f"/api/people/{first}/intake/email", json={"content": self.lure}).status_code, 200)
        self.client.post(f"/api/people/{first}/intake/share", json={"text": DEBIT, "sender": "YourBank"})
        one = self.client.get(f"/api/people/{first}/state").json()
        two = self.client.get(f"/api/people/{second}/state").json()
        self.assertGreaterEqual(len(one["incidents"]), 1)
        self.assertTrue(one["world"]["flagged"])
        self.assertTrue([item for item in one["reviews"] if item["status"] == "PENDING"])
        self.assertEqual((two["incidents"], two["reviews"], two["reports"]), ([], [], []))
        self.assertEqual((two["world"]["flagged"], two["world"]["outbox"], two["world"]["disputes"]), ([], [], {}))
        summary = {item["id"]: item for item in self.client.get("/api/people/summary").json()}
        self.assertGreaterEqual(summary[first]["needs"], 1)
        self.assertEqual(summary[second]["needs"], 0)

    def test_a_setting_or_a_reset_for_one_person_leaves_the_other_alone(self):
        first = self.add_person("Thandi")
        second = self.add_person("Sipho")
        self.client.post(f"/api/people/{first}/intake/email", json={"content": self.lure})
        self.client.post(f"/api/people/{second}/intake/email", json={"content": self.lure})
        self.client.post(f"/api/people/{first}/settings/guardian", json={"enrolled": False})
        self.assertFalse(self.client.get(f"/api/people/{first}/state").json()["world"]["guardian"])
        self.assertTrue(self.client.get(f"/api/people/{second}/state").json()["world"]["guardian"])
        self.client.post(f"/api/people/{first}/reset")
        self.assertEqual(self.client.get(f"/api/people/{first}/state").json()["incidents"], [])
        self.assertEqual(len(self.client.get(f"/api/people/{second}/state").json()["incidents"]), 1)

    def test_the_persons_phone_syncs_its_inbox_and_reads_only_its_own_view(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id, "person_1")
        self.user = "person_1"
        inbox = [{"text": DEBIT, "sender": "YourBank", "timestamp": "2026-10-02T06:00:00"},
                 {"text": "Your OTP is 123456", "sender": "YourBank", "timestamp": "2026-10-02T06:01:00"}]
        first = self.client.post(f"/api/people/{person_id}/intake/share/batch", json=inbox)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()[1]["status"], "withheld")
        again = self.client.post(f"/api/people/{person_id}/intake/share/batch", json=inbox).json()
        self.assertEqual(first.json()[0]["report_id"], again[0]["report_id"])  # a re-sync processes nothing twice
        self.assertEqual(self.client.get(f"/api/people/{person_id}/person/state").json(), {"guardian": True, "disputes": []})
        self.assertEqual(self.client.get(f"/api/people/{person_id}/state").status_code, 403)  # the full state is the caregiver's
        self.assertEqual(self.client.get("/api/privacy/patterns").status_code, 200)
        self.user = "caregiver_1"
        self.assertEqual(len(self.client.get(f"/api/people/{person_id}/state").json()["reports"]), 1)

    def test_a_paired_phone_reaches_only_its_own_persons_view(self):
        mine = self.add_person("Thandi")
        theirs = self.add_person("Sipho", as_user="caregiver_2")
        self.user = "caregiver_1"
        code = self.client.post(f"/api/people/{mine}/phone").json()["code"]
        self.assertIsNotNone(self.client.get(f"/api/people/{mine}/phone").json()["paired_at"])
        app.dependency_overrides.clear()  # the phone has no Clerk session, only its pairing code
        self.assertRegex(code, r"^[A-HJ-NP-Z2-9]{10}$")
        phone = {"X-Device-Key": f" {code[:5].lower()}-{code[5:]} "}  # typed loosely on a phone, still accepted
        me = self.client.get("/api/me", headers=phone).json()
        self.assertEqual((me["role"], me["person"]["id"]), ("person", mine))
        sync = self.client.post(f"/api/people/{mine}/intake/share/batch", headers=phone,
                                json=[{"text": DEBIT, "sender": "YourBank", "timestamp": "2026-10-02T06:00:00"}])
        self.assertEqual(sync.status_code, 200)
        self.assertEqual(self.client.get(f"/api/people/{mine}/person/state", headers=phone).status_code, 200)
        self.assertEqual(self.client.get(f"/api/people/{mine}/state", headers=phone).status_code, 403)       # the caregiver's view
        self.assertEqual(self.client.post(f"/api/people/{mine}/settings/guardian", headers=phone, json={"enrolled": False}).status_code, 403)
        self.assertEqual(self.client.get(f"/api/people/{theirs}/outbox", headers=phone).status_code, 404)    # someone else
        self.assertEqual(self.client.get("/api/me", headers={"X-Device-Key": "wrong"}).status_code, 401)
        app.dependency_overrides[auth.who] = lambda: self.user
        self.client.post(f"/api/people/{mine}/phone")  # a new code unpairs the old phone
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/me", headers=phone).status_code, 401)

    def test_someone_protecting_themselves_sets_up_alone_and_decides_alone(self):
        self.user = "self_1"
        made = self.client.post("/api/me/self", json={"name": "Lindiwe"})
        self.assertEqual(made.status_code, 201)
        me = made.json()
        person_id = me["person"]["id"]
        self.assertEqual((me["role"], me["self_protected"]), ("person", True))
        self.assertEqual(self.client.post("/api/me/self", json={"name": "Again"}).status_code, 409)
        self.assertFalse(self.client.get(f"/api/people/{person_id}/person/state").json()["guardian"])  # no-guardian mode
        with patch.object(people, "google_token", return_value="google-token"):
            self.assertEqual(self.client.post("/api/me/gmail").json()["mailbox"]["status"], "connected")
        code = self.client.post("/api/me/phone").json()["code"]
        app.dependency_overrides.clear()
        phone = {"X-Device-Key": code}
        self.assertEqual(self.client.get("/api/me", headers=phone).json()["person"]["id"], person_id)
        self.client.post(f"/api/people/{person_id}/intake/share/batch", headers=phone,
                         json=[{"text": DEBIT, "sender": "YourBank", "timestamp": "2026-10-02T06:00:00"}])
        app.dependency_overrides[auth.who] = lambda: self.user
        mine = self.client.get(f"/api/people/{person_id}/person/reviews?status=PENDING").json()
        self.assertEqual([item["audience"] for item in mine], ["PERSON"])  # the decision is theirs
        self.assertEqual(self.client.get(f"/api/people/{person_id}/state").status_code, 403)  # no caregiver view to reach

    def test_a_person_with_a_caregiver_cannot_set_up_their_own_phone_or_gmail(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id, "person_1")
        self.user = "person_1"
        self.assertFalse(self.client.get("/api/me").json()["self_protected"])
        self.assertEqual(self.client.post("/api/me/phone").status_code, 403)
        self.assertEqual(self.client.post("/api/me/gmail").status_code, 403)

    def test_the_person_connects_through_a_single_use_invite(self):
        person_id = self.add_person()
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        app.dependency_overrides.clear()
        looked = self.client.get(f"/api/invites/{token}").json()        # no sign-in needed to look
        self.assertEqual((looked["valid"], looked["person_name"]), (True, "Thandi"))
        app.dependency_overrides[auth.who] = lambda: self.user
        self.user = "person_1"
        with patch.object(people, "google_token", return_value="google-token"):
            accepted = self.client.post(f"/api/invites/{token}/accept").json()
            again = self.client.post(f"/api/invites/{token}/accept")
        self.assertEqual((accepted["role"], accepted["mailbox"]["status"]), ("person", "connected"))
        self.assertEqual(self.sent_roles[-1], ("person_1", "person"))
        self.assertEqual(again.status_code, 410)
        self.assertEqual(self.client.get(f"/api/people/{person_id}/state").status_code, 403)   # the person is not the caregiver
        self.assertEqual(self.client.get(f"/api/people/{person_id}/outbox").status_code, 200)   # but may use the few routes meant for them

    def test_the_person_can_reach_only_their_own_routes(self):
        mine = self.add_person("Thandi")
        other = self.add_person("Sipho")
        self.invite_and_accept(mine)
        self.user = "person_1"
        self.assertEqual(self.client.get(f"/api/people/{mine}/outbox").status_code, 200)
        self.assertEqual(self.client.get(f"/api/people/{other}/outbox").status_code, 404)
        self.assertEqual(self.client.get("/api/people/summary").status_code, 403)
        self.assertEqual(self.client.post("/api/people", json={"name": "X"}).status_code, 409)   # a protected person cannot look after anyone

    def test_an_invite_the_person_cannot_use_leaves_nothing_behind(self):
        person_id = self.add_person()
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        self.user = "person_1"
        refused = people.HTTPException(403, "Google is connected without Gmail read access. Sign in with Google again to grant it.")
        with patch.object(people, "google_token", side_effect=refused):
            self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 403)
        self.assertEqual(get_store().mailboxes(person_id), [])
        self.assertEqual(get_store().links_of("person_1"), [])
        self.assertIsNone(people.invite_problem(get_store().invite(token)))     # still usable once access is granted

    def test_cancelled_and_expired_invites_are_refused_in_plain_words(self):
        person_id = self.add_person()
        cancelled = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        self.assertEqual(self.client.post(f"/api/people/{person_id}/invites/{cancelled}/cancel").status_code, 200)
        expired = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        get_store().db.execute("UPDATE invites SET expires_at = ? WHERE token = ?", ("2020-01-01T00:00:00+00:00", expired))
        self.user = "person_1"
        for token, words in ((cancelled, "cancelled"), (expired, "expired"), ("nonsense", "not valid")):
            refused = self.client.post(f"/api/invites/{token}/accept")
            self.assertEqual(refused.status_code, 410)
            self.assertIn(words, refused.json()["detail"])
        self.user = "caregiver_1"
        self.assertEqual(self.client.get(f"/api/people/{person_id}/invites").json(), [])

    def test_the_caregiver_cannot_accept_their_own_invite(self):
        person_id = self.add_person()
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        with patch.object(people, "google_token", return_value="google-token"):
            self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 409)

    def test_the_person_can_disconnect_and_the_caregiver_can_see_it(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id)
        revoked = []
        self.user = "caregiver_1"
        self.assertEqual(self.client.post("/api/me/disconnect").status_code, 403)
        self.user = "person_1"
        with patch.object(people, "google_token", return_value="google-token"), patch.object(people, "revoke", revoked.append):
            self.assertEqual(self.client.post("/api/me/disconnect").json()["mailbox"]["status"], "disconnected")
        self.assertEqual(revoked, ["google-token"])
        self.user = "caregiver_1"
        listed = self.client.get(f"/api/people/{person_id}/mailboxes").json()
        self.assertEqual([item["status"] for item in listed], ["disconnected"])
        self.assertTrue({"token", "owner_user_id", "payload"}.isdisjoint(listed[0]))   # state only, never a token or a message
        self.assertEqual(self.client.get("/api/people/summary").json()[0]["problems"], 1)

    def test_the_same_person_can_reconnect_after_disconnecting(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id)
        self.user = "person_1"
        with patch.object(people, "google_token", return_value="google-token"), patch.object(people, "revoke"):
            self.assertEqual(self.client.post("/api/me/disconnect").status_code, 200)
        old_box = get_store().mailboxes(person_id)[0]["id"]
        self.user = "caregiver_1"
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        self.user = "person_1"
        with patch.object(people, "google_token", return_value="google-token"):
            connected = self.client.post(f"/api/invites/{token}/accept")
        self.assertEqual(connected.status_code, 200)
        self.assertEqual(connected.json()["mailbox"]["status"], "connected")
        self.assertNotEqual(connected.json()["mailbox"]["id"], old_box)

    def test_replacing_a_mailbox_removes_the_previous_person_account(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id)
        token = self.client.post(f"/api/people/{person_id}/invites").json()["token"]
        self.user = "person_2"
        with patch.object(people, "google_token", return_value="google-token"):
            self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 200)
        self.user = "person_1"
        self.assertEqual(self.client.get(f"/api/people/{person_id}/outbox").status_code, 403)
        self.user = "person_2"
        self.assertEqual(self.client.get(f"/api/people/{person_id}/outbox").status_code, 200)

    def test_only_the_person_can_decide_a_person_review(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id)
        self.client.post(f"/api/people/{person_id}/settings/guardian", json={"enrolled": False})
        sent = self.client.post(f"/api/people/{person_id}/intake/share", json={"text": DEBIT}).json()
        self.assertEqual(self.client.post(f"/api/people/{person_id}/reviews/{sent['review_id']}/decision", json={"approved": True}).status_code, 403)
        self.user = "person_1"
        reviews = self.client.get(f"/api/people/{person_id}/person/reviews?status=PENDING").json()
        self.assertEqual([item["review_id"] for item in reviews], [sent["review_id"]])
        self.assertEqual(self.client.post(f"/api/people/{person_id}/reviews/{sent['review_id']}/decision", json={"approved": True}).status_code, 200)

    def test_person_feedback_clears_the_answered_warning(self):
        person_id = self.add_person()
        self.invite_and_accept(person_id)
        sent = self.client.post(f"/api/people/{person_id}/intake/email", json={"content": self.lure}).json()
        self.assertEqual(self.client.post(f"/api/people/{person_id}/incidents/{sent['incident_id']}/feedback", json={"legitimate": True}).status_code, 403)
        self.user = "person_1"
        self.assertEqual(len(self.client.get(f"/api/people/{person_id}/outbox").json()), 1)
        self.assertEqual(self.client.post(f"/api/people/{person_id}/incidents/{sent['incident_id']}/feedback", json={"legitimate": False}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/people/{person_id}/outbox").json(), [])

class WorldIsolationTests(unittest.TestCase):
    def test_a_runtime_with_its_own_world_never_touches_the_shared_one_or_another(self):
        lure = take_in_email  # the same email, processed for two people
        raw = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        reset_world()
        first, second = TriageRuntime(world=World()), TriageRuntime(world=World())
        lure(raw, first)
        self.assertTrue(first.world.flagged)
        self.assertEqual((second.world.flagged, second.world.outbox), (set(), []))
        self.assertEqual(default_world().flagged, set())
        self.assertEqual(WORLD.flagged, set())                              # outside any runtime, WORLD is the shared default

    def test_two_worlds_can_be_used_from_different_threads_at_once(self):
        from concurrent.futures import ThreadPoolExecutor
        raw = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        runtimes = [TriageRuntime(world=World()) for _ in range(6)]
        with ThreadPoolExecutor(max_workers=6) as pool_:
            list(pool_.map(lambda rt: take_in_email(raw, rt), runtimes))
        for rt in runtimes:
            self.assertEqual(len(rt.incidents), 1)
            self.assertEqual(len(rt.world.outbox), 1)


class GoogleTokenTests(unittest.TestCase):
    def test_google_token_needs_gmail_read_scope(self):
        class FakeUsers:
            def __init__(self, scopes): self.scopes = scopes
            def get_o_auth_access_token(self, user_id, provider):
                return [type("Token", (), {"token": "google-token", "scopes": self.scopes})()]

        class FakeClerk:
            def __init__(self, scopes): self.users = FakeUsers(scopes)
            def __enter__(self): return self
            def __exit__(self, *args): return False

        with patch.dict(os.environ, {"CLERK_SECRET_KEY": "sk_test_fake"}):
            with patch.object(gmail, "Clerk", lambda bearer_auth: FakeClerk([gmail.READ_SCOPE])):
                self.assertEqual(gmail.google_token("user_1"), "google-token")
            with patch.object(gmail, "Clerk", lambda bearer_auth: FakeClerk(["openid", "email"])):
                with self.assertRaises(gmail.HTTPException) as refused:
                    gmail.google_token("user_1")
                self.assertEqual(refused.exception.status_code, 403)

    def test_the_caregivers_own_gmail_is_no_longer_readable_through_the_api(self):
        paths = set(app.openapi()["paths"])
        self.assertFalse([path for path in paths if path.startswith("/api/gmail")])


class ScannerTests(unittest.TestCase):
    """The scanner with Clerk and Gmail replaced by stand-ins."""

    def setUp(self):
        self.store = Store(":memory:")
        pool.forget_everyone()
        self.person = self.store.create_person("Thandi", "Gran", "caregiver_1")
        invite = self.store.create_invite(self.person["id"], "caregiver_1")
        self.mailbox = self.store.accept_invite(invite["token"], "person_1")
        self.rt = pool.runtime_for(self.person["id"])
        self.lure = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        self.inbox = {"a": self.lure, "b": SAFE_EMAIL, "c": CODE_EMAIL}
        self.queries = []

    def tearDown(self):
        pool.forget_everyone()
        self.store.close()

    def scan(self, inbox=None, failure=None):
        inbox = self.inbox if inbox is None else inbox

        def ids(token, query):
            self.queries.append(query)
            return iter(list(inbox))

        def token_for(user_id):
            if failure:
                raise failure
            return "google-token"

        with patch.object(scanner, "google_token", token_for), patch.object(scanner, "message_ids", ids), \
                patch.object(scanner, "raw_email", lambda token, message_id: inbox[message_id]):
            scanner.scan_once(self.store)
        return self.store.mailbox(self.mailbox["id"])

    def test_first_scan_looks_back_a_fortnight_and_later_ones_only_since_the_last(self):
        self.scan()
        self.scan({})
        self.assertIn("newer_than:14d", self.queries[0])
        self.assertIn("after:", self.queries[1])
        self.assertIsNotNone(self.store.mailbox(self.mailbox["id"])["last_checked"])

    def test_only_an_id_and_a_verdict_are_kept_for_mail_that_is_not_a_threat(self):
        mailbox = self.scan()
        verdicts = dict(self.store.db.execute("SELECT message_id, verdict FROM scanned").fetchall())
        self.assertEqual(verdicts, {"a": "flagged", "b": "safe", "c": "withheld"})
        self.assertEqual(mailbox["checked"], 3)
        self.assertEqual(len(self.rt.incidents), 1)                              # only the lure became an alert
        self.assertEqual(len(self.rt.reports), 1)
        everything = " ".join(str(report.payload) + str(report.metadata) for report in self.rt.reports.values())
        self.assertNotIn("Woolworths", everything)
        self.assertNotIn("482913", everything)

    def test_safe_mail_joining_an_alert_is_removed_from_memory(self):
        flagged = scanner.handle_mail(self.mailbox, self.lure)
        self.assertEqual(flagged, "flagged")
        incident_id = next(iter(self.rt.incidents))
        safe = self.rt.process(RawInputReport(report_id="SAFE-JOIN", source="email", payload="Private safe message",
                                               metadata={"incident_id": incident_id}))
        self.assertEqual(safe.labels["threat"], "BENIGN")
        scanner.forget(safe, self.rt)
        self.assertNotIn("SAFE-JOIN", self.rt.reports)
        self.assertNotIn("SAFE-JOIN", self.rt.incidents[incident_id].report_ids)

    def test_mail_goes_to_the_person_whose_mailbox_it_came_from(self):
        other = self.store.create_person("Sipho", "Uncle", "caregiver_1")
        invite = self.store.create_invite(other["id"], "caregiver_1")
        other_box = self.store.accept_invite(invite["token"], "person_2")
        inboxes = {"tok-person_1": {"a": self.lure}, "tok-person_2": {}}     # only Thandi's mailbox holds the lure
        with patch.object(scanner, "google_token", lambda user_id: f"tok-{user_id}"),                 patch.object(scanner, "message_ids", lambda token, query: iter(list(inboxes[token]))),                 patch.object(scanner, "raw_email", lambda token, message_id: inboxes[token][message_id]):
            scanner.scan_once(self.store)
        self.assertEqual(len(self.rt.incidents), 1)
        self.assertEqual(len(pool.runtime_for(other["id"]).incidents), 0)
        self.assertEqual(self.store.mailbox(other_box["id"])["checked"], 0)
        self.assertTrue(self.rt.world.flagged)
        self.assertFalse(pool.runtime_for(other["id"]).world.flagged)

    def test_a_message_already_scanned_is_not_read_again(self):
        self.scan()
        reads = []
        with patch.object(scanner, "handle_mail", lambda mailbox, raw: reads.append(raw) or "safe"):
            with patch.object(scanner, "google_token", return_value="t"), patch.object(scanner, "message_ids", lambda t, q: iter(["a", "b"])), \
                    patch.object(scanner, "raw_email", lambda t, m: self.inbox[m]):
                scanner.scan_once(self.store)
        self.assertEqual(reads, [])

    def test_flagged_mail_keeps_its_text_until_the_alert_is_resolved(self):
        self.scan()
        report = next(iter(self.rt.reports.values()))
        self.assertEqual(report.metadata["origin"], f"mailbox:{self.mailbox['id']}")
        self.assertIn("protection plan", report.payload)
        incident = next(iter(self.rt.incidents.values()))
        self.assertEqual(scanner.blank_resolved(), 0)
        incident.status = IncidentState.RESOLVED
        self.assertEqual(scanner.blank_resolved(), 1)
        self.assertEqual((report.payload, incident.summary), ("", ""))
        self.assertNotIn("sender", report.metadata)

    def test_resolved_mail_that_was_shared_by_hand_is_left_alone(self):
        shared = take_in_email(self.lure, self.rt)            # came in through the API, not a mailbox
        self.rt.incidents[shared.incident_id].status = IncidentState.RESOLVED
        self.assertEqual(scanner.blank_resolved(), 0)
        self.assertIn("protection plan", self.rt.reports[shared.report_id].payload)
        self.assertNotEqual(self.rt.incidents[shared.incident_id].summary, "")

    def test_a_refused_token_is_a_problem_at_once(self):
        mailbox = self.scan(failure=scanner.HTTPException(403, "Google is connected without Gmail read access."))
        self.assertEqual(mailbox["status"], "problem")
        self.assertIn("Gmail read access", mailbox["last_error"])

    def test_a_short_outage_is_retried_quietly_and_a_long_one_is_a_problem(self):
        import httpx
        down = httpx.ConnectError("no route")
        self.assertEqual(self.scan(failure=down)["status"], "connected")
        earlier = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        self.store.db.execute("UPDATE mailboxes SET failing_since = ?", (earlier,))
        self.assertEqual(self.scan(failure=down)["status"], "problem")

    def test_a_mailbox_recovers_when_the_token_works_again(self):
        self.scan(failure=scanner.HTTPException(401, "Google refused the token."))
        recovered = self.scan({})
        self.assertEqual((recovered["status"], recovered["last_error"]), ("connected", None))

    def test_a_disconnected_mailbox_is_never_read(self):
        self.store.disconnect(self.person["id"])
        self.scan()
        self.assertEqual(self.queries, [])
        self.assertEqual(len(self.rt.reports), 0)

    def test_the_forwarded_inbox_follows_the_same_rules_and_reports_its_health(self):
        forwarded = self.store.ensure_forwarded(self.person["id"], "kinguard@example.com")
        handle = scanner.forwarded_handler(self.store)
        handle(SAFE_EMAIL)
        handle(self.lure)
        self.assertEqual(len(self.rt.incidents), 1)
        self.assertEqual(self.store.mailbox(forwarded["id"])["checked"], 2)
        scanner.note_forwarded(self.store, "OSError")
        self.assertEqual(self.store.mailbox(forwarded["id"])["last_error"], "OSError")
        scanner.note_forwarded(self.store, None)
        self.assertIsNone(self.store.mailbox(forwarded["id"])["last_error"])

    def test_report_numbers_are_not_reused_after_mail_is_forgotten(self):
        first = self.rt.next_report_number()
        scanner.handle_mail(self.mailbox, SAFE_EMAIL)
        self.assertEqual(self.rt.next_report_number(), first + 2)


MANDATE = "Nedbank: Mandate registered for R189.00 by TECHCARE SUPPORT. Reply within 24h to reject."
DEBIT = "YourBank: Debit order of R349.00 to TECHCARE ref TCS8841 from acc 1234567890 on 02 Oct."


def message(report_id: str, text: str, timestamp: str = "2026-10-02T06:00:00") -> RawInputReport:
    return parse_record({"report_id": report_id, "timestamp": timestamp, "source": "sms", "payload": text, "metadata": {"sender": "bank"}})


class MandateDeadlineAndSoloTests(unittest.TestCase):
    def setUp(self):
        self.runtime = TriageRuntime()

    def test_mandate_request_from_an_unverified_company_is_advised_against(self):
        report = message("M1", MANDATE)
        self.assertEqual(report.metadata["signals"]["kind"], "mandate")
        self.assertEqual(report.metadata["signals"]["merchant"], "techcare support")
        decision = self.runtime.process(report)
        self.assertEqual(decision.proposed_action.type, ActionType.ADVISE_DECLINE)
        self.assertEqual(decision.action_outcome, ActionOutcome.EXECUTED)
        self.assertFalse(decision.requires_human_approval)
        self.assertIn("do not approve", WORLD.outbox[0]["message"])

    def test_mandate_request_from_an_established_company_is_left_to_the_person(self):
        decision = self.runtime.process(message("M1", "Capitec: New debit order approval request from STREAMBOX."))
        self.assertIsNone(decision.proposed_action)
        self.assertEqual(WORLD.outbox, [])

    def test_a_debit_that_has_run_is_not_mistaken_for_a_mandate_request(self):
        self.assertEqual(message("D1", DEBIT).metadata["signals"]["kind"], "debit")

    def test_dispute_carries_its_deadline_and_the_steps_to_lodge_it(self):
        decision = self.runtime.process(message("D1", DEBIT))
        self.assertEqual(decision.proposed_action.details["dispute_by"], "2026-12-01")
        self.assertIn("Shall we prepare a dispute", decision.proposed_action.details["ask"])
        self.runtime.decide_review(decision.review_id, approved=True)
        dispute = WORLD.disputes["2026/118822/07"]
        self.assertEqual(dispute["dispute_by"], "2026-12-01")
        self.assertEqual(len(dispute["steps"]), 4)

    def test_without_a_guardian_the_person_is_asked_instead(self):
        with_guardian = self.runtime.process(message("D1", DEBIT))
        self.assertEqual(self.runtime.reviews[with_guardian.review_id].audience, "CAREGIVER")
        self.runtime.reset()
        WORLD.guardian = False
        solo = self.runtime.process(message("D1", DEBIT))
        review = self.runtime.reviews[solo.review_id]
        self.assertEqual(review.audience, "PERSON")
        self.assertIsNone(review.not_before)
        self.runtime.decide_review(solo.review_id, approved=True)
        self.assertIn("2026/118822/07", WORLD.disputes)

    def test_solo_override_of_a_high_risk_sender_needs_a_cooling_off(self):
        WORLD.guardian = False
        lure = self.runtime.process(parse_record(kinguard_rows()["K01"]))
        answer = self.runtime.process(RawInputReport(report_id="F1", source="person", payload="legitimate",
                                                     metadata={"incident_id": lure.incident_id, "feedback": "legitimate"}))
        review = self.runtime.reviews[answer.review_id]
        self.assertEqual(review.audience, "PERSON")
        self.assertIsNotNone(review.not_before)
        with self.assertRaises(ValueError):
            self.runtime.decide_review(answer.review_id, approved=True)
        self.assertIn("techcare-help.example", WORLD.flagged)
        later = self.runtime.now() + timedelta(hours=25)
        self.runtime.now = lambda: later
        self.runtime.decide_review(answer.review_id, approved=True)
        self.assertNotIn("techcare-help.example", WORLD.flagged)

    def test_guardian_setting_and_audience_filter_over_the_api(self):
        client = TestClient(app)
        client.post("/api/reset")
        self.assertTrue(client.get("/api/state").json()["world"]["guardian"])
        self.assertEqual(client.post("/api/settings/guardian", json={"enrolled": False}).json(), {"guardian": False})
        sent = client.post("/api/intake/share", json={"text": DEBIT, "sender": "YourBank"}).json()
        self.assertEqual([item["review_id"] for item in client.get("/api/reviews", params={"audience": "PERSON"}).json()], [sent["review_id"]])
        self.assertEqual(client.get("/api/reviews", params={"audience": "CAREGIVER"}).json(), [])
        lure = client.post("/api/intake/email", json={"content": (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")}).json()
        answer = client.post(f"/api/incidents/{lure['incident_id']}/feedback", json={"legitimate": True}).json()
        self.assertEqual(client.post(f"/api/reviews/{answer['review_id']}/decision", json={"approved": True}).status_code, 409)
        client.post("/api/reset")
        self.assertTrue(client.get("/api/state").json()["world"]["guardian"])


class WhatsAppAndNewScamTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/reset")

    def tearDown(self):
        self.client.post("/api/reset")

    def test_relative_on_a_new_number_asking_for_money_is_flagged(self):
        text = "Hi mom this is my new number, my phone was stolen. Please send R2000 to this account today."
        verdict = gate(text, extract_signals(text, {}))
        self.assertEqual(verdict.threat, ThreatDomain.IMPERSONATION)
        self.assertGreaterEqual(verdict.score, 0.5)
        honest = "This is my new number by the way."
        self.assertLess(gate(honest, extract_signals(honest, {})).score, 0.3)

    def test_advance_fee_wording_is_flagged(self):
        text = "Your inheritance is ready for release once the clearance fee is paid."
        self.assertEqual(gate(text, extract_signals(text, {})).threat, ThreatDomain.ADVANCE_FEE)

    def test_opt_out_wording_and_shop_vouchers_are_not_suspicious(self):
        for ordinary in ("Dear Student, join us for Open Day on Saturday. Reply STOP to opt out",
                         "Woolies: Activate your voucher on our app before your next shop.",
                         "Telkom: out of bundle voice rates increase to 75c from 1 August."):
            self.assertLess(gate(ordinary, extract_signals(ordinary, {})).score, 0.3, ordinary)
        for suspicious in ("Win tickets! Dial *180*6# @ R1/day. First day FREE.", "Buy a Google Play voucher and send me the code."):
            self.assertGreaterEqual(gate(suspicious, extract_signals(suspicious, {})).score, 0.3, suspicious)

    def test_job_scams_are_named(self):
        for text in ("We are currently hiring online part-time staff Daily salary: R800. Click wa.me/27600000000",
                     "Recruiting jobs for $3-10/day +WS https://to0.xyz/b/abc",
                     "ATH Hash invites you to earn 515 ZAR, small investment, big return"):
            self.assertEqual(gate(text, extract_signals(text, {})).threat, ThreatDomain.JOB_SCAM, text)

    def test_credit_and_insurance_offers_are_warned_about_but_never_blocked(self):
        runtime = TriageRuntime()
        text = "RCS STORE CARD: you've been selected to apply for up to R55 000 credit Click: https://m-s.pe/Gr No=out"
        decision = runtime.process(message("C1", text))
        self.assertEqual(decision.labels["threat"], ThreatDomain.SALES_OFFER.value)
        self.assertEqual(decision.proposed_action.type, ActionType.WARN_PERSON)  # scores 0.6 with the prize rule, still not blocked
        self.assertIn("You do not have to reply", decision.proposed_action.details["message"])
        honest = "Reply YES for help with your application. No=out"
        self.assertLess(gate(honest, extract_signals(honest, {})).score, 0.3)

    def test_guardian_brief_is_plain_and_links_to_whatsapp(self):
        self.assertEqual(self.client.get("/api/guardian/briefs").json(), [])
        sent = self.client.post("/api/intake/share", json={"text": DEBIT, "sender": "YourBank"}).json()
        with patch.dict("os.environ", {"GUARDIAN_WHATSAPP": "+27 82 123 4567"}):
            briefs = self.client.get("/api/guardian/briefs").json()
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0]["review_id"], sent["review_id"])
        self.assertIn("Shall we prepare a dispute", briefs[0]["text"])
        self.assertIn("lodged by", briefs[0]["text"])
        self.assertTrue(briefs[0]["whatsapp_link"].startswith("https://wa.me/27821234567?text=Scam%20Stop"))
        self.client.post(f"/api/reviews/{sent['review_id']}/decision", json={"approved": False})
        self.assertEqual(self.client.get("/api/guardian/briefs").json(), [])
        self.client.post("/api/settings/guardian", json={"enrolled": False})
        self.client.post("/api/intake/share", json={"text": DEBIT.replace("TCS8841", "TCS8850"), "sender": "YourBank"})
        self.assertEqual(self.client.get("/api/guardian/briefs").json(), [])


class CollectionTests(unittest.TestCase):
    EXPORT = """<?xml version='1.0' encoding='UTF-8'?>
<smses count="7">
  <sms address="Capitec" type="1" body="Capitec: Debit order of R99.00 to STREAMBOX ref SBX1001 from acc 1234567890 on 03 Oct." contact_name="(Unknown)" />
  <sms address="Capitec" type="1" body="Capitec: Debit order of R99.00 to STREAMBOX ref SBX1001 from acc 1234567890 on 03 Nov." contact_name="(Unknown)" />
  <sms address="Capitec" type="1" body="Capitec: your one-time PIN is 482913." contact_name="(Unknown)" />
  <sms address="+27825550199" type="1" body="Hi mom this is my new number, please send R2000 today" contact_name="(Unknown)" />
  <sms address="+27821112222" type="1" body="See you at lunch" contact_name="Thandi" />
  <sms address="+27825550199" type="2" body="Who is this?" contact_name="(Unknown)" />
  <mms address="x"><parts><part text="picture" /></parts></mms>
</smses>"""

    def test_export_is_reduced_to_safe_unlabelled_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "sms.xml"
            export.write_text(self.EXPORT, encoding="utf-8")
            sample = collect(export, per_sender=8, limit=150)
        texts = [text for text, _ in sample]
        self.assertEqual(len(sample), 1)                                   # one debit notice; repeats, codes, sent texts and personal numbers dropped
        self.assertFalse(any("PIN" in text or "lunch" in text or "Who is this" in text or "new number" in text for text in texts))
        self.assertFalse(any("1234567890" in text for text in texts))

    def test_personal_looking_numbers_are_left_out_even_without_a_contact_name(self):
        for business in ("Capitec", "MTN136", "33388", "+2781160933200100"):
            self.assertFalse(looks_personal(business))
        for person in ("+27825550199", "0825550199", "+37061910800"):
            self.assertTrue(looks_personal(person))

    def test_messages_that_hand_over_a_secret_are_withheld(self):
        for secret in ("Your password is Kx81!pq", "Use recovery code 4821-9921 to sign in", "Your login details: user ST10451674"):
            self.assertIsNotNone(withhold({"payload": secret}))
        self.assertIsNone(withhold({"payload": "Urgent: confirm your password at http://bank-secure.example"}))
        self.assertIsNotNone(withhold({"payload": "Steam: Use code 53867 to add this phone to your account"}))
        self.assertIsNone(withhold({"payload": "Use code SAVE20 for 20% off"}))

    def test_card_numbers_and_prepaid_tokens_are_masked(self):
        masked = redact("Token 3916 2010 5929 9797 0998 and card 4111-1111-1111-1111, query 0860 288 673")
        self.assertNotIn("3916", masked)
        self.assertNotIn("4111", masked)
        self.assertIn("0860 288 673", masked)

    def test_identifiers_and_names_are_masked_for_labelling(self):
        masked = mask_for_labelling("Hi Simphiwe, order #OD-4471923 for ST10451674 (st10451674@myemeris.example) R1500.00, call 0105550142",
                                    ["Simphiwe"])
        for leaked in ("Simphiwe", "4471923", "10451674", "@myemeris"):
            self.assertNotIn(leaked, masked)
        self.assertIn("R1500.00", masked)
        self.assertIn("0105550142", masked)

    def test_unlabelled_lines_are_refused_not_counted_as_benign(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.tsv"
            tab = chr(9)
            path.write_text(f"scam{tab}You have won{tab}33388\n?{tab}See you later{tab}Mum\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_labelled(path)
            path.write_text(f"scam{tab}You have won{tab}33388\nbenign{tab}See you later{tab}Mum\nunsure{tab}Maybe{tab}x\n", encoding="utf-8")
            self.assertEqual(load_labelled(path), [("You have won", {}, True), ("See you later", {}, False)])  # unsure is left out


class PhoneSyncTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/reset")

    def tearDown(self):
        self.client.post("/api/reset")

    def test_inbox_sync_is_idempotent_and_filters_codes(self):
        inbox = [{"text": DEBIT, "sender": "YourBank", "timestamp": "2026-10-02T06:00:00"},
                 {"text": "Your OTP is 123456", "sender": "YourBank", "timestamp": "2026-10-02T06:01:00"},
                 {"text": "See you at lunch", "sender": "Checkers", "timestamp": "2026-10-02T07:00:00"}]
        first = self.client.post("/api/intake/share/batch", json=inbox).json()
        self.assertEqual(["report_id" in item for item in first], [True, False, True])
        self.assertEqual(first[1]["status"], "withheld")
        again = self.client.post("/api/intake/share/batch", json=inbox).json()
        self.assertEqual(first[0]["report_id"], again[0]["report_id"])
        state = self.client.get("/api/state").json()
        self.assertEqual(len(state["reports"]), 2)
        self.assertEqual(len(state["reviews"]), 1)

    def test_phone_can_fetch_the_same_privacy_filter(self):
        patterns = self.client.get("/api/privacy/patterns").json()
        self.assertEqual(len(patterns["withhold"]), 2)
        import re
        self.assertTrue(any(re.search(pattern, "Your recovery code is 4471", re.I) for pattern in patterns["withhold"]))


class PersistenceTests(unittest.TestCase):
    def test_state_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"KINGUARD_STATE_FILE": str(Path(directory) / "state.json")}):
            first = TriageRuntime()
            lure = first.process(parse_record(kinguard_rows()["K01"]))
            debit = first.process(parse_record(kinguard_rows()["K04"]))
            first.decide_review(debit.review_id, approved=True)
            WORLD.guardian = False
            first.save()
            reset_world()
            second = TriageRuntime()
            self.assertEqual(set(second.incidents), {lure.incident_id})
            self.assertEqual(second.reviews[debit.review_id].status, "APPROVED")
            self.assertIn("techcare-help.example", WORLD.flagged)
            self.assertIn("2026/118822/07", WORLD.disputes)
            self.assertFalse(WORLD.guardian)
            self.assertEqual(second.process(parse_record(kinguard_rows()["K01"])), lure)  # same message again: same decision
            fresh = second.process(parse_record(kinguard_rows()["K05"]))
            self.assertEqual(fresh.incident_id, "I0002")  # numbering carries on
            second.reset()
            self.assertEqual(TriageRuntime().incidents, {})

    def test_each_person_is_saved_to_their_own_file_and_reloaded_into_their_own_world(self):
        raw = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"KINGUARD_STATE_FILE": str(Path(directory) / "state.json")}):
            reset_world()
            first = TriageRuntime(world=World(), person_id="P1")
            take_in_email(raw, first)
            number = first.next_report_number()
            first.save()
            self.assertTrue((Path(directory) / "people" / "P1.json").exists())
            again = TriageRuntime(world=World(), person_id="P1")
            self.assertEqual(again.world.flagged, first.world.flagged)
            self.assertTrue(again.world.flagged)
            self.assertEqual(default_world().flagged, set())                       # loaded into the person's world, not the shared one
            self.assertEqual(TriageRuntime(world=World(), person_id="P2").incidents, {})
            self.assertEqual(again.next_report_number(), number + 1)              # generated report ids are not reused after a restart

    def test_forgotten_safe_mail_is_gone_from_the_saved_file_too(self):
        safe = "From: Mum <mum@example.org>\nTo: you@example.org\nSubject: Lunch\nMessage-ID: <lunch-1@example.org>\n\nSee you at one."
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"KINGUARD_STATE_FILE": str(Path(directory) / "state.json")}):
            pool.forget_everyone()
            self.assertEqual(scanner.handle_mail({"person_id": "P9", "id": "M1"}, safe), "safe")
            saved = json.loads((Path(directory) / "people" / "P9.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["reports"], [])
            pool.forget_everyone()


class MarkedScammerTests(unittest.TestCase):
    def test_a_marked_scammer_is_remembered_and_the_person_is_told_how_to_block_them(self):
        runtime = TriageRuntime()
        scam = runtime.process(RawInputReport(report_id="W1", source="whatsapp", timestamp="2026-10-01T09:05:00",
                                              payload="Congratulations! You have been selected for a R5000 reward. Pay the R200 release fee via voucher to claim.",
                                              metadata={"sender": "Raven"}))
        self.assertEqual(scam.proposed_action.type, ActionType.FLAG_SENDER)
        self.assertEqual(scam.action_outcome, ActionOutcome.EXECUTED)
        warning = WORLD.outbox[-1]["message"]
        self.assertNotIn("blocked", warning.lower())  # nothing outside Scam Stop was blocked
        self.assertIn("block them in WhatsApp", warning)
        follow_up = runtime.process(RawInputReport(report_id="W2", source="whatsapp", timestamp="2026-10-01T11:00:00",
                                                   payload="Hi, did you get my message?", metadata={"sender": "Raven"}))
        self.assertNotEqual(follow_up.labels["threat"], ThreatDomain.BENIGN.value)
        self.assertIn("already marked as a scammer", follow_up.trace[1])
        self.assertEqual(follow_up.action_outcome, ActionOutcome.EXECUTED)  # warned at once, not held for a human
        stranger = runtime.process(RawInputReport(report_id="W3", source="whatsapp", timestamp="2026-10-01T11:01:00",
                                                  payload="Hi, did you get my message?", metadata={"sender": "Thandi"}))
        self.assertEqual(stranger.labels["threat"], ThreatDomain.BENIGN.value)


class PersonAnswerTests(unittest.TestCase):
    def test_not_mine_confirms_the_warning_and_never_downgrades_it(self):
        runtime = TriageRuntime()
        scam = runtime.process(RawInputReport(report_id="S1", source="sms", timestamp="2026-10-01T09:11:00",
                                              payload="Congratulations! You have been selected for a R5000 reward. Pay the R200 release fee via voucher to claim.",
                                              metadata={"sender": "+27845243073"}))
        before = runtime.incidents[scam.incident_id].model_copy(deep=True)
        answer = runtime.process(RawInputReport(report_id="F-0001", source="person", timestamp="2026-10-01T09:40:00",
                                                payload="The person says they did not agree to this.",
                                                metadata={"incident_id": scam.incident_id, "feedback": "not_mine"}))
        after = runtime.incidents[scam.incident_id]
        self.assertEqual(answer.incident_id, scam.incident_id)
        self.assertEqual(after.labels["threat"], before.labels["threat"])  # it used to become BENIGN
        self.assertNotEqual(after.labels["threat"], ThreatDomain.BENIGN.value)
        self.assertEqual((after.severity, after.status), (before.severity, before.status))
        self.assertIn("confirms the warning", answer.trace[1])
        self.assertIsNone(answer.proposed_action)


class PlainQuestionTests(unittest.TestCase):
    def test_every_action_that_can_be_held_carries_a_plain_question(self):
        runtime = TriageRuntime()
        text = "You have been selected. Reply to this number."
        decisions = [runtime.process(message("Q1", "Urgent: send a gift card today to claim.")),
                     runtime.process(message("Q2", DEBIT)),
                     runtime.process(message("Q3", "Debit order of R89.00 to ZZQX HOLDINGS ref ZZQ1234 on 02 Oct."))]
        for decision in decisions:
            self.assertTrue(decision.proposed_action.details.get("ask"), decision.proposed_action.type)


class LearningTests(unittest.TestCase):
    def test_a_rejected_doubtful_warning_is_not_raised_again_for_that_sender(self):
        runtime = TriageRuntime()
        promo = "Your account has been recharged with R 5.00 and you have received R 5.00 FREE airtime."
        fake = {key: {"type": "noul", "noul": 0.84 if key == "prize" else 0.0} for key in TEXT_RULES}
        fake["threat"] = {"type": "choice", "choice": "PRIZE_SCAM", "confidence": 0.9}
        with patch.dict("os.environ", {"ENABLE_JEV": "1"}), patch("domain.gate.system_one", return_value=fake):
            first = runtime.process(message("L1", promo))
            self.assertEqual(first.action_outcome, ActionOutcome.HELD_FOR_REVIEW)
            runtime.decide_review(first.review_id, approved=False)
            again = runtime.process(message("L2", promo, timestamp="2026-10-09T06:00:00"))
            scam = runtime.process(message("L3", "Urgent: you have won! Send a gift card voucher to claim now.", timestamp="2026-10-09T07:00:00"))
        self.assertIsNone(again.proposed_action)
        self.assertIn("fine", again.trace[1])
        self.assertIsNotNone(scam.proposed_action)  # strong evidence from the same sender is still acted on


if __name__ == "__main__":
    unittest.main()
