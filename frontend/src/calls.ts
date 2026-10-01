import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

/**
 * What the person tapped on the phone after a call from an unknown number.
 * `asked_code`: the caller asked for a PIN, OTP or password. `told_kin`: they asked the app to tell their next of kin.
 */
export type CallAnswer = 'known' | 'asked_code' | 'told_kin' | null

/** One phone call the Android call monitor noticed. Only who, when and how long: the call itself is never heard. */
export type Call = {
  call_id: string
  number: string
  at: string
  seconds: number
  in_contacts: boolean
  contact_name: string | null
  /** The phone showed the common call scams after the call ended. */
  tips_shown: boolean
  answer: CallAnswer
}

export function callNeedsYou(call: Call): boolean {
  return call.answer === 'asked_code' || call.answer === 'told_kin'
}

export function callAnswerText(call: Call, name: string): string {
  if (call.in_contacts) return `In ${name}’s contacts · no tips shown`
  switch (call.answer) {
    case 'asked_code':
      return `${name} said: they asked for a PIN or code`
    case 'told_kin':
      return `${name} asked for you to be told about this call`
    case 'known':
      return `Tips shown · ${name} tapped “Someone I know”`
    default:
      return call.tips_shown ? 'Tips shown · no answer yet' : 'Unknown number'
  }
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.round(seconds / 60)
  return `${minutes} min`
}

export function isToday(iso: string, now = new Date()): boolean {
  const date = new Date(iso)
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
}

/**
 * Calls the phone reported for one person, newest first. `supported` is false while the server has no
 * calls route yet, so screens can say the call monitor is not switched on rather than "no calls".
 */
export function useCalls(personId: string, intervalMs = 10000) {
  const [calls, setCalls] = useState<Call[]>([])
  const [supported, setSupported] = useState<boolean | null>(null)

  const refresh = useCallback(async () => {
    try {
      const next = await api<Call[]>(`/people/${personId}/calls`)
      setCalls([...next].sort((a, b) => b.at.localeCompare(a.at)))
      setSupported(true)
    } catch {
      setSupported(false)
    }
  }, [personId])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, intervalMs])

  return { calls, supported, refresh }
}

/** The common call scams the phone shows after an unknown caller hangs up. Kept here so the dashboard can show the same list. */
export const CALL_SCAMS = [
  { title: 'Said they are from your bank', text: 'and asked for a PIN, OTP or to “confirm” a payment.' },
  { title: 'Said you won a prize', text: 'but you must pay a fee first to get it.' },
  { title: 'Said a family member is in trouble', text: 'and needs money now. Hang up and call them yourself.' },
  { title: 'Said your computer or phone has a virus', text: 'and asked you to install an app.' },
  { title: 'Rushed you or said to keep it secret', text: 'Real companies give you time to think.' },
] as const
