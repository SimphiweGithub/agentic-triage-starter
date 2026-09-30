import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.fsm import transition_state
from core.guardrails import enforce_action_safety
from core.runtime import TriageRuntime
from domain.enums import ActionType, IncidentState, Relationship, SeverityLevel
from domain.policy import ALLOWED_SERVICE_ACTIONS, FORBIDDEN_ACTIONS
from domain.schemas import ActionProposal, Assessment, RawInputReport
from evaluation import evaluate
from runner import run
from main import app


def report(report_id: str, payload: str) -> RawInputReport:
    return RawInputReport(report_id=report_id, source="sensor", payload=payload)


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
        ALLOWED_SERVICE_ACTIONS.clear()
        try:
            self.assertTrue(enforce_action_safety(action, 0.99).requires_review)
        finally:
            from domain.enums import ServiceDomain
            ALLOWED_SERVICE_ACTIONS[ServiceDomain.UNSPECIFIED] = {ActionType.RECORD_ONLY}

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
        assessment = Assessment(severity=SeverityLevel.LOW, confidence=0.9,
                                requested_state=IncidentState.INVESTIGATING,
                                proposed_action=ActionProposal(type=ActionType.RECORD_ONLY), rationale="test")
        with patch("core.runtime.assess", return_value=assessment):
            duplicate = runtime.process(report("R2", "same signal"))
        self.assertIsNone(duplicate.proposed_action)

    def test_runtime_queues_illegal_state(self):
        assessment = Assessment(severity=SeverityLevel.HIGH, confidence=0.9,
                                requested_state=IncidentState.CLOSED, rationale="test")
        with patch("core.runtime.assess", return_value=assessment):
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
            import json
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


if __name__ == "__main__":
    unittest.main()
