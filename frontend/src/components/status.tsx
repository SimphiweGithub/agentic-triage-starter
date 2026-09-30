import { Check, CircleHelp, Monitor, ShieldCheck, Smartphone, Tablet } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { GROUP_WORD, type Group } from '@/format'
import type { DeviceKind } from '@/devices'
import { cn } from '@/lib/utils'

const GROUP_STYLE: Record<Group, string> = {
  needs: 'bg-warn-soft text-warn',
  handled: 'bg-info-soft text-info',
  safe: 'bg-muted text-foreground',
}

export function GroupBadge({ group, className }: { group: Group; className?: string }) {
  return <Badge className={cn('h-6 px-3 text-sm font-bold', GROUP_STYLE[group], className)}>{GROUP_WORD[group]}</Badge>
}

export function GroupIcon({ group }: { group: Group }) {
  const Icon = group === 'needs' ? CircleHelp : group === 'handled' ? ShieldCheck : Check
  return (
    <span className={cn('grid size-10 shrink-0 place-items-center rounded-full', GROUP_STYLE[group])}>
      <Icon className="size-5" aria-hidden="true" />
    </span>
  )
}

export function DeviceIcon({ kind, className }: { kind: DeviceKind; className?: string }) {
  const Icon = kind === 'phone' ? Smartphone : kind === 'tablet' ? Tablet : Monitor
  return <Icon className={className} aria-hidden="true" />
}

