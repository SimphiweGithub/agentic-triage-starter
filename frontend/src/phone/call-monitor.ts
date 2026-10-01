import { registerPlugin } from '@capacitor/core'
import type { CallAnswer } from '../calls'

/** A call that just ended from a number not in the contacts, waiting for the person to say how it went. */
export interface EndedCall {
  callId: string
  number: string
  seconds: number
  timestamp: string // ISO 8601, UTC
}

/** What the native CallMonitor plugin reports. Never who called. */
export interface CallMonitorStatus {
  /** Android allowed the app to see call state and contacts. */
  granted: boolean
  /** The call reminders are switched on. */
  enabled: boolean
  calls: number // incoming calls seen since install
  lastCall: string // ISO 8601, UTC; empty if none yet
  lastAnswered: boolean
  tips: string
}

/**
 * The native call monitor. It only sees that a call started and ended, the number and whether it is a contact,
 * never the audio. After a call from an unknown number it reports the call to the server and shows a notification
 * that opens the app on the call scams screen.
 */
interface CallMonitorPlugin {
  requestAccess(): Promise<{ granted: boolean }>
  status(): Promise<CallMonitorStatus>
  setEnabled(options: { enabled: boolean }): Promise<void>
  /** The unknown call the notification was about, if the app was opened from it. Cleared once read. */
  takeEndedCall(): Promise<{ call: EndedCall | null }>
}

/** Native side: android/app/src/main/java/za/kinguard/app/CallMonitorPlugin.java. `takeEndedCall` is not implemented natively yet, so it rejects and the app treats that as no call. */
export const CallMonitor = registerPlugin<CallMonitorPlugin>('CallMonitor')

/** Tell the server what the person tapped after the call. */
export async function answerCall(server: string, person: string, code: string, callId: string, answer: Exclude<CallAnswer, null>): Promise<void> {
  const response = await fetch(`${server}/api/people/${encodeURIComponent(person)}/calls/${encodeURIComponent(callId)}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Device-Key': code },
    body: JSON.stringify({ answer }),
  })
  if (!response.ok) throw new Error(`The server answered ${response.status}`)
}
