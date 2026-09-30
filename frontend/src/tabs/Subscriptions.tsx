import { PERSON, STATUS_WORD, actionLabel, formatTime, statusTone, threatLabel, titleCase } from '../format'
import type { KinGuardState } from '../types'

type Props = { state: KinGuardState; onOpen: (incidentId: string) => void }

export function Subscriptions({ state, onOpen }: Props) {
  const merchants = state.incidents
    .filter((item) => item.labels.merchant)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  const disputes = Object.entries(state.world.disputes)

  return (
    <div className="subscriptions">
      <section className="card wide">
        <h2>Companies taking money or asking for it</h2>
        <p className="muted">Every alert that names a company, newest first.</p>
        {merchants.length === 0 ? (
          <p className="muted">No companies seen yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>What it looks like</th>
                <th>Status</th>
                <th>Latest action</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {merchants.map((incident) => {
                const last = incident.actions.at(-1)
                return (
                  <tr key={incident.incident_id}>
                    <td>
                      <button type="button" className="link" onClick={() => onOpen(incident.incident_id)}>
                        {titleCase(incident.labels.merchant)}
                      </button>
                      {incident.labels.reg_no && <code>{incident.labels.reg_no}</code>}
                    </td>
                    <td>{threatLabel(incident.labels.threat)}</td>
                    <td>
                      <span className={`chip tone-${statusTone(incident.status)}`}>{STATUS_WORD[incident.status]}</span>
                    </td>
                    <td>{last ? `${actionLabel(last.action.type, last.action.details)} (${last.outcome.toLowerCase().replaceAll('_', ' ')})` : '—'}</td>
                    <td>{formatTime(incident.updated_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Debits being stopped</h2>
        <p className="muted">Operators the bank is asked to refuse.</p>
        <List items={state.world.blocked} empty="None." />
      </section>

      <section className="card">
        <h2>Disputes drafted</h2>
        {disputes.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="disputes">
            {disputes.map(([regNo, text]) => (
              <li key={regNo}>
                <code>{regNo}</code>
                <p>{text}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Trusted by {PERSON.name}</h2>
        <p className="muted">Companies {PERSON.name} confirmed as their own.</p>
        <List items={state.world.trusted.map(titleCase)} empty="None." />
      </section>
    </div>
  )
}

function List({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="muted">{empty}</p>
  return (
    <ul className="tags">
      {items.map((item) => (
        <li key={item}>
          <code>{item}</code>
        </li>
      ))}
    </ul>
  )
}
