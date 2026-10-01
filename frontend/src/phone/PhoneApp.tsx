import { LocalNotifications } from '@capacitor/local-notifications'
import { useCallback, useEffect, useRef, useState } from 'react'
import { PERSON } from '../format'
import { SmsInbox, type PhoneSms } from './sms'
import './phone.css'

const FIRST_SYNC_DAYS = 7
const CHECK_EVERY_MS = 15000
const saved = {
  get: (key: string, fallback: string) => localStorage.getItem(`kinguard.${key}`) ?? fallback,
  set: (key: string, value: string) => localStorage.setItem(`kinguard.${key}`, value),
}

interface Warning {
  incident_id: string
  message: string
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

/** The protected person's phone: reads texts, sends them to the Scam Stop server, shows warnings and, with no guardian, asks them. */
export function PhoneApp() {
  const [server, setServer] = useState(() => saved.get('server', 'http://localhost:8000'))
  const [code, setCode] = useState(() => saved.get('pairing', '')) // from the dashboard: Devices → Pair the phone app
  const [draft, setDraft] = useState(code) // what is typed; it becomes the code only on "Pair this phone"
  const [person, setPerson] = useState('') // whose phone this is, as the server says
  const [personChecked, setPersonChecked] = useState(false) // nothing is sent until we know whose phone this is
  const [consented, setConsented] = useState(() => saved.get('consented', '') === 'yes')
  const [granted, setGranted] = useState(false)
  const [guardian, setGuardian] = useState(true)
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [questions, setQuestions] = useState<Question[]>([])
  const [disputes, setDisputes] = useState<Dispute[]>([])
  const [status, setStatus] = useState('')
  const [counts, setCounts] = useState({ checked: 0, kept: 0 })
  const [now, setNow] = useState(0)
  const filters = useRef<RegExp[]>([])

  /** Calls about this person go to /api/people/{id}/...; `shared` routes that hold no data stay at /api. */
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

  /** Never let a one-time code or password leave the phone: the server's own filter, applied here first. */
  const allowed = useCallback(async (messages: PhoneSms[]) => {
    if (filters.current.length === 0) {
      const patterns = await call<{ withhold: string[]; flags: string }>('/privacy/patterns', undefined, true)
      filters.current = patterns.withhold.map((pattern) => new RegExp(pattern, patterns.flags))
    }
    return messages.filter((sms) => sms.text.trim() && !filters.current.some((pattern) => pattern.test(sms.text)))
  }, [call])

  const send = useCallback(
    async (messages: PhoneSms[]) => {
      const kept = await allowed(messages)
      if (kept.length > 0) {
        await call('/intake/share/batch', kept.map((sms) => ({ text: sms.text, sender: sms.sender, channel: 'sms', timestamp: sms.timestamp })))
      }
      setCounts((before) => ({ checked: before.checked + kept.length, kept: before.kept + messages.length - kept.length }))
    },
    [allowed, call],
  )

  /** Send every text received since the last sync (the last week, the first time). */
  const sync = useCallback(async () => {
    try {
      const since = Number(saved.get('since', String(Date.now() - FIRST_SYNC_DAYS * 24 * 3600 * 1000)))
      const { messages } = await SmsInbox.getMessages({ since, limit: 200 })
      await send(messages)
      if (messages.length > 0) saved.set('since', String(messages[messages.length - 1].millis))
      setStatus(`Checked at ${new Date().toLocaleTimeString()}`)
    } catch (error) {
      setStatus(`Could not reach Scam Stop: ${error instanceof Error ? error.message : String(error)}`)
    }
  }, [send])

  /** Warnings, the person's own questions and any disputes to lodge; a notification for anything new. */
  const refresh = useCallback(async () => {
    try {
      const [outbox, pending, mine] = await Promise.all([
        call<Warning[]>('/outbox'),
        call<Question[]>('/person/reviews?status=PENDING'),
        call<{ guardian: boolean; disputes: Dispute[] }>('/person/state'),
      ])
      const warned = Number(saved.get('warned', '0'))
      for (const [index, warning] of outbox.slice(warned).entries()) {
        await LocalNotifications.schedule({ notifications: [{ id: warned + index + 1, title: 'Scam Stop', body: warning.message }] })
      }
      saved.set('warned', String(outbox.length))
      const asked = new Set(saved.get('asked', '').split(',').filter(Boolean))
      for (const question of pending.filter((item) => !asked.has(item.review_id))) {
        await LocalNotifications.schedule({ notifications: [{ id: 100000 + asked.size, title: 'Scam Stop needs your answer', body: askText(question) }] })
        asked.add(question.review_id)
      }
      saved.set('asked', [...asked].join(','))
      setWarnings([...outbox].reverse())
      setGuardian(mine.guardian)
      setQuestions(mine.guardian ? [] : pending)
      setDisputes(mine.disputes)
      setStatus((before) => (before.startsWith('Could not load') ? '' : before))
      setNow(Date.now())
    } catch (error) {
      setStatus(`Could not load warnings: ${error instanceof Error ? error.message : String(error)}`)
    }
  }, [call])

  async function agree(hasGuardian: boolean) {
    saved.set('consented', 'yes')
    setConsented(true)
    await call('/settings/guardian', { enrolled: hasGuardian }).catch(() => undefined)
    setGuardian(hasGuardian)
    const answer = await SmsInbox.requestAccess()
    setGranted(answer.granted)
    await LocalNotifications.requestPermissions()
  }

  async function answer(question: Question, approved: boolean) {
    try {
      await call(`/reviews/${question.review_id}/decision`, { approved })
      await refresh()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }

  async function changeGuardian(hasGuardian: boolean) {
    await call('/settings/guardian', { enrolled: hasGuardian }).catch(() => undefined)
    await refresh()
  }

  // Ask the server whose phone this is. Paired, the code names the person. Without a code (development
  // mode only) the first person the developer looks after is used.
  useEffect(() => {
    setPersonChecked(false)
    fetch(`${server}/api/me`, { headers: code ? { 'X-Device-Key': code } : {} })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 401 ? 'This pairing code is not accepted. Ask for a new one.' : `server answered ${response.status}`)
        return response.json()
      })
      .then((me: { person?: { id: string } | null; people?: { id: string }[] }) => {
        setPerson(me.person?.id ?? me.people?.[0]?.id ?? '')
        setStatus('')
      })
      .catch((error) => setStatus(error instanceof Error ? error.message : String(error)))
      .finally(() => setPersonChecked(true))
  }, [server, code])

  // On start: if consent was given before, check access quietly.
  useEffect(() => {
    if (!consented) return
    SmsInbox.requestAccess().then((access) => setGranted(access.granted))
  }, [consented])

  // Once access is granted: sync, then send each new text the moment it arrives.
  useEffect(() => {
    if (!granted || !personChecked) return
    const first = setTimeout(sync, 0)
    const listening = SmsInbox.addListener('smsReceived', (sms) => {
      send([sms]).then(() => saved.set('since', String(sms.millis))).catch(() => setStatus('Could not reach Scam Stop; will retry'))
    })
    return () => {
      clearTimeout(first)
      listening.then((handle) => handle.remove())
    }
  }, [granted, personChecked, send, sync])

  // Every few seconds: warnings, questions and disputes.
  useEffect(() => {
    if (!granted || !personChecked) return
    const timer = setInterval(refresh, CHECK_EVERY_MS)
    const first = setTimeout(refresh, 0)
    return () => {
      clearInterval(timer)
      clearTimeout(first)
    }
  }, [granted, personChecked, refresh])

  if (!consented) {
    return (
      <main className="phone">
        <p className="brand">Scam Stop</p>
        <h1>Hello {PERSON.name}</h1>
        <p>Scam Stop reads the text messages you receive and checks them for scams and unwanted debit orders.</p>
        <ul>
          <li>One-time PINs, passwords and recovery codes are never sent anywhere.</li>
          <li>Other texts are sent to your Scam Stop server to be checked.</li>
          <li>Scam Stop never sends, deletes or replies to a message.</li>
        </ul>
        <p>Is there someone in your family who should approve anything that touches your bank?</p>
        <button type="button" className="big" onClick={() => agree(true)}>
          I agree. My family will help
        </button>
        <button type="button" className="big secondary" onClick={() => agree(false)}>
          I agree. I will decide myself
        </button>
      </main>
    )
  }

  return (
    <main className="phone">
      <p className="brand">Scam Stop</p>
      <p className={granted ? 'state on' : 'state off'}>{granted ? 'Your messages are being watched' : 'Scam Stop needs permission to read your messages'}</p>
      {!granted && (
        <button type="button" className="big" onClick={() => agree(guardian)}>
          Allow access
        </button>
      )}

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

      <h2>Warnings</h2>
      {warnings.length === 0 ? <p className="muted">Nothing to worry about yet.</p> : warnings.map((warning, index) => (
        <p key={`${warning.incident_id}-${index}`} className="warning">{warning.message}</p>
      ))}

      <details>
        <summary>Settings</summary>
        <p>{guardian ? 'A family member approves anything that touches your bank.' : 'You decide yourself. Scam Stop asks you, and waits a day before undoing a warning.'}</p>
        {code ? (
          <p className="muted">Your family member can change this on the dashboard.</p>
        ) : (
          <button type="button" onClick={() => changeGuardian(!guardian)}>
            {guardian ? 'I will decide myself' : 'My family will help'}
          </button>
        )}
        <label>
          Scam Stop server
          <input value={server} onChange={(event) => { setServer(event.target.value); saved.set('server', event.target.value); filters.current = [] }} />
        </label>
        <label>
          Pairing code (from the dashboard: Devices → Pair the phone app)
          <input value={draft} autoCapitalize="characters" autoCorrect="off" onChange={(event) => setDraft(event.target.value)} />
        </label>
        <button type="button" onClick={() => { const next = draft.trim(); saved.set('pairing', next); setCode(next) }}>
          Pair this phone
        </button>
        <p className="muted">{person ? `Watching for ${person}` : 'Not linked to anyone yet.'}</p>
        <button type="button" onClick={sync}>Check now</button>
        <p className="muted">{status}</p>
        <p className="muted">{counts.checked} texts sent to be checked · {counts.kept} kept on the phone</p>
      </details>
    </main>
  )
}

function askText(question: Question): string {
  return question.proposed_action?.details.ask || question.reason
}
