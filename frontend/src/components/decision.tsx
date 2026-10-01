import { Banknote, CalendarClock, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { approveEffect, approveLabel, formatTime, PERSON, rejectEffect, reviewDeadline, reviewQuestion } from '@/format'
import type { GuardianBrief, Review } from '@/types'
import { cn } from '@/lib/utils'
import { useDecide } from './use-decide'

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
  const { busy, waitUntil, decide } = useDecide(review, onDecided)
  const deadline = reviewDeadline(review)

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

type RowProps = {
  review: Review
  meta: string
  onDecided: (message: string) => void
  onOpen: () => void
  /** Why the signed-in user cannot answer, for roles that may only suggest. Undefined when they can. */
  blocked?: string
}

/** A decision as one row of the Today list: the question, where it came from, and the answers as buttons. */
export function DecisionRow({ review, meta, onDecided, onOpen, blocked }: RowProps) {
  const { busy, waitUntil, decide } = useDecide(review, onDecided)
  const deadline = reviewDeadline(review)
  return (
    <article className="grid gap-3 border-t border-warn-edge/40 px-5 py-4 first:border-t-0">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-warn-soft text-warn">
          <Banknote className="size-5" aria-hidden="true" />
        </span>
        <div className="grid min-w-0 flex-1 gap-1">
          <strong className="text-base leading-snug">{reviewQuestion(review)}</strong>
          <span className="text-sm text-muted-foreground">{meta}</span>
          {deadline && <span className="text-sm font-bold text-warn">{deadline}</span>}
          {waitUntil && <span className="text-sm font-bold text-warn">You can confirm this after {formatTime(waitUntil)}. Saying no is always possible.</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 sm:pl-12">
        {!blocked ? (
          <Button className="h-11 px-5 text-base" disabled={busy || Boolean(waitUntil)} onClick={() => decide(true)}>
            {approveLabel(review)}
          </Button>
        ) : (
          <span className="self-center text-sm text-muted-foreground">{blocked}</span>
        )}
        <Button variant="outline" className="h-11 px-5 text-base" onClick={onOpen}>
          See the evidence
        </Button>
        {!blocked && (
          <Button variant="ghost" className="h-11 px-4 text-base" disabled={busy} onClick={() => decide(false)}>
            No, leave it
          </Button>
        )}
      </div>
    </article>
  )
}
