import { CalendarClock, Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { post, scoped } from '@/api'
import { Button } from '@/components/ui/button'
import { actionLabel, approveEffect, approveLabel, formatTime, PERSON, rejectEffect, reviewDeadline, reviewQuestion } from '@/format'
import type { GuardianBrief, Review } from '@/types'
import { cn } from '@/lib/utils'

type Props = {
  review: Review
  brief?: GuardianBrief
  /** Called after the answer is saved, with a sentence to show the person deciding. */
  onDecided: (message: string) => void
  /** Inside a list that already has its own frame, skip the card border. */
  embedded?: boolean
}

/** One question, two answers, and a line under each answer saying what it does. */
export function ReviewCard({ review, brief, onDecided, embedded }: Props) {
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

  const deadline = reviewDeadline(review)
  const waitUntil = review.not_before && new Date(review.not_before).getTime() > now ? review.not_before : null

  async function decide(approved: boolean) {
    setBusy(true)
    try {
      await post(scoped(`/reviews/${review.review_id}/decision`), { approved })
      const what = review.proposed_action ? actionLabel(review.proposed_action.type, review.proposed_action.details) : 'This alert'
      onDecided(approved ? `Done: ${what}.` : `Understood. ${what} was not done.`)
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save your answer. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={cn('grid gap-4', embedded ? '' : 'rounded-xl border-2 border-warn-edge bg-card p-4')} aria-label="Waiting for your decision">
      {!embedded && (
        <p className="flex items-center gap-2 text-xs font-bold tracking-wider text-warn uppercase">
          <Clock className="size-4" aria-hidden="true" />
          {review.audience === 'PERSON' ? `${PERSON.name} needs to decide` : 'Waiting for your decision'}
        </p>
      )}
      <h3 className="text-lg leading-snug font-bold">{reviewQuestion(review)}</h3>

      {deadline && (
        <p className="flex items-center gap-2 text-sm font-bold text-warn">
          <CalendarClock className="size-4" aria-hidden="true" />
          {deadline}
        </p>
      )}
      {waitUntil && <p className="text-sm font-bold text-warn">You can confirm this after {formatTime(waitUntil)}. Saying no is always possible.</p>}

      <div className="grid gap-4">
        <div className="grid content-start gap-1.5">
          <Button className="h-11 w-full px-4 text-base" disabled={busy || Boolean(waitUntil)} onClick={() => decide(true)}>
            {approveLabel(review)}
          </Button>
          <p className="text-sm text-muted-foreground">{approveEffect(review)}</p>
        </div>
        <div className="grid content-start gap-1.5">
          <Button variant="outline" className="h-11 w-full px-4 text-base" disabled={busy} onClick={() => decide(false)}>
            No, leave it
          </Button>
          <p className="text-sm text-muted-foreground">{rejectEffect(review)}</p>
        </div>
      </div>

      {brief && (
        <Button variant="link" className="h-auto w-fit p-0 text-sm" render={<a href={brief.whatsapp_link} target="_blank" rel="noreferrer" />}>
          Send this question to my WhatsApp
        </Button>
      )}
    </section>
  )
}
