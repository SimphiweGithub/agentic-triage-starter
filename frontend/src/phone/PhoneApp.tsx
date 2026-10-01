import { LocalNotifications } from '@capacitor/local-notifications'
import { useCallback, useEffect, useState } from 'react'
import { SmsInbox, type BridgeStatus, type PhoneSms } from './sms'
import './phone.css'

const FIRST_SYNC_DAYS = 7
const saved = {
  get: (key: string, fallback: string) => localStorage.getItem(`kinguard.${key}`) ?? fallback,
  set: (key: string, value: string) => localStorage.setItem(`kinguard.${key}`, value),
}

/**
 * The phone is only a bridge. Once paired and allowed, native code (SmsReceiver, NotificationBridge,
 * Forwarder) sends every new text and WhatsApp message to the Scam Stop server with this app closed,
 * and shows the server's warnings as notifications. Everything else happens on the dashboard.
 * This screen only sets the bridge up and shows whether it is working.
 */
export function PhoneApp() {
  const [server, setServer] = useState(() => saved.get('server', 'http://localhost:8000'))
  const [serverDraft, setServerDraft] = useState(server)
  const [code, setCode] = useState(() => saved.get('pairing', '')) // from the dashboard: Devices → Pair the phone app
  const [codeDraft, setCodeDraft] = useState(code)
  const [person, setPerson] = useState('')
  const [bridge, setBridge] = useState<BridgeStatus | null>(null)
  const [problem, setProblem] = useState('')

  const checkBridge = useCallback(async () => setBridge(await SmsInbox.bridgeStatus().catch(() => null)), [])
  const smsAllowed = Boolean(bridge?.sms)

  // Pair: learn whose phone this is, then hand server, person, code and the privacy filter to the native bridge.
  useEffect(() => {
    if (!code) return
    const headers = { 'X-Device-Key': code }
    Promise.all([
      fetch(`${server}/api/me`, { headers }).then(async (response) => {
        if (!response.ok) throw new Error(response.status === 401 ? 'This pairing code is not accepted. Ask for a new one on the dashboard.' : `The server answered ${response.status}`)
        return response.json() as Promise<{ person: { id: string; name: string } | null }>
      }),
      fetch(`${server}/api/privacy/patterns`).then((response) => response.json() as Promise<{ withhold: string[] }>),
    ])
      .then(async ([me, patterns]) => {
        const id = me.person?.id ?? ''
        setPerson(me.person?.name ?? '')
        await SmsInbox.configureBridge({ server, person: id, code, patterns: patterns.withhold })
        await backfill(server, id, code, patterns.withhold)
        setProblem('')
        await checkBridge()
      })
      .catch((error) => setProblem(error instanceof Error ? error.message : `Cannot reach the server: ${String(error)}`))
  }, [server, code, smsAllowed, checkBridge]) // again once texts are allowed, so the first week is sent

  // Re-check after returning from Android settings, and every few seconds while the screen is open.
  useEffect(() => {
    checkBridge()
    const back = () => document.visibilityState === 'visible' && checkBridge()
    document.addEventListener('visibilitychange', back)
    const timer = setInterval(checkBridge, 5000)
    return () => {
      document.removeEventListener('visibilitychange', back)
      clearInterval(timer)
    }
  }, [checkBridge])

  async function allowTexts() {
    await SmsInbox.requestAccess()
    await LocalNotifications.requestPermissions() // for the warnings the bridge shows
    await checkBridge()
  }

  const paired = Boolean(person && bridge?.configured)
  const ready = paired && Boolean(bridge?.sms && bridge.notificationAccess)

  return (
    <main className="phone">
      <p className="brand">Scam Stop</p>
      <p className={ready ? 'state on' : 'state off'}>
        {ready ? `Protecting ${person}'s texts and WhatsApp. You can close this app.` : 'Finish the steps below to switch protection on'}
      </p>

      <ol className="steps">
        <li className={paired ? 'done' : ''}>
          <strong>{paired ? `Paired with ${person}` : 'Pair with the family dashboard'}</strong>
          <label>
            Pairing code (dashboard → Devices → Pair the phone app)
            <input value={codeDraft} autoCapitalize="characters" autoCorrect="off" onChange={(event) => setCodeDraft(event.target.value)} />
          </label>
          <button type="button" onClick={() => { const next = codeDraft.trim(); saved.set('pairing', next); setCode(next) }}>
            {paired ? 'Pair again' : 'Pair this phone'}
          </button>
        </li>
        <li className={bridge?.sms ? 'done' : ''}>
          <strong>Allow texts and notifications</strong>
          <p className="muted">One-time PINs, passwords and recovery codes never leave the phone. Scam Stop never sends, deletes or answers a message.</p>
          {!bridge?.sms && <button type="button" onClick={allowTexts}>Allow</button>}
        </li>
        <li className={bridge?.notificationAccess ? 'done' : ''}>
          <strong>Allow WhatsApp to be checked</strong>
          <p className="muted">Android asks on its own screen: find Scam Stop in the list and switch it on.</p>
          {!bridge?.notificationAccess && <button type="button" onClick={() => SmsInbox.openNotificationAccess()}>Open Android settings</button>}
        </li>
      </ol>

      {bridge && paired && (
        <p className="muted">
          {bridge.sent} messages forwarded{bridge.lastSent ? `, last at ${new Date(bridge.lastSent).toLocaleTimeString()}` : ''}
          {bridge.queued > 0 ? ` · ${bridge.queued} waiting for the server` : ''}
        </p>
      )}
      {(problem || bridge?.lastError) && <p className="warning">{problem || `Last problem: ${bridge?.lastError}`}</p>}

      <details>
        <summary>Server</summary>
        <label>
          Scam Stop server address
          <input value={serverDraft} autoCapitalize="none" autoCorrect="off" onChange={(event) => setServerDraft(event.target.value)} />
        </label>
        <button type="button" onClick={() => { const next = serverDraft.trim().replace(/\/$/, ''); saved.set('server', next); setServer(next) }}>
          Save
        </button>
      </details>
    </main>
  )
}

/** Once per person: the last week of texts, so the dashboard starts with history. New messages are the bridge's job. */
async function backfill(server: string, person: string, code: string, withhold: string[]) {
  if (!person || saved.get('backfilled', '') === person) return
  const access = await SmsInbox.requestAccess()
  if (!access.granted) return
  const { messages } = await SmsInbox.getMessages({ since: Date.now() - FIRST_SYNC_DAYS * 24 * 3600 * 1000, limit: 200 })
  const filters = withhold.map((pattern) => new RegExp(pattern, 'i'))
  const kept = messages.filter((sms: PhoneSms) => sms.text.trim() && !filters.some((pattern) => pattern.test(sms.text)))
  if (kept.length > 0) {
    const response = await fetch(`${server}/api/people/${encodeURIComponent(person)}/intake/share/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Device-Key': code },
      body: JSON.stringify(kept.map((sms) => ({ text: sms.text, sender: sms.sender, channel: 'sms', timestamp: sms.timestamp }))),
    })
    if (!response.ok) return
  }
  saved.set('backfilled', person)
}
