import { UserButton } from '../auth'
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
import { ROLE, initial, type CircleMember } from '@/circle'
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
  callsWaiting: number
  /** The active person's care circle, and which of them is signed in. */
  circle: CircleMember[]
  you: CircleMember | undefined
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

export function AppSidebar({ tab, onTab, alertsWaiting, callsWaiting, circle, you, devices, guardian, people, activeId, onSelectPerson, onAddPerson, onOpenDevice, onAddDevice }: Props) {
  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" aria-hidden="true" />
          </span>
          <strong className="text-xl">Scam Stop</strong>
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
                    {active && <CircleFaces circle={circle} />}
                    {!active && waiting > 0 && (
                      <SidebarMenuBadge className="bg-warn text-white!" aria-label={`${waiting} waiting for ${person.name}`}>
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
                  {item.id === 'alerts' && alertsWaiting > 0 && <SidebarMenuBadge className="bg-warn text-white!">{alertsWaiting}</SidebarMenuBadge>}
                  {item.id === 'calls' && callsWaiting > 0 && <SidebarMenuBadge className="bg-warn text-white!">{callsWaiting}</SidebarMenuBadge>}
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
        <div className="grid justify-items-start gap-1.5 rounded-lg border bg-background p-3 text-sm">
          {you && <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-bold', ROLE[you.role].chip)}>{ROLE[you.role].label}</span>}
          <strong>Looking after {PERSON.name}</strong>
          <span className="text-muted-foreground">
            {guardian === false
              ? `No next of kin enrolled: ${PERSON.name} decides for themselves, after a cooling-off.`
              : you?.role === 'next_of_kin'
                ? `You approve anything that touches ${PERSON.name}’s bank.`
                : you
                  ? ROLE[you.role].summary
                  : 'Anything that touches the bank waits for the next of kin.'}
          </span>
        </div>
        <UserButton />
      </SidebarFooter>
    </Sidebar>
  )
}

/** The other people in the active person's circle, as overlapping initials. */
function CircleFaces({ circle }: { circle: CircleMember[] }) {
  const others = circle.filter((member) => member.role !== 'protected')
  if (others.length === 0) return null
  return (
    <div className="flex items-center gap-2 px-2 pt-1 pb-2 text-xs text-muted-foreground">
      <span className="flex">
        {others.slice(0, 4).map((member, index) => (
          <span key={member.id} title={`${member.you ? 'You' : member.name} · ${ROLE[member.role].label}`} className={cn('grid size-6 place-items-center rounded-full border-2 border-sidebar text-[11px] font-bold', ROLE[member.role].avatar, index > 0 && '-ml-2')}>
            {member.you ? 'Y' : initial(member.name)}
          </span>
        ))}
      </span>
      <span>
        {others.length} {others.length === 1 ? 'person' : 'people'} in the circle
      </span>
    </div>
  )
}
