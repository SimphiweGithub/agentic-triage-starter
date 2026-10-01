"""Small durable storage: who is looked after, who looks after them, invites and connected mailboxes.

Incidents and reviews are saved separately, one JSON file per person (core/store.py).
"""
import hashlib
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "kinguard.db"
INVITE_DAYS = 7
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O, 0, I or 1, which look alike
OUTAGE_MINUTES = 15  # a temporary Gmail failure only becomes a problem after this long

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, relation TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS links (
    person_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
    PRIMARY KEY (person_id, user_id));
CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY, person_id TEXT NOT NULL, created_by TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, accepted_at TEXT, cancelled_at TEXT);
CREATE TABLE IF NOT EXISTS mailboxes (
    id TEXT PRIMARY KEY, person_id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, owner_user_id TEXT, connected_at TEXT NOT NULL,
    last_checked TEXT, last_error TEXT, failing_since TEXT);
CREATE TABLE IF NOT EXISTS scanned (
    mailbox_id TEXT NOT NULL, message_id TEXT NOT NULL, verdict TEXT NOT NULL, at TEXT NOT NULL,
    PRIMARY KEY (mailbox_id, message_id));
CREATE TABLE IF NOT EXISTS phones (
    key_hash TEXT PRIMARY KEY, person_id TEXT NOT NULL, user_id TEXT NOT NULL, created_by TEXT NOT NULL,
    created_at TEXT NOT NULL, revoked_at TEXT);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.getenv("KINGUARD_DB") or DEFAULT_PATH)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def reset(self) -> None:
        """Empty every table. For tests."""
        with self.lock:
            for table in ("people", "links", "invites", "mailboxes", "scanned", "phones"):
                self.db.execute(f"DELETE FROM {table}")
            self.db.commit()

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    # ---- people and who looks after them ----

    def people(self) -> list[dict]:
        with self.lock:
            return self._all("SELECT * FROM people ORDER BY created_at")

    def person(self, person_id: str) -> dict | None:
        with self.lock:
            return self._one("SELECT * FROM people WHERE id = ?", (person_id,))

    def create_person(self, name: str, relation: str, caregiver_id: str) -> dict:
        """Add a person and make `caregiver_id` their caregiver. A caregiver may look after several people."""
        with self.lock:
            person_id = f"P{secrets.token_hex(4)}"
            self.db.execute("INSERT INTO people VALUES (?, ?, ?, ?)", (person_id, name.strip(), relation.strip(), stamp(now())))
            self.db.execute("INSERT INTO links VALUES (?, ?, 'caregiver')", (person_id, caregiver_id))
            self.db.commit()
            return self.person(person_id)

    def create_self(self, name: str, user_id: str) -> dict:
        """Someone protecting themselves, with no caregiver: they are linked to their own record as the person."""
        with self.lock:
            person_id = f"P{secrets.token_hex(4)}"
            self.db.execute("INSERT INTO people VALUES (?, ?, '', ?)", (person_id, name.strip(), stamp(now())))
            self.db.execute("INSERT INTO links VALUES (?, ?, 'person')", (person_id, user_id))
            self.db.commit()
            return self.person(person_id)

    def has_caregiver(self, person_id: str) -> bool:
        with self.lock:
            return self._one("SELECT 1 FROM links WHERE person_id = ? AND role = 'caregiver'", (person_id,)) is not None

    def links_of(self, user_id: str) -> list[dict]:
        """Every person this user is linked to, with their role. A caregiver may have several; a protected person has one."""
        with self.lock:
            return self._all("SELECT person_id, role FROM links WHERE user_id = ? ORDER BY rowid", (user_id,))

    def people_of(self, user_id: str) -> list[dict]:
        """The people this user is linked to, oldest first."""
        with self.lock:
            return self._all("SELECT p.* FROM people p JOIN links l ON l.person_id = p.id WHERE l.user_id = ? ORDER BY p.created_at, p.rowid", (user_id,))

    def first_person(self) -> dict | None:
        """The earliest person added. The server's own IMAP mailbox belongs to them."""
        with self.lock:
            return self._one("SELECT * FROM people ORDER BY created_at, rowid LIMIT 1")

    # ---- invites ----

    def create_invite(self, person_id: str, created_by: str) -> dict:
        with self.lock:
            token = secrets.token_urlsafe(24)
            created = now()
            self.db.execute("INSERT INTO invites (token, person_id, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                            (token, person_id, created_by, stamp(created), stamp(created + timedelta(days=INVITE_DAYS))))
            self.db.commit()
            return self.invite(token)

    def invite(self, token: str) -> dict | None:
        with self.lock:
            return self._one("SELECT * FROM invites WHERE token = ?", (token,))

    def pending_invites(self, person_id: str) -> list[dict]:
        with self.lock:
            return [item for item in self._all("SELECT * FROM invites WHERE person_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL ORDER BY created_at DESC", (person_id,))
                    if not invite_problem(item)]

    def cancel_invite(self, person_id: str, token: str) -> bool:
        with self.lock:
            cursor = self.db.execute("UPDATE invites SET cancelled_at = ? WHERE token = ? AND person_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL",
                                     (stamp(now()), token, person_id))
            self.db.commit()
            return cursor.rowcount > 0

    def accept_invite(self, token: str, user_id: str) -> dict:
        """Mark the invite used, link the user as the protected person, and start watching their Gmail."""
        with self.lock:
            invite = self.invite(token)
            problem = invite_problem(invite)
            if problem:
                raise ValueError(problem)
            person_id = invite["person_id"]
            self.db.execute("UPDATE invites SET accepted_at = ? WHERE token = ?", (stamp(now()), token))
            self.db.execute("DELETE FROM links WHERE person_id = ? AND role = 'person' AND user_id != ? AND user_id NOT LIKE 'phone:%'",
                            (person_id, user_id))  # a paired phone stays paired when the person connects Gmail
            self.db.execute("INSERT OR REPLACE INTO links VALUES (?, ?, 'person')", (person_id, user_id))
            self.db.commit()
            return self.connect_gmail(person_id, user_id)

    def connect_gmail(self, person_id: str, user_id: str) -> dict:
        """Start watching `user_id`'s Gmail for the person: from an accepted invite, or by someone protecting themselves."""
        with self.lock:
            self.db.execute("DELETE FROM scanned WHERE mailbox_id IN (SELECT id FROM mailboxes WHERE person_id = ? AND kind = 'gmail')", (person_id,))
            self.db.execute("DELETE FROM mailboxes WHERE person_id = ? AND kind = 'gmail'", (person_id,))  # one Gmail per person for now
            mailbox_id = f"M{secrets.token_hex(4)}"
            self.db.execute("INSERT INTO mailboxes (id, person_id, kind, label, status, owner_user_id, connected_at) VALUES (?, ?, 'gmail', 'Gmail', 'connected', ?, ?)",
                            (mailbox_id, person_id, user_id, stamp(now())))
            self.db.commit()
            return self.mailbox(mailbox_id)

    # ---- mailboxes ----

    def mailbox(self, mailbox_id: str) -> dict | None:
        with self.lock:
            return self._one("SELECT m.*, (SELECT COUNT(*) FROM scanned s WHERE s.mailbox_id = m.id) AS checked FROM mailboxes m WHERE m.id = ?", (mailbox_id,))

    def mailboxes(self, person_id: str | None = None) -> list[dict]:
        with self.lock:
            sql = "SELECT m.*, (SELECT COUNT(*) FROM scanned s WHERE s.mailbox_id = m.id) AS checked FROM mailboxes m"
            return self._all(sql + (" WHERE m.person_id = ?" if person_id else "") + " ORDER BY m.connected_at", (person_id,) if person_id else ())

    def ensure_forwarded(self, person_id: str, label: str) -> dict:
        """The server's own IMAP mailbox, shown beside the person's Gmail. Created once."""
        with self.lock:
            found = self._one("SELECT id FROM mailboxes WHERE person_id = ? AND kind = 'forwarded'", (person_id,))
            if not found:
                mailbox_id = f"M{secrets.token_hex(4)}"
                self.db.execute("INSERT INTO mailboxes (id, person_id, kind, label, status, connected_at) VALUES (?, ?, 'forwarded', ?, 'connected', ?)",
                                (mailbox_id, person_id, label, stamp(now())))
                self.db.commit()
                return self.mailbox(mailbox_id)
            return self.mailbox(found["id"])

    def disconnect(self, person_id: str) -> None:
        with self.lock:
            self.db.execute("UPDATE mailboxes SET status = 'disconnected', last_error = NULL, failing_since = NULL WHERE person_id = ? AND kind = 'gmail'", (person_id,))
            self.db.commit()

    def mark_checked(self, mailbox_id: str) -> None:
        with self.lock:
            self.db.execute("UPDATE mailboxes SET status = 'connected', last_checked = ?, last_error = NULL, failing_since = NULL WHERE id = ? AND status != 'disconnected'",
                            (stamp(now()), mailbox_id))
            self.db.commit()

    def mark_failure(self, mailbox_id: str, reason: str, permanent: bool) -> None:
        """A revoked or refused token is a problem at once. A temporary failure becomes one after OUTAGE_MINUTES."""
        with self.lock:
            row = self._one("SELECT failing_since, status FROM mailboxes WHERE id = ?", (mailbox_id,))
            if row is None or row["status"] == "disconnected":
                return
            since = row["failing_since"] or stamp(now())
            long_enough = now() - datetime.fromisoformat(since) >= timedelta(minutes=OUTAGE_MINUTES)
            status = "problem" if permanent or long_enough else row["status"]
            self.db.execute("UPDATE mailboxes SET status = ?, last_error = ?, failing_since = ? WHERE id = ?", (status, reason, since, mailbox_id))
            self.db.commit()

    # ---- the person's paired phone ----

    def pair_phone(self, person_id: str, created_by: str) -> str:
        """A new pairing code for the person's phone. Only its hash is kept; an earlier phone is unpaired."""
        with self.lock:
            code = "".join(secrets.choice(CODE_LETTERS) for _ in range(10))  # about 50 bits; easy to type on a phone
            user_id = f"phone:{secrets.token_hex(4)}"
            for row in self._all("SELECT user_id FROM phones WHERE person_id = ? AND revoked_at IS NULL", (person_id,)):
                self.db.execute("DELETE FROM links WHERE user_id = ?", (row["user_id"],))
            self.db.execute("UPDATE phones SET revoked_at = ? WHERE person_id = ? AND revoked_at IS NULL", (stamp(now()), person_id))
            self.db.execute("INSERT INTO phones VALUES (?, ?, ?, ?, ?, NULL)", (_hash(code), person_id, user_id, created_by, stamp(now())))
            self.db.execute("INSERT INTO links VALUES (?, ?, 'person')", (person_id, user_id))
            self.db.commit()
            return code

    def phone_user(self, code: str) -> str | None:
        """The user id a pairing code stands for, or None if it is unknown or was replaced."""
        with self.lock:
            row = self._one("SELECT user_id FROM phones WHERE key_hash = ? AND revoked_at IS NULL", (_hash(code),))
            return row["user_id"] if row else None

    def phone_paired(self, person_id: str) -> str | None:
        """When the person's current phone was paired, or None."""
        with self.lock:
            row = self._one("SELECT created_at FROM phones WHERE person_id = ? AND revoked_at IS NULL", (person_id,))
            return row["created_at"] if row else None

    # ---- what has been scanned (an id and a verdict, never the message) ----

    def seen(self, mailbox_id: str, message_id: str) -> bool:
        with self.lock:
            return self._one("SELECT 1 FROM scanned WHERE mailbox_id = ? AND message_id = ?", (mailbox_id, message_id)) is not None

    def record_scanned(self, mailbox_id: str, message_id: str, verdict: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO scanned VALUES (?, ?, ?, ?)", (mailbox_id, message_id, verdict, stamp(now())))
            self.db.commit()


def _hash(code: str) -> str:
    """Codes are compared without spaces, dashes or case, so `ab3k-7q2m` typed on a phone still matches."""
    return hashlib.sha256("".join(code.split()).replace("-", "").upper().encode("utf-8")).hexdigest()


def invite_problem(invite: dict | None) -> str | None:
    """Why an invite cannot be used, in words the person would understand, or None if it can."""
    if invite is None:
        return "This link is not valid."
    if invite["cancelled_at"]:
        return "This link was cancelled. Ask for a new one."
    if invite["accepted_at"]:
        return "This link has already been used."
    if datetime.fromisoformat(invite["expires_at"]) < now():
        return "This link has expired. Ask for a new one."
    return None


_store: Store | None = None


def get_store() -> Store:
    """One shared store, opened on first use so tests can point KINGUARD_DB elsewhere first."""
    global _store
    if _store is None:
        _store = Store()
    return _store
