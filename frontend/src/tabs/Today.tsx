import { ArrowRight, CircleCheck, Lock, Phone } from 'lucide-react'
import { useState } from 'react'
import type { Actions } from '@/actions'
import { callAnswerText, callNeedsYou, duration, isToday, type Call } from '@/calls'
import { canApprove, type CircleRole } from '@/circle'
import { DecisionRow } from '@/components/decision'
import { GroupBadge, GroupIcon } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { KIND_CHANNELS, type Device } from '@/devices'
import { CHANNELS, PERSON, alertGroup, formatTime, incidentChannel, incidentReports, incidentTitle, money } from '@/format'
import type { KinGuardState, Review } from '@/types'
import { cn } from '@/lib/utils'

type Props = {
  state: KinGuardState
  devices: Device[]
  actions: Actions
  calls: Call[]
  /** False while the server has no calls route: the call monitor is shown as not switched on. */
  callsSupported: boolean | null
  role: CircleRole | undefined
  onOpenActions: () => void
  onOpenAlert: (incidentId: string) => void
  onOpenDevice: (deviceId: string) => void
  onAddDevice: () => void
  onCheck: () => void
  onDecided: (message: string) => void
  onGo: (tab: 'alerts' | 'calls' | 'devices' | 'money') => void
}

const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

function greeting(now: Date): string {
  const hour = now.getHours()
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
}

function amountAtRisk(reviews: Review[]): number {
  const byIncident = new Map<string, number>()
  for (const review of reviews) {
    const amount = review.proposed_action?.details.amount
    if (typeof amount === 'number') byIncident.set(review.incident_id, amount)
  }
  return [...byIncident.values()].reduce((sum, value) => sum + value, 0)
}

