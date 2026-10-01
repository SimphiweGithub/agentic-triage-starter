"""Who is calling. Clerk proves who the user is; the store says which person they are linked to and in what role."""
import os
from dataclasses import dataclass

from clerk_backend_api import Clerk
from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Depends, HTTPException, Request

from api.store import get_store


@dataclass
class Caller:
    user_id: str
    role: str | None            # "caregiver", "person", or None before they are linked to anyone
    person_ids: list[str]       # a caregiver may look after several people; a protected person has one

    @property
    def person_id(self) -> str | None:
        return self.person_ids[0] if self.person_ids else None


def dev_open() -> bool:
    """Development only: KINGUARD_DEV_OPEN=1 skips Clerk so the plain console and local scripts still work."""
    return os.getenv("KINGUARD_DEV_OPEN") == "1"


def who(request: Request) -> str:
    """The Clerk user id behind the request's session token, or 401. A paired phone sends its pairing code instead."""
    code = request.headers.get("x-device-key")
    if code:
        user_id = get_store().phone_user(code)
        if user_id is None:
            raise HTTPException(401, "This phone is not paired any more. Ask for a new pairing code.")
        return user_id  # linked to one person as role "person", so it reaches only that person's own routes
    if dev_open():
        return request.headers.get("x-dev-user", "dev")  # lets a developer act as different people without Clerk
    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        raise HTTPException(503, "Sign-in is not configured: set CLERK_SECRET_KEY in .env")
    parties = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
    state = authenticate_request(request, AuthenticateRequestOptions(secret_key=secret, authorized_parties=parties or None))
    if not state.is_signed_in or not state.payload:
        raise HTTPException(401, "Sign in first")
    return state.payload["sub"]


def caller(user_id: str = Depends(who)) -> Caller:
    links = get_store().links_of(user_id)
    return Caller(user_id, links[0]["role"] if links else None, [item["person_id"] for item in links])


def caregiver(me: Caller = Depends(caller)) -> Caller:
    """Someone who looks after people. Before they are linked to anyone there is nothing for them to see."""
    if me.role == "caregiver" or (dev_open() and me.role is None):
        return me
    raise HTTPException(403, "Add the person you look after first." if me.role is None else "Only the caregiver can do this.")


def member(me: Caller = Depends(caller)) -> Caller:
    """The caregiver or the protected person: the few routes both may use."""
    if me.role is not None or dev_open():
        return me
    raise HTTPException(403, "Add the person you look after first.")


def _may_see(me: Caller, person_id: str) -> bool:
    """Linked to this person, or in development mode with nobody linked (the plain console)."""
    return person_id in me.person_ids or (dev_open() and me.role is None and get_store().person(person_id) is not None)


def caregiver_of(person_id: str, me: Caller = Depends(caregiver)) -> Caller:
    """The caregiver of this particular person. Someone else's person looks like it does not exist."""
    if not _may_see(me, person_id):
        raise HTTPException(404, "Person not found")
    return me


def member_of(person_id: str, me: Caller = Depends(member)) -> Caller:
    """This person's caregiver, or the person themselves."""
    if not _may_see(me, person_id):
        raise HTTPException(404, "Person not found")
    return me


def active_caregiver_person(person_id: str | None = None, me: Caller = Depends(caregiver)) -> str | None:
    """The person a caregiver route is about: the one in the address, checked. None means the plain console in development mode."""
    if person_id is None:
        if dev_open() and me.role is None:
            return None
        raise HTTPException(404, "Name the person in the address: /api/people/{id}/...")
    if not _may_see(me, person_id):
        raise HTTPException(404, "Person not found")
    return person_id


def active_member_person(person_id: str | None = None, me: Caller = Depends(member)) -> str | None:
    """The same for the routes the protected person may also use."""
    if person_id is None:
        if dev_open() and me.role is None:
            return None
        raise HTTPException(404, "Name the person in the address: /api/people/{id}/...")
    if not _may_see(me, person_id):
        raise HTTPException(404, "Person not found")
    return person_id


def set_clerk_role(user_id: str, role: str) -> None:
    """Store the role on the Clerk user too, so the front end can read it. The store stays the authority."""
    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret or dev_open():
        return
    try:
        with Clerk(bearer_auth=secret) as clerk:
            clerk.users.update_metadata(user_id=user_id, public_metadata={"role": role})
    except Exception as error:  # a Clerk hiccup must not undo a link that is already saved
        print(f"could not set the Clerk role for {user_id}: {type(error).__name__}: {error}")
