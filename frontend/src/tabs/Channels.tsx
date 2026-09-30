import { useAuth } from '@clerk/react'
import { useState, type FormEvent } from 'react'
import { api, post } from '../api'
import { PERSON, formatTime } from '../format'
import type { Decision, GmailMessage, Health, KinGuardState } from '../types'

type Withheld = { status: 'withheld'; reason: string }
type Intake = Decision | Withheld

type Props = {
  state: KinGuardState
  health: Health | null
  onChecked: (incidentId: string | null) => void
}

function describe(result: Intake): string {
  if ('status' in result && result.status === 'withheld') return `Not stored: ${result.reason}`
  const decision = result as Decision
  return decision.labels.threat === 'BENIGN' ? `Looks safe (${decision.incident_id})` : `Checked: alert ${decision.incident_id}`
}

export function Channels({ state, health, onChecked }: Props) {
  return (
    <div className="channels">
      <GmailCard enabled={Boolean(health?.gmail)} onChecked={onChecked} />
      <ShareCard onChecked={onChecked} />

      <section className="card">
        <h2>Blocked senders</h2>
        <p className="muted">Addresses and domains the mail filter now stops before they reach {PERSON.name}.</p>
        {state.world.flagged.length === 0 ? (
          <p className="muted">None yet.</p>
        ) : (
          <ul className="tags">
            {state.world.flagged.map((sender) => (
              <li key={sender}>
                <code>{sender}</code>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Other channels</h2>
        <ul className="status-list">
          <li>
            <span className={`dot ${health?.mailbox ? 'on' : ''}`} /> Forwarded inbox (IMAP){' '}
            <span className="muted">{health?.mailbox ? 'checking every few seconds' : 'off: set IMAP_HOST on the server'}</span>
          </li>
          <li>
            <span className="dot on" /> SMS and WhatsApp <span className="muted">shared by hand, below or from the phone</span>
          </li>
        </ul>
      </section>
    </div>
  )
}

function GmailCard({ enabled, onChecked }: { enabled: boolean; onChecked: (id: string | null) => void }) {
  const { getToken } = useAuth()
  const [messages, setMessages] = useState<GmailMessage[] | null>(null)
  const [results, setResults] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function authorised() {
    return { Authorization: `Bearer ${await getToken()}` }
  }

  async function load() {
    setBusy('list')
    setError('')
    try {
      setMessages(await api<GmailMessage[]>('/gmail/messages?max_results=15', { headers: await authorised() }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  async function check(id: string) {
    setBusy(id)
    setError('')
    try {
      const result = await post<Intake>(`/gmail/messages/${id}/intake`, undefined, await authorised())
      setResults((current) => ({ ...current, [id]: describe(result) }))
      onChecked('incident_id' in result ? result.incident_id : null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="card gmail">
      <div className="card-head">
        <div>
          <h2>Gmail</h2>
          <p className="muted">Read only. Pick an email to have KinGuard check it.</p>
        </div>
        <button type="button" className="button primary" onClick={load} disabled={!enabled || busy !== null}>
          {busy === 'list' ? 'Loading…' : messages ? 'Refresh' : 'Load recent emails'}
        </button>
      </div>
      {!enabled && <p className="banner tone-warn">Gmail is off: the server needs CLERK_SECRET_KEY.</p>}
      {error && <p className="error">{error}</p>}
      {messages && messages.length === 0 && <p className="muted">No emails found.</p>}
      {messages && messages.length > 0 && (
        <ul className="mail-list">
          {messages.map((message) => (
            <li key={message.id}>
              <div>
                <strong>{message.subject || '(no subject)'}</strong>
                <span className="muted">
                  {message.sender} · {formatTime(message.date) || message.date}
                </span>
                <p>{message.snippet}</p>
              </div>
              {results[message.id] ? (
                <span className="chip tone-ok">{results[message.id]}</span>
              ) : (
                <button type="button" className="button" onClick={() => check(message.id)} disabled={busy !== null}>
                  {busy === message.id ? 'Checking…' : 'Check'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ShareCard({ onChecked }: { onChecked: (id: string | null) => void }) {
  const [text, setText] = useState('')
  const [sender, setSender] = useState('')
  const [channel, setChannel] = useState('sms')
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setResult('')
    try {
      const outcome = await post<Intake>('/intake/share', { text, sender, channel })
      setResult(describe(outcome))
      setText('')
      onChecked('incident_id' in outcome ? outcome.incident_id : null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Check a message by hand</h2>
      <p className="muted">Paste an SMS or WhatsApp message {PERSON.name} received.</p>
      <form className="share" onSubmit={submit}>
        <label>
          Message
          <textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} required />
        </label>
        <div className="row">
          <label>
            From
            <input value={sender} onChange={(event) => setSender(event.target.value)} placeholder="YourBank" />
          </label>
          <label>
            Channel
            <select value={channel} onChange={(event) => setChannel(event.target.value)}>
              <option value="sms">SMS</option>
              <option value="whatsapp">WhatsApp</option>
            </select>
          </label>
        </div>
        <button type="submit" className="button primary" disabled={busy || !text.trim()}>
          {busy ? 'Checking…' : 'Check message'}
        </button>
      </form>
      {result && <p className="banner tone-ok">{result}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
