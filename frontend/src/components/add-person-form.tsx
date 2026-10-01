import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { post } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Me } from '@/types'

/** Name someone to look after. Used on the first-run screen and in the "add someone" dialog. */
export function AddPersonForm({ onAdded, submitLabel = 'Continue' }: { onAdded: (me: Me) => void; submitLabel?: string }) {
  const [name, setName] = useState('')
  const [relation, setRelation] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      onAdded(await post<Me>('/people', { name: name.trim(), relation: relation.trim() }))
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not add them. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <div className="grid gap-1.5">
        <Label htmlFor="person-name">Their name</Label>
        <Input id="person-name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={80} className="h-10 text-base" />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="person-relation">Who are they to you? (optional)</Label>
        <Input id="person-relation" value={relation} onChange={(event) => setRelation(event.target.value)} placeholder="Mom, Gran, Uncle…" maxLength={40} className="h-10 text-base" />
      </div>
      <Button type="submit" className="h-11 w-fit px-6 text-base" disabled={busy || !name.trim()}>
        {busy ? 'Adding…' : submitLabel}
      </Button>
    </form>
  )
}
