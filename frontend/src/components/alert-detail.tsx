import { Check } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import {
  PERSON,
  actionLabel,
  alertGroup,
  findings,
  formatTime,
  incidentReports,
  incidentTitle,
  sourceLabel,
  threatLabel,
  traceToSteps,
} from '@/format'
import type { Decision, GuardianBrief, Incident, KinGuardState, Report } from '@/types'
import { ReviewCard } from './decision'
import { GroupBadge } from './status'

type Props = {
  incidentId: string | null
  state: KinGuardState
  briefs: GuardianBrief[]
  onClose: () => void
  onDecided: (message: string) => void
}

/** The whole story of one alert in a modal, so nobody has to leave the page they are on. */
export function AlertDetailDialog({ incidentId, state, briefs, onClose, onDecided }: Props) {
  const incident = incidentId ? state.incidents.find((item) => item.incident_id === incidentId) : undefined
  return (
    <Dialog open={Boolean(incident)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90svh] gap-5 overflow-y-auto p-6 sm:max-w-2xl">
        {incident && <Body key={incident.incident_id} incident={incident} state={state} briefs={briefs} onDecided={onDecided} />}
      </DialogContent>
    </Dialog>
  )
}

function Body({ incident, state, briefs, onDecided }: { incident: Incident; state: KinGuardState; briefs: GuardianBrief[]; onDecided: (message: string) => void }) {
  const [showTech, setShowTech] = useState(false)
  const reports = incidentReports(incident, state)
  const decisions = new Map(state.decisions.map((item) => [item.report_id, item]))
  const told = state.world.outbox.filter((item) => item.incident_id === incident.incident_id).at(-1)?.message
  const pending = state.reviews.filter((item) => item.incident_id === incident.incident_id && item.status === 'PENDING')
  const decided = state.reviews.filter((item) => item.incident_id === incident.incident_id && item.status !== 'PENDING' && item.status !== 'SUPERSEDED')
  const noticed = [...new Set(reports.flatMap((report) => findings(decisions.get(report.report_id)?.trace ?? [])))]
  const done = incident.actions.filter((item) => item.outcome === 'EXECUTED')
  const failed = incident.actions.filter((item) => item.outcome === 'FAILED')

  return (
    <>
      <DialogHeader className="gap-2">
        <GroupBadge group={alertGroup(incident)} />
        <DialogTitle className="text-2xl leading-tight font-bold">{incidentTitle(incident)}</DialogTitle>
        <DialogDescription className="text-base text-foreground">{told ?? threatLabel(incident.labels.threat)}</DialogDescription>
      </DialogHeader>

      {incident.review_hold && <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm font-bold text-warn">{incident.review_hold}</p>}

      {pending.map((review) => (
        <ReviewCard key={review.review_id} review={review} brief={briefs.find((item) => item.review_id === review.review_id)} onDecided={onDecided} />
      ))}

      <ol className="flex flex-col gap-5">
        <Step n={1} title={reports.length > 1 ? `The ${reports.length} messages ${PERSON.name} got` : `The message ${PERSON.name} got`}>
          {reports.map((report) => (
            <Message key={report.report_id} report={report} />
          ))}
        </Step>
        <Step n={2} title="What we noticed">
          {noticed.length === 0 ? (
            <p className="text-muted-foreground">Nothing unusual was found.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5">
              {noticed.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </Step>
        <Step n={3} title="What KinGuard did">
          {done.length === 0 ? (
            <p className="text-muted-foreground">Nothing. It was kept for the record only.</p>
          ) : (
            <ul className="space-y-1">
              {done.map((item, index) => (
                <li key={index} className="flex items-start gap-2">
                  <Check className="mt-1 size-4 shrink-0 text-info" aria-hidden="true" />
                  {actionLabel(item.action.type, item.action.details)}
                </li>
              ))}
            </ul>
          )}
          {failed.map((item, index) => (
            <p key={index} className="rounded-lg bg-destructive/10 px-3 py-2 text-sm font-bold text-destructive">
              {actionLabel(item.action.type, item.action.details)} did not work: {item.detail}
            </p>
          ))}
          {decided.length > 0 && (
            <ul className="space-y-1 text-sm text-muted-foreground">
              {decided.map((review) => (
                <li key={review.review_id}>
                  {review.proposed_action ? actionLabel(review.proposed_action.type, review.proposed_action.details) : review.reason}:{' '}
                  {review.status === 'APPROVED' ? 'you approved it' : review.status === 'REJECTED' ? 'you said no' : 'approved, but it failed'}
                </li>
              ))}
            </ul>
          )}
        </Step>
      </ol>

      <Separator />
      <div>
        <Button variant="ghost" size="sm" className="text-muted-foreground" aria-expanded={showTech} onClick={() => setShowTech((open) => !open)}>
          {showTech ? 'Hide technical details' : 'Show technical details'}
        </Button>
        {showTech && (
          <div className="mt-2 overflow-x-auto rounded-lg bg-terminal p-4 font-mono text-xs leading-relaxed text-[#e4e8e2]">
            <p className="text-[#9fb3ac]">
              {incident.incident_id} · severity {incident.severity.toLowerCase()} · confidence {incident.confidence.toFixed(2)} · updated {formatTime(incident.updated_at)}
            </p>
            {reports.map((report) => (
              <TechSteps key={report.report_id} report={report} decision={decisions.get(report.report_id)} />
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-4">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted font-bold">{n}</span>
      <div className="grid min-w-0 flex-1 gap-2">
        <h3 className="text-base font-bold">{title}</h3>
        {children}
      </div>
    </li>
  )
}

function Message({ report }: { report: Report }) {
  const sender = String(report.metadata.sender_name || report.metadata.sender || '')
  const quote = report.payload.length > 400 ? `${report.payload.slice(0, 400)}…` : report.payload
  return (
    <div className="grid gap-1.5">
      <p className="text-sm text-muted-foreground">
        {sourceLabel(report.source)}
        {sender && ` · from ${sender}`} · {formatTime(report.timestamp)}
      </p>
      <blockquote className="rounded-lg bg-background px-4 py-3 break-words">{quote}</blockquote>
    </div>
  )
}

function TechSteps({ report, decision }: { report: Report; decision?: Decision }) {
  return (
    <div className="mt-3">
      <p className="text-[#9fb3ac]">
        {report.report_id} · {sourceLabel(report.source)} · {decision ? `${decision.relationship.toLowerCase()}, ${decision.action_outcome.toLowerCase().replaceAll('_', ' ')}` : 'no decision'}
      </p>
      {decision &&
        traceToSteps(decision.trace).map((step, index) => (
          <div key={index} className="break-words">
            <strong>{step.title}</strong>
            {step.tag && ` (${step.tag})`}
            {step.body && `: ${step.body}`}
            {step.bullets && `: ${step.bullets.join('; ')}`}
          </div>
        ))}
    </div>
  )
}
