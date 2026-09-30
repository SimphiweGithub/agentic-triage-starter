import { SignInButton, SignUpButton, UserButton } from '@clerk/react'
import { MailCheck, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { api, post } from './api'
import { AddPersonForm } from './components/add-person-form'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from './components/ui/dialog'
import { formatTime } from './format'
import type { InviteLook, Me } from './types'

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-svh place-items-center p-4">
      <Card className="w-full max-w-lg p-2">{children}</Card>
    </main>
  )
}

function Brand() {
  return (
    <p className="flex items-center gap-2 font-bold text-primary">
      <ShieldCheck className="size-5" aria-hidden="true" /> KinGuard
    </p>
  )
}

export function SignedOutScreen() {
  return (
    <Centered>
      <CardHeader>
        <Brand />
        <CardTitle className="text-3xl leading-tight font-bold">Watch over the people you look after</CardTitle>
        <CardDescription className="text-base">
          Scam messages, predatory debit orders and creeping subscriptions are caught and explained. Anything that touches the bank waits for you.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <SignInButton>
          <Button className="h-11 px-6 text-base">Sign in</Button>
        </SignInButton>
        <SignUpButton>
          <Button variant="outline" className="h-11 px-6 text-base">
            Create an account
          </Button>
        </SignUpButton>
      </CardContent>
    </Centered>
  )
}

/**
 * Where the person lands from an invite link. Signed out, they are asked to sign in with Google;
 * signed in, one button links their Gmail. The wording is plain on purpose.
 */
export function ConnectScreen({ token, signedIn, onDone }: { token: string; signedIn: boolean; onDone: () => void }) {
  const [look, setLook] = useState<InviteLook | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    api<InviteLook>(`/invites/${token}`)
      .then((found) => live && setLook(found))
      .catch(() => live && setLook({ valid: false, problem: 'This link could not be checked. Try again in a moment.', person_name: null }))
    return () => {
      live = false
    }
  }, [token])

  async function connect() {
    setBusy(true)
    try {
      await post(`/invites/${token}/accept`)
      toast.success('Your Gmail is connected. Thank you.')
      onDone()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not connect. Try again.')
    } finally {
      setBusy(false)
    }
  }

  if (!look) return <p className="my-16 text-center text-muted-foreground">Checking your link…</p>

  if (!look.valid) {
    return (
      <Centered>
        <CardHeader>
          <Brand />
          <CardTitle className="text-2xl font-bold">This link can’t be used</CardTitle>
          <CardDescription className="text-base">{look.problem}</CardDescription>
        </CardHeader>
      </Centered>
    )
  }

  return (
    <Centered>
      <CardHeader>
        <Brand />
        <CardTitle className="text-3xl leading-tight font-bold">Hello {look.person_name}</CardTitle>
        <CardDescription className="text-base text-foreground">Someone who cares about you would like KinGuard to watch your Gmail for scam emails.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <ul className="grid gap-3 text-base">
          <li className="flex gap-3">
            <MailCheck className="mt-1 size-5 shrink-0 text-info" aria-hidden="true" />
            KinGuard reads new emails only to spot scams.
          </li>
          <li className="flex gap-3">
            <MailCheck className="mt-1 size-5 shrink-0 text-info" aria-hidden="true" />
            The person who invited you sees warnings about suspicious emails. They never see the rest of your mail.
          </li>
          <li className="flex gap-3">
            <MailCheck className="mt-1 size-5 shrink-0 text-info" aria-hidden="true" />
            You can stop this at any time, with one button.
          </li>
        </ul>
        {signedIn ? (
          <Button className="h-12 w-full text-lg" disabled={busy} onClick={connect}>
            {busy ? 'Connecting…' : 'Connect my Gmail'}
          </Button>
        ) : (
          <SignInButton forceRedirectUrl={window.location.href} signUpForceRedirectUrl={window.location.href}>
            <Button className="h-12 w-full text-lg">Connect my Gmail</Button>
          </SignInButton>
        )}
        <p className="text-sm text-muted-foreground">
          You will be asked to sign in with Google and to allow KinGuard to read your email. Not sure? You can close this page and come back later, the link stays valid for a week.
        </p>
      </CardContent>
    </Centered>
  )
}

/** What the protected person sees: that it is working, and a way to stop it. Never the alerts. */
export function PersonHome({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const mailbox = me.mailbox

  async function disconnect() {
    setBusy(true)
    try {
      await post('/me/disconnect')
      toast('KinGuard no longer reads your Gmail.')
      setConfirm(false)
      onChanged()
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not disconnect. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const connected = mailbox?.status === 'connected'
  return (
    <Centered>
      <CardHeader>
        <div className="flex items-center justify-between">
          <Brand />
          <UserButton />
        </div>
        <CardTitle className="text-3xl leading-tight font-bold">
          {connected ? 'You’re connected' : mailbox?.status === 'problem' ? 'KinGuard can’t read your Gmail right now' : 'You’re disconnected'}
        </CardTitle>
        <CardDescription className="text-base text-foreground">
          {connected
            ? mailbox?.last_checked
              ? `KinGuard last checked your Gmail on ${formatTime(mailbox.last_checked)}.`
              : 'KinGuard will check your Gmail in a moment.'
            : mailbox?.status === 'problem'
              ? 'The person who looks after you has been told, and will send you a new link.'
              : 'KinGuard no longer reads your email. To connect again, ask for a new link.'}
        </CardDescription>
      </CardHeader>
      {connected && (
        <CardContent>
          <Button variant="outline" className="h-11 px-5 text-base" onClick={() => setConfirm(true)}>
            Stop KinGuard reading my Gmail
          </Button>
        </CardContent>
      )}
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold">Stop KinGuard reading your Gmail?</DialogTitle>
            <DialogDescription>It stops straight away. To start again you would need a new link from the person who invited you.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Keep it connected
            </Button>
            <Button variant="destructive" disabled={busy} onClick={disconnect}>
              Yes, stop it
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Centered>
  )
}

export function AddPersonScreen({ onAdded }: { onAdded: () => void }) {
  return (
    <Centered>
      <CardHeader>
        <div className="flex items-center justify-between">
          <Brand />
          <UserButton />
        </div>
        <CardTitle className="text-3xl leading-tight font-bold">Who are you looking after?</CardTitle>
        <CardDescription className="text-base">You will then be able to invite them to connect their own Gmail. You never need their password. You can add more people later.</CardDescription>
      </CardHeader>
      <CardContent>
        <AddPersonForm onAdded={onAdded} />
      </CardContent>
    </Centered>
  )
}
