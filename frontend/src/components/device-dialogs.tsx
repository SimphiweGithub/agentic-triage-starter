import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { KIND_CHANNELS, KIND_LABEL, type DeviceKind, type useDevices } from '@/devices'
import { CHANNELS, PERSON, formatTime, type Channel } from '@/format'
import { DeviceIcon } from './status'

type Store = ReturnType<typeof useDevices>

const CHANNEL_HOW: Record<Channel, string> = {
  SMS: 'Texts are shared to Scam Stop from the phone',
  WhatsApp: 'Messages are shared or forwarded to Scam Stop',
}

/** One device: switch each channel on or off, rename it, or remove it. */
export function DeviceDialog({ deviceId, store, onClose }: { deviceId: string | null; store: Store; onClose: () => void }) {
  const device = store.devices.find((item) => item.id === deviceId)
  return (
    <Dialog open={Boolean(device)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90svh] gap-5 overflow-y-auto p-6 sm:max-w-lg">
        {device && <DeviceBody key={device.id} device={device} store={store} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

function DeviceBody({ device, store, onClose }: { device: Store['devices'][number]; store: Store; onClose: () => void }) {
  const [name, setName] = useState(device.name)
  const [confirm, setConfirm] = useState(false)

  function toggle(channel: Channel, next: boolean) {
    store.update(device.id, { on: next ? [...device.on, channel] : device.on.filter((item) => item !== channel) })
    toast(next ? `${channel} switched on for ${device.name}` : `${channel} switched off for ${device.name}. Messages there are not checked.`)
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-3 text-2xl font-bold">
          <span className="grid size-11 place-items-center rounded-xl bg-muted">
            <DeviceIcon kind={device.kind} className="size-6" />
          </span>
          {device.name}
        </DialogTitle>
        <DialogDescription>
          {KIND_LABEL[device.kind]} · added {formatTime(device.added)}
        </DialogDescription>
      </DialogHeader>

      <section className="grid gap-1">
        <h3 className="text-base font-bold">Channels on this device</h3>
        <ul className="divide-y">
          {CHANNELS.map((channel) => {
            const possible = KIND_CHANNELS[device.kind].includes(channel)
            const on = device.on.includes(channel)
            return (
              <li key={channel} className="flex items-center gap-4 py-3">
                <div className="grid min-w-0 flex-1">
                  <strong>{channel}</strong>
                  <span className="text-sm text-muted-foreground">{!possible ? 'Not on this device' : on ? CHANNEL_HOW[channel] : 'Switched off. Messages here are not checked.'}</span>
                </div>
                {possible && <Switch checked={on} onCheckedChange={(next: boolean) => toggle(channel, next)} aria-label={`${channel} on ${device.name}`} />}
              </li>
            )
          })}
        </ul>
      </section>

      <div className="flex items-end gap-2">
        <div className="grid flex-1 gap-1.5">
          <Label htmlFor="device-name">Rename</Label>
          <Input id="device-name" value={name} onChange={(event) => setName(event.target.value)} className="h-10 text-base" />
        </div>
        <Button variant="outline" className="h-10 px-4" disabled={!name.trim() || name.trim() === device.name} onClick={() => {
            store.update(device.id, { name: name.trim() })
            toast.success(`Renamed to ${name.trim()}`)
          }}>
          Save name
        </Button>
      </div>

      <DialogFooter>
        {confirm ? (
          <>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                store.remove(device.id)
                toast(`${device.name} removed`)
                onClose()
              }}
            >
              Yes, remove {device.name}
            </Button>
          </>
        ) : (
          <Button variant="ghost" className="text-destructive" onClick={() => setConfirm(true)}>
            Remove device
          </Button>
        )}
      </DialogFooter>
    </>
  )
}

/** Name it, pick the kind, choose every channel. */
export function AddDeviceDialog({ open, store, onClose, onAdded }: { open: boolean; store: Store; onClose: () => void; onAdded: (id: string) => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90svh] gap-5 overflow-y-auto p-6 sm:max-w-lg">
        {open && <AddBody store={store} onAdded={onAdded} />}
      </DialogContent>
    </Dialog>
  )
}

function AddBody({ store, onAdded }: { store: Store; onAdded: (id: string) => void }) {
  const [name, setName] = useState('')
  const [kind, setKind] = useState<DeviceKind>('phone')
  const [chosen, setChosen] = useState<Channel[]>(['SMS', 'WhatsApp'])
  const possible = KIND_CHANNELS[kind]
  const on = chosen.filter((channel) => possible.includes(channel))

  return (
    <>
      <DialogHeader>
        <DialogTitle className="text-xl font-bold">Add a device</DialogTitle>
        <DialogDescription>Choose every channel Scam Stop should check on it. Email is set up separately, from the person’s mailboxes.</DialogDescription>
      </DialogHeader>

      <div className="grid gap-1.5">
        <Label htmlFor="new-name">Name {PERSON.name} will recognise</Label>
        <Input id="new-name" value={name} onChange={(event) => setName(event.target.value)} placeholder={`${PERSON.name}'s phone`} className="h-10 text-base" />
      </div>

      <div className="grid gap-1.5">
        <Label id="new-kind">Kind of device</Label>
        <ToggleGroup variant="outline" aria-labelledby="new-kind" value={[kind]} onValueChange={(next: string[]) => next[0] && setKind(next[0] as DeviceKind)}>
          {(Object.keys(KIND_LABEL) as DeviceKind[]).map((item) => (
            <ToggleGroupItem key={item} value={item} className="h-10 gap-2 px-4">
              <DeviceIcon kind={item} className="size-4" />
              {KIND_LABEL[item]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <section className="grid gap-1">
        <h3 className="text-base font-bold">Channels to check</h3>
        <ul className="divide-y">
          {CHANNELS.map((channel) => {
            const ok = possible.includes(channel)
            return (
              <li key={channel} className="flex items-center gap-4 py-3">
                <div className="grid flex-1">
                  <strong>{channel}</strong>
                  <span className="text-sm text-muted-foreground">{ok ? CHANNEL_HOW[channel] : `Not on a ${KIND_LABEL[kind].toLowerCase()}`}</span>
                </div>
                <Switch
                  checked={ok && on.includes(channel)}
                  disabled={!ok}
                  aria-label={`Check ${channel}`}
                  onCheckedChange={(next: boolean) => setChosen(next ? [...chosen, channel] : chosen.filter((item) => item !== channel))}
                />
              </li>
            )
          })}
        </ul>
      </section>

      <DialogFooter>
        <Button className="h-10 px-5" onClick={() => {
            const added = store.add(name, kind, on)
            toast.success(`${added.name} added`)
            onAdded(added.id)
          }}>
          Save device
        </Button>
      </DialogFooter>
    </>
  )
}
