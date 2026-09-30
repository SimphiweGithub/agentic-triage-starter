import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, post } from '@/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PERSON, formatTime } from '@/format'
import type { Invite } from '@/types'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  personId: string
  /** Called when an invite is made or cancelled, so the page behind can refresh. */
  onChanged: () => void
}

function linkFor(invite: Invite): string {
  return `${window.location.origin}/?invite=${invite.token}`
}

function whatsappFor(invite: Invite): string {
  const text = `Hello ${PERSON.name}. I would like to set up KinGuard to help watch for scam emails. Open this link to connect your Gmail. It takes a minute and you can stop it any time: ${linkFor(invite)}`
  return `https://wa.me/?text=${encodeURIComponent(text)}`
}

/** Make a single-use link the person opens to connect their own Gmail. */
export function InviteDialog({ open, onOpenChange, personId, onChanged }: Props) {
  const [invites, setInvites] = useState<Invite[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setInvites(await api<Invite[]>(`/people/${personId}/invites`))
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not load the invite links.')
    }
  }, [personId])

  useEffect(() => {
    if (!open) return
    const first = setTimeout(load, 0)
    return () => clearTimeout(first)
  }, [open, load])

  async function create() {
    setBusy(true)
    try {
      await post<Invite>(`/people/${personId}/invites`)
      await load()
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not make a link.')
    } finally {
      setBusy(false)
    }
  }

  async function cancel(invite: Invite) {
    try {
      await post(`/people/${personId}/invites/${invite.token}/cancel`)
      toast('Link cancelled. It no longer works.')
      await load()
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not cancel that link.')
    }
  }

  async function copy(invite: Invite) {
    try {
      await navigator.clipboard.writeText(linkFor(invite))
      toast.success('Link copied')
    } catch {
      toast.error('Could not copy. Select the link and copy it by hand.')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] gap-4 overflow-y-auto p-6 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">Invite {PERSON.name} to connect Gmail</DialogTitle>
          <DialogDescription>
            {PERSON.name} opens the link, signs in with Google and allows KinGuard to read their email. You never see their password, and you only see warnings about suspicious emails. Each link works once and lasts a week.
          </DialogDescription>
        </DialogHeader>

        <Button className="h-11 w-fit px-5 text-base" disabled={busy} onClick={create}>
          {invites.length > 0 ? 'Make another link' : 'Make a link'}
        </Button>

        {invites.length > 0 && (
          <ul className="grid gap-3">
            {invites.map((invite) => (
              <li key={invite.token} className="grid gap-2 rounded-xl border p-3">
                <p className="text-sm text-muted-foreground">Works until {formatTime(invite.expires_at)}</p>
                <code className="rounded-md bg-muted px-2 py-1 text-xs break-all">{linkFor(invite)}</code>
                <div className="flex flex-wrap gap-2">
                  <Button className="h-10 px-4" onClick={() => copy(invite)}>
                    Copy link
                  </Button>
                  <Button variant="outline" className="h-10 px-4" render={<a href={whatsappFor(invite)} target="_blank" rel="noreferrer" />}>
                    Send on WhatsApp
                  </Button>
                  <Button variant="ghost" className="h-10 px-4 text-destructive" onClick={() => cancel(invite)}>
                    Cancel link
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
