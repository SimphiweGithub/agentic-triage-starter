"""Phone calls the person's Android phone noticed. Only who called, when and for how long: a call is never heard or recorded.

The paired phone reports a call when it ends and, for an unknown number, shows the common call scams. What the
person taps then is sent back as the call's answer. The caregivers see the calls; a helper does not.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import Caller, dev_open, member_of
from api.store import get_store

router = APIRouter(tags=["calls"])

ANSWERS = ("known", "asked_code", "told_kin")


class CallReport(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)   # chosen by the phone, so a report sent twice is kept once
    number: str = Field(min_length=1, max_length=32)
    at: str = Field(min_length=1, max_length=40)         # when the call started, ISO 8601
    seconds: int = Field(ge=0, le=24 * 3600)
    in_contacts: bool = False
    contact_name: str | None = Field(default=None, max_length=80)
    tips_shown: bool = False


class CallAnswer(BaseModel):
    answer: str = Field(pattern="^(" + "|".join(ANSWERS) + ")$")


def _from_phone(person_id: str, me: Caller) -> None:
    """Calls are reported and answered by the person's own phone. A caregiver cannot put words in their mouth."""
    if not dev_open() and me.links.get(person_id) != "person":
        raise HTTPException(403, "Only the person's phone can report calls")


@router.get("/people/{person_id}/calls")
def calls(person_id: str, _: Caller = Depends(member_of)):
    """The newest calls first."""
    return get_store().calls(person_id)


@router.post("/people/{person_id}/calls", status_code=201)
def report_call(person_id: str, call: CallReport, me: Caller = Depends(member_of)):
    _from_phone(person_id, me)
    return get_store().record_call(person_id, call.model_dump())


@router.post("/people/{person_id}/calls/{call_id}/answer")
def answer_call(person_id: str, call_id: str, body: CallAnswer, me: Caller = Depends(member_of)):
    """What the person tapped after an unknown call: someone they know, the caller asked for a PIN or code, or tell family."""
    _from_phone(person_id, me)
    answered = get_store().answer_call(person_id, call_id, body.answer)
    if answered is None:
        raise HTTPException(404, "Call not found")
    return answered
