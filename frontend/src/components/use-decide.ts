import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { post, scoped } from '@/api'
import { actionLabel } from '@/format'
import type { Review } from '@/types'

/** Saving an answer to a review, and the cooling-off before a yes is allowed. Shared by the full card and the compact row. */
export function useDecide(review: Review, onDecided: (message: string) => void) {
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

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

  return { busy, waitUntil, decide }
}
