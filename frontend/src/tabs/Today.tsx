import { ArrowRight, CircleCheck, ClipboardList } from 'lucide-react'
import type { Actions } from '@/actions'
import { GroupBadge, GroupIcon } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { KIND_CHANNELS, type Device } from '@/devices'
import { CHANNELS, PERSON, alertGroup, formatTime, incidentChannel, incidentReports, incidentTitle, reviewQuestion } from '@/format'
import type { KinGuardState } from '@/types'
import { cn } from '@/lib/utils'

type Props = {
  state: KinGuardState
  devices: Device[]
  actions: Actions
  onOpenActions: () => void
  onOpenAlert: (incidentId: string) => void
  onOpenDevice: (deviceId: string) => void
  onAddDevice: () => void
  onGo: (tab: 'alerts' | 'devices' | 'money') => void
}

export function Today({ state, devices, actions, onOpenActions, onOpenAlert, onOpenDevice, onAddDevice, onGo }: Props) {
  const reports = new Map(state.reports.map((item) => [item.report_id, item]))
  const recent = [...state.incidents].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 6)
  const handled = state.incidents.filter((item) => alertGroup(item) === 'handled').length
  const disputes = Object.keys(state.world.disputes).length

  return (
    <>
      <header className="grid gap-1">
        <h1 className="text-3xl leading-tight font-bold tracking-tight">
          {PERSON.name} is safe. {actions.total === 0 ? 'Nothing needs you right now.' : actions.total === 1 ? 'One thing needs you.' : `${actions.total} things need you.`}
        </h1>
        <p className="text-lg text-muted-foreground">
          {state.reports.length === 0 ? 'No messages checked yet.' : `${state.reports.length} ${state.reports.length === 1 ? 'message' : 'messages'} checked so far`}
        </p>
      </header>

      <Card className={cn(actions.total > 0 ? 'ring-2 ring-warn-edge' : '')}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg font-bold">
            {actions.total > 0 ? <ClipboardList className="size-5 text-warn" aria-hidden="true" /> : <CircleCheck className="size-5 text-info" aria-hidden="true" />}
            {actions.total > 0 ? 'Waiting for you' : 'All clear'}
          </CardTitle>
          <CardDescription className="text-base">
            {actions.total > 0
              ? [
                  actions.reviews.length > 0 && `${actions.reviews.length} ${actions.reviews.length === 1 ? 'decision' : 'decisions'}`,
                  actions.failed.length > 0 && `${actions.failed.length} that did not work`,
                  actions.gaps.length > 0 && `${actions.gaps.length} coverage ${actions.gaps.length === 1 ? 'gap' : 'gaps'}`,
                ]
                  .filter(Boolean)
                  .join(' · ')
              : 'New decisions and gaps will show up here.'}
          </CardDescription>
        </CardHeader>
        {actions.total > 0 && (
          <CardContent className="grid gap-3">
            {actions.reviews[0] && <p className="text-base font-bold">{reviewQuestion(actions.reviews[0])}</p>}
            <Button className="h-11 w-fit px-5 text-base" onClick={onOpenActions}>
              Review now <ArrowRight aria-hidden="true" />
            </Button>
          </CardContent>
        )}
      </Card>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">What happened recently</CardTitle>
            <Button variant="link" className="absolute top-3 right-3 text-base" onClick={() => onGo('alerts')}>
              See all alerts
            </Button>
          </CardHeader>
          <CardContent>
            {recent.length === 0 ? (
              <p className="text-muted-foreground">Nothing yet. Messages are checked as they arrive.</p>
            ) : (
              <ul className="divide-y">
                {recent.map((incident) => {
                  const group = alertGroup(incident)
                  return (
                    <li key={incident.incident_id}>
                      <button type="button" className="flex w-full items-center gap-4 rounded-lg py-3 text-left hover:bg-muted/60" onClick={() => onOpenAlert(incident.incident_id)}>
                        <GroupIcon group={group} />
                        <span className="grid min-w-0 flex-1">
                          <strong className="truncate text-base">{incidentTitle(incident)}</strong>
                          <span className="text-sm text-muted-foreground">{incidentChannel(incident, reports)}</span>
                        </span>
                        <span className="grid justify-items-end gap-1">
                          <GroupBadge group={group} />
                          <span className="text-sm text-muted-foreground">{formatTime(incidentReports(incident, state).at(-1)?.timestamp ?? incident.updated_at)}</span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-6">
          <Coverage devices={devices} onOpenDevice={onOpenDevice} onAddDevice={onAddDevice} />
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-bold">So far, KinGuard</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="grid gap-3">
                <Stat n={handled} text={handled === 1 ? 'scam handled' : 'scams handled'} />
                <Stat n={state.world.flagged.length} text={state.world.flagged.length === 1 ? 'sender blocked' : 'senders blocked'} />
                <Stat n={disputes} text={disputes === 1 ? 'dispute ready for the bank' : 'disputes ready for the bank'} />
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function Stat({ n, text }: { n: number; text: string }) {
  return (
    <li className="flex items-baseline gap-3">
      <strong className="min-w-8 text-3xl text-primary">{n}</strong>
      <span>{text}</span>
    </li>
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
