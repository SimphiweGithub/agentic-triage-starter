import { LocalNotifications } from '@capacitor/local-notifications'
import { Check, Lock, MicOff, Phone, ShieldCheck, Users } from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { CALL_SCAMS, duration } from '../calls'
import { ROLE, type CircleRole } from '../circle'
import type { CallAnswer } from '../calls'
import { warnedAboutBin } from '../format'
import type { Review } from '../types'
import { answerCall, CallMonitor, type EndedCall } from './call-monitor'
import { SmsInbox, type BridgeStatus, type PhoneSms } from './sms'
import './phone.css'

const FIRST_SYNC_DAYS = 7
const saved = {
  get: (key: string, fallback: string) => {
    try {
      return localStorage.getItem(`kinguard.${key}`) ?? fallback
    } catch {
      return fallback
    }
  },
  set: (key: string, value: string) => {
    try {
      localStorage.setItem(`kinguard.${key}`, value)
    } catch {
      // Remembering is a convenience; the screen still works this time.
    }
  },
}

const ROLES: CircleRole[] = ['protected', 'next_of_kin', 'caregiver', 'helper']
const ROLE_PICK: Record<CircleRole, { title: string; text: string }> = {
  protected: { title: 'I’m being looked after', text: 'Big, simple screens. Warnings and call tips.' },
  next_of_kin: { title: 'I’m their next of kin', text: 'Family who approves anything about money.' },
  caregiver: { title: 'I’m their caregiver', text: 'Day-to-day help. See alerts, check in.' },
  helper: { title: 'I’m a trusted helper', text: 'A neighbour or friend for emergencies.' },
}

/** The phone app. Who holds the phone decides what it shows: the protected person gets the bridge and the call tips. */
export function PhoneApp() {
  const [role, setRole] = useState<CircleRole | null>(() => (ROLES.find((item) => item === saved.get('role', '')) ?? null))

  function choose(next: CircleRole | null) {
    saved.set('role', next ?? '')
    setRole(next)
  }

  if (!role) return <RolePicker onPick={choose} />
  if (role !== 'protected') return <HelperPhone role={role} onChangeRole={() => choose(null)} />
  return <ProtectedPhone onChangeRole={() => choose(null)} />
}

function Brand() {
  return (
    <p className="brand">
      <span className="brand-mark">
        <ShieldCheck aria-hidden="true" />
      </span>
      Scam Stop
    </p>
  )
}

