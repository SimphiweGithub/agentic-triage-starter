import { useCallback, useEffect, useState } from 'react'
import type { GuardianBrief, Health, KinGuardState, Mailbox } from './types'

// Empty in development: Vite forwards /api to the backend (see vite.config.ts).
const BASE = `${import.meta.env.VITE_API_URL ?? ''}/api`

type TokenGetter = () => Promise<string | null>
let getToken: TokenGetter | null = null

/** The signed-in session's token getter, set once by the app. Every call below then carries the token. */
export function setTokenGetter(getter: TokenGetter | null): void {
  getToken = getter
}

let activePerson: string | null = null

/** The person the caregiver is looking at. Calls made through `scoped` are about them and nobody else. */
export function setActivePerson(id: string | null): void {
  activePerson = id
}

/** A path about the active person, for example `scoped('/reviews/REV-1/decision')`. */
export function scoped(path: string): string {
  if (!activePerson) throw new Error('No person is selected')
  return `/people/${activePerson}${path}`
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken ? await getToken() : null
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return body as T
}

export function post<T>(path: string, body?: unknown, headers?: HeadersInit): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}), headers })
}

/** Everything the dashboard shows, refreshed every few seconds so new alerts appear on their own. */
export function useKinGuard(personId: string, intervalMs = 5000) {
  const [state, setState] = useState<KinGuardState | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [briefs, setBriefs] = useState<GuardianBrief[]>([])
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([])
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [next, nextHealth, nextBriefs, nextMailboxes] = await Promise.all([
        api<KinGuardState>(`/people/${personId}/state`),
        api<Health>('/health'),
        api<GuardianBrief[]>(`/people/${personId}/guardian/briefs`).catch(() => [] as GuardianBrief[]),
        api<Mailbox[]>(`/people/${personId}/mailboxes`).catch(() => [] as Mailbox[]),
      ])
      setState(next)
      setHealth(nextHealth)
      setBriefs(nextBriefs)
      setMailboxes(nextMailboxes)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    }
  }, [personId])

  useEffect(() => {
    // Deferred so the first fetch's setState does not run synchronously inside the effect.
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, intervalMs])

  return { state, health, briefs, mailboxes, error, refresh }
}