export function Today({ state, devices, actions, calls, callsSupported, role, onOpenActions, onOpenAlert, onOpenDevice, onAddDevice, onCheck, onDecided, onGo }: Props) {
  const [now] = useState(() => new Date())
  const reports = new Map(state.reports.map((item) => [item.report_id, item]))
  const handled = state.incidents.filter((item) => alertGroup(item) === 'handled').length
  const weekAgo = now.getTime() - 7 * 24 * 3600 * 1000
  const thisWeek = calls.filter((call) => new Date(call.at).getTime() >= weekAgo)
  const urgentCalls = calls.filter((call) => callNeedsYou(call) && new Date(call.at).getTime() >= weekAgo)
  const atRisk = amountAtRisk(actions.reviews)
  const waiting = actions.total + urgentCalls.length
  const otherWaiting = actions.gaps.length + actions.failed.length + actions.mailboxes.length

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <p className="text-base text-muted-foreground">
            {DAY.format(now)} · {greeting(now)}
          </p>
          <h1 className="text-3xl leading-tight font-bold tracking-tight md:text-4xl">
            {PERSON.name} is safe.{' '}
            <span className={waiting > 0 ? 'text-warn' : 'text-muted-foreground'}>
              {waiting === 0 ? 'Nothing needs you right now.' : waiting === 1 ? 'One thing needs you.' : `${waiting} things need you.`}
            </span>
          </h1>
        </div>
        <Button variant="outline" className="h-11 px-5 text-base" onClick={onCheck}>
          Check a message
        </Button>
      </header>

      <section aria-label="Protection at a glance" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Messages checked" value={String(state.reports.length)} note="Email, SMS and WhatsApp" />
        <Stat
          label="Calls noticed this week"
          value={callsSupported ? String(thisWeek.length) : '—'}
          note={callsSupported ? `${thisWeek.filter((call) => !call.in_contacts).length} from unknown numbers` : 'Call monitor not on yet'}
        />
        <Stat label="Scams handled" value={String(handled)} note={`${state.world.flagged.length} ${state.world.flagged.length === 1 ? 'scammer' : 'scammers'} marked`} tone="info" />
        <Stat
          label="Money at risk"
          value={atRisk > 0 ? money(atRisk).replace('.00', '') : 'R0'}
          note={atRisk > 0 ? `${actions.reviews.length} ${actions.reviews.length === 1 ? 'decision' : 'decisions'} waiting` : 'Nothing disputed right now'}
          tone={atRisk > 0 ? 'warn' : undefined}
        />
      </section>

      {waiting > 0 ? (
        <section aria-labelledby="waiting" className="overflow-hidden rounded-xl border-2 border-warn-edge bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 bg-warn-soft/50 px-5 py-4">
            <h2 id="waiting" className="text-lg font-bold">
              Waiting for you
            </h2>
            {!canApprove(role) && <span className="text-sm text-warn">Only the next of kin can approve money decisions</span>}
          </div>
          {urgentCalls.map((call) => (
            <article key={call.call_id} className="grid gap-3 border-t border-warn-edge/40 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-warn-soft text-warn">
                  <Phone className="size-5" aria-hidden="true" />
                </span>
                <div className="grid min-w-0 flex-1 gap-1">
                  <strong className="text-base leading-snug">
                    {call.answer === 'asked_code' ? `${PERSON.name} says a caller asked for a code` : `${PERSON.name} wants you to know about a call`}
                  </strong>
                  <span className="text-base text-muted-foreground">
                    {duration(call.seconds)} call from <span className="font-mono">{call.number}</span>, not in their contacts.{' '}
                    {call.answer === 'asked_code' ? 'Phone them, then their bank’s fraud line if they shared it.' : 'Phone them to check they are all right.'}
                  </span>
                  <span className="text-sm text-muted-foreground">Call monitor · {formatTime(call.at)}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 sm:pl-12">
                <Button variant="outline" className="h-11 px-5 text-base" onClick={() => onGo('calls')}>
                  See the call
                </Button>
              </div>
            </article>
          ))}
          {actions.reviews.map((review) => {
            const incident = state.incidents.find((item) => item.incident_id === review.incident_id)
            return (
              <DecisionRow
                key={review.review_id}
                review={review}
                meta={incident ? `${incidentChannel(incident, reports)} · ${formatTime(review.created_at)}` : formatTime(review.created_at)}
                onDecided={onDecided}
                onOpen={() => onOpenAlert(review.incident_id)}
                blocked={review.audience === 'PERSON' ? `${PERSON.name} decides this themselves.` : canApprove(role) ? undefined : 'Only the next of kin can approve this.'}
              />
            )
          })}
          {otherWaiting > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-warn-edge/40 px-5 py-4">
              <span className="text-base">
                {[
                  actions.failed.length > 0 && `${actions.failed.length} ${actions.failed.length === 1 ? 'action' : 'actions'} that did not work`,
                  actions.mailboxes.length > 0 && `${actions.mailboxes.length} ${actions.mailboxes.length === 1 ? 'mailbox' : 'mailboxes'} not checked`,
                  actions.gaps.length > 0 && `${actions.gaps.length} coverage ${actions.gaps.length === 1 ? 'gap' : 'gaps'}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
              <Button variant="outline" className="h-10 px-4" onClick={onOpenActions}>
                Open the list <ArrowRight aria-hidden="true" />
              </Button>
            </div>
          )}
        </section>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg font-bold">
              <CircleCheck className="size-5 text-info" aria-hidden="true" />
              All clear
            </CardTitle>
            <CardDescription className="text-base">New decisions, risky calls and gaps will show up here.</CardDescription>
          </CardHeader>
        </Card>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <Recent state={state} calls={calls} onOpenAlert={onOpenAlert} onGo={onGo} />
        <div className="grid gap-6">
          <CallsToday calls={calls} supported={callsSupported} onGo={onGo} />
          <Coverage devices={devices} onOpenDevice={onOpenDevice} onAddDevice={onAddDevice} />
        </div>
      </div>
    </>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'info' | 'warn' }) {
  return (
    <div className={cn('grid gap-1 rounded-xl border bg-card px-4 py-3', tone === 'warn' && 'border-warn-edge bg-warn-soft')}>
      <span className={cn('text-sm text-muted-foreground', tone === 'warn' && 'text-warn')}>{label}</span>
      <strong className={cn('text-3xl', tone === 'info' && 'text-info', tone === 'warn' && 'text-warn')}>{value}</strong>
      <span className={cn('text-sm text-muted-foreground', tone === 'warn' && 'text-warn')}>{note}</span>
    </div>
  )
}

type Entry = { key: string; at: string; title: string; detail: string; group: 'needs' | 'handled' | 'safe'; call: boolean; open: () => void }

function Recent({ state, calls, onOpenAlert, onGo }: { state: KinGuardState; calls: Call[]; onOpenAlert: (id: string) => void; onGo: Props['onGo'] }) {
  const reports = new Map(state.reports.map((item) => [item.report_id, item]))
  const entries: Entry[] = [
    ...state.incidents.map((incident) => ({
      key: incident.incident_id,
      at: incidentReports(incident, state).at(-1)?.timestamp ?? incident.updated_at,
      title: incidentTitle(incident),
      detail: incidentChannel(incident, reports),
      group: alertGroup(incident),
      call: false,
      open: () => onOpenAlert(incident.incident_id),
    })),
    ...calls
      .filter((call) => !call.in_contacts)
      .map((call) => ({
        key: call.call_id,
        at: call.at,
        title: call.answer === 'asked_code' ? 'Unknown caller asked for a code' : 'Call from an unknown number',
        detail: `Call · ${call.number} · ${duration(call.seconds)}`,
        group: (callNeedsYou(call) ? 'needs' : 'safe') as Entry['group'],
        call: true,
        open: () => onGo('calls'),
      })),
  ]
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 6)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-bold">What happened recently</CardTitle>
        <Button variant="link" className="absolute top-3 right-3 text-base" onClick={() => onGo('alerts')}>
          See all alerts
        </Button>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-muted-foreground">Nothing yet. Messages and calls are checked as they arrive.</p>
        ) : (
          <ul className="divide-y">
            {entries.map((entry) => (
              <li key={entry.key}>
                <button type="button" className="flex w-full items-center gap-4 rounded-lg py-3 text-left hover:bg-muted/60" onClick={entry.open}>
                  {entry.call ? (
                    <span className={cn('grid size-10 shrink-0 place-items-center rounded-full', entry.group === 'needs' ? 'bg-warn-soft text-warn' : 'bg-muted text-foreground')}>
                      <Phone className="size-5" aria-hidden="true" />
                    </span>
                  ) : (
                    <GroupIcon group={entry.group} />
                  )}
                  <span className="grid min-w-0 flex-1">
                    <strong className="truncate text-base">{entry.title}</strong>
                    <span className="truncate text-sm text-muted-foreground">{entry.detail}</span>
                  </span>
                  <span className="grid justify-items-end gap-1">
                    <GroupBadge group={entry.group} />
                    <span className="text-sm text-muted-foreground">{formatTime(entry.at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function CallsToday({ calls, supported, onGo }: { calls: Call[]; supported: boolean | null; onGo: Props['onGo'] }) {
  const today = calls.filter((call) => isToday(call.at)).slice(0, 4)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-bold">Calls today</CardTitle>
        <span className="absolute top-4 right-4 flex items-center gap-1.5 text-sm text-muted-foreground">
          <Lock className="size-3.5" aria-hidden="true" /> Never listened to
        </span>
        <CardDescription>
          The phone notes that a call happened, who from and how long. After a call from an unknown number, {PERSON.name} is shown common call scams.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {!supported ? (
          <p className="text-muted-foreground">The call monitor is not switched on yet. Turn it on in the Scam Stop app on {PERSON.name}’s Android phone.</p>
        ) : today.length === 0 ? (
          <p className="text-muted-foreground">No calls yet today.</p>
        ) : (
          <ol className="grid gap-2">
            {today.map((call) => (
              <li key={call.call_id} className={cn('grid gap-1 rounded-lg px-3 py-2.5', callNeedsYou(call) ? 'border border-warn-edge bg-warn-soft/60' : 'bg-muted/60')}>
                <div className="flex justify-between gap-2">
                  <strong className={cn(!call.contact_name && 'font-mono')}>{call.contact_name ?? call.number}</strong>
                  <span className="text-sm text-muted-foreground">
                    {formatTime(call.at).split(' ').at(-1)} · {duration(call.seconds)}
                  </span>
                </div>
                <span className={cn('text-sm', callNeedsYou(call) ? 'font-bold text-warn' : 'text-muted-foreground')}>{callAnswerText(call, PERSON.name)}</span>
              </li>
            ))}
          </ol>
        )}
        <Button variant="link" className="h-auto w-fit p-0 text-base" onClick={() => onGo('calls')}>
          See all calls
        </Button>
      </CardContent>
    </Card>
  )
}

function Coverage({ devices, onOpenDevice, onAddDevice }: { devices: Device[]; onOpenDevice: (id: string) => void; onAddDevice: () => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-bold">What is being watched</CardTitle>
        <CardDescription>Every device and channel. A gap means scams could get through there.</CardDescription>
      </CardHeader>
      <CardContent>
        {devices.length === 0 ? (
          <div className="grid gap-3">
            <p className="text-muted-foreground">Add each phone, tablet and computer {PERSON.name} uses, so any gap in protection is easy to see.</p>
            <Button className="h-10 w-fit px-4" onClick={onAddDevice}>
              Add a device
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th scope="col" className="py-2 text-left font-normal">
                    Device
                  </th>
                  {CHANNELS.map((channel) => (
                    <th key={channel} scope="col" className="px-1 py-2 text-center font-normal">
                      {channel}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.id} className="border-t">
                    <th scope="row" className="py-2 text-left">
                      <button type="button" className="font-bold hover:underline" onClick={() => onOpenDevice(device.id)}>
                        {device.name}
                      </button>
                    </th>
                    {CHANNELS.map((channel) => {
                      const possible = KIND_CHANNELS[device.kind].includes(channel)
                      const on = device.on.includes(channel)
                      return (
                        <td key={channel} className="px-1 py-2 text-center">
                          <span className={cn('inline-block min-w-10 rounded-md px-2 py-0.5 text-xs font-bold', !possible ? 'text-muted-foreground' : on ? 'bg-info-soft text-info' : 'bg-warn-soft text-warn')}>
                            {possible ? (on ? 'On' : 'Off') : '—'}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
