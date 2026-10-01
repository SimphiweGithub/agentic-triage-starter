import { Banknote, Bell, House, Phone, Smartphone, Users } from 'lucide-react'

export const TABS = [
  { id: 'today', label: 'Today', icon: House },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'calls', label: 'Calls', icon: Phone },
  { id: 'money', label: 'Money', icon: Banknote },
  { id: 'devices', label: 'Devices', icon: Smartphone },
  { id: 'circle', label: 'Care circle', icon: Users },
] as const

export type TabId = (typeof TABS)[number]['id']
