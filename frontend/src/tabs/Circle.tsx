import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { post } from '@/api'
import { ACCESS_WORD, INVITE_ROLES, PERMISSIONS, ROLE, canApprove, circleInviteLink, initial, type CircleInvite, type CircleMember, type CircleRole } from '@/circle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PERSON, formatTime } from '@/format'
import { cn } from '@/lib/utils'

type Props = {
  personId: string
  members: CircleMember[]
  /** False while the server has no circle route: only the person and the signed-in user are shown. */
  listed: boolean | null
  you: CircleMember | undefined
  /** Whether a guardian is enrolled, from the engine's world. */
  guardian: boolean | undefined
  onChanged: () => void
}

const ROLE_ORDER: CircleRole[] = ['protected', 'next_of_kin', 'caregiver', 'helper']

export function Circle({ personId, members, listed, you, guardian, onChanged }: Props) {
  const sorted = [...members].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || Number(Boolean(a.pending)) - Number(Boolean(b.pending)))
  const mayInvite = canApprove(you?.role)
  const [removing, setRemoving] = useState<string | null>(null)

  async function remove(member: CircleMember) {
    setRemoving(member.id)
    try {
      await post(`/people/${personId}/circle/${member.id}/remove`)
      toast(`${member.name || 'They'} left ${PERSON.name}’s circle.`)
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not remove them. Try again.')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <>
      <header className="grid gap-1">
        <h1 className="text-3xl font-bold tracking-tight">{PERSON.name}’s care circle</h1>
        <p className="max-w-3xl text-lg text-muted-foreground">Everyone who helps keep {PERSON.name} safe, and what each person is allowed to see and do. {PERSON.name} can see this list too.</p>
      </header>

      {listed === false && (
        <p className="rounded-xl border border-info/30 bg-info-soft px-4 py-3 text-base text-info">
          The server does not list the circle yet, so only {PERSON.name} and you are shown. Invites by role will work once it does.
        </p>
      )}

      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="People in the circle">
        {sorted.map((member) => (
          <li key={member.id} className={cn('grid content-start gap-3 rounded-xl bg-card p-5 ring-1 ring-foreground/10', member.role === 'protected' && 'ring-2 ring-primary')}>
            <div className="flex items-center gap-3">
              <span className={cn('grid size-12 shrink-0 place-items-center rounded-full text-lg font-bold', ROLE[member.role].avatar)}>{initial(member.name || ROLE[member.role].label)}</span>
              <span className="grid min-w-0">
                <strong className="truncate text-lg">{member.you ? 'You' : member.name || ROLE[member.role].label}</strong>
                {member.relation && <span className="text-sm text-muted-foreground">{member.relation}</span>}
              </span>
            </div>
            <RoleChip role={member.role} />
            <p className="text-base text-muted-foreground">{ROLE[member.role].summary}</p>
            <span className="text-sm text-muted-foreground">{member.status}</span>
            {mayInvite && !member.you && !member.pending && (member.role === 'caregiver' || member.role === 'helper') && (
              <Button variant="ghost" className="h-10 w-fit px-3 text-destructive" disabled={removing === member.id} onClick={() => remove(member)}>
                Remove from the circle
              </Button>
            )}
          </li>
        ))}
      </ul>

      <div className="grid items-start gap-6 2xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section aria-labelledby="perm" className="grid gap-4 rounded-xl bg-card p-5 ring-1 ring-foreground/10">
          <div className="grid gap-1">
            <h2 id="perm" className="text-lg font-bold">
              What each role can do
            </h2>
            <p className="text-muted-foreground">Roles decide access. The server checks every request against them, not just this screen.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-base">
              <thead>
                <tr>
                  <th scope="col" className="py-2 text-left text-sm font-normal text-muted-foreground">
                    Permission
                  </th>
                  {ROLE_ORDER.map((role) => (
                    <th key={role} scope="col" className="px-1.5 py-2">
                      <RoleChip role={role} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {PERMISSIONS.map((row) => (
                  <tr key={row.label} className="border-t">
                    <th scope="row" className="min-w-56 py-3 pr-2 text-left font-normal">
                      {row.label}
                    </th>
                    {ROLE_ORDER.map((role) => (
                      <td key={role} className={cn('text-center font-bold', row.access[role] === 'no' ? 'text-muted-foreground' : 'text-primary')}>
                        {ACCESS_WORD[row.access[role]]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-muted-foreground">
            {guardian === false
              ? `There is no next of kin, so ${PERSON.name} decides bank actions themselves after a cooling-off.`
              : `If there is no next of kin, ${PERSON.name} decides bank actions themselves after a cooling-off.`}
          </p>
        </section>

        {mayInvite ? (
          <InviteForm personId={personId} onChanged={onChanged} />
        ) : (
          <section className="grid gap-2 rounded-xl bg-card p-5 ring-1 ring-foreground/10">
            <h2 className="text-lg font-bold">Invite someone</h2>
            <p className="text-muted-foreground">Only the next of kin can invite people. Ask them to add anyone else who helps.</p>
          </section>
        )}
      </div>
    </>
  )
}

export function RoleChip({ role, className }: { role: CircleRole; className?: string }) {
  return <Badge className={cn('h-6 px-3 text-sm font-bold', ROLE[role].chip, className)}>{ROLE[role].label}</Badge>
}

const INVITE_NOTE: Record<CircleRole, string> = {
  protected: '',
  next_of_kin: 'Approves bank actions. One per person.',
  caregiver: 'Sees alerts and calls, checks in, cannot approve money.',
  helper: 'A neighbour or friend. Sees only who is in the circle.',
}

function InviteForm({ personId, onChanged }: { personId: string; onChanged: () => void }) {
  const [name, setName] = useState('')
  const [role, setRole] = useState<CircleRole>('caregiver')
  const [busy, setBusy] = useState(false)
  const [made, setMade] = useState<CircleInvite | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const invite = await post<CircleInvite>(`/people/${personId}/circle/invites`, { name: name.trim(), role })
      setMade(invite)
      setName('')
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error && caught.message !== 'Not Found' ? caught.message : 'The server cannot make circle invites yet.')
    } finally {
      setBusy(false)
    }
  }

  async function copy(invite: CircleInvite) {
    try {
      await navigator.clipboard.writeText(circleInviteLink(invite))
      toast.success('Link copied')
    } catch {
      toast.error('Could not copy. Select the link and copy it by hand.')
    }
  }

  return (
    <form onSubmit={create} aria-labelledby="invite" className="grid max-w-xl gap-4 rounded-xl bg-card p-5 ring-2 ring-primary">
      <h2 id="invite" className="text-lg font-bold">
        Invite someone
      </h2>
      <div className="grid gap-2">
        <Label htmlFor="invite-name">Their name</Label>
        <Input id="invite-name" className="h-11 text-base" value={name} required onChange={(event) => setName(event.target.value)} />
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">Their role</legend>
        {INVITE_ROLES.map((item) => (
          <label key={item} className={cn('flex cursor-pointer gap-3 rounded-lg border p-3', role === item && 'border-2 border-primary bg-primary/5')}>
            <input type="radio" name="invite-role" className="mt-1 size-5 accent-primary" checked={role === item} onChange={() => setRole(item)} />
            <span className="grid gap-0.5">
              <strong>{ROLE[item].label}</strong>
              <span className="text-sm text-muted-foreground">{INVITE_NOTE[item]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <Button type="submit" className="h-11 text-base" disabled={busy || !name.trim()}>
        {busy ? 'Making the link…' : 'Create invite link'}
      </Button>
      {made && (
        <div className="grid gap-2 rounded-lg border p-3">
          <p className="text-sm text-muted-foreground">
            For {made.name} as {ROLE[made.role].label.toLowerCase()} · works until {formatTime(made.expires_at)}
          </p>
          <code className="rounded-md bg-muted px-2 py-1 text-xs break-all">{circleInviteLink(made)}</code>
          <Button className="h-10 w-fit px-4" type="button" onClick={() => copy(made)}>
            Copy link
          </Button>
        </div>
      )}
      <p className="text-sm text-muted-foreground">{PERSON.name} sees everyone in the circle and can remove anyone but the next of kin.</p>
    </form>
  )
}
