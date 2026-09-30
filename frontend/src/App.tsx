import { ClerkLoading, Show, SignInButton, SignUpButton, UserButton } from '@clerk/react'
import { useEffect, useState } from 'react'
import './App.css'
import { useKinGuard } from './api'
import { PERSON } from './format'
import { Alerts } from './tabs/Alerts'
import { AuditTrail } from './tabs/AuditTrail'
import { Channels } from './tabs/Channels'
import { Subscriptions } from './tabs/Subscriptions'

const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'channels', label: 'Protected channels' },
  { id: 'subscriptions', label: 'Subscriptions' },
  { id: 'audit', label: 'Audit trail' },
] as const

type TabId = (typeof TABS)[number]['id']

function tabFromHash(): TabId {
  const hash = window.location.hash.slice(1)
  return TABS.some((tab) => tab.id === hash) ? (hash as TabId) : 'alerts'
}

function App() {
  return (
    <>
      <ClerkLoading>
        <p className="empty muted">Loading KinGuard…</p>
      </ClerkLoading>
      <Show when="signed-out">
        <SignedOutScreen />
      </Show>
      <Show when="signed-in">
        <Dashboard />
      </Show>
    </>
  )
}

function SignedOutScreen() {
  return (
    <main className="signed-out">
      <div className="card">
        <p className="brand">KinGuard</p>
        <h1>Watch over {PERSON.name}'s messages and money</h1>
        <p className="muted">
          Scam messages, predatory debit orders and creeping subscriptions are caught and explained. Anything that touches the bank waits
          for you.
        </p>
        <div className="row">
          <SignInButton>
            <button type="button" className="button primary">
              Sign in
            </button>
          </SignInButton>
          <SignUpButton>
            <button type="button" className="button">
              Create an account
            </button>
          </SignUpButton>
        </div>
      </div>
    </main>
  )
}

function Dashboard() {
  const { state, health, error, refresh } = useKinGuard()
  const [tab, setTab] = useState<TabId>(tabFromHash)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  function go(next: TabId) {
    window.history.pushState(null, '', `#${next}`)
    setTab(next)
  }

  function openAlert(incidentId: string | null) {
    if (incidentId) setSelectedId(incidentId)
    refresh()
  }

  const waiting = state?.incidents.filter((item) => item.status === 'PENDING_REVIEW').length ?? 0

  return (
    <div className="shell">
      <header className="topbar">
        <nav className="tabs" aria-label="Sections">
          {TABS.map((item) => (
            <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} aria-current={tab === item.id ? 'page' : undefined} onClick={() => go(item.id)}>
              {item.label}
              {item.id === 'alerts' && waiting > 0 && <span className="count">{waiting}</span>}
            </button>
          ))}
        </nav>
        <div className="people">
          <span className="person active">
            <span className="avatar">{PERSON.name.charAt(0)}</span>
            {PERSON.name} · {PERSON.relation}
          </span>
          <UserButton />
        </div>
      </header>

      {error && <p className="banner tone-danger offline">Can't reach the KinGuard server: {error}. Retrying every few seconds.</p>}

      <main className="content">
        {!state ? (
          <p className="empty muted">{error ? '' : 'Loading…'}</p>
        ) : tab === 'alerts' ? (
          <Alerts state={state} selectedId={selectedId} onSelect={setSelectedId} onChanged={refresh} onOpenChannels={() => go('channels')} />
        ) : tab === 'channels' ? (
          <Channels
            state={state}
            health={health}
            onChecked={(id) => {
              openAlert(id)
            }}
          />
        ) : tab === 'subscriptions' ? (
          <Subscriptions
            state={state}
            onOpen={(id) => {
              openAlert(id)
              go('alerts')
            }}
          />
        ) : (
          <AuditTrail
            state={state}
            onOpen={(id) => {
              openAlert(id)
              go('alerts')
            }}
          />
        )}
      </main>
    </div>
  )
}

export default App
