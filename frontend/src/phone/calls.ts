import { registerPlugin } from '@capacitor/core'

/** The call reminders, as the native CallMonitor plugin reports them. Never who called. */
export interface CallStatus {
  granted: boolean // the phone's call state may be read
  enabled: boolean // reminders are switched on
  calls: number // incoming calls seen since install
  lastCall: string // ISO 8601, UTC; empty if none yet
  lastAnswered: boolean
  tips: string
}

interface CallMonitorPlugin {
  requestAccess(): Promise<{ granted: boolean }>
  status(): Promise<CallStatus>
  setEnabled(options: { enabled: boolean }): Promise<void>
}

/** The plugin in android/app/src/main/java/za/kinguard/app/CallMonitorPlugin.java. */
export const CallMonitor = registerPlugin<CallMonitorPlugin>('CallMonitor')
