"""Act, check, correct: run an approved action and, if it fails, try a corrected one."""
from core.guardrails import enforce_action_safety
from domain.enums import ActionOutcome
from domain.policy import FORBIDDEN_ACTIONS, MAX_CORRECTIONS
from domain.schemas import ActionProposal, ActionRecord, IncidentRecord, RawInputReport, ToolResult
from domain.tools import ACTION_TOOLS, correct


def run_tool(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult | None:
    """Call the tool for this action. None means no tool is registered. A crash becomes a failed result."""
    tool = ACTION_TOOLS.get(action.type)
    if tool is None:
        return None
    try:
        return tool(action, incident, report)
    except Exception as error:
        return ToolResult(ok=False, detail=f"tool crashed: {type(error).__name__}: {error}")


def execute_with_correction(action: ActionProposal, confidence: float, incident: IncidentRecord, report: RawInputReport) -> list[ActionRecord]:
    """Every attempt, including corrected ones, passes the guardrails before its tool runs."""
    attempts: list[ActionRecord] = []
    for _ in range(1 + MAX_CORRECTIONS):
        safety = enforce_action_safety(action, confidence)
        if safety.requires_review:
            attempts.append(ActionRecord(report_id=report.report_id, action=action, outcome=ActionOutcome.HELD_FOR_REVIEW, detail=safety.reason))
            break
        result = run_tool(action, incident, report)
        if result is None:
            attempts.append(ActionRecord(report_id=report.report_id, action=action, outcome=ActionOutcome.PROPOSED, detail="no tool registered"))
            break
        outcome = ActionOutcome.EXECUTED if result.ok else ActionOutcome.FAILED
        attempts.append(ActionRecord(report_id=report.report_id, action=action, outcome=outcome, detail=result.detail))
        if result.ok:
            break
        action = correct(action, result, report)
        if action is None:
            break
    return attempts


def execute_approved(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ActionRecord:
    """Run an action a human approved. Approval replaces the confidence and impact checks, never the forbidden list."""
    if action.type in FORBIDDEN_ACTIONS:
        return ActionRecord(report_id=report.report_id, action=action, outcome=ActionOutcome.FAILED, detail="forbidden action; approval cannot override")
    result = run_tool(action, incident, report)
    if result is None:
        return ActionRecord(report_id=report.report_id, action=action, outcome=ActionOutcome.PROPOSED, detail="approved; no tool registered")
    outcome = ActionOutcome.EXECUTED if result.ok else ActionOutcome.FAILED
    return ActionRecord(report_id=report.report_id, action=action, outcome=outcome, detail=f"approved by a human; {result.detail}")
