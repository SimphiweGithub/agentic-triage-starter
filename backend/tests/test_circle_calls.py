"""The care circle's roles and the phone's call reports: who may see, answer and change what."""
import os

os.environ["KINGUARD_SKIP_ENV_FILE"] = "1"
os.environ["KINGUARD_STATE_FILE"] = ""
os.environ["KINGUARD_DB"] = ":memory:"
os.environ["KINGUARD_DEV_OPEN"] = "1"

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import auth, people, pool
from api.store import Store, get_store
from main import app

ROOT = Path(__file__).resolve().parents[1]
DEBIT = "YourBank: Debit order of R349.00 to TECHCARE ref TCS8841 from acc 1234567890 on 02 Oct."
CALL = {"call_id": "c1", "number": "010 500 4412", "at": "2026-10-01T10:12:00+00:00", "seconds": 362, "in_contacts": False, "tips_shown": True}


class CircleAndCallTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"KINGUARD_DEV_OPEN": "0", "CLERK_SECRET_KEY": "sk_test_fake"})
        self.env.start()
        get_store().reset()
        pool.forget_everyone()
        self.client = TestClient(app)
        self.user = "kin"
        app.dependency_overrides[auth.who] = lambda: self.user
        self.roles = []
        self.role_patch = patch.object(people, "set_clerk_role", lambda user_id, role: self.roles.append((user_id, role)))
        self.role_patch.start()
        self.person = self.client.post("/api/people", json={"name": "Thandi", "relation": "Gran"}).json()["people"][0]["id"]

    def tearDown(self):
        self.role_patch.stop()
        app.dependency_overrides.clear()
        self.env.stop()
        get_store().reset()
        pool.forget_everyone()

    def url(self, path: str) -> str:
        return f"/api/people/{self.person}{path}"

    def join(self, user: str, role: str, name: str) -> None:
        """The next of kin invites `user` in `role`; they open the link signed in and accept."""
        self.user = "kin"
        invite = self.client.post(self.url("/circle/invites"), json={"name": name, "role": role})
        self.assertEqual(invite.status_code, 201, invite.text)
        token = invite.json()["token"]
        self.user = user
        look = self.client.get(f"/api/invites/{token}").json()
        self.assertEqual((look["role"], look["invitee_name"], look["person_name"]), (role, name, "Thandi"))
        self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 200)

    def phone(self) -> dict:
        self.user = "kin"
        code = self.client.post(self.url("/phone")).json()["code"]
        return {"X-Device-Key": code}

    def caregiver_review(self) -> str:
        self.user = "kin"
        lure = (ROOT / "samples" / "lure.eml").read_text(encoding="utf-8")
        self.client.post(self.url("/intake/email"), json={"content": lure})
        return self.client.post(self.url("/intake/share"), json={"text": DEBIT, "sender": "YourBank"}).json()["review_id"]

    # ---- the circle ----

    def test_whoever_adds_a_person_is_their_next_of_kin(self):
        circle = self.client.get(self.url("/circle")).json()
        self.assertEqual([(item["role"], item["you"]) for item in circle], [("protected", False), ("next_of_kin", True)])
        self.assertEqual(circle[0]["name"], "Thandi")
        self.assertTrue(circle[1]["id"].startswith("U"))
        self.assertNotIn("kin", circle[1]["id"])  # the sign-in id is never shown

    def test_invites_are_shown_as_waiting_until_accepted_and_never_show_their_token(self):
        token = self.client.post(self.url("/circle/invites"), json={"name": "Naledi", "role": "caregiver"}).json()["token"]
        waiting = self.client.get(self.url("/circle")).json()[-1]
        self.assertEqual((waiting["name"], waiting["role"], waiting.get("pending")), ("Naledi", "caregiver", True))
        self.assertNotIn(token, str(waiting))
        self.assertEqual(self.client.get(self.url("/invites")).json(), [])  # the Gmail invites stay separate
        self.user = "naledi"
        self.client.post(f"/api/invites/{token}/accept")
        self.assertEqual([(item["name"], item["role"], item["you"]) for item in self.client.get(self.url("/circle")).json()][-1],
                         ("Naledi", "caregiver", True))
        self.assertEqual(self.client.post(f"/api/invites/{token}/accept").status_code, 410)  # single use

    def test_there_is_one_next_of_kin(self):
        refused = self.client.post(self.url("/circle/invites"), json={"name": "Lindiwe", "role": "next_of_kin"})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.client.post(self.url("/circle/invites"), json={"name": "X", "role": "boss"}).status_code, 422)

    def test_a_caregiver_sees_alerts_but_only_the_next_of_kin_answers_decisions_and_invites(self):
        review = self.caregiver_review()
        self.join("naledi", "caregiver", "Naledi")
        self.assertEqual(self.client.get(self.url("/state")).status_code, 200)
        self.assertEqual(self.client.post(self.url(f"/reviews/{review}/decision"), json={"approved": True}).status_code, 403)
        self.assertEqual(self.client.post(self.url("/circle/invites"), json={"name": "Mr Pillay", "role": "helper"}).status_code, 403)
        self.user = "kin"
        self.assertEqual(self.client.post(self.url(f"/reviews/{review}/decision"), json={"approved": True}).status_code, 200)

    def test_a_helper_sees_the_circle_and_nothing_else(self):
        self.join("pillay", "helper", "Mr Pillay")
        me = self.client.get("/api/me").json()
        self.assertEqual((me["role"], [item["name"] for item in me["people"]]), ("helper", ["Thandi"]))
        self.assertEqual(self.roles[-1], ("pillay", "helper"))
        self.assertEqual(self.client.get(self.url("/circle")).status_code, 200)
        for path in ("/state", "/outbox", "/calls", "/mailboxes"):
            self.assertEqual(self.client.get(self.url(path)).status_code, 403 if path in ("/state", "/mailboxes") else 404, path)

    def test_the_next_of_kin_or_the_person_removes_people_but_not_the_next_of_kin(self):
        self.join("naledi", "caregiver", "Naledi")
        circle = self.client.get(self.url("/circle")).json()
        naledi = next(item["id"] for item in circle if item["name"] == "Naledi")
        kin = next(item["id"] for item in circle if item["role"] == "next_of_kin")
        self.assertEqual(self.client.post(self.url(f"/circle/{kin}/remove")).status_code, 403)  # a caregiver may not
        self.user = "kin"
        self.assertEqual(self.client.post(self.url(f"/circle/{kin}/remove")).status_code, 409)
        self.assertEqual(self.client.post(self.url(f"/circle/{naledi}/remove")).status_code, 200)
        self.user = "naledi"
        self.assertEqual(self.client.get(self.url("/state")).status_code, 403)  # no longer linked to anyone

    def test_the_person_cannot_join_someone_elses_circle_as_a_carer(self):
        token = self.client.post(self.url("/circle/invites"), json={"name": "Gran", "role": "caregiver"}).json()["token"]
        phone = self.phone()
        app.dependency_overrides.clear()
        refused = self.client.post(f"/api/invites/{token}/accept", headers=phone)
        self.assertEqual(refused.status_code, 409)

    def test_an_older_database_gains_the_new_columns_and_keeps_its_caregivers_as_next_of_kin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            old = sqlite3.connect(path)
            old.executescript("""CREATE TABLE people (id TEXT PRIMARY KEY, name TEXT NOT NULL, relation TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
                CREATE TABLE links (person_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY (person_id, user_id));
                CREATE TABLE invites (token TEXT PRIMARY KEY, person_id TEXT NOT NULL, created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, accepted_at TEXT, cancelled_at TEXT);
                INSERT INTO people VALUES ('P1', 'Thandi', 'Gran', '2026-01-01T00:00:00+00:00');
                INSERT INTO links VALUES ('P1', 'old_caregiver', 'caregiver');""")
            old.commit()
            old.close()
            store = Store(path)
            self.assertEqual(store.circle_role("P1", "old_caregiver"), "next_of_kin")
            self.assertEqual(store.next_of_kin("P1"), "old_caregiver")
            store.close()

    # ---- calls ----

    def test_the_phone_reports_and_answers_calls_and_the_caregivers_see_them(self):
        phone = self.phone()
        app.dependency_overrides.clear()
        self.assertEqual(self.client.post(self.url("/calls"), headers=phone, json=CALL).status_code, 201)
        self.assertEqual(self.client.post(self.url("/calls"), headers=phone, json=CALL).status_code, 201)  # sent twice, kept once
        answered = self.client.post(self.url("/calls/c1/answer"), headers=phone, json={"answer": "asked_code"})
        self.assertEqual(answered.json()["answer"], "asked_code")
        self.assertEqual(self.client.post(self.url("/calls/nope/answer"), headers=phone, json={"answer": "known"}).status_code, 404)
        self.assertEqual(self.client.post(self.url("/calls/c1/answer"), headers=phone, json={"answer": "hello"}).status_code, 422)
        app.dependency_overrides[auth.who] = lambda: self.user
        self.user = "kin"
        listed = self.client.get(self.url("/calls")).json()
        self.assertEqual([(item["call_id"], item["number"], item["seconds"], item["answer"]) for item in listed], [("c1", "010 500 4412", 362, "asked_code")])
        self.assertEqual(self.client.post(self.url("/calls"), json={**CALL, "call_id": "c2"}).status_code, 403)  # only the phone reports
        self.assertEqual(self.client.post(self.url("/calls/c1/answer"), json={"answer": "known"}).status_code, 403)

    def test_another_persons_calls_are_out_of_reach(self):
        theirs = self.client.post("/api/people", json={"name": "Sipho"}).json()["people"][-1]["id"]
        phone = self.phone()
        app.dependency_overrides.clear()
        self.assertEqual(self.client.post(f"/api/people/{theirs}/calls", headers=phone, json=CALL).status_code, 404)
        app.dependency_overrides[auth.who] = lambda: "stranger"
        self.assertEqual(self.client.get(self.url("/calls")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
