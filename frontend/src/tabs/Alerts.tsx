import { useState } from 'react'
import { GroupBadge, GroupIcon } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { GROUP_WORD, PERSON, alertGroup, formatTime, incidentChannel, incidentChannels, incidentTitle, threatLabel, type Group } from '@/format'
import type { Incident, KinGuardState } from '@/types'

type Props = {
  state: KinGuardState
  onOpenAlert: (incidentId: string) => void
  onCheck: () => void
}

const GROUPS: (Group | 'all')[] = ['all', 'needs', 'handled', 'safe']

function byPriority(a: Incident, b: Incident): number {
  const waiting = Number(alertGroup(b) === 'needs') - Number(alertGroup(a) === 'needs')
  return waiting || b.updated_at.localeCompare(a.updated_at)
}

export function Alerts({ state, onOpenAlert, onCheck }: Props) {
  const [group, setGroup] = useState<Group | 'all'>('all')
  const [channel, setChannel] = useState('all')
  const reports = new Map(state.reports.map((item) => [item.report_id, item]))
  const all = [...state.incidents].sort(byPriority)
  const channels = [...new Set(all.flatMap((item) => incidentChannels(item, reports)))]
  const shown = all.filter((item) => (group === 'all' || alertGroup(item) === group) && (channel === 'all' || incidentChannels(item, reports).includes(channel)))
  const count = (item: Group | 'all') => (item === 'all' ? all.length : all.filter((incident) => alertGroup(incident) === item).length)

  if (all.length === 0) {
    return (
      <div className="mx-auto my-16 grid max-w-md justify-items-center gap-3 text-center">
        <h1 className="text-2xl font-bold">No alerts for {PERSON.name}</h1>
        <p className="text-muted-foreground">Messages from Gmail, the live inbox or shared SMS are checked as they arrive and show up here.</p>
        <Button className="h-11 px-5 text-base" onClick={onCheck}>
          Check a message now
        </Button>
      </div>
    )
  }

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="text-3xl font-bold tracking-tight">Alerts</h1>
          <p className="text-lg text-muted-foreground">Open one to see the message, what we noticed and what was done.</p>
        </div>
        <Button variant="outline" className="h-10 px-4" onClick={onCheck}>
          Check a message
        </Button>
      </header>

      <div className="flex flex-wrap gap-x-6 gap-y-3">
        <ToggleGroup variant="outline" aria-label="Show" value={[group]} onValueChange={(next: string[]) => next[0] && setGroup(next[0] as Group | 'all')}>
          {GROUPS.map((item) => (
            <ToggleGroupItem key={item} value={item} className="h-10 px-4 text-sm">
              {item === 'all' ? 'All' : GROUP_WORD[item]} ({count(item)})
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {channels.length > 1 && (
          <ToggleGroup variant="outline" aria-label="Channel" value={[channel]} onValueChange={(next: string[]) => next[0] && setChannel(next[0])}>
            {['all', ...channels].map((item) => (
              <ToggleGroupItem key={item} value={item} className="h-10 px-4 text-sm">
                {item === 'all' ? 'All channels' : item}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>

      {shown.length === 0 ? (
        <p className="text-muted-foreground">Nothing matches. Try another filter.</p>
      ) : (
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y">
              {shown.map((incident) => {
                const item = alertGroup(incident)
                return (
                  <li key={incident.incident_id}>
                    <button type="button" className="flex w-full items-center gap-4 px-5 py-4 text-left hover:bg-muted/60" onClick={() => onOpenAlert(incident.incident_id)}>
                      <GroupIcon group={item} />
                      <span className="grid min-w-0 flex-1 gap-0.5">
                        <strong className="truncate text-base">{incidentTitle(incident)}</strong>
                        <span className="truncate text-sm text-muted-foreground">
                          {incidentChannel(incident, reports)} · {threatLabel(incident.labels.threat)}
                        </span>
                      </span>
                      <span className="grid justify-items-end gap-1">
                        <GroupBadge group={item} />
                        <span className="text-sm text-muted-foreground">{formatTime(incident.updated_at)}</span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </CardContent>
        </Card>
      )}
    </>
  )
}
