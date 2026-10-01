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
  | 'ADVISE_DECLINE'
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
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'APPROVED_ACTION_FAILED' | 'SUPERSEDED' | string
  /** Who is asked: the caregiver, or the person themselves when no guardian is enrolled. */
  audience: 'CAREGIVER' | 'PERSON' | string
  /** Cooling-off: approving before this time returns 409. */
  not_before: string | null
  created_at: string
}

export type Dispute = {
  text: string
  dispute_by: string
  steps: string[]
}

export type GuardianBrief = {
  review_id: string
  incident_id: string
  text: string
  whatsapp_link: string
}

export type World = {
  outbox: { incident_id: string; message: string }[]
  flagged: string[]
  disputes: Record<string, Dispute>
  blocked: string[]
  trusted: string[]
  guardian: boolean
}

export type KinGuardState = {
  reports: Report[]
  incidents: Incident[]
  decisions: Decision[]
  reviews: Review[]
  replay?: { total: number; position: number }
  world: World
}

export type Health = {
  status: string
  mailbox: boolean
  jev: boolean
  gemini: boolean
  live_lookups: boolean
  gmail: boolean
  guardian: boolean
}

export type Role = 'caregiver' | 'person'

export type MailboxStatus = 'connected' | 'problem' | 'disconnected'

/** A mailbox as the server reports it: its state, never a token or a message. */
export type Mailbox = {
  id: string
  kind: 'gmail' | 'forwarded'
  label: string
  status: MailboxStatus
  connected_at: string
  last_checked: string | null
  last_error: string | null
  /** How many messages have been checked. */
  checked: number
}

export type PersonRecord = { id: string; name: string; relation: string }

export type Me = {
  user_id: string
  role: Role | null
  /** The person a protected person is, or a caregiver's first. */
  person: PersonRecord | null
  /** Everyone a caregiver looks after. */
  people: PersonRecord[]
  can_add_person: boolean
  /** The person's own Gmail, for the `person` role. */
  mailbox: Mailbox | null
}

export type Invite = { token: string; created_at: string; expires_at: string }

export type InviteLook = { valid: boolean; problem: string | null; person_name: string | null }

/** For the switcher: how many decisions wait for one person, and how many of their mailboxes are in trouble. */
export type PersonSummary = PersonRecord & { needs: number; problems: number }
