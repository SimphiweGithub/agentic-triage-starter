import { useCallback, useEffect, useState } from 'react'
import type { Health, KinGuardState } from './types'

// Empty in development: Vite forwards /api to the backend (see vite.config.ts).
const BASE = `${import.meta.env.VITE_API_URL ?? ''}/api`

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
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
export function useKinGuard(intervalMs = 5000) {
  const [state, setState] = useState<KinGuardState | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [next, nextHealth] = await Promise.all([api<KinGuardState>('/state'), api<Health>('/health')])
      setState(next)
      setHealth(nextHealth)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    }
  }, [])

  useEffect(() => {
    // Deferred so the first fetch's setState does not run synchronously inside the effect.
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, intervalMs])

  return { state, health, error, refresh }
}
