import { UserButton } from '@clerk/react'
import { Plus, ShieldCheck } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { deviceGaps, type Device } from '@/devices'
import { PERSON } from '@/format'
import type { PersonSummary } from '@/types'
import { cn } from '@/lib/utils'
import { TABS, type TabId } from '@/nav'
import { DeviceIcon } from './status'

type Props = {
  tab: TabId
  onTab: (tab: TabId) => void
  alertsWaiting: number
  devices: Device[]
  /** Whether a caregiver is enrolled for the active person. Undefined until their state has loaded. */
  guardian: boolean | undefined
  people: PersonSummary[]
  activeId: string
  onSelectPerson: (id: string) => void
  onAddPerson: () => void
  onOpenDevice: (id: string) => void
  onAddDevice: () => void
}

export function AppSidebar({ tab, onTab, alertsWaiting, devices, guardian, people, activeId, onSelectPerson, onAddPerson, onOpenDevice, onAddDevice }: Props) {
  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" aria-hidden="true" />
          </span>
          <strong className="text-xl">KinGuard</strong>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-bold tracking-wider uppercase">Looking after</SidebarGroupLabel>
          <SidebarGroupAction title="Add someone" onClick={onAddPerson}>
            <Plus aria-hidden="true" /> <span className="sr-only">Add someone to look after</span>
          </SidebarGroupAction>
          <SidebarGroupContent>
            <SidebarMenu>
              {people.map((person) => {
                const active = person.id === activeId
                const waiting = person.needs + person.problems
                return (
                  <SidebarMenuItem key={person.id}>
                    <SidebarMenuButton size="lg" isActive={active} aria-current={active ? 'true' : undefined} onClick={() => onSelectPerson(person.id)}>
                      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/15 text-sm font-bold text-primary">{person.name.charAt(0).toUpperCase()}</span>
                      <span className="grid flex-1 leading-tight">
                        <strong>{person.name}</strong>
                        {person.relation && <span className="text-xs font-normal text-muted-foreground">{person.relation}</span>}
                      </span>
                    </SidebarMenuButton>
                    {!active && waiting > 0 && (
                      <SidebarMenuBadge className="bg-warn text-white" aria-label={`${waiting} waiting for ${person.name}`}>
                        {waiting}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {TABS.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton size="lg" className="text-base font-bold" isActive={tab === item.id} aria-current={tab === item.id ? 'page' : undefined} onClick={() => onTab(item.id)}>
                    <item.icon className="size-5" aria-hidden="true" />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                  {item.id === 'alerts' && alertsWaiting > 0 && <SidebarMenuBadge className="bg-warn text-white">{alertsWaiting}</SidebarMenuBadge>}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-bold tracking-wider uppercase">Devices</SidebarGroupLabel>
          <SidebarGroupAction title="Add a device" onClick={onAddDevice}>
            <Plus aria-hidden="true" /> <span className="sr-only">Add a device</span>
          </SidebarGroupAction>
          <SidebarGroupContent>
            <SidebarMenu>
              {devices.length === 0 && <li className="px-2 py-1 text-sm text-muted-foreground">None added yet.</li>}
              {devices.map((device) => {
                const gaps = deviceGaps(device).length
                return (
                  <SidebarMenuItem key={device.id}>
                    <SidebarMenuButton size="lg" onClick={() => onOpenDevice(device.id)}>
                      <DeviceIcon kind={device.kind} className="size-5" />
                      <span className="grid flex-1 leading-tight">
                        <strong>{device.name}</strong>
                        <span className="text-xs font-normal text-muted-foreground">{device.on.length === 0 ? 'Paused' : gaps > 0 ? 'Has a gap' : 'Fully covered'}</span>
                      </span>
                      <span className={cn('size-2.5 rounded-full', device.on.length === 0 ? 'bg-input' : gaps > 0 ? 'bg-warn-edge' : 'bg-info')} aria-hidden="true" />
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-3 p-4">
        <div className="grid gap-1 rounded-lg bg-background p-3 text-sm">
          <strong>Looking after {PERSON.name}</strong>
          <span className="text-muted-foreground">
            {guardian === false ? `No guardian enrolled: ${PERSON.name} decides for themselves, after a cooling-off.` : 'You are the guardian. Anything that touches the bank waits for you.'}
          </span>
        </div>
        <UserButton />
      </SidebarFooter>
    </Sidebar>
  )
}
