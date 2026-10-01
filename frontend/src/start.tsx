import { HeartHandshake, House, ShieldCheck, Stethoscope, UserRound } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { LOCAL_DEMO, SignInButton, SignUpButton, UserButton } from './auth'
import { ROLE, type CircleRole } from './circle'
import { AddPersonForm } from './components/add-person-form'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Input } from './components/ui/input'
import { Label } from './components/ui/label'
import { cn } from './lib/utils'

const INTENT_KEY = 'kinguard.intent'
const ORDER: CircleRole[] = ['next_of_kin', 'caregiver', 'helper', 'protected']

const CHOICE: Record<CircleRole, { title: string; text: string; icon: ReactNode }> = {
  next_of_kin: { title: 'I look after a family member', text: 'Set up Scam Stop for them. You approve anything about their money.', icon: <House aria-hidden="true" /> },
  caregiver: { title: 'I’m their caregiver', text: 'You help day to day. Their family sends you an invite.', icon: <Stethoscope aria-hidden="true" /> },
  helper: { title: 'I’m a trusted helper', text: 'A neighbour or friend. Their family sends you an invite.', icon: <HeartHandshake aria-hidden="true" /> },
  protected: { title: 'I’m being looked after', text: 'Your family sends you a link to connect your Gmail.', icon: <UserRound aria-hidden="true" /> },
}

/** The role chosen before signing in, remembered so the first screen after sign-in can continue from it. */
function savedIntent(): CircleRole | null {
  try {
    const value = localStorage.getItem(INTENT_KEY)
    return ORDER.find((role) => role === value) ?? null
  } catch {
    return null
  }
}

function saveIntent(role: CircleRole | null): void {
  try {
    if (role) localStorage.setItem(INTENT_KEY, role)
    else localStorage.removeItem(INTENT_KEY)
  } catch {
    // Remembering the choice is a convenience: the screen after sign-in asks again.
  }
}

function Frame({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className="grid min-h-svh place-items-center p-4">
      <Card className={cn('w-full p-2', wide ? 'max-w-2xl' : 'max-w-lg')}>{children}</Card>
    </main>
  )
}

function Brand({ account }: { account?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <p className="flex items-center gap-2 text-lg font-bold">
        <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
          <ShieldCheck className="size-5" aria-hidden="true" />
        </span>
        Scam Stop
      </p>
      {account && <UserButton />}
    </div>
  )
}

function RoleChoices({ value, onChange }: { value: CircleRole | null; onChange: (role: CircleRole) => void }) {
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="sr-only">Your role</legend>
      {ORDER.map((role) => (
        <label
          key={role}
          className={cn(
            'flex cursor-pointer gap-3 rounded-xl border bg-card p-4 transition hover:border-primary',
            value === role && 'border-primary ring-2 ring-primary',
          )}
        >
          <input type="radio" name="start-role" className="sr-only" checked={value === role} onChange={() => onChange(role)} />
          <span className={cn('grid size-11 shrink-0 place-items-center rounded-lg [&>svg]:size-5', ROLE[role].chip)}>{CHOICE[role].icon}</span>
          <span className="grid gap-0.5">
            <strong className="text-base leading-snug">{CHOICE[role].title}</strong>
            <span className="text-sm text-muted-foreground">{CHOICE[role].text}</span>
          </span>
        </label>
      ))}
    </fieldset>
  )
}

/** Signed out: pick how you are involved, then sign in or create an account. */
export function StartScreen() {
  const [role, setRole] = useState<CircleRole | null>(savedIntent)

  function pick(next: CircleRole) {
    setRole(next)
    saveIntent(next)
  }

  return (
    <Frame wide>
      <CardHeader className="gap-2">
        <Brand />
        <CardTitle className="text-3xl leading-tight font-bold">Keep the people you love safe from scams</CardTitle>
        <CardDescription className="text-base">Scam messages, risky calls and unwanted debit orders are caught and explained. First, how are you involved?</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <RoleChoices value={role} onChange={pick} />
        <div className="flex flex-wrap items-center gap-3">
          <SignUpButton>
            <Button className="h-11 px-6 text-base" disabled={!role}>
              Create an account
            </Button>
          </SignUpButton>
          <SignInButton>
            <Button variant="outline" className="h-11 px-6 text-base" disabled={!role}>
              Sign in
            </Button>
          </SignInButton>
          {!role && <span className="text-sm text-muted-foreground">Choose one to continue.</span>}
        </div>
      </CardContent>
    </Frame>
  )
}

