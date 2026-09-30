import { LocalNotifications } from '@capacitor/local-notifications'
import { useCallback, useEffect, useRef, useState } from 'react'
import { PERSON } from '../format'
import { SmsInbox, type PhoneSms } from './sms'
import './phone.css'

const FIRST_SYNC_DAYS = 7
const OUTBOX_EVERY_MS = 15000
const saved = {
  get: (key: string, fallback: string) => localStorage.getItem(`kinguard.${key}`) ?? fallback,
  set: (key: string, value: string) => localStorage.setItem(`kinguard.${key}`, value),
}

interface Warning {
  incident_id: string
  message: string
}

/** The protected person's phone: reads texts, sends them to the KinGuard server, and shows its warnings. */
export function PhoneApp() {
  const [server, setServer] = useState(() => saved.get('server', 'http://localhost:8000'))
  const [consented, setConsented] = useState(() => saved.get('consented', '') === 'yes')
  const [granted, setGranted] = useState(false)
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [status, setStatus] = useState('')
  const [counts, setCounts] = useState({ checked: 0, kept: 0 })
  const filters = useRef<RegExp[]>([])

  const call = useCallback(
    async <T,>(path: string, body?: unknown): Promise<T> => {
      const response = await fetch(`${server}/api${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      if (!response.ok) throw new Error(`server answered ${response.status}`)
      return (await response.json()) as T
    },
    [server],
  )

  /** Never let a one-time code or password leave the phone: the server's own filter, applied here first. */
  const allowed = useCallback(async (messages: PhoneSms[]) => {
    if (filters.current.length === 0) {
      const patterns = await call<{ withhold: string[]; flags: string }>('/privacy/patterns')
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
      setStatus(`Could not reach KinGuard: ${error instanceof Error ? error.message : String(error)}`)
    }
  }, [send])

  async function agree() {
    saved.set('consented', 'yes')
    setConsented(true)
    const answer = await SmsInbox.requestAccess()
    setGranted(answer.granted)
    await LocalNotifications.requestPermissions()
  }

  // On start: if consent was given before, check access quietly and do a first sync.
  useEffect(() => {
    if (!consented) return
    SmsInbox.requestAccess().then((answer) => setGranted(answer.granted))
  }, [consented])

  // Once access is granted: sync, then send each new text the moment it arrives.
  useEffect(() => {
    if (!granted) return
    const first = setTimeout(sync, 0)
    const listening = SmsInbox.addListener('smsReceived', (sms) => {
      send([sms]).then(() => saved.set('since', String(sms.millis))).catch(() => setStatus('Could not reach KinGuard; will retry'))
    })
    return () => {
      clearTimeout(first)
      listening.then((handle) => handle.remove())
    }
  }, [granted, send, sync])

  // Every few seconds: fetch the warnings, and notify for any that are new.
  useEffect(() => {
    if (!granted) return
    const check = async () => {
      try {
        const all = await call<Warning[]>('/outbox')
        const seen = Number(saved.get('warned', '0'))
        for (const [index, warning] of all.slice(seen).entries()) {
          await LocalNotifications.schedule({ notifications: [{ id: seen + index + 1, title: 'KinGuard', body: warning.message }] })
        }
        saved.set('warned', String(all.length))
        setWarnings([...all].reverse())
      } catch {
        // the sync status already says when the server cannot be reached
      }
    }
    const timer = setInterval(check, OUTBOX_EVERY_MS)
    const first = setTimeout(check, 0)
    return () => {
      clearInterval(timer)
      clearTimeout(first)
    }
  }, [granted, call])

  if (!consented) {
    return (
      <main className="phone">
        <p className="brand">KinGuard</p>
        <h1>Hello {PERSON.name}</h1>
        <p>KinGuard reads the text messages you receive and checks them for scams and unwanted debit orders.</p>
        <ul>
          <li>One-time PINs, passwords and recovery codes are never sent anywhere.</li>
          <li>Other texts are sent to your family's KinGuard server to be checked.</li>
          <li>KinGuard never sends, deletes or replies to a message.</li>
        </ul>
        <button type="button" className="big" onClick={agree}>
          I agree, protect my messages
        </button>
      </main>
    )
  }

  return (
    <main className="phone">
      <p className="brand">KinGuard</p>
      <p className={granted ? 'state on' : 'state off'}>{granted ? 'Your messages are being watched' : 'KinGuard needs permission to read your messages'}</p>
      {!granted && (
        <button type="button" className="big" onClick={agree}>
          Allow access
        </button>
      )}
      <h2>Warnings</h2>
      {warnings.length === 0 ? <p className="muted">Nothing to worry about yet.</p> : warnings.map((warning, index) => (
        <p key={`${warning.incident_id}-${index}`} className="warning">{warning.message}</p>
      ))}
      <details>
        <summary>Settings</summary>
        <label>
          KinGuard server
          <input value={server} onChange={(event) => { setServer(event.target.value); saved.set('server', event.target.value); filters.current = [] }} />
        </label>
        <button type="button" onClick={sync}>Check now</button>
        <p className="muted">{status}</p>
        <p className="muted">{counts.checked} texts sent to be checked · {counts.kept} kept on the phone</p>
      </details>
    </main>
  )
}
