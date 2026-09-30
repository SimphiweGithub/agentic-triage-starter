import { Banknote, Bell, House, Smartphone } from 'lucide-react'

export const TABS = [
  { id: 'today', label: 'Today', icon: House },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'devices', label: 'Devices', icon: Smartphone },
  { id: 'money', label: 'Money', icon: Banknote },
] as const

export type TabId = (typeof TABS)[number]['id']
