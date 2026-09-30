import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { PersonSummary } from './types'

/** Everyone the caregiver looks after, with what is waiting on each, refreshed now and then so the switcher can show badges. */
export function usePeopleSummary(intervalMs = 10000) {
  const [people, setPeople] = useState<PersonSummary[]>([])

  const refresh = useCallback(async () => {
    try {
      setPeople(await api<PersonSummary[]>('/people/summary'))
    } catch {
      // The dashboard shows its own connection problem; the switcher just keeps what it had.
    }
  }, [])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, intervalMs])

  return { people, refresh }
}