/** The invite token in a pasted link (`…/?invite=abc`) or the bare token itself. */
function tokenFrom(text: string): string {
  const trimmed = text.trim()
  try {
    return new URL(trimmed).searchParams.get('invite') ?? ''
  } catch {
    return /^[\w-]{16,}$/.test(trimmed) ? trimmed : ''
  }
}

/**
 * Signed in but not linked to anyone yet. A family member sets up the person they look after; everyone else
 * joins through the invite they were sent, because a role is only ever given by whoever runs the circle.
 */
export function RoleStart({ onAdded }: { onAdded: () => void }) {
  const [role, setRole] = useState<CircleRole | null>(savedIntent)
  const [link, setLink] = useState('')
  const [problem, setProblem] = useState('')

  function pick(next: CircleRole | null) {
    setRole(next)
    saveIntent(next)
  }

  function openInvite(event: FormEvent) {
    event.preventDefault()
    const token = tokenFrom(link)
    if (!token) {
      setProblem('That does not look like a Scam Stop invite link. Copy the whole link from the message you were sent.')
      return
    }
    window.location.assign(`${window.location.pathname}?invite=${encodeURIComponent(token)}`)
  }

  if (!role) {
    return (
      <Frame wide>
        <CardHeader className="gap-2">
          <Brand account />
          <CardTitle className="text-3xl leading-tight font-bold">How are you involved?</CardTitle>
          <CardDescription className="text-base">Scam Stop shows each person what fits their role.</CardDescription>
        </CardHeader>
        <CardContent>
          <RoleChoices value={role} onChange={pick} />
        </CardContent>
      </Frame>
    )
  }

  const change = (
    <Button variant="link" className="h-auto w-fit p-0 text-sm" onClick={() => pick(null)}>
      Choose a different role
    </Button>
  )

  if (role === 'next_of_kin') {
    return (
      <Frame>
        <CardHeader className="gap-2">
          <Brand account />
          <span className={cn('w-fit rounded-full px-3 py-0.5 text-sm font-bold', ROLE.next_of_kin.chip)}>{ROLE.next_of_kin.label}</span>
          <CardTitle className="text-3xl leading-tight font-bold">Who are you looking after?</CardTitle>
          <CardDescription className="text-base">
            You become their next of kin. Next you can invite them to connect their Gmail, pair their phone, and invite carers and helpers.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <AddPersonForm
            onAdded={() => {
              saveIntent(null)
              onAdded()
            }}
          />
          {change}
        </CardContent>
      </Frame>
    )
  }

  return (
    <Frame>
      <CardHeader className="gap-2">
        <Brand account />
        <span className={cn('w-fit rounded-full px-3 py-0.5 text-sm font-bold', ROLE[role].chip)}>{ROLE[role].label}</span>
        <CardTitle className="text-3xl leading-tight font-bold">Open your invite</CardTitle>
        <CardDescription className="text-base">
          {role === 'protected'
            ? 'The family member who set up Scam Stop for you sends you a link. Open it on this device, or paste it here.'
            : 'The next of kin of the person you help sends you an invite from their Care circle page. Open it on this device, or paste it here.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <form className="grid gap-3" onSubmit={openInvite}>
          <div className="grid gap-1.5">
            <Label htmlFor="invite-link">Invite link</Label>
            <Input
              id="invite-link"
              className="h-11 text-base"
              value={link}
              placeholder={`${window.location.origin}/?invite=…`}
              onChange={(event) => {
                setLink(event.target.value)
                setProblem('')
              }}
            />
          </div>
          {problem && <p className="text-sm font-bold text-warn">{problem}</p>}
          <Button type="submit" className="h-11 w-fit px-6 text-base" disabled={!link.trim()}>
            Continue
          </Button>
        </form>
        <p className="text-sm text-muted-foreground">No invite yet? Ask them to send one. Invites work once and last a week.</p>
        {change}
        {LOCAL_DEMO && <p className="text-sm text-warn">Local demo: sign-in is off, so everyone shares one account.</p>}
      </CardContent>
    </Frame>
  )
}