function RolePicker({ onPick }: { onPick: (role: CircleRole) => void }) {
  const [picked, setPicked] = useState<CircleRole>('protected')
  return (
    <main className="phone">
      <Brand />
      <h1>Whose phone is this?</h1>
      <p className="lead">Pick the one that fits. The app changes to suit you.</p>
      <fieldset className="choices">
        <legend className="sr-only">Role</legend>
        {ROLES.map((role) => (
          <label key={role} className={picked === role ? 'choice picked' : 'choice'}>
            <input type="radio" name="role" checked={picked === role} onChange={() => setPicked(role)} />
            <span>
              <strong>{ROLE_PICK[role].title}</strong>
              <span className="muted">{ROLE_PICK[role].text}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <button type="button" className="big push" onClick={() => onPick(picked)}>
        Continue
      </button>
    </main>
  )
}

/** Family, carers and helpers use the dashboard; on their own phone the app only says where to go. */
function HelperPhone({ role, onChangeRole }: { role: CircleRole; onChangeRole: () => void }) {
  const server = saved.get('server', 'http://localhost:8000')
  return (
    <main className="phone">
      <Brand />
      <span className="chip">{ROLE[role].label}</span>
      <h1>Use the family dashboard</h1>
      <p className="lead">{ROLE[role].summary}</p>
      <p>Alerts, calls and decisions are on the dashboard. Open it in your phone’s browser and sign in.</p>
      <a className="big" href={server}>
        Open the dashboard
      </a>
      <button type="button" className="link push" onClick={onChangeRole}>
        This is not my role
      </button>
    </main>
  )
}

type View = 'home' | 'setup' | 'call'

/**
 * The phone of the person being looked after. Native code (SmsReceiver, NotificationBridge, Forwarder and the call
 * monitor) sends new texts, WhatsApp messages and unknown calls to the server with this app closed, and shows the
 * server's warnings as notifications. This screen sets that up, answers questions, and shows call scam tips.
 */
function ProtectedPhone({ onChangeRole }: { onChangeRole: () => void }) {
  const [server, setServer] = useState(() => saved.get('server', 'http://localhost:8000'))
  const [serverDraft, setServerDraft] = useState(server)
  const [code, setCode] = useState(() => saved.get('pairing', '')) // from the dashboard: Devices → Pair the phone app
  const [codeDraft, setCodeDraft] = useState(code)
  const [person, setPerson] = useState({ id: '', name: '' })
  const [bridge, setBridge] = useState<BridgeStatus | null>(null)
  const [callsAllowed, setCallsAllowed] = useState<boolean | null>(null)
  const [callsSkipped, setCallsSkipped] = useState(() => saved.get('calls-skipped', '') === '1')
  const [problem, setProblem] = useState('')
  const [view, setView] = useState<View>('home')
  const [call, setCall] = useState<EndedCall | null>(null)

  const checkBridge = useCallback(async () => {
    setBridge(await SmsInbox.bridgeStatus().catch(() => null))
    setCallsAllowed(await CallMonitor.status().then((status) => status.allowed).catch(() => null))
  }, [])
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
        setPerson({ id, name: me.person?.name ?? '' })
        await SmsInbox.configureBridge({ server, person: id, code, patterns: patterns.withhold })
        await backfill(server, id, code, patterns.withhold)
        setProblem('')
        await checkBridge()
      })
      .catch((error) => setProblem(error instanceof Error ? error.message : `Cannot reach the server: ${String(error)}`))
  }, [server, code, smsAllowed, checkBridge]) // again once texts are allowed, so the first week is sent

  // Re-check after returning from Android settings or a call notification, and every few seconds while open.
  useEffect(() => {
    const look = async () => {
      await checkBridge()
      const ended = await CallMonitor.takeEndedCall().catch(() => ({ call: null }))
      if (ended.call) {
        setCall(ended.call)
        setView('call')
      }
    }
    const first = setTimeout(look, 0)
    const back = () => document.visibilityState === 'visible' && look()
    document.addEventListener('visibilitychange', back)
    const timer = setInterval(checkBridge, 5000)
    return () => {
      clearTimeout(first)
      document.removeEventListener('visibilitychange', back)
      clearInterval(timer)
    }
  }, [checkBridge])

  async function allowTexts() {
    await SmsInbox.requestAccess().catch(() => undefined)
    await LocalNotifications.requestPermissions().catch(() => undefined) // for the warnings the bridge shows
    await checkBridge()
  }

  async function allowCalls() {
    const result = await CallMonitor.requestAccess().catch(() => null)
    if (!result) setProblem('This version of the app cannot watch calls yet. Ask for an update.')
    await checkBridge()
  }

  function skipCalls() {
    saved.set('calls-skipped', '1')
    setCallsSkipped(true)
  }

  const paired = Boolean(person.name && bridge?.configured)
  const messagesReady = paired && Boolean(bridge?.sms && bridge.notificationAccess)
  const ready = messagesReady && (callsAllowed === true || callsSkipped)
  const shown: View = view === 'call' ? 'call' : ready && view === 'home' ? 'home' : 'setup'

  if (shown === 'call') {
    return (
      <CallTips
        call={call}
        onAnswer={async (answer) => {
          if (call && answer) await answerCall(server, person.id, code, call.callId, answer).catch(() => undefined)
          setCall(null)
          setView('home')
        }}
      />
    )
  }

  if (shown === 'home') {
    return <ProtectedHome server={server} person={person} code={code} callsOn={callsAllowed === true} onScams={() => setView('call')} onSetup={() => setView('setup')} />
  }

  const steps = [paired, Boolean(bridge?.sms), Boolean(bridge?.notificationAccess), callsAllowed === true || callsSkipped]
  return (
    <main className="phone">
      <Brand />
      <p className="step-count">
        Step {Math.min(steps.filter(Boolean).length + 1, steps.length)} of {steps.length}
      </p>
      <h1>Switch protection on</h1>
      <div className="progress" aria-hidden="true">
        {steps.map((done, index) => (
          <span key={index} className={done ? 'on' : ''} />
        ))}
      </div>

      <ol className="steps">
        <Step done={paired} title={paired ? `Paired with ${person.name}’s circle` : 'Pair with the family dashboard'}>
          {!paired && (
            <>
              <label>
                Pairing code (dashboard → Devices → Pair the phone app)
                <input value={codeDraft} autoCapitalize="characters" autoCorrect="off" onChange={(event) => setCodeDraft(event.target.value)} />
              </label>
              <button
                type="button"
                className="big"
                onClick={() => {
                  const next = codeDraft.trim()
                  saved.set('pairing', next)
                  setCode(next)
                }}
              >
                Pair this phone
              </button>
            </>
          )}
        </Step>
        <Step done={Boolean(bridge?.sms)} title={bridge?.sms ? 'Texts checked' : 'Allow texts and notifications'} note="PINs and codes never leave the phone">
          {!bridge?.sms && (
            <button type="button" className="big" onClick={allowTexts}>
              Allow
            </button>
          )}
        </Step>
        <Step done={Boolean(bridge?.notificationAccess)} title={bridge?.notificationAccess ? 'WhatsApp checked' : 'Allow WhatsApp to be checked'} note="Android asks on its own screen: find Scam Stop in the list and switch it on">
          {!bridge?.notificationAccess && (
            <button type="button" className="big" onClick={() => SmsInbox.openNotificationAccess().catch(() => undefined)}>
              Open Android settings
            </button>
          )}
        </Step>
        <li className={callsAllowed ? 'step done' : 'step feature'}>
          <div className="step-head">
            <span className="step-icon">{callsAllowed ? <Check aria-hidden="true" /> : <Phone aria-hidden="true" />}</span>
            <strong>{callsAllowed ? 'Help after phone calls is on' : 'Help after phone calls'}</strong>
          </div>
          {!callsAllowed && (
            <>
              <p>When a number you don’t know calls you, Scam Stop shows you the tricks scam callers use, right after you hang up.</p>
              <ul className="promises">
                <li>
                  <MicOff aria-hidden="true" />
                  <span>
                    <strong>Never listens to or records</strong> what anyone says
                  </span>
                </li>
                <li>
                  <Users aria-hidden="true" />
                  <span>Calls from your contacts are ignored</span>
                </li>
                <li>
                  <Lock aria-hidden="true" />
                  <span>Only the number, time and length are shared with your circle</span>
                </li>
              </ul>
              <button type="button" className="big" onClick={allowCalls}>
                Allow call alerts
              </button>
              <p className="muted">Android will ask to let Scam Stop see phone calls and your contacts.</p>
              {!callsSkipped && (
                <button type="button" className="link" onClick={skipCalls}>
                  Not now
                </button>
              )}
            </>
          )}
        </li>
      </ol>

      {bridge && paired && (
        <p className="muted">
          {bridge.sent} messages forwarded{bridge.lastSent ? `, last at ${new Date(bridge.lastSent).toLocaleTimeString()}` : ''}
          {bridge.queued > 0 ? ` · ${bridge.queued} waiting for the server` : ''}
        </p>
      )}
      {(problem || bridge?.lastError) && <p className="warning">{problem || `Last problem: ${bridge?.lastError}`}</p>}
      {ready && (
        <button type="button" className="big" onClick={() => setView('home')}>
          Done
        </button>
      )}

      <details>
        <summary>Server</summary>
        <label>
          Scam Stop server address
          <input value={serverDraft} autoCapitalize="none" autoCorrect="off" onChange={(event) => setServerDraft(event.target.value)} />
        </label>
        <button
          type="button"
          onClick={() => {
            const next = serverDraft.trim().replace(/\/$/, '')
            saved.set('server', next)
            setServer(next)
          }}
        >
          Save
        </button>
        <button type="button" className="link" onClick={onChangeRole}>
          This is not my phone
        </button>
      </details>
    </main>
  )
}

