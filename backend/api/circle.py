"""The care circle: everyone who helps keep one person safe, and the role each of them has.

Roles: the protected person, one next of kin (approves money decisions and decides who is in the circle),
caregivers (see alerts and calls, may not approve) and trusted helpers (see only the circle).
"""
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import Caller, circle_member_of, dev_open, next_of_kin_of
from api.store import CIRCLE_ROLES, get_store

router = APIRouter(tags=["circle"])


class CircleInviteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern="^(" + "|".join(CIRCLE_ROLES) + ")$")


def member_id(user_id: str) -> str:
    """A stable id for a circle member that does not reveal their sign-in id."""
    return "U" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def _invite_id(token: str) -> str:
    """An invite shown in the circle never shows its token: the token is what lets someone join."""
    return "I" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _day(stamp: str) -> str:
    moment = datetime.fromisoformat(stamp)
    return f"{moment.day} {moment:%b}"


def _circle_invite(row: dict) -> dict:
    return {"token": row["token"], "role": row["role"], "name": row["name"], "expires_at": row["expires_at"]}


@router.get("/people/{person_id}/circle")
def circle(person_id: str, me: Caller = Depends(circle_member_of)):
    """The person first, then everyone linked to them, then invites not yet accepted. `you` marks the caller."""
    store = get_store()
    person = store.person(person_id)
    paired = store.phone_paired(person_id)
    gmail = any(item["kind"] == "gmail" and item["status"] == "connected" for item in store.mailboxes(person_id))
    protected_status = "Phone paired" if paired else "Gmail connected" if gmail else "Phone not paired yet"
    members = [{"id": person_id, "name": person["name"], "relation": person["relation"], "role": "protected", "status": protected_status,
                "you": me.links.get(person_id) == "person"}]
    for row in store.circle(person_id):
        joined = row["joined_at"]
        status = "Manages the circle" if row["circle_role"] == "next_of_kin" else f"Joined {_day(joined)}" if joined else "In the circle"
        members.append({"id": member_id(row["user_id"]), "name": row["name"], "relation": "", "role": row["circle_role"], "status": status,
                        "you": row["user_id"] == me.user_id})
    for row in store.pending_invites(person_id, circle=True):
        members.append({"id": _invite_id(row["token"]), "name": row["name"], "relation": "", "role": row["role"],
                        "status": f"Invite sent · until {_day(row['expires_at'])}", "you": False, "pending": True})
    return members


@router.post("/people/{person_id}/circle/invites", status_code=201)
def invite_to_circle(person_id: str, body: CircleInviteRequest, me: Caller = Depends(next_of_kin_of)):
    """A single-use link that adds someone to the circle in the role chosen. One next of kin per person."""
    store = get_store()
    if body.role == "next_of_kin" and store.next_of_kin(person_id):
        raise HTTPException(409, "There is already a next of kin")
    return _circle_invite(store.create_circle_invite(person_id, me.user_id, body.name, body.role))


@router.get("/people/{person_id}/circle/invites")
def circle_invites(person_id: str, _: Caller = Depends(next_of_kin_of)):
    """Circle invites not yet accepted, with their links, for the next of kin to send again or cancel."""
    return [_circle_invite(row) for row in get_store().pending_invites(person_id, circle=True)]


@router.post("/people/{person_id}/circle/invites/{token}/cancel")
def cancel_circle_invite(person_id: str, token: str, _: Caller = Depends(next_of_kin_of)):
    store = get_store()
    invite = store.invite(token)
    if not invite or invite["person_id"] != person_id or not invite["role"] or not store.cancel_invite(person_id, token):
        raise HTTPException(404, "That invite is not waiting any more")
    return {"status": "cancelled"}


@router.post("/people/{person_id}/circle/{member}/remove")
def remove_from_circle(person_id: str, member: str, me: Caller = Depends(circle_member_of)):
    """The next of kin removes someone, or the protected person does. Nobody removes the person, and the next of kin stays."""
    store = get_store()
    role = store.circle_role(person_id, me.user_id)
    if not dev_open() and role not in ("next_of_kin", "protected"):
        raise HTTPException(403, "Only the next of kin or the person themselves can remove someone")
    target = next((row for row in store.circle(person_id) if member_id(row["user_id"]) == member), None)
    if target is None:
        raise HTTPException(404, "That person is not in the circle")
    if target["circle_role"] == "next_of_kin":
        raise HTTPException(409, "The next of kin cannot be removed here")
    store.remove_from_circle(person_id, target["user_id"])
    return {"status": "removed"}
