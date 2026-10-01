"""Who is looked after, who looks after them, and how the person connects their own Gmail."""
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import Caller, caller, caregiver, caregiver_of, set_clerk_role, who
from api.gmail import google_token, revoke
from api.pool import runtime_for
from api.store import Store, get_store, invite_problem

router = APIRouter(tags=["people"])


class NewPerson(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    relation: str = Field(default="", max_length=40)


def _mailbox(row: dict) -> dict:
    """A mailbox as the front end sees it: its state, never a token or a message."""
    return {"id": row["id"], "kind": row["kind"], "label": row["label"], "status": row["status"], "connected_at": row["connected_at"],
            "last_checked": row["last_checked"], "last_error": row["last_error"], "checked": row["checked"]}


def _invite(row: dict) -> dict:
    return {"token": row["token"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def _person(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "relation": row["relation"]}


def _me(me: Caller, store: Store) -> dict:
    people = [_person(item) for item in store.people_of(me.user_id)]
    mailbox = None
    if me.role == "person":
        mailbox = next((_mailbox(item) for item in store.mailboxes(me.person_id) if item["kind"] == "gmail"), None)
    return {"user_id": me.user_id, "role": me.role,
            "person": people[0] if people else None,   # the person a protected person is; a caregiver's first
            "people": people,                         # everyone a caregiver looks after
            "can_add_person": me.role != "person",
            "mailbox": mailbox}


@router.get("/me")
def me(me: Caller = Depends(caller)):
    """Who the signed-in user is: a caregiver (with the people they look after), the protected person, or nobody yet."""
    return _me(me, get_store())


@router.post("/people", status_code=201)
def add_person(body: NewPerson, me: Caller = Depends(caller)):
    """A caregiver adds someone to look after. Anyone not yet linked becomes a caregiver by doing this; a protected person cannot."""
    store = get_store()
    if me.role == "person":
        raise HTTPException(409, "You are the person being looked after")
    first = store.first_person() is None
    person = store.create_person(body.name, body.relation, me.user_id)
    if first and os.getenv("IMAP_HOST"):
        store.ensure_forwarded(person["id"], os.getenv("IMAP_USER", "Forwarded inbox"))  # the server's one IMAP mailbox belongs to the first person
    if me.role is None:
        set_clerk_role(me.user_id, "caregiver")
    return _me(caller(me.user_id), store)


@router.get("/people/summary")
def summary(me: Caller = Depends(caregiver)):
    """For the switcher: each person the caregiver looks after, with how many decisions wait and how many mailboxes are in trouble."""
    store = get_store()
    result = []
    for row in store.people_of(me.user_id):
        waiting = sum(1 for item in runtime_for(row["id"]).snapshot()["reviews"] if item.status == "PENDING")
        trouble = sum(1 for item in store.mailboxes(row["id"]) if item["status"] != "connected")
        result.append({**_person(row), "needs": waiting, "problems": trouble})
    return result


@router.get("/people/{person_id}/mailboxes")
def mailboxes(person_id: str, _: Caller = Depends(caregiver_of)):
    """The person's mailboxes with their state. The caregiver sees whether mail is being checked, never the mail."""
    return [_mailbox(item) for item in get_store().mailboxes(person_id)]


@router.get("/people/{person_id}/invites")
def invites(person_id: str, _: Caller = Depends(caregiver_of)):
    return [_invite(item) for item in get_store().pending_invites(person_id)]


@router.post("/people/{person_id}/invites", status_code=201)
def create_invite(person_id: str, me: Caller = Depends(caregiver_of)):
    """A single-use link the person opens to connect their own Gmail. It expires in 7 days."""
    return _invite(get_store().create_invite(person_id, me.user_id))


@router.post("/people/{person_id}/invites/{token}/cancel")
def cancel_invite(person_id: str, token: str, _: Caller = Depends(caregiver_of)):
    if not get_store().cancel_invite(person_id, token):
        raise HTTPException(404, "That invite is not waiting any more")
    return {"status": "cancelled"}


@router.post("/people/{person_id}/phone", status_code=201)
def pair_phone(person_id: str, me: Caller = Depends(caregiver_of)):
    """A pairing code for the person's phone app. Shown once; a new code unpairs the previous phone."""
    return {"code": get_store().pair_phone(person_id, me.user_id)}


@router.get("/people/{person_id}/phone")
def phone(person_id: str, _: Caller = Depends(caregiver_of)):
    """Whether a phone is paired, and when. Never the code."""
    return {"paired_at": get_store().phone_paired(person_id)}


@router.get("/invites/{token}")
def look_at_invite(token: str):
    """What the person sees before signing in. No sign-in needed; it reveals only the name and whether the link works."""
    store = get_store()
    invite = store.invite(token)
    problem = invite_problem(invite)
    person = store.person(invite["person_id"]) if invite else None
    ok = problem is None
    return {"valid": ok, "problem": problem, "person_name": person["name"] if person and ok else None,
            "role": invite["role"] if invite and ok else None,          # empty: the person connects Gmail; else the circle role offered
            "invitee_name": invite["name"] if invite and ok and invite["role"] else None}


@router.post("/invites/{token}/accept")
def accept_invite(token: str, user_id: str = Depends(who)):
    """The person signed in with Google from the link. Check Gmail works, then link them and start watching.
    A circle invite instead links the signed-in user to the person in the role it offers."""
    store = get_store()
    problem = invite_problem(store.invite(token))
    if problem:
        raise HTTPException(410, problem)
    if store.invite(token)["role"]:
        return _join_circle(token, user_id, store)
    links = store.links_of(user_id)
    invited_person = store.invite(token)["person_id"]
    if links and (len(links) != 1 or links[0] != {"person_id": invited_person, "role": "person"}):
        raise HTTPException(409, "This account is already linked to someone")
    if os.getenv("KINGUARD_DEV_OPEN") != "1":
        google_token(user_id)  # refuses, with a plain reason, if Gmail read access was not granted; the link stays usable
    try:
        store.accept_invite(token, user_id)
    except ValueError as error:
        raise HTTPException(410, str(error)) from error
    set_clerk_role(user_id, "person")
    return _me(caller(user_id), store)


def _join_circle(token: str, user_id: str, store: Store) -> dict:
    invite = store.invite(token)
    links = store.links_of(user_id)
    before = caller(user_id).role
    if any(item["role"] == "person" for item in links):
        raise HTTPException(409, "This account belongs to someone who is looked after")
    if any(item["person_id"] == invite["person_id"] for item in links):
        raise HTTPException(409, "You are already in this circle")
    try:
        store.accept_circle_invite(token, user_id)
    except ValueError as error:
        raise HTTPException(410, str(error)) from error
    after = caller(user_id)
    if after.role != before:
        set_clerk_role(user_id, after.role)  # a helper who is now also a caregiver somewhere uses the dashboard
    return _me(after, store)


@router.post("/me/disconnect")
def disconnect(me: Caller = Depends(caller)):
    """The person stops Scam Stop reading their Gmail. Takes effect at once; only a new invite reconnects it."""
    if me.role != "person":
        raise HTTPException(403, "Only the person whose mail it is can disconnect it")
    store = get_store()
    if os.getenv("KINGUARD_DEV_OPEN") != "1":
        try:
            revoke(google_token(me.user_id))
        except HTTPException:
            pass  # already refused by Google: nothing left to revoke
    store.disconnect(me.person_id)
    return _me(me, store)
