import { useState } from 'react'
import { post } from '../api'
import {
  PERSON,
  SEVERITY_WORD,
  STATUS_WORD,
  actionLabel,
  formatTime,
  incidentTitle,
  severityTone,
  sourceLabel,
  statusTone,
  threatLabel,
  traceToSteps,
} from '../format'
import type { Decision, Incident, KinGuardState, Report, Review } from '../types'

type Props = {
  state: KinGuardState
  selectedId: string | null
  onSelect: (id: string) => void
  onChanged: () => void
  onOpenChannels: () => void
}

function byPriority(a: Incident, b: Incident): number {
  const waiting = Number(b.status === 'PENDING_REVIEW') - Number(a.status === 'PENDING_REVIEW')
  return waiting || b.updated_at.localeCompare(a.updated_at)
}

export function Alerts({ state, selectedId, onSelect, onChanged, onOpenChannels }: Props) {
  const incidents = [...state.incidents].sort(byPriority)
  const selected = incidents.find((item) => item.incident_id === selectedId) ?? incidents[0]

  if (incidents.length === 0) {
    return (
      <div className="empty">
        <h2>No alerts for {PERSON.name}</h2>
        <p>Messages from Gmail, the live inbox or shared SMS are checked as they arrive and show up here.</p>
        <button type="button" className="button primary" onClick={onOpenChannels}>
          Check a message now
        </button>
      </div>
    )
  }

  return (
    <div className="alerts">
      <aside className="alert-list" aria-label={`Alerts for ${PERSON.name}`}>
        <h3 className="eyebrow">Alerts for {PERSON.name}</h3>
        <ul>
          {incidents.map((incident) => {
            const lastDone = [...incident.actions].reverse().find((item) => item.outcome === 'EXECUTED')
            const active = incident.incident_id === selected.incident_id
            return (
              <li key={incident.incident_id}>
                <button
                  type="button"
                  className={`alert-card tone-${statusTone(incident.status)}${active ? ' active' : ''}`}
                  aria-current={active}
                  onClick={() => onSelect(incident.incident_id)}
                >
                  <strong>{incidentTitle(incident)}</strong>
                  {incident.status === 'PENDING_REVIEW' ? (
                    <span className="chip tone-warn">Needs your decision</span>
                  ) : lastDone ? (
                    <span className="chip tone-ok">{actionLabel(lastDone.action.type, lastDone.action.details)}</span>
                  ) : null}
                  <time>{formatTime(incident.updated_at)}</time>
                </button>
              </li>
            )
          })}
        </ul>
      </aside>

      <AlertDetail key={selected.incident_id} incident={selected} state={state} onChanged={onChanged} />
    </div>
  )
}

function AlertDetail({ incident, state, onChanged }: { incident: Incident; state: KinGuardState; onChanged: () => void }) {
  const reports = incident.report_ids
    .map((id) => state.reports.find((item) => item.report_id === id))
    .filter((item): item is Report => Boolean(item))
  const decisions = new Map(state.decisions.map((item) => [item.report_id, item]))
  const reviews = state.reviews.filter((item) => item.incident_id === incident.incident_id)
  const told = state.world.outbox.filter((item) => item.incident_id === incident.incident_id)

  return (
    <section className="alert-detail" aria-labelledby="alert-title">
      <div className="detail-meta">
        <span className={`pill tone-${severityTone(incident.severity)}`}>
          {SEVERITY_WORD[incident.severity]} · {STATUS_WORD[incident.status]}
        </span>
        <code>{incident.incident_id}</code>
        <time>{formatTime(incident.updated_at)}</time>
      </div>
      <h1 id="alert-title">{incidentTitle(incident)}</h1>
      {incident.review_hold && <p className="hold">{incident.review_hold}</p>}

      <div className="detail-grid">
        <div>
          <h3 className="eyebrow">Investigation</h3>
          <ol className="timeline">
            {reports.map((report) => (
              <ReportSteps key={report.report_id} report={report} decision={decisions.get(report.report_id)} />
            ))}
          </ol>
        </div>

        <Outcome incident={incident} reviews={reviews} told={told.map((item) => item.message)} onChanged={onChanged} />
      </div>
    </section>
  )
}

