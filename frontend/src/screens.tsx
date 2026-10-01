import { SignInButton, UserButton } from './auth'
import { MailCheck, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { api, post } from './api'
import { Button } from './components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from './components/ui/dialog'
import { ROLE } from './circle'
import { formatTime, reviewQuestion } from './format'
import type { InviteLook, Me, Review } from './types'

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
      <ShieldCheck className="size-5" aria-hidden="true" /> Scam Stop
    </p>
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
      .catch(() => live && setLook({ valid: false, problem: 'This link could not be checked. Try again in a moment.', person_name: null, role: null, invitee_name: null }))
    return () => {
      live = false
    }
  }, [token])

  async function connect() {
    setBusy(true)
    try {
      await post(`/invites/${token}/accept`)
      toast.success(look?.role ? `You are now in ${look.person_name}’s care circle.` : 'Your Gmail is connected. Thank you.')
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

  if (look.role) {
    const role = ROLE[look.role]
    return (
      <Centered>
        <CardHeader>
          <Brand />
          <CardTitle className="text-3xl leading-tight font-bold">
            {look.invitee_name ? `Hello ${look.invitee_name}` : 'Hello'}
          </CardTitle>
          <CardDescription className="text-base text-foreground">
            You are invited to help keep {look.person_name} safe from scams, as their {role.label.toLowerCase()}.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <p className="text-base">{role.summary}</p>
          {signedIn ? (
            <Button className="h-12 w-full text-lg" disabled={busy} onClick={connect}>
              {busy ? 'Joining…' : `Join ${look.person_name}’s circle`}
            </Button>
          ) : (
            <SignInButton forceRedirectUrl={window.location.href} signUpForceRedirectUrl={window.location.href}>
              <Button className="h-12 w-full text-lg">Sign in to join</Button>
            </SignInButton>
          )}
          <p className="text-sm text-muted-foreground">The link works once and lasts a week.</p>
        </CardContent>
      </Centered>
    )
  }

  return (
    <Centered>
      <CardHeader>
        <Brand />
        <CardTitle className="text-3xl leading-tight font-bold">Hello {look.person_name}</CardTitle>
        <CardDescription className="text-base text-foreground">Someone who cares about you would like Scam Stop to watch your Gmail for scam emails.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <ul className="grid gap-3 text-base">
          <li className="flex gap-3">
            <MailCheck className="mt-1 size-5 shrink-0 text-info" aria-hidden="true" />
            Scam Stop reads new emails only to spot scams.
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
          You will be asked to sign in with Google and to allow Scam Stop to read your email. Not sure? You can close this page and come back later, the link stays valid for a week.
        </p>
      </CardContent>
    </Centered>
  )
}

/** What the protected person sees: that it is working, and a way to stop it. Never the alerts. */
export function PersonHome({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [warnings, setWarnings] = useState<{ incident_id: string; message: string }[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [answering, setAnswering] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const mailbox = me.mailbox
  const personId = me.person?.id

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!personId) return
    let live = true
    const refresh = async () => {
      try {
        const [nextWarnings, nextReviews] = await Promise.all([
          api<{ incident_id: string; message: string }[]>(`/people/${personId}/outbox`),
          api<Review[]>(`/people/${personId}/person/reviews?status=PENDING`),
        ])
        if (live) {
          setWarnings(nextWarnings)
          setReviews(nextReviews)
        }
      } catch {
        if (live) toast.error('Could not load your Scam Stop messages. Retrying.', { id: 'person-refresh' })
      }
    }
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, 5000)
    return () => {
      live = false
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [personId])

  async function answerIncident(incidentId: string, legitimate: boolean) {
    setAnswering(incidentId)
    try {
      await post(`/people/${personId}/incidents/${incidentId}/feedback`, { legitimate })
      toast.success('Your answer was saved.')
      setWarnings((current) => current.filter((item) => item.incident_id !== incidentId))
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save your answer.')
    } finally {
      setAnswering(null)
    }
  }

  async function answerReview(reviewId: string, approved: boolean) {
    setAnswering(reviewId)
    try {
      await post(`/people/${personId}/reviews/${reviewId}/decision`, { approved })
      setReviews((current) => current.filter((item) => item.review_id !== reviewId))
      toast.success('Your decision was saved.')
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save your decision.')
    } finally {
      setAnswering(null)
    }
  }

  async function disconnect() {
    setBusy(true)
    try {
      await post('/me/disconnect')
      toast('Scam Stop no longer reads your Gmail.')
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
          {connected ? 'You’re connected' : mailbox?.status === 'problem' ? 'Scam Stop can’t read your Gmail right now' : 'You’re disconnected'}
        </CardTitle>
        <CardDescription className="text-base text-foreground">
          {connected
            ? mailbox?.last_checked
              ? `Scam Stop last checked your Gmail on ${formatTime(mailbox.last_checked)}.`
              : 'Scam Stop will check your Gmail in a moment.'
            : mailbox?.status === 'problem'
              ? 'The person who looks after you has been told, and will send you a new link.'
              : 'Scam Stop no longer reads your email. To connect again, ask for a new link.'}
        </CardDescription>
      </CardHeader>
      {reviews.length > 0 && (
        <CardContent className="grid gap-4">
          <h2 className="text-lg font-bold">Decisions waiting for you</h2>
          {reviews.map((review) => {
            const waiting = review.not_before && new Date(review.not_before).getTime() > now
            return (
              <section key={review.review_id} className="grid gap-3 rounded-lg border p-4">
                <p className="font-medium">{reviewQuestion(review)}</p>
                {waiting && <p className="text-sm">You can confirm this after {formatTime(review.not_before!)}. You can say no now.</p>}
                <div className="flex flex-wrap gap-2">
                  <Button disabled={Boolean(waiting) || Boolean(answering)} onClick={() => answerReview(review.review_id, true)}>Yes, approve</Button>
                  <Button variant="outline" disabled={Boolean(answering)} onClick={() => answerReview(review.review_id, false)}>No, leave it</Button>
                </div>
              </section>
            )
          })}
        </CardContent>
      )}
      {warnings.length > 0 && (
        <CardContent className="grid gap-4">
          <h2 className="text-lg font-bold">Warnings for you</h2>
          {[...new Map(warnings.map((item) => [item.incident_id, item])).values()].map((warning) => (
            <section key={warning.incident_id} className="grid gap-3 rounded-lg border p-4">
              <p>{warning.message}</p>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" disabled={Boolean(answering)} onClick={() => answerIncident(warning.incident_id, true)}>This is mine</Button>
                <Button variant="outline" disabled={Boolean(answering)} onClick={() => answerIncident(warning.incident_id, false)}>I did not agree to this</Button>
              </div>
            </section>
          ))}
        </CardContent>
      )}
      {connected && (
        <CardContent>
          <Button variant="outline" className="h-11 px-5 text-base" onClick={() => setConfirm(true)}>
            Stop Scam Stop reading my Gmail
          </Button>
        </CardContent>
      )}
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold">Stop Scam Stop reading your Gmail?</DialogTitle>
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

/** A trusted helper sees whose circle they are in and what that means. Alerts and calls stay with the family. */
export function HelperHome({ me }: { me: Me }) {
  return (
    <Centered>
      <CardHeader>
        <div className="flex items-center justify-between">
          <Brand />
          <UserButton />
        </div>
        <span className="w-fit rounded-full bg-helper-soft px-3 py-0.5 text-sm font-bold text-helper">{ROLE.helper.label}</span>
        <CardTitle className="text-3xl leading-tight font-bold">Thank you for helping</CardTitle>
        <CardDescription className="text-base text-foreground">
          You are a trusted helper for {me.people.map((person) => person.name).join(', ') || 'someone'}. {ROLE.helper.summary}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground">There is nothing to do here. Their family may ask you to check on them in person.</p>
      </CardContent>
    </Centered>
  )
}
