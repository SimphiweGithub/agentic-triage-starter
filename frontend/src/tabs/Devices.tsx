import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, post, scoped } from '@/api'
import { DeviceIcon } from '@/components/status'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { KIND_CHANNELS, KIND_LABEL, channelActivity, deviceGaps, type Device } from '@/devices'
import { CHANNELS, PERSON, formatTime } from '@/format'
import type { KinGuardState, Mailbox } from '@/types'
import { cn } from '@/lib/utils'

type Props = {
  state: KinGuardState
  mailboxes: Mailbox[]
  devices: Device[]
  onOpenDevice: (id: string) => void
  onAddDevice: () => void
  onCheck: () => void
  onInvite: () => void
}

function statusOf(device: Device): { word: string; style: string } {
  if (device.on.length === 0) return { word: 'Paused', style: 'bg-muted text-foreground' }
  return deviceGaps(device).length > 0 ? { word: 'Gap', style: 'bg-warn-soft text-warn' } : { word: 'Fully covered', style: 'bg-info-soft text-info' }
}

export function Devices({ state, mailboxes, devices, onOpenDevice, onAddDevice, onCheck, onInvite }: Props) {
  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="text-3xl font-bold tracking-tight">Mailboxes and devices</h1>
          <p className="text-lg text-muted-foreground">Where {PERSON.name}’s messages come from. Email is checked through their own mailbox; texts and WhatsApp through their devices.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="h-11 px-4 text-base" onClick={onCheck}>
            Check a message
          </Button>
          <Button className="h-11 px-5 text-base" onClick={onAddDevice}>
            <Plus aria-hidden="true" /> Add a device
          </Button>
        </div>
      </header>

      <Mailboxes mailboxes={mailboxes} onInvite={onInvite} />
      <PhonePairing />

      <Alert>
        <AlertDescription className="font-bold text-info">
          Devices are saved in this browser for now. The server does not track devices yet, so switching a channel off here is a reminder, not a filter.
        </AlertDescription>
      </Alert>

      {devices.length === 0 ? (
        <div className="mx-auto my-10 grid max-w-md justify-items-center gap-3 text-center">
          <h2 className="text-xl font-bold">No devices added yet</h2>
          <p className="text-muted-foreground">Add each phone, tablet and computer {PERSON.name} uses, and choose which channels Scam Stop checks on each.</p>
          <Button className="h-11 px-5 text-base" onClick={onAddDevice}>
            Add a device
          </Button>
        </div>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {devices.map((device) => {
            const status = statusOf(device)
            return (
              <li key={device.id}>
                <button type="button" className="h-full w-full rounded-xl text-left ring-1 ring-foreground/10 transition hover:ring-2 hover:ring-primary" onClick={() => onOpenDevice(device.id)}>
                  <Card className="h-full ring-0">
                    <CardHeader>
                      <div className="flex items-center gap-3">
                        <span className="grid size-12 place-items-center rounded-xl bg-muted">
                          <DeviceIcon kind={device.kind} className="size-6" />
                        </span>
                        <div className="grid min-w-0 flex-1">
                          <CardTitle className="truncate text-lg font-bold">{device.name}</CardTitle>
                          <CardDescription>
                            {KIND_LABEL[device.kind]} · {device.on.length} of {KIND_CHANNELS[device.kind].length} channels on
                          </CardDescription>
                        </div>
                        <Badge className={cn('h-6 px-3 text-sm font-bold', status.style)}>{status.word}</Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-2">
                      {KIND_CHANNELS[device.kind].map((channel) => (
                        <Badge key={channel} variant="outline" className={cn('h-6 text-sm', device.on.includes(channel) ? 'text-info' : 'text-warn')}>
                          {channel}: {device.on.includes(channel) ? 'on' : 'off'}
                        </Badge>
                      ))}
                    </CardContent>
                  </Card>
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">Messages kept on each channel</CardTitle>
            <CardDescription>Messages that were flagged or shared by hand. Safe email is checked and not kept.</CardDescription>
          </CardHeader>
          <CardContent>
            <Activity state={state} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">Blocked senders</CardTitle>
            <CardDescription>Addresses and domains the mail filter now stops before they reach {PERSON.name}.</CardDescription>
          </CardHeader>
          <CardContent>
            {state.world.flagged.length === 0 ? (
              <p className="text-muted-foreground">None yet.</p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {state.world.flagged.map((sender) => (
                  <li key={sender}>
                    <code className="rounded-md bg-muted px-2 py-1 text-sm">{sender}</code>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

const STATUS_WORD: Record<Mailbox['status'], string> = { connected: 'Being checked', problem: 'Not working', disconnected: 'Disconnected' }
const STATUS_STYLE: Record<Mailbox['status'], string> = { connected: 'bg-info-soft text-info', problem: 'bg-warn-soft text-warn', disconnected: 'bg-warn-soft text-warn' }

function Mailboxes({ mailboxes, onInvite }: { mailboxes: Mailbox[]; onInvite: () => void }) {
  const gmail = mailboxes.find((item) => item.kind === 'gmail')
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-bold">{PERSON.name}’s mailboxes</CardTitle>
        <CardDescription>Scam Stop reads new mail itself. You only see warnings about suspicious emails, never the rest of {PERSON.name}’s mail.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <ul className="divide-y">
          {!gmail && (
            <li className="flex flex-wrap items-center gap-3 py-3">
              <div className="grid flex-1">
                <strong>Gmail</strong>
                <span className="text-sm text-muted-foreground">Not connected yet. {PERSON.name} connects it themselves from a link you send.</span>
              </div>
              <Badge className="h-6 bg-muted px-3 text-sm font-bold text-foreground">Not connected</Badge>
            </li>
          )}
          {mailboxes.map((mailbox) => (
            <li key={mailbox.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="grid flex-1">
                <strong>{mailbox.kind === 'gmail' ? 'Gmail' : `Forwarded inbox${mailbox.label ? ` (${mailbox.label})` : ''}`}</strong>
                <span className="text-sm text-muted-foreground">
                  {mailbox.status === 'connected'
                    ? mailbox.last_checked
                      ? `Last checked ${formatTime(mailbox.last_checked)} · ${mailbox.checked} ${mailbox.checked === 1 ? 'message' : 'messages'} checked`
                      : 'Waiting for the first check'
                    : mailbox.status === 'disconnected'
                      ? `${PERSON.name} disconnected it. A new invite link connects it again.`
                      : (mailbox.last_error ?? 'Google refused the connection.')}
                </span>
              </div>
              <Badge className={cn('h-6 px-3 text-sm font-bold', STATUS_STYLE[mailbox.status])}>{STATUS_WORD[mailbox.status]}</Badge>
            </li>
          ))}
        </ul>
        <Button variant={gmail?.status === 'connected' ? 'outline' : 'default'} className="h-11 w-fit px-5 text-base" onClick={onInvite}>
          {gmail ? `Send ${PERSON.name} a new invite link` : `Invite ${PERSON.name} to connect Gmail`}
        </Button>
      </CardContent>
    </Card>
  )
}

function Activity({ state }: { state: KinGuardState }) {
  const seen = channelActivity(state)
  return (
    <ul className="divide-y">
      {[...CHANNELS, 'Email'].map((channel) => {
        const item = seen[channel]
        return (
          <li key={channel} className="flex items-center gap-3 py-3">
            <div className="grid flex-1">
              <strong>{channel}</strong>
              <span className="text-sm text-muted-foreground">{item ? `${item.count} ${item.count === 1 ? 'message' : 'messages'} flagged or shared, latest ${formatTime(item.last)}` : 'No messages yet'}</span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** Pairs the Scam Stop Android app with this person. The phone cannot sign in, so it uses a code instead. */
function PhonePairing() {
  const [pairedAt, setPairedAt] = useState<string | null>(null)
  const [code, setCode] = useState<string | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<{ paired_at: string | null }>(scoped('/phone'))
      .then((answer) => setPairedAt(answer.paired_at))
      .catch(() => undefined)
  }, [])

  async function pair() {
    try {
      const answer = await post<{ code: string }>(scoped('/phone'))
      setCode(answer.code)
      setPairedAt(new Date().toISOString())
      setError('')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-bold">{PERSON.name}’s phone app</CardTitle>
        <CardDescription>
          The Scam Stop app on {PERSON.name}’s Android phone reads their texts. It pairs with a code instead of signing in. A new code unpairs the previous phone.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">{pairedAt ? `A phone was paired on ${formatTime(pairedAt)}.` : 'No phone is paired yet.'}</p>
        {code && (
          <div className="grid gap-1 rounded-lg bg-muted p-4">
            <span className="text-sm text-muted-foreground">Type this into the app under Settings → Pairing code. It is shown only once.</span>
            <code className="text-2xl font-bold tracking-wider select-all">{code}</code>
          </div>
        )}
        {error && <p className="text-sm text-warn">{error}</p>}
        <Button variant={pairedAt ? 'outline' : 'default'} className="h-11 w-fit px-5 text-base" onClick={pair}>
          {pairedAt ? 'Pair a new phone' : 'Pair the phone app'}
        </Button>
      </CardContent>
    </Card>
  )
}
