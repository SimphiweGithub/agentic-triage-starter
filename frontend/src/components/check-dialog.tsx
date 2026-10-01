import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { post, scoped } from '@/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { PERSON } from '@/format'
import type { Decision } from '@/types'

type Withheld = { status: 'withheld'; reason: string }
type Intake = Decision | Withheld

function describe(result: Intake): string {
  if ('status' in result && result.status === 'withheld') return `Not stored: ${result.reason}`
  const decision = result as Decision
  return decision.labels.threat === 'BENIGN' ? `Looks safe (${decision.incident_id})` : `Checked: alert ${decision.incident_id}`
}

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called with the alert an intake produced, so the page behind can refresh. */
  onChecked: (incidentId: string | null) => void
}

/** Paste an SMS or WhatsApp message the person received. Their email is scanned on its own, so it is not offered here. */
export function CheckDialog({ open, onOpenChange, onChecked }: Props) {
  const [text, setText] = useState('')
  const [sender, setSender] = useState('')
  const [channel, setChannel] = useState('sms')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const outcome = await post<Intake>(scoped('/intake/share'), { text, sender, channel })
      toast.success(describe(outcome))
      setText('')
      onChecked('incident_id' in outcome ? outcome.incident_id : null)
      onOpenChange(false)
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not check the message.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] gap-4 overflow-y-auto p-6 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">Check a message</DialogTitle>
          <DialogDescription>Paste an SMS or WhatsApp message {PERSON.name} received and Scam Stop will say whether it is safe. Emails are checked automatically once {PERSON.name} connects their Gmail.</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="share-text">Message</Label>
            <Textarea id="share-text" value={text} onChange={(event) => setText(event.target.value)} rows={4} required className="text-base" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="share-from">From</Label>
            <Input id="share-from" value={sender} onChange={(event) => setSender(event.target.value)} placeholder="YourBank" className="h-10 text-base" />
          </div>
          <div className="grid gap-1.5">
            <Label id="share-channel">Channel</Label>
            <ToggleGroup variant="outline" aria-labelledby="share-channel" value={[channel]} onValueChange={(next: string[]) => next[0] && setChannel(next[0])}>
              <ToggleGroupItem value="sms" className="h-10 px-4">
                SMS
              </ToggleGroupItem>
              <ToggleGroupItem value="whatsapp" className="h-10 px-4">
                WhatsApp
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
          <Button type="submit" className="h-11 w-fit px-6 text-base" disabled={busy || !text.trim()}>
            {busy ? 'Checking…' : 'Check message'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
