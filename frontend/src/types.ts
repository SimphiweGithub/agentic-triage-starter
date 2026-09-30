// Shapes returned by the Scam Stop backend. See backend/API.md.

export type IncidentState =
  | 'NEW'
  | 'TRIAGED'
  | 'INVESTIGATING'
  | 'PENDING_REVIEW'
  | 'CONTAINED'
  | 'RESOLVED'
  | 'CLOSED'

export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type ActionType =
  | 'RECORD_ONLY'
  | 'WARN_PERSON'
  | 'FLAG_SENDER'
  | 'DRAFT_DISPUTE'
  | 'BLOCK_OPERATOR'
  | 'WITHDRAW'

export type ActionOutcome =
  | 'NONE'
  | 'PROPOSED'
  | 'EXECUTED'
  | 'FAILED'
  | 'HELD_FOR_REVIEW'
  | 'SUPPRESSED_DUPLICATE'
  | 'SUPPRESSED_REPEAT'

export type ActionProposal = {
  type: ActionType
  service: string
  details: Record<string, unknown>
}

export type ActionRecord = {
  report_id: string
  action: ActionProposal
  outcome: ActionOutcome
  detail: string
}

export type Report = {
  report_id: string
  timestamp: string
  source: string
  payload: string
  metadata: Record<string, unknown>
}

export type Incident = {
  incident_id: string
  status: IncidentState
  severity: Severity
  confidence: number
  report_ids: string[]
  summary: string
  updated_at: string
  review_hold: string | null
  actions: ActionRecord[]
  labels: Record<string, string>
}

export type Decision = {
  report_id: string
  incident_id: string
  relationship: 'NEW' | 'RELATED' | 'DUPLICATE'
  status: IncidentState
  severity: Severity
  confidence: number
  proposed_action: ActionProposal | null
  action_outcome: ActionOutcome
  suppressed_action: ActionProposal | null
  requires_human_approval: boolean
  review_id: string | null
  previous_status: IncidentState | null
  previous_severity: Severity | null
  previous_confidence: number | null
  labels: Record<string, string>
  trace: string[]
}

export type Review = {
  review_id: string
  report_id: string
  incident_id: string
  reason: string
  proposed_action: ActionProposal | null
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'APPROVED_ACTION_FAILED' | string
  created_at: string
}

export type World = {
  outbox: { incident_id: string; message: string }[]
  flagged: string[]
  disputes: Record<string, string>
  blocked: string[]
  trusted: string[]
}

export type KinGuardState = {
  reports: Report[]
  incidents: Incident[]
  decisions: Decision[]
  reviews: Review[]
  world: World
}

export type Health = {
  status: string
  mailbox: boolean
  jev: boolean
  gemini: boolean
  live_lookups: boolean
  gmail: boolean
}

export type GmailMessage = {
  id: string
  thread_id: string
  sender: string
  subject: string
  date: string
  snippet: string
}
