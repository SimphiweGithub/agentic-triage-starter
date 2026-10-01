import { Lock, MicOff, Phone, Users } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { CALL_SCAMS, callAnswerText, callNeedsYou, duration, type Call } from '@/calls'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { PERSON, formatTime } from '@/format'
import { cn } from '@/lib/utils'

type Props = {
  calls: Call[]
  /** False while the server has no calls route. */
  supported: boolean | null
}

type Filter = 'all' | 'needs' | 'unknown' | 'contacts'

const FILTER_WORD: Record<Filter, string> = { all: 'All', needs: 'Needs you', unknown: 'Unknown numbers', contacts: 'Contacts' }

function matches(call: Call, filter: Filter): boolean {
  if (filter === 'needs') return callNeedsYou(call)
  if (filter === 'unknown') return !call.in_contacts
  if (filter === 'contacts') return call.in_contacts
  return true
}

/** Calls the phone noticed. Never what was said: only the number, the time, the length and what the person tapped afterwards. */
export function Calls({ calls, supported }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const shown = calls.filter((call) => matches(call, filter))

  return (
    <>
      <header className="grid gap-1">
        <h1 className="text-3xl font-bold tracking-tight">Calls</h1>
        <p className="text-lg text-muted-foreground">
          After a call from a number {PERSON.name} doesn’t know, their phone shows common call scams and asks how it went.
        </p>
      </header>

      <ul className="grid gap-3 md:grid-cols-3">
        <Assurance icon={<MicOff className="size-5" aria-hidden="true" />} title="Never listened to" text="Calls are not heard or recorded. Scam Stop only learns that a call happened." />
        <Assurance icon={<Users className="size-5" aria-hidden="true" />} title="Contacts are left alone" text={`Calls from people in ${PERSON.name}’s contacts don’t show any tips.`} />
        <Assurance icon={<Lock className="size-5" aria-hidden="true" />} title="Only the basics are shared" text="The care circle sees the number, the time and the length, nothing else." />
      </ul>

      {!supported ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">The call monitor is not on yet</CardTitle>
            <CardDescription className="text-base">
              Open the Scam Stop app on {PERSON.name}’s Android phone and finish the step “Help after phone calls”. Calls will show up here once it is on.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <ToggleGroup variant="outline" aria-label="Show" value={[filter]} onValueChange={(next: string[]) => next[0] && setFilter(next[0] as Filter)}>
            {(Object.keys(FILTER_WORD) as Filter[]).map((item) => (
              <ToggleGroupItem key={item} value={item} className="h-10 px-4 text-sm">
                {FILTER_WORD[item]} ({calls.filter((call) => matches(call, item)).length})
              </ToggleGroupItem>
            ))}
          </ToggleGroup>

          {shown.length === 0 ? (
            <p className="text-muted-foreground">{calls.length === 0 ? 'No calls noticed yet.' : 'Nothing matches. Try another filter.'}</p>
          ) : (
            <Card>
              <CardContent className="p-0">
                <ul className="divide-y">
                  {shown.map((call) => (
                    <li key={call.call_id} className="flex items-center gap-4 px-5 py-4">
                      <span className={cn('grid size-10 shrink-0 place-items-center rounded-full', callNeedsYou(call) ? 'bg-warn-soft text-warn' : 'bg-muted text-foreground')}>
                        <Phone className="size-5" aria-hidden="true" />
                      </span>
                      <span className="grid min-w-0 flex-1 gap-0.5">
                        <strong className={cn('truncate text-base', !call.contact_name && 'font-mono')}>{call.contact_name ?? call.number}</strong>
                        <span className={cn('text-sm', callNeedsYou(call) ? 'font-bold text-warn' : 'text-muted-foreground')}>{callAnswerText(call, PERSON.name)}</span>
                      </span>
                      <span className="grid justify-items-end gap-1">
                        {callNeedsYou(call) ? (
                          <Badge className="h-6 bg-warn-soft px-3 text-sm font-bold text-warn">Needs you</Badge>
                        ) : (
                          <Badge className="h-6 bg-muted px-3 text-sm font-bold text-foreground">{call.in_contacts ? 'Contact' : 'Unknown'}</Badge>
                        )}
                        <span className="text-sm text-muted-foreground">
                          {formatTime(call.at)} · {duration(call.seconds)}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-bold">What {PERSON.name} is shown after an unknown call</CardTitle>
          <CardDescription>The same list appears on their phone, with a reminder that a bank never asks for a PIN or code.</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid gap-3 md:grid-cols-2">
            {CALL_SCAMS.map((scam, index) => (
              <li key={scam.title} className="flex gap-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-warn-soft font-bold text-warn">{index + 1}</span>
                <span className="grid">
                  <strong>{scam.title}</strong>
                  <span className="text-sm text-muted-foreground">{scam.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </>
  )
}

function Assurance({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <li className="flex gap-3 rounded-xl border bg-card p-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">{icon}</span>
      <span className="grid gap-0.5">
        <strong>{title}</strong>
        <span className="text-sm text-muted-foreground">{text}</span>
      </span>
    </li>
  )
}
