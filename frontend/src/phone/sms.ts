import { registerPlugin } from '@capacitor/core'

/** One received text, as the native SmsInbox plugin reports it. */
export interface PhoneSms {
  sender: string
  text: string
  timestamp: string // ISO 8601, UTC
  millis: number
}

/** How the native bridge is doing. It forwards new texts and chat messages by itself, with the app closed. */
export interface BridgeStatus {
  notificationAccess: boolean // WhatsApp and other chat apps can be read
  sms: boolean // texts can be read
  configured: boolean // knows the server, person and pairing code
  queued: number // waiting because the server could not be reached
  sent: number
  lastSent: string
  lastError: string
}

interface SmsInboxPlugin {
  requestAccess(): Promise<{ granted: boolean }>
  getMessages(options: { since: number; limit: number }): Promise<{ messages: PhoneSms[] }>
  configureBridge(options: { server: string; person: string; code: string; patterns: string[] }): Promise<void>
  bridgeStatus(): Promise<BridgeStatus>
  openNotificationAccess(): Promise<void>
}

/** The plugin in android/app/src/main/java/za/kinguard/app/SmsInboxPlugin.java. */
export const SmsInbox = registerPlugin<SmsInboxPlugin>('SmsInbox')
