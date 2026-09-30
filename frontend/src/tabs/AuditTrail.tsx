import { STATUS_WORD, actionLabel, formatTime, sourceLabel } from '../format'
import type { KinGuardState } from '../types'

type Props = { state: KinGuardState; onOpen: (incidentId: string) => void }

/** Every decision the agent made, newest first. One row per message taken in. */
export function AuditTrail({ state, onOpen }: Props) {
  const reports = new Map(state.reports.map((item) => [item.report_id, item]))
  const reviews = new Map(state.reviews.map((item) => [item.review_id, item]))
  const rows = state.decisions
    .map((decision) => ({ decision, report: reports.get(decision.report_id) }))
    .sort((a, b) => (b.report?.timestamp ?? '').localeCompare(a.report?.timestamp ?? ''))

  if (rows.length === 0) return <p className="empty muted">Nothing has been checked yet.</p>

  return (
    <section className="card wide audit">
      <h2>Audit trail</h2>
      <p className="muted">Every message taken in and what the agent did with it. Open a row to see the full reasoning.</p>
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Message</th>
            <th>Alert</th>
            <th>Status</th>
            <th>Action</th>
            <th>Human</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ decision, report }) => {
            const review = decision.review_id ? reviews.get(decision.review_id) : undefined
            const action = decision.proposed_action ?? decision.suppressed_action
            return (
              <tr key={decision.report_id}>
                <td>{formatTime(report?.timestamp)}</td>
                <td>
                  {sourceLabel(report?.source ?? '')} <code>{decision.report_id}</code>
                </td>
                <td>
                  <button type="button" className="link" onClick={() => onOpen(decision.incident_id)}>
                    {decision.incident_id}
                  </button>{' '}
                  <span className="muted">{decision.relationship.toLowerCase()}</span>
                </td>
                <td>
                  {decision.previous_status && decision.previous_status !== decision.status
                    ? `${STATUS_WORD[decision.previous_status]} → ${STATUS_WORD[decision.status]}`
                    : STATUS_WORD[decision.status]}
                </td>
                <td>
                  {action ? `${actionLabel(action.type, action.details)}: ${decision.action_outcome.toLowerCase().replaceAll('_', ' ')}` : '—'}
                </td>
                <td>{review ? `${review.review_id} ${review.status.toLowerCase().replaceAll('_', ' ')}` : decision.requires_human_approval ? 'needed' : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