function ReportSteps({ report, decision }: { report: Report; decision?: Decision }) {
  const sender = String(report.metadata.sender_name || report.metadata.sender || '')
  const quote = report.payload.length > 280 ? `${report.payload.slice(0, 280)}…` : report.payload
  return (
    <>
      <li className="step tone-neutral">
        <span className="step-icon">{sourceLabel(report.source).charAt(0)}</span>
        <div>
          <p className="step-title">
            {sourceLabel(report.source)} received
            <code>{[sender, report.report_id].filter(Boolean).join(' · ')}</code>
            <time>{formatTime(report.timestamp)}</time>
          </p>
          <blockquote>“{quote}”</blockquote>
          {decision?.labels.threat && (
            <div className="facts">
              <Fact name="threat" value={threatLabel(decision.labels.threat)} />
              {decision.labels.merchant && <Fact name="merchant" value={decision.labels.merchant} />}
              {decision.labels.reg_no && <Fact name="company reg" value={decision.labels.reg_no} />}
            </div>
          )}
        </div>
      </li>
      {decision &&
        traceToSteps(decision.trace).map((step, index) => (
          <li key={index} className={`step tone-${step.tone}`}>
            <span className="step-icon">{step.icon}</span>
            <div>
              <p className="step-title">
                {step.title}
                {step.tag && <code>{step.tag}</code>}
              </p>
              {step.body && <p>{step.body}</p>}
              {step.bullets && (
                <ul className="reasons">
                  {step.bullets.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
    </>
  )
}

function Fact({ name, value }: { name: string; value: string }) {
  return (
    <div className="fact">
      <span>{name}</span>
      <strong>{value}</strong>
    </div>
  )
}

function Outcome({ incident, reviews, told, onChanged }: { incident: Incident; reviews: Review[]; told: string[]; onChanged: () => void }) {
  const done = incident.actions.filter((item) => item.outcome === 'EXECUTED')
  const failed = incident.actions.filter((item) => item.outcome === 'FAILED')
  const pending = reviews.filter((item) => item.status === 'PENDING')
  const decided = reviews.filter((item) => item.status !== 'PENDING')
  const percent = Math.round(incident.confidence * 100)

  return (
    <aside className="outcome card" aria-label="Outcome">
      <h2>Outcome</h2>
      <div className="confidence">
        <span className="eyebrow">Confidence</span>
        <div className={`bar tone-${severityTone(incident.severity)}`} role="meter" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <strong>{incident.confidence.toFixed(2)}</strong>
      </div>

      {pending.length > 0 && (
        <>
          <h3 className="eyebrow">Waiting for you</h3>
          {pending.map((review) => (
            <PendingReview key={review.review_id} review={review} onChanged={onChanged} />
          ))}
        </>
      )}

      <h3 className="eyebrow">Already done by the agent</h3>
      {done.length === 0 ? (
        <p className="muted">Nothing yet.</p>
      ) : (
        <ul className="checks">
          {done.map((item, index) => (
            <li key={index}>
              <span aria-hidden="true">✓</span> {actionLabel(item.action.type, item.action.details)}
            </li>
          ))}
        </ul>
      )}
      {failed.map((item, index) => (
        <p key={index} className="banner tone-danger">
          {actionLabel(item.action.type, item.action.details)} failed: {item.detail}
        </p>
      ))}

      {told.length > 0 && (
        <>
          <h3 className="eyebrow">What {PERSON.name} was told</h3>
          {told.map((message, index) => (
            <p key={index} className="banner tone-ok">
              {message}
            </p>
          ))}
        </>
      )}

      {decided.length > 0 && (
        <ul className="history">
          {decided.map((review) => (
            <li key={review.review_id}>
              {review.proposed_action ? actionLabel(review.proposed_action.type, review.proposed_action.details) : review.reason}:{' '}
              {review.status === 'APPROVED' ? 'approved' : review.status === 'REJECTED' ? 'rejected' : 'approved, but it failed'}
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

function PendingReview({ review, onChanged }: { review: Review; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function decide(approved: boolean) {
    setBusy(true)
    setError('')
    try {
      await post(`/reviews/${review.review_id}/decision`, { approved })
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="review">
      <strong>{review.proposed_action ? actionLabel(review.proposed_action.type, review.proposed_action.details) : 'Check this alert'}</strong>
      <p>{review.reason}</p>
      <div className="row">
        <button type="button" className="button primary" disabled={busy} onClick={() => decide(true)}>
          Approve
        </button>
        <button type="button" className="button" disabled={busy} onClick={() => decide(false)}>
          Reject
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}
