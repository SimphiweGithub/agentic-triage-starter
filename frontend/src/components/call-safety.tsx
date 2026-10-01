import { PhoneIncoming } from 'lucide-react'
import { useState } from 'react'
import { CALL_RULE, CALL_SCAMS } from '@/callScams'
import { Button } from '@/components/ui/button'
import { CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'

const KEY = 'kinguard.callSafety'

function remembered(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off'
  } catch {
    return true
  }
}

/**
 * The prompt shown when a call comes in. A web page cannot see calls, so the Android app is meant to open
 * this with `incoming`; no number or caller detail is ever passed in or stored.
 */
export function CallScamsDialog({ open, onOpenChange, incoming }: { open: boolean; onOpenChange: (open: boolean) => void; incoming: boolean }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto p-6 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">{incoming ? 'You just received a call' : 'Common call scams'}</DialogTitle>
          <DialogDescription>{incoming ? 'KinGuard did not listen to it. Here are common call scams to watch out for.' : 'Watch out for these when someone calls you.'}</DialogDescription>
        </DialogHeader>
        <ul className="grid gap-3">
          {CALL_SCAMS.map((scam) => (
            <li key={scam.id} className="rounded-lg border p-3">
              <p className="font-medium">{scam.title}</p>
              <p className="text-sm">{scam.text}</p>
            </li>
          ))}
        </ul>
        <p className="font-medium">{CALL_RULE}</p>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>Got it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** On the protected person's home screen: a switch, the tips on demand, and (dev only) a pretend incoming call. */
export function CallSafetyCard() {
  const [on, setOn] = useState(remembered)
  const [open, setOpen] = useState(false)
  const [incoming, setIncoming] = useState(false)

  function toggle(next: boolean) {
    setOn(next)
    try {
      localStorage.setItem(KEY, next ? 'on' : 'off')
    } catch {
      // Remembering the choice is a convenience only.
    }
  }

  function show(isIncoming: boolean) {
    setIncoming(isIncoming)
    setOpen(true)
  }

  return (
    <CardContent className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-bold">
          <PhoneIncoming className="size-5 text-info" aria-hidden="true" /> Call safety
        </h2>
        <Switch checked={on} onCheckedChange={toggle} aria-label="Remind me about call scams when I get a call" />
      </div>
      <p className="text-sm text-muted-foreground">
        {on ? 'On the KinGuard Android app, you will get a reminder when a call comes in. KinGuard never listens to your calls.' : 'Reminders are off.'}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => show(false)}>
          Show me common call scams
        </Button>
        {import.meta.env.DEV && on && (
          <Button variant="ghost" onClick={() => show(true)}>
            Simulate incoming call (dev)
          </Button>
        )}
      </div>
      <CallScamsDialog open={open} onOpenChange={setOpen} incoming={incoming} />
    </CardContent>
  )
}
