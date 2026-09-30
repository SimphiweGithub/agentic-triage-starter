import { ClerkLoading, Show, useAuth } from '@clerk/react'
import { ClipboardList, MessageSquarePlus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { setActivePerson, setTokenGetter, useKinGuard } from './api'
import { collectActions } from './actions'
import { ActionsPanel } from './components/actions-panel'
import { AlertDetailDialog } from './components/alert-detail'
import { AppSidebar } from './components/app-sidebar'
import { CheckDialog } from './components/check-dialog'
import { AddDeviceDialog, DeviceDialog } from './components/device-dialogs'
import { InviteDialog } from './components/invite-dialog'
import { Badge } from './components/ui/badge'
import { Button } from './components/ui/button'
import { Separator } from './components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from './components/ui/sidebar'
import { useDevices } from './devices'
import { TABS, type TabId } from './nav'
import { incidentTitle, reviewQuestion, setPerson } from './format'
import { clearInviteFromAddress, inviteFromAddress, useMe } from './me'
import { Alerts } from './tabs/Alerts'
import { Devices } from './tabs/Devices'
import { Money } from './tabs/Money'
import { Today } from './tabs/Today'
import { AddPersonScreen, ConnectScreen, PersonHome, SignedOutScreen } from './screens'
import { usePeopleSummary } from './people'
import { AddPersonForm } from './components/add-person-form'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'
import type { Mailbox, Me, PersonRecord, PersonSummary } from './types'

function tabFromHash(): TabId {
  const hash = window.location.hash.slice(1)
  return TABS.some((tab) => tab.id === hash) ? (hash as TabId) : 'today'
}

function App() {
  const invite = inviteFromAddress()
  return (
    <>
      <ClerkLoading>
        <p className="my-16 text-center text-muted-foreground">Loading KinGuard…</p>
      </ClerkLoading>
      <Show when="signed-out">{invite ? <ConnectScreen token={invite} signedIn={false} onDone={() => undefined} /> : <SignedOutScreen />}</Show>
      <Show when="signed-in">
        <Authed />
      </Show>
    </>
  )
}

/** Signed in: every call now carries the session token, then the role decides what to show. */
function Authed() {
  const { getToken } = useAuth()
  setTokenGetter(() => getToken()) // set while rendering, so it is ready before any child fetches
  const { me, error, refresh } = useMe()
  const invite = inviteFromAddress()

  if (!me) return <p className="my-16 text-center text-muted-foreground">{error || 'Loading…'}</p>
  setPerson(me.person)

  if (me.role === 'person') {
    if (invite) clearInviteFromAddress()
    return <PersonHome me={me} onChanged={refresh} />
  }
  if (me.role === null && invite) {
    return (
      <ConnectScreen
        token={invite}
        signedIn
        onDone={() => {
          clearInviteFromAddress()
          refresh()
        }}
      />
    )
  }
  if (me.role === 'caregiver' && me.people.length > 0) return <Workspace me={me} onMeChanged={refresh} />
  return <AddPersonScreen onAdded={refresh} />
}

const CHOSEN_KEY = 'kinguard.person'

/** The caregiver's people. One is active at a time; choosing another remounts the dashboard so nothing carries over. */
function Workspace({ me, onMeChanged }: { me: Me; onMeChanged: () => void }) {
  const { people: summary, refresh: refreshSummary } = usePeopleSummary()
  const [chosen, setChosen] = useState(() => {
    try {
      return localStorage.getItem(CHOSEN_KEY)
    } catch {
      return null
    }
  })
  const [adding, setAdding] = useState(false)
  const active = me.people.find((item) => item.id === chosen) ?? me.people[0]
  // Set while rendering, so the name and the address scope are right before anything below fetches or draws.
  setPerson(active)
  setActivePerson(active.id)

  function select(id: string) {
    setChosen(id)
    try {
      localStorage.setItem(CHOSEN_KEY, id)
    } catch {
      // Remembering the choice is a convenience only.
    }
  }

  // Tell the caregiver when someone they are not looking at gets a new decision.
  const waiting = useRef<Map<string, number> | null>(null)
  useEffect(() => {
    const previous = waiting.current
    waiting.current = new Map(summary.map((item) => [item.id, item.needs]))
    if (!previous) return
    for (const person of summary) {
      if (person.id === active.id || person.needs <= (previous.get(person.id) ?? 0)) continue
      toast(`${person.name} has a decision waiting`, { action: { label: `Switch to ${person.name}`, onClick: () => select(person.id) } })
    }
  }, [summary, active.id])

  const rows: PersonSummary[] = me.people.map((person) => summary.find((item) => item.id === person.id) ?? { ...person, needs: 0, problems: 0 })

  return (
    <>
      <Dashboard key={active.id} person={active} people={rows} inheritDevices={me.people[0].id === active.id} onSelectPerson={select} onAddPerson={() => setAdding(true)} />
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold">Who else are you looking after?</DialogTitle>
            <DialogDescription>Each person has their own alerts, devices and mailboxes. Nothing is shared between them.</DialogDescription>
          </DialogHeader>
          <AddPersonForm
            submitLabel="Add them"
            onAdded={(next) => {
              const added = next.people[next.people.length - 1]
              setAdding(false)
              onMeChanged()
              refreshSummary()
              select(added.id)
              toast.success(`${added.name} added`)
            }}
          />
        </DialogContent>
      </Dialog>
    </>
  )
}

type DashboardProps = {
  person: PersonRecord
  people: PersonSummary[]
  /** The first person keeps the device list saved before several people were supported. */
  inheritDevices: boolean
  onSelectPerson: (id: string) => void
  onAddPerson: () => void
}

function Dashboard({ person, people, inheritDevices, onSelectPerson, onAddPerson }: DashboardProps) {
  const personId = person.id
  const { state, briefs, mailboxes, error, refresh } = useKinGuard(personId)
  const store = useDevices(personId, inheritDevices)
  const [tab, setTab] = useState<TabId>(tabFromHash)
  // Everything that opens on top of the current page lives here, so any page can open any of it.
  const [alertId, setAlertId] = useState<string | null>(null)
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [checkOpen, setCheckOpen] = useState(false)
  const [actionsOpen, setActionsOpen] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Network trouble is a notification, not a banner: it appears once and goes away when the server is back.
  useEffect(() => {
    if (error) toast.error("Can't reach the KinGuard server. Retrying every few seconds.", { id: 'offline', duration: Infinity })
    else toast.dismiss('offline')
  }, [error])

  // Tell the caregiver about anything new that arrives while they are looking at the screen.
  const seen = useRef<{ incidents: Set<string>; reviews: Set<string> } | null>(null)
  const mine = useRef(new Set<string>())
  useEffect(() => {
    if (!state) return
    const previous = seen.current
    const pending = state.reviews.filter((item) => item.status === 'PENDING')
    seen.current = { incidents: new Set(state.incidents.map((item) => item.incident_id)), reviews: new Set(pending.map((item) => item.review_id)) }
    if (!previous) return // the first load is not news
    const asked = new Set<string>()
    for (const review of pending) {
      if (previous.reviews.has(review.review_id)) continue
      asked.add(review.incident_id)
      toast('A decision is waiting for you', { description: reviewQuestion(review), action: { label: 'Review', onClick: () => setActionsOpen(true) } })
    }
    for (const incident of state.incidents) {
      if (previous.incidents.has(incident.incident_id) || asked.has(incident.incident_id) || mine.current.has(incident.incident_id)) continue
      toast('New alert', { description: incidentTitle(incident), action: { label: 'Open', onClick: () => setAlertId(incident.incident_id) } })
    }
  }, [state])

  // Tell the caregiver when a mailbox stops being checked: the person disconnected, or Google refused the connection.
  const mailboxStates = useRef<Map<string, Mailbox['status']> | null>(null)
  useEffect(() => {
    const previous = mailboxStates.current
    mailboxStates.current = new Map(mailboxes.map((item) => [item.id, item.status]))
    if (!previous) return
    for (const mailbox of mailboxes) {
      const before = previous.get(mailbox.id)
      if (before === undefined || before === mailbox.status || mailbox.status === 'connected') continue
      toast.error(mailbox.status === 'disconnected' ? `${person.name} disconnected their Gmail` : `KinGuard cannot read ${person.name}’s Gmail`, {
        description: mailbox.status === 'problem' ? (mailbox.last_error ?? undefined) : 'Only a new invite link can connect it again.',
        action: { label: 'See what to do', onClick: () => setActionsOpen(true) },
      })
    }
  }, [mailboxes, person.name])

  function go(next: TabId) {
    window.history.pushState(null, '', `#${next}`)
    setTab(next)
  }

  function openAlert(incidentId: string) {
    setActionsOpen(false)
    setAlertId(incidentId)
  }

  function openDevice(id: string) {
    setActionsOpen(false)
    setDeviceId(id)
  }

  function decided(message: string) {
    toast.success(message)
    refresh()
  }

  function checked(incidentId: string | null) {
    refresh()
    if (incidentId) {
      mine.current.add(incidentId)
      toast.success('Message checked', { action: { label: 'Open the alert', onClick: () => openAlert(incidentId) } })
    } else {
      toast('Message checked. Nothing was stored.')
    }
  }

  const actions = state ? collectActions(state, store.devices, mailboxes) : { reviews: [], gaps: [], failed: [], mailboxes: [], total: 0 }
  const alertsWaiting = actions.reviews.length

  return (
    <SidebarProvider>
      <AppSidebar
        tab={tab}
        onTab={go}
        alertsWaiting={alertsWaiting}
        devices={store.devices}
        guardian={state?.world.guardian}
        people={people}
        activeId={personId}
        onSelectPerson={onSelectPerson}
        onAddPerson={onAddPerson}
        onOpenDevice={openDevice}
        onAddDevice={() => setAddOpen(true)}
      />

      <SidebarInset>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <span className="text-base font-bold">{TABS.find((item) => item.id === tab)?.label}</span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" className="h-10 gap-2 px-3" onClick={() => setCheckOpen(true)}>
              <MessageSquarePlus aria-hidden="true" />
              <span className="hidden sm:inline">Check a message</span>
            </Button>
            <Button className="h-10 gap-2 px-3" variant={actions.total > 0 ? 'default' : 'outline'} onClick={() => setActionsOpen(true)}>
              <ClipboardList aria-hidden="true" />
              <span>Needs you</span>
              {actions.total > 0 && <Badge className="bg-warn-soft text-warn">{actions.total}</Badge>}
            </Button>
          </div>
        </header>


        <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 md:p-8">
          {!state ? (
            <p className="my-16 text-center text-muted-foreground">{error ? '' : 'Loading…'}</p>
          ) : tab === 'today' ? (
            <Today
              state={state}
              devices={store.devices}
              actions={actions}
              onOpenActions={() => setActionsOpen(true)}
              onOpenAlert={openAlert}
              onOpenDevice={openDevice}
              onAddDevice={() => setAddOpen(true)}
              onGo={go}
            />
          ) : tab === 'alerts' ? (
            <Alerts state={state} onOpenAlert={openAlert} onCheck={() => setCheckOpen(true)} />
          ) : tab === 'devices' ? (
            <Devices state={state} mailboxes={mailboxes} devices={store.devices} onOpenDevice={openDevice} onAddDevice={() => setAddOpen(true)} onCheck={() => setCheckOpen(true)} onInvite={() => setInviteOpen(true)} />
          ) : (
            <Money state={state} onOpenAlert={openAlert} />
          )}
        </main>
      </SidebarInset>

      {state && (
        <>
          <ActionsPanel
            open={actionsOpen}
            onOpenChange={setActionsOpen}
            actions={actions}
            state={state}
            briefs={briefs}
            store={store}
            onOpenAlert={openAlert}
            onOpenDevice={openDevice}
            onInvite={() => {
              setActionsOpen(false)
              setInviteOpen(true)
            }}
            onDecided={decided}
          />
          <AlertDetailDialog incidentId={alertId} state={state} briefs={briefs} onClose={() => setAlertId(null)} onDecided={decided} />
        </>
      )}
      <DeviceDialog deviceId={deviceId} store={store} onClose={() => setDeviceId(null)} />
      <AddDeviceDialog
        open={addOpen}
        store={store}
        onClose={() => setAddOpen(false)}
        onAdded={(id) => {
          setAddOpen(false)
          setDeviceId(id)
        }}
      />
      <CheckDialog open={checkOpen} onOpenChange={setCheckOpen} onChecked={checked} />
      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} personId={personId} onChanged={refresh} />
    </SidebarProvider>
  )
}

export default App
