import { LocalNotifications } from '@capacitor/local-notifications'
import { useCallback, useEffect, useState } from 'react'
import { PERSON } from '../format'
import { SmsInbox, type BridgeStatus, type PhoneSms } from './sms'
import './phone.css'

const FIRST_SYNC_DAYS = 7
const CHECK_EVERY_MS = 15000
const saved = {
  get: (key: string, fallback: string) => localStorage.getItem(`kinguard.${key}`) ?? fallback,
  set: (key: string, value: string) => localStorage.setItem(`kinguard.${key}`, value),
}

/** A decision the server is asking the person to make themselves, when no guardian is enrolled. */
interface Question {
  review_id: string
  reason: string
  not_before: string | null
  proposed_action: { type: string; details: { ask?: string } } | null
}

interface Dispute {
  text: string
  dispute_by: string
  steps: string[]
}

/**
 * The phone is a bridge. Once paired and allowed, the native code forwards every new text and chat
 * message to the server by itself, with this app closed, and shows the warnings the server sends back.
 * This screen is for setting that up, and for the few things only the person can do: answer their own
 * questions when no family member is enrolled, and see disputes to lodge. The dashboard does the rest.
 */
export function PhoneApp() {
  const [server, setServer] = useState(() => saved.get('server', 'http://localhost:8000'))
  const [code, setCode] = useState(() => saved.get('pairing', '')) // from the dashboard: Devices → Pair the phone app
  const [draft, setDraft] = useState(code)
  const [person, setPerson] = useState('')
  const [bridge, setBridge] = useState<BridgeStatus | null>(null)
  const [guardian, setGuardian] = useState(true)
  const [questions, setQuestions] = useState<Question[]>([])
  const [disputes, setDisputes] = useState<Dispute[]>([])
  const [status, setStatus] = useState('')
  const [now, setNow] = useState(0)

  const call = useCallback(
    async <T,>(path: string, body?: unknown, shared = false): Promise<T> => {
      const base = person && !shared ? `${server}/api/people/${encodeURIComponent(person)}` : `${server}/api`
      const response = await fetch(`${base}${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json', ...(code ? { 'X-Device-Key': code } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const answer = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(typeof answer.detail === 'string' ? answer.detail : `server answered ${response.status}`)
      return answer as T
    },
    [server, person, code],
  )

  const checkBridge = useCallback(async () => setBridge(await SmsInbox.bridgeStatus().catch(() => null)), [])

  // Pair: learn whose phone this is, then hand the server, person, code and privacy filter to the native bridge.
  useEffect(() => {
    if (!code) return
    const headers = { 'X-Device-Key': code }
    Promise.all([
      fetch(`${server}/api/me`, { headers }).then(async (response) => {
        if (!response.ok) throw new Error(response.status === 401 ? 'This pairing code is not accepted. Ask for a new one.' : `server answered ${response.status}`)
        return response.json() as Promise<{ person: { id: string } | null }>
      }),
      fetch(`${server}/api/privacy/patterns`).then((response) => response.json() as Promise<{ withhold: string[] }>),
    ])
      .then(async ([me, patterns]) => {
        const id = me.person?.id ?? ''
        setPerson(id)
        await SmsInbox.configureBridge({ server, person: id, code, patterns: patterns.withhold })
        setStatus('')
        await checkBridge()
      })
      .catch((error) => setStatus(error instanceof Error ? error.message : String(error)))
  }, [server, code, checkBridge])

  /** The last week of texts, once, so the dashboard starts with history. New texts are the bridge's job. */
  const backfill = useCallback(async () => {
    if (!person || saved.get('backfilled', '') === person) return
    const { messages } = await SmsInbox.getMessages({ since: Date.now() - FIRST_SYNC_DAYS * 24 * 3600 * 1000, limit: 200 })
    const filters = (await call<{ withhold: string[]; flags: string }>('/privacy/patterns', undefined, true)).withhold.map((pattern) => new RegExp(pattern, 'i'))
    const kept = messages.filter((sms: PhoneSms) => sms.text.trim() && !filters.some((pattern) => pattern.test(sms.text)))
    if (kept.length > 0) {
      await call('/intake/share/batch', kept.map((sms) => ({ text: sms.text, sender: sms.sender, channel: 'sms', timestamp: sms.timestamp })))
    }
    saved.set('backfilled', person)
  }, [person, call])

  /** The person's own questions and disputes. Warnings arrive as notifications from the bridge itself. */
  const refresh = useCallback(async () => {
    if (!person) return
    try {
      const [pending, mine] = await Promise.all([
        call<Question[]>('/person/reviews?status=PENDING'),
        call<{ guardian: boolean; disputes: Dispute[] }>('/person/state'),
      ])
      const asked = new Set(saved.get('asked', '').split(',').filter(Boolean))
      for (const question of pending.filter((item) => !asked.has(item.review_id))) {
        await LocalNotifications.schedule({ notifications: [{ id: 100000 + asked.size, title: 'Scam Stop needs your answer', body: askText(question) }] })
        asked.add(question.review_id)
      }
      saved.set('asked', [...asked].join(','))
      setGuardian(mine.guardian)
      setQuestions(mine.guardian ? [] : pending)
      setDisputes(mine.disputes)
      setNow(Date.now())
      await checkBridge()
    } catch (error) {
      setStatus(`Could not reach Scam Stop: ${error instanceof Error ? error.message : String(error)}`)
    }
  }, [person, call, checkBridge])

  useEffect(() => {
    if (!person) return
    backfill().catch(() => undefined)
    const timer = setInterval(refresh, CHECK_EVERY_MS)
    const first = setTimeout(refresh, 0)
    return () => {
      clearInterval(timer)
      clearTimeout(first)
    }
  }, [person, backfill, refresh])

  useEffect(() => {
    checkBridge()
    const back = () => document.visibilityState === 'visible' && checkBridge()  // after returning from Android settings
    document.addEventListener('visibilitychange', back)
    return () => document.removeEventListener('visibilitychange', back)
  }, [checkBridge])

  async function allowTexts() {
    await SmsInbox.requestAccess()
    await LocalNotifications.requestPermissions()
    await checkBridge()
  }

  async function answer(question: Question, approved: boolean) {
    try {
      await call(`/reviews/${question.review_id}/decision`, { approved })
      await refresh()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }

  const ready = Boolean(bridge?.configured && bridge.sms && bridge.notificationAccess)

  return (
    <main className="phone">
      <p className="brand">Scam Stop</p>
      <p className={ready ? 'state on' : 'state off'}>
        {ready ? `Protecting ${PERSON.name}'s texts and WhatsApp. You can close this app.` : 'Finish the steps below to switch protection on'}
      </p>

      <h2>Set up</h2>
      <ol className="steps">
        <li className={person ? 'done' : ''}>
          <strong>Pair with the family dashboard</strong>
          <label>
            Pairing code (dashboard → Devices → Pair the phone app)
            <input value={draft} autoCapitalize="characters" autoCorrect="off" onChange={(event) => setDraft(event.target.value)} />
          </label>
          <button type="button" onClick={() => { const next = draft.trim(); saved.set('pairing', next); setCode(next) }}>
            {person ? 'Paired. Pair again' : 'Pair this phone'}
          </button>
        </li>
        <li className={bridge?.sms ? 'done' : ''}>
          <strong>Allow texts and notifications</strong>
          <p className="muted">One-time PINs, passwords and recovery codes never leave the phone. Scam Stop never sends, deletes or answers a message.</p>
          {!bridge?.sms && <button type="button" onClick={allowTexts}>Allow</button>}
        </li>
        <li className={bridge?.notificationAccess ? 'done' : ''}>
          <strong>Allow WhatsApp to be checked</strong>
          <p className="muted">Android asks for this on its own screen: find Scam Stop in the list and switch it on.</p>
          {!bridge?.notificationAccess && <button type="button" onClick={() => SmsInbox.openNotificationAccess()}>Open Android settings</button>}
        </li>
      </ol>

      {questions.length > 0 && (
        <>
          <h2>Needs your answer</h2>
          {questions.map((question) => {
            const waitUntil = question.not_before ? new Date(question.not_before) : null
            const waiting = waitUntil !== null && waitUntil.getTime() > now
            return (
              <div key={question.review_id} className="question">
                <p>{askText(question)}</p>
                {waiting && <p className="muted">To keep you safe, you can say yes after {waitUntil.toLocaleString()}. Nobody can rush you.</p>}
                <div className="row">
                  <button type="button" className="big" disabled={waiting} onClick={() => answer(question, true)}>Yes</button>
                  <button type="button" className="big secondary" onClick={() => answer(question, false)}>No</button>
                </div>
              </div>
            )
          })}
        </>
      )}

      {disputes.length > 0 && (
        <>
          <h2>Disputes to lodge with your bank</h2>
          {disputes.map((dispute) => (
            <div key={dispute.text} className="question">
              <p>{dispute.text}</p>
              {dispute.dispute_by && <p><strong>Lodge it before {dispute.dispute_by}.</strong></p>}
              <ol>{dispute.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            </div>
          ))}
        </>
      )}

      <details>
        <summary>Status</summary>
        <p className="muted">{guardian ? 'A family member approves anything that touches your bank.' : 'You decide yourself. Scam Stop asks you, and waits a day before undoing a warning.'}</p>
        {bridge && (
          <p className="muted">
            {bridge.sent} messages checked{bridge.lastSent ? `, last at ${new Date(bridge.lastSent).toLocaleTimeString()}` : ''}
            {bridge.queued > 0 ? ` · ${bridge.queued} waiting for the server` : ''}
            {bridge.lastError ? ` · last problem: ${bridge.lastError}` : ''}
          </p>
        )}
        <label>
          Scam Stop server
          <input value={server} onChange={(event) => { setServer(event.target.value); saved.set('server', event.target.value) }} />
        </label>
        <p className="muted">{status}</p>
      </details>
    </main>
  )
}

function askText(question: Question): string {
  return question.proposed_action?.details.ask || question.reason
}
