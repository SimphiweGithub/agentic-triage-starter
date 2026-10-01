import { useCallback, useState } from 'react'
import { sourceLabel, type Channel } from './format'
import type { KinGuardState } from './types'

export type DeviceKind = 'phone' | 'tablet' | 'computer'

export type Device = {
  id: string
  name: string
  kind: DeviceKind
  /** Channels switched on. A channel missing from KIND_CHANNELS[kind] is not possible on that device. */
  on: Channel[]
  added: string
}

export const KIND_LABEL: Record<DeviceKind, string> = { phone: 'Phone', tablet: 'Tablet', computer: 'Computer' }

export const KIND_CHANNELS: Record<DeviceKind, Channel[]> = {
  phone: ['SMS', 'WhatsApp'],
  tablet: ['WhatsApp'],
  computer: ['WhatsApp'],
}

const LEGACY_KEY = 'kinguard.devices'
const keyFor = (personId: string) => `kinguard.devices.${personId}`

function load(personId: string, inherit: boolean): Device[] {
  try {
    // Before several people were supported there was one list. The first person keeps it.
    const saved = localStorage.getItem(keyFor(personId)) ?? (inherit ? localStorage.getItem(LEGACY_KEY) : null)
    const parsed: unknown = JSON.parse(saved ?? '[]')
    if (!Array.isArray(parsed)) return []
    // Email used to be a per-device channel; mailboxes belong to the person now, so drop it from saved devices.
    return (parsed as Device[]).map((device) => ({ ...device, on: device.on.filter((channel) => KIND_CHANNELS[device.kind]?.includes(channel)) }))
  } catch {
    return []
  }
}

/**
 * The server does not know about devices yet, so they are kept in this browser.
 * Switching a channel off here is a reminder for the caregiver, not a filter on the server.
 */
export function useDevices(personId: string, inherit = false) {
  const [devices, setDevices] = useState<Device[]>(() => load(personId, inherit))

  const save = useCallback(
    (next: Device[]) => {
      setDevices(next)
      try {
        localStorage.setItem(keyFor(personId), JSON.stringify(next))
      } catch {
        // Storage can be blocked; the list still works until the page closes.
      }
    },
    [personId],
  )

  const add = (name: string, kind: DeviceKind, on: Channel[]) => {
    const device: Device = { id: crypto.randomUUID(), name: name.trim() || `New ${KIND_LABEL[kind].toLowerCase()}`, kind, on, added: new Date().toISOString() }
    save([...devices, device])
    return device
  }
  const update = (id: string, patch: Partial<Device>) => save(devices.map((item) => (item.id === id ? { ...item, ...patch } : item)))
  const remove = (id: string) => save(devices.filter((item) => item.id !== id))

  return { devices, add, update, remove }
}

export function deviceGaps(device: Device): Channel[] {
  return KIND_CHANNELS[device.kind].filter((channel) => !device.on.includes(channel))
}

/** What the server has really seen on each channel: the newest message and how many. */
export function channelActivity(state: KinGuardState): Record<string, { last: string; count: number }> {
  const result: Record<string, { last: string; count: number }> = {}
  for (const report of state.reports) {
    const name = sourceLabel(report.source)
    const seen = result[name] ?? { last: '', count: 0 }
    result[name] = { last: report.timestamp > seen.last ? report.timestamp : seen.last, count: seen.count + 1 }
  }
  return result
}