function Step({ done, title, note, children }: { done: boolean; title: string; note?: string; children?: ReactNode }) {
  return (
    <li className={done ? 'step done' : 'step'}>
      <div className="step-head">
        <span className="step-icon">{done ? <Check aria-hidden="true" /> : null}</span>
        <span className="step-text">
          <strong>{title}</strong>
          {note && <span className="muted">{note}</span>}
        </span>
      </div>
      {!done && children}
    </li>
  )
}

/** After a call from an unknown number: the common call scams, and three big answers. Without a call it is the plain list. */
function CallTips({ call, onAnswer }: { call: EndedCall | null; onAnswer: (answer: CallAnswer) => void }) {
  return (
    <main className="phone">
      {call ? (
        <p className="lead">
          Call from <span className="mono">{call.number}</span> · {duration(call.seconds)}
        </p>
      ) : (
        <Brand />
      )}
      <h1>{call ? 'Did the caller do any of these?' : 'Common phone scams'}</h1>
      <ol className="tips">
        {CALL_SCAMS.map((scam, index) => (
          <li key={scam.title}>
            <span className="tip-number">{index + 1}</span>
            <span>
              <strong>{scam.title}</strong>
              <span className="tip-text">{scam.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="rule">
        <ShieldCheck aria-hidden="true" />
        <span>
          <strong>Your bank will never ask for a PIN or code.</strong> Unsure? Hang up and call the number on the back of your card.
        </span>
      </p>
      {call ? (
        <div className="answers push">
          <button type="button" className="big danger" onClick={() => onAnswer('asked_code')}>
            They asked for a PIN or code
          </button>
          <div className="row">
            <button type="button" className="big secondary" onClick={() => onAnswer('told_kin')}>
              Tell my family
            </button>
            <button type="button" className="big secondary" onClick={() => onAnswer('known')}>
              Someone I know
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className="big secondary push" onClick={() => onAnswer(null)}>
          Back
        </button>
      )}
    </main>
  )
}

type Warning = { incident_id: string; message: string }

/** Home for the person being looked after: that they are protected, one question at a time, and the call scams. */
function ProtectedHome({ server, person, code, callsOn, onScams, onSetup }: { server: string; person: { id: string; name: string }; code: string; callsOn: boolean; onScams: () => void; onSetup: () => void }) {
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [busy, setBusy] = useState(false)
  const base = `${server}/api/people/${encodeURIComponent(person.id)}`
  const headers = { 'Content-Type': 'application/json', 'X-Device-Key': code }

  const load = useCallback(async () => {
    const get = <T,>(path: string) => fetch(`${base}${path}`, { headers: { 'X-Device-Key': code } }).then((response) => (response.ok ? (response.json() as Promise<T>) : Promise.reject()))
    const [nextWarnings, nextReviews] = await Promise.all([get<Warning[]>('/outbox').catch(() => []), get<Review[]>('/person/reviews?status=PENDING').catch(() => [])])
    setWarnings([...new Map(nextWarnings.map((item) => [item.incident_id, item])).values()])
    setReviews(nextReviews)
  }, [base, code])

  useEffect(() => {
    const first = setTimeout(load, 0)
    const timer = setInterval(load, 15000)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [load])

  async function send(path: string, body: unknown) {
    setBusy(true)
    try {
      await fetch(`${base}${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
      await load()
    } finally {
      setBusy(false)
    }
  }

  const review = reviews[0]
  const warning = review ? undefined : warnings[0]
  const name = person.name.split(' ')[0]
  return (
    <main className="phone">
      <div className="safe">
        <span className="safe-mark">
          <ShieldCheck aria-hidden="true" />
        </span>
        <span>
          <strong>You’re protected{name ? `, ${name}` : ''}</strong>
          <span>{callsOn ? 'Texts, WhatsApp, email and calls' : 'Texts, WhatsApp and email'}</span>
        </span>
      </div>

      {review && (
        <section className="question" aria-labelledby="question">
          <span className="question-label">{reviews.length === 1 ? '1 question for you' : `${reviews.length} questions for you`}</span>
          <h2 id="question">{typeof review.proposed_action?.details.ask === 'string' ? review.proposed_action.details.ask : review.reason}</h2>
          <div className="row">
            <button type="button" className="big secondary" disabled={busy} onClick={() => send(`/reviews/${review.review_id}/decision`, { approved: true })}>
              Yes
            </button>
            <button type="button" className="big danger" disabled={busy} onClick={() => send(`/reviews/${review.review_id}/decision`, { approved: false })}>
              No
            </button>
          </div>
          <span className="muted">Your family will see your answer.</span>
        </section>
      )}

      {warning && (
        <section className="question" aria-labelledby="warning">
          <span className="question-label">A warning for you</span>
          <h2 id="warning">{warning.message}</h2>
          <div className="row">
            <button type="button" className="big secondary" disabled={busy} onClick={() => send(`/incidents/${warning.incident_id}/feedback`, { legitimate: true })}>
              This is mine
            </button>
            <button type="button" className="big danger" disabled={busy} onClick={() => send(`/incidents/${warning.incident_id}/feedback`, { legitimate: false })}>
              I didn’t agree
            </button>
          </div>
          {warnedAboutBin(warning.message) && <span className="muted">If this email is really yours, “This is mine” puts it back in your inbox.</span>}
        </section>
      )}

      {!review && !warning && <p className="lead">Nothing needs you. Scam Stop is watching quietly.</p>}

      <button type="button" className="big secondary" onClick={onScams}>
        <Phone aria-hidden="true" /> Common phone scams
      </button>
      <button type="button" className="link push" onClick={onSetup}>
        Settings and setup
      </button>
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
