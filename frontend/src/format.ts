import type { ActionType, Incident, IncidentState, KinGuardState, Report, Review, Severity } from './types'

/**
 * The person being looked after. It is filled in from the server before the dashboard shows,
 * so nothing is hard-coded. The object is shared, so every screen sees the same name.
 */
export const PERSON = { name: 'them', relation: '' }

export function setPerson(person: { name: string; relation: string } | null): void {
  PERSON.name = person?.name || 'them'
  PERSON.relation = person?.relation || ''
}

const THREAT: Record<string, string> = {
  TECH_SUPPORT_SCAM: 'Tech-support scam',
  GREY_MARKET_SUBSCRIPTION: 'Unwanted subscription',
  IDENTITY_FARMING: 'Phishing for personal details',
  PRIZE_SCAM: 'Prize scam',
  IMPERSONATION: 'Someone pretending to be family',
  ADVANCE_FEE: 'Pay-a-fee-first scam',
  JOB_SCAM: 'Fake job or investment',
  SALES_OFFER: 'Unrequested loan or insurance offer',
  BENIGN: 'Looks safe',
  UNKNOWN: 'Suspicious message',
}

export function threatLabel(threat: string | undefined): string {
  return (threat && THREAT[threat]) || 'Suspicious message'
}

export function titleCase(text: string): string {
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function incidentTitle(incident: Incident): string {
  const merchant = incident.labels.merchant
  return merchant ? `${threatLabel(incident.labels.threat)} · ${titleCase(merchant)}` : threatLabel(incident.labels.threat)
}

export const STATUS_WORD: Record<IncidentState, string> = {
  PENDING_REVIEW: 'needs you',
  CONTAINED: 'contained',
  INVESTIGATING: 'checking',
  RESOLVED: 'resolved',
  CLOSED: 'resolved',
  NEW: 'new',
  TRIAGED: 'new',
}

export const SEVERITY_WORD: Record<Severity, string> = {
  LOW: 'Low',
  MEDIUM: 'Medium',
  HIGH: 'High',
  CRITICAL: 'Critical',
}

export type Tone = 'danger' | 'warn' | 'info' | 'ok' | 'neutral'

export function severityTone(severity: Severity): Tone {
  return { CRITICAL: 'danger', HIGH: 'warn', MEDIUM: 'info', LOW: 'neutral' }[severity] as Tone
}

export function statusTone(status: IncidentState): Tone {
  if (status === 'PENDING_REVIEW') return 'warn'
  if (status === 'CONTAINED' || status === 'RESOLVED' || status === 'CLOSED') return 'ok'
  return 'neutral'
}

export function actionLabel(type: ActionType, details: Record<string, unknown> = {}): string {
  const target = typeof details.target === 'string' ? details.target : ''
  const company = typeof details.company === 'string' ? details.company : ''
  switch (type) {
    case 'FLAG_SENDER':
      return target ? `Marked ${target} as a scammer` : 'Marked the sender as a scammer'
    case 'WARN_PERSON':
      return `Warned ${PERSON.name}`
    case 'DRAFT_DISPUTE':
      return company ? `Dispute the debit from ${company}` : 'Dispute the debit order'
    case 'BLOCK_OPERATOR':
      return company ? `Stop debits from ${company}` : 'Stop the debit operator'
    case 'ADVISE_DECLINE':
      return company ? `Decline the debit request from ${company}` : `Advised ${PERSON.name} to decline`
    case 'WITHDRAW':
      return 'Undid earlier actions'
    case 'RECORD_ONLY':
      return 'Recorded for the file'
  }
}

const TIME = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatTime(iso: string | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : TIME.format(date).replace(/^(\w+),? /, '$1 ').replace('Sept', 'Sep')
}

export function sourceLabel(source: string): string {
  const known: Record<string, string> = { email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp', person: 'Answer from ' + PERSON.name }
  return known[source] ?? titleCase(source || 'message')
}

// ---- trace lines → investigation steps ----

export type Step = {
  icon: string
  title: string
  tag?: string
  body?: string
  bullets?: string[]
  tone: Tone
}

/**
 * The backend's trace is plain text, one line per step (see backend/core/runtime.py).
 * Known prefixes become labelled steps; anything else is shown as it is.
 */
export function traceToSteps(lines: string[]): Step[] {
  const steps: Step[] = []
  for (const line of lines) {
    let match: RegExpMatchArray | null
    if ((match = line.match(/^Correlation: (\w+) \(([\d.]+)\) — (.*)$/))) {
      const [, relationship, score, reason] = match
      if (relationship === 'NEW') continue // nothing to say about a first message
      steps.push({
        icon: '⇄',
        title: relationship === 'DUPLICATE' ? 'Same message seen before' : 'Linked to this alert',
        tag: `match ${Number(score).toFixed(2)}`,
        body: reason,
        tone: 'neutral',
      })
    } else if ((match = line.match(/^Risk ([\d.]+)\. (.*)$/))) {
      const [, score, rest] = match
      const bullets = rest.replace(/\.$/, '').split('; ').filter(Boolean)
      steps.push({ icon: 'J', title: 'Risk check', tag: `risk ${Number(score).toFixed(2)}`, bullets, tone: Number(score) >= 0.6 ? 'warn' : 'info' })
    } else if ((match = line.match(/^Benign: (.*)$/))) {
      steps.push({ icon: 'J', title: 'Risk check', tag: 'benign', body: match[1], tone: 'ok' })
    } else if ((match = line.match(/^FSM: (\w+) → (\w+)$/))) {
      const [, requested, granted] = match
      const word = STATUS_WORD[granted as IncidentState] ?? granted
      steps.push({
        icon: '→',
        title: `Alert is now ${word}`,
        body: requested !== granted ? `Asked for ${STATUS_WORD[requested as IncidentState] ?? requested}; the rules allowed ${word}.` : undefined,
        tone: 'neutral',
      })
    } else if ((match = line.match(/^(?:Action|Review (REV-\d+)): (\w+) → (\w+)(?: \((.*)\))?$/))) {
      const [, reviewId, type, outcome, detail] = match
      const label = actionLabel(type as ActionType)
      const done = outcome === 'EXECUTED'
      steps.push({
        icon: done ? '✓' : outcome === 'FAILED' ? '!' : outcome === 'HELD_FOR_REVIEW' ? '⏸' : '·',
        title: done ? label : outcome === 'HELD_FOR_REVIEW' ? `${label}: waiting for you` : `${label}: ${outcome.toLowerCase().replaceAll('_', ' ')}`,
        tag: reviewId ? `after ${reviewId}` : undefined,
        body: detail,
        tone: done ? 'ok' : outcome === 'FAILED' ? 'danger' : outcome === 'HELD_FOR_REVIEW' ? 'warn' : 'neutral',
      })
    } else if ((match = line.match(/^Review: (.*) \((REV-\d+)\)$/))) {
      steps.push({ icon: '?', title: 'Asked you to decide', tag: match[2], body: match[1], tone: 'warn' })
    } else if (line === 'Policy: No action proposed') {
      steps.push({ icon: '·', title: 'No action needed', tone: 'neutral' })
    } else {
      steps.push({ icon: '·', title: line.split(':')[0], body: line.includes(':') ? line.slice(line.indexOf(':') + 1).trim() : undefined, tone: 'neutral' })
    }
  }
  return steps
}

// ---- plain-language view of an alert ----

export type Group = 'needs' | 'handled' | 'safe'

export const GROUP_WORD: Record<Group, string> = { needs: 'Needs you', handled: 'Handled', safe: 'Looked safe' }

export function alertGroup(incident: Incident): Group {
  if (incident.status === 'PENDING_REVIEW') return 'needs'
  return incident.labels.threat === 'BENIGN' ? 'safe' : 'handled'
}

/** Channels that belong to a device. Mailboxes belong to the person and are listed separately. */
export const CHANNELS = ['SMS', 'WhatsApp', 'Calls'] as const
export type Channel = (typeof CHANNELS)[number]

/** The channel the first message of an alert arrived on. */
/** Every channel an alert's messages came through, in order: one scam can arrive by SMS and WhatsApp alike. */
export function incidentChannels(incident: Incident, reports: Map<string, Report>): string[] {
  const seen = incident.report_ids.map((id) => reports.get(id)).filter((item): item is Report => Boolean(item)).map((item) => sourceLabel(item.source))
  return seen.length > 0 ? [...new Set(seen)] : ['Message']
}

/** "SMS + WhatsApp · 2 messages": where an alert's messages came from, and how many there are. */
export function incidentChannel(incident: Incident, reports: Map<string, Report>): string {
  const count = incident.report_ids.length
  return incidentChannels(incident, reports).join(' + ') + (count > 1 ? ` · ${count} messages` : '')
}

export function incidentReports(incident: Incident, state: KinGuardState): Report[] {
  const byId = new Map(state.reports.map((item) => [item.report_id, item]))
  return incident.report_ids.map((id) => byId.get(id)).filter((item): item is Report => Boolean(item))
}

/** The question to put to whoever approves, in the backend's own words. */
export function reviewQuestion(review: Review): string {
  const ask = review.proposed_action?.details.ask
  return typeof ask === 'string' && ask ? ask : review.reason
}

export function reviewDeadline(review: Review): string {
  const by = review.proposed_action?.details.dispute_by
  return typeof by === 'string' && by ? `A dispute must be lodged by ${by}.` : ''
}

export function approveLabel(review: Review): string {
  switch (review.proposed_action?.type) {
    case 'DRAFT_DISPUTE':
      return 'Yes, prepare the dispute'
    case 'BLOCK_OPERATOR':
      return 'Yes, stop these debits'
    default:
      return 'Yes, go ahead'
  }
}

export function money(amount: unknown): string {
  return typeof amount === 'number' ? `R${amount.toFixed(2)}` : ''
}

/** What each step of the reasoning found, as short sentences (the "Risk" line of the trace). */
export function findings(lines: string[]): string[] {
  return traceToSteps(lines).flatMap((step) => step.bullets ?? (step.tag === 'benign' && step.body ? [step.body] : []))
}

/** What saying yes will do, in plain words, so the button explains itself. */
export function approveEffect(review: Review): string {
  switch (review.proposed_action?.type) {
    case 'DRAFT_DISPUTE':
      return `Scam Stop writes the dispute for the bank. It cannot send it: you or ${PERSON.name} lodge it.`
    case 'BLOCK_OPERATOR':
      return 'Scam Stop asks the bank to refuse every debit from this company.'
    case 'FLAG_SENDER':
      return `Scam Stop marks this sender as a scammer, warns ${PERSON.name} about anything else they send, and tells ${PERSON.name} how to block them.`
    case 'WITHDRAW':
      return 'Scam Stop undoes what it did earlier, for example un-marking a sender.'
    default:
      return 'Scam Stop goes ahead with what it proposed.'
  }
}

/** What saying no will do. */
export function rejectEffect(review: Review): string {
  switch (review.proposed_action?.type) {
    case 'DRAFT_DISPUTE':
      return 'Nothing is written. Scam Stop keeps watching this company.'
    case 'BLOCK_OPERATOR':
      return 'Debits are not stopped. Scam Stop keeps watching and will ask again if it happens again.'
    default:
      return 'Nothing is done. Scam Stop keeps watching.'
  }
}

/** A short label for the kind of decision, used as a heading in lists. */
export function decisionKind(review: Review): string {
  switch (review.proposed_action?.type) {
    case 'DRAFT_DISPUTE':
      return 'Dispute a debit'
    case 'BLOCK_OPERATOR':
      return 'Stop a company taking money'
    case 'FLAG_SENDER':
      return 'Mark a sender as a scammer'
    case 'WITHDRAW':
      return 'Undo earlier actions'
    default:
      return 'Check an alert'
  }
}
