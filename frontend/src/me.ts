import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { Me } from './types'

/** Who the signed-in user is: a caregiver, the protected person, or nobody yet. Refreshed now and then. */
export function useMe(intervalMs = 15000) {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>('/me'))
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
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

  return { me, error, refresh, setMe }
}

/** The invite token in the address, if the person arrived from an invite link. */
export function inviteFromAddress(): string | null {
  return new URLSearchParams(window.location.search).get('invite')
}

export function clearInviteFromAddress(): void {
  const url = new URL(window.location.href)
  url.searchParams.delete('invite')
  window.history.replaceState(null, '', url.pathname + url.search + url.hash)
}
