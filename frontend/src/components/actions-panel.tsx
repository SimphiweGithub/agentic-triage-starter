import { ChevronDown, CircleCheck } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import type { Actions } from '@/actions'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { useDevices } from '@/devices'
import { PERSON, actionLabel, decisionKind, formatTime, incidentTitle } from '@/format'
import type { GuardianBrief, KinGuardState } from '@/types'
import { cn } from '@/lib/utils'
import { ReviewCard } from './decision'
import { DeviceIcon } from './status'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  actions: Actions
  state: KinGuardState
  briefs: GuardianBrief[]
  store: ReturnType<typeof useDevices>
  onOpenAlert: (incidentId: string) => void
  onOpenDevice: (deviceId: string) => void
  onInvite: () => void
  onDecided: (message: string) => void
}

type Section = 'decisions' | 'problems' | 'gaps'

/** Everything waiting on the caregiver, split by what kind of help it needs. */
export function ActionsPanel({ open, onOpenChange, actions, state, briefs, store, onOpenAlert, onOpenDevice, onInvite, onDecided }: Props) {
  const counts: Record<Section, number> = { decisions: actions.reviews.length, problems: actions.failed.length + actions.mailboxes.length, gaps: actions.gaps.length }
  const [picked, setPicked] = useState<Section>('decisions')
  // If the tab you are on empties (you answered the last decision), move to one that still has something.
  const section: Section = counts[picked] > 0 ? picked : (['decisions', 'problems', 'gaps'] as Section[]).find((item) => counts[item] > 0) ?? picked

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="gap-0 sm:max-w-md">
        <SheetHeader className="gap-1 border-b p-5">
          <SheetTitle className="text-xl font-bold">Needs you</SheetTitle>
          <SheetDescription>
            {actions.total === 0 ? `Nothing is waiting on you. ${PERSON.name} is protected.` : 'KinGuard will not do these things without you, or could not finish them.'}
          </SheetDescription>
        </SheetHeader>

        {actions.total === 0 ? (
          <div className="grid justify-items-center gap-2 p-10 text-center">
            <CircleCheck className="size-10 text-info" aria-hidden="true" />
            <p className="text-lg font-bold">All clear</p>
            <p className="text-muted-foreground">New decisions, problems and gaps will show up here.</p>
          </div>
        ) : (
          <Tabs value={section} onValueChange={(next) => setPicked(next as Section)} className="min-h-0 flex-1 gap-0">
            <TabsList className="m-4 mb-0 grid w-auto grid-cols-3 group-data-horizontal/tabs:h-11">
              <Tab value="decisions" label="Decisions" count={counts.decisions} />
              <Tab value="problems" label="Problems" count={counts.problems} />
              <Tab value="gaps" label="Gaps" count={counts.gaps} />
            </TabsList>

            <TabsContent value="decisions" className="min-h-0 flex-1 overflow-y-auto p-4">
              <Intro>KinGuard paused before doing these. Nothing happens until you answer. Open one to see what each answer does.</Intro>
              <Decisions actions={actions} state={state} briefs={briefs} onOpenAlert={onOpenAlert} onDecided={onDecided} />
            </TabsContent>

            <TabsContent value="problems" className="min-h-0 flex-1 overflow-y-auto p-4">
              <Intro>Something KinGuard tried did not work, or mail is not being checked, so a scam may get through. Each item says what to do.</Intro>
              <ul className="grid gap-3">
                {actions.mailboxes.map((mailbox) => (
                  <li key={mailbox.id} className="grid gap-2 rounded-xl border bg-card p-4">
                    <strong>
                      {mailbox.kind === 'forwarded'
                        ? 'The forwarded inbox is not answering'
                        : mailbox.status === 'disconnected'
                          ? `${PERSON.name} disconnected their Gmail`
                          : `KinGuard cannot read ${PERSON.name}’s Gmail`}
                    </strong>
                    <p className="text-sm text-muted-foreground">
                      {mailbox.kind === 'forwarded'
                        ? `Check the mailbox settings on the server.${mailbox.last_error ? ` (${mailbox.last_error})` : ''}`
                        : mailbox.status === 'disconnected'
                          ? `Their email is no longer being checked. Only a new invite link can connect it again.`
                          : `${mailbox.last_error ?? 'Google refused the connection.'} ${mailbox.last_checked ? `Last checked ${formatTime(mailbox.last_checked)}.` : ''}`}
                    </p>
                    {mailbox.kind === 'gmail' && (
                      <Button className="h-10 w-fit px-4" onClick={onInvite}>
                        Send {PERSON.name} a new invite link
                      </Button>
                    )}
                  </li>
                ))}
                {actions.failed.map(({ incident, record }, index) => (
                  <li key={index} className="grid gap-2 rounded-xl border bg-card p-4">
                    <strong>{actionLabel(record.action.type, record.action.details)} did not work</strong>
                    <p className="text-sm text-muted-foreground">Why: {record.detail || 'No reason was given.'}</p>
                    <Button variant="outline" className="h-10 w-fit px-4" onClick={() => onOpenAlert(incident.incident_id)}>
                      Open {incidentTitle(incident)}
                    </Button>
                  </li>
                ))}
              </ul>
            </TabsContent>

            <TabsContent value="gaps" className="min-h-0 flex-1 overflow-y-auto p-4">
              <Intro>A channel is switched off on a device, so messages there are not being checked. Switching it on starts checking again.</Intro>
              <ul className="grid gap-3">
                {actions.gaps.map(({ device, channels }) => (
                  <li key={device.id} className="grid gap-3 rounded-xl border bg-card p-4">
                    <div className="flex items-center gap-3">
                      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-warn-soft text-warn">
                        <DeviceIcon kind={device.kind} className="size-5" />
                      </span>
                      <div className="grid">
                        <strong>{device.name}</strong>
                        <span className="text-sm text-muted-foreground">{channels.join(' and ')} {channels.length === 1 ? 'is' : 'are'} off</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="h-10 px-4"
                        onClick={() => {
                          store.update(device.id, { on: [...device.on, ...channels] })
                          toast.success(`${channels.join(' and ')} switched on for ${device.name}`)
                        }}
                      >
                        Switch on {channels.join(' and ')}
                      </Button>
                      <Button variant="outline" className="h-10 px-4" onClick={() => onOpenDevice(device.id)}>
                        Open device
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </TabsContent>
          </Tabs>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Tab({ value, label, count }: { value: Section; label: string; count: number }) {
  return (
    <TabsTrigger value={value} disabled={count === 0} className="h-9 gap-2 text-sm font-bold">
      {label}
      <Badge className={cn('h-5 min-w-5 justify-center px-1.5', count > 0 ? 'bg-warn-soft text-warn' : 'bg-muted text-muted-foreground')}>{count}</Badge>
    </TabsTrigger>
  )
}

function Intro({ children }: { children: ReactNode }) {
  return <p className="mb-4 text-sm text-muted-foreground">{children}</p>
}

/** One row per decision. Only one is open at a time, so the list stays short. */
function Decisions({ actions, state, briefs, onOpenAlert, onDecided }: Pick<Props, 'actions' | 'state' | 'briefs' | 'onOpenAlert' | 'onDecided'>) {
  const [openId, setOpenId] = useState<string | undefined>()
  const current = openId ?? actions.reviews[0]?.review_id

  return (
    <ul className="grid gap-3">
      {actions.reviews.map((review) => {
        const incident = state.incidents.find((item) => item.incident_id === review.incident_id)
        const isOpen = current === review.review_id
        return (
          <li key={review.review_id} className={cn('overflow-hidden rounded-xl border bg-card', isOpen && 'border-2 border-warn-edge')}>
            <button
              type="button"
              className="flex w-full items-center gap-3 p-4 text-left hover:bg-muted/50"
              aria-expanded={isOpen}
              onClick={() => setOpenId(isOpen ? '' : review.review_id)}
            >
              <span className="grid min-w-0 flex-1">
                <strong>{decisionKind(review)}</strong>
                <span className="truncate text-sm text-muted-foreground">{incident ? incidentTitle(incident) : review.incident_id}</span>
              </span>
              <ChevronDown className={cn('size-5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-180')} aria-hidden="true" />
            </button>
            {isOpen && (
              <div className="grid gap-3 border-t p-4">
                <ReviewCard embedded review={review} brief={briefs.find((item) => item.review_id === review.review_id)} onDecided={onDecided} />
                <Button variant="link" className="h-auto w-fit p-0 text-sm" onClick={() => onOpenAlert(review.incident_id)}>
                  See the full alert and why we flagged it
                </Button>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
