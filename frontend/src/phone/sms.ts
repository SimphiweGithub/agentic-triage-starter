import { registerPlugin, type PluginListenerHandle } from '@capacitor/core'

/** One received text, as the native SmsInbox plugin reports it. */
export interface PhoneSms {
  sender: string
  text: string
  timestamp: string // ISO 8601, UTC
  millis: number
}

interface SmsInboxPlugin {
  requestAccess(): Promise<{ granted: boolean }>
  getMessages(options: { since: number; limit: number }): Promise<{ messages: PhoneSms[] }>
  addListener(event: 'smsReceived', listener: (sms: PhoneSms) => void): Promise<PluginListenerHandle>
}

/** The plugin in android/app/src/main/java/za/kinguard/app/SmsInboxPlugin.java. */
export const SmsInbox = registerPlugin<SmsInboxPlugin>('SmsInbox')
