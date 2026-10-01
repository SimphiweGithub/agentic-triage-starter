import { Lock, Phone } from 'lucide-react'
import { GroupBadge, GroupIcon } from '@/components/status'
import { Button } from '@/components/ui/button'
import type { Group } from '@/format'
import { cn } from '@/lib/utils'

/**
 * A still picture of the caregiver's Today page for the signed-out landing page. Everything here is made up:
 * nobody's real alerts are ever shown before sign-in. It reuses the dashboard's badges and colours so it looks the same.
 */

type Row = { title: string; detail: string; group: Group; call?: boolean; time: string }

const ROWS: Row[] = [
  { title: 'Debit order from “Lifestyle Rewards”', detail: 'Bank SMS · R349.00 a month', group: 'needs', time: '09:42' },
  { title: 'Fake courier asking for a customs fee', detail: 'SMS · link blocked', group: 'handled', time: '08:15' },
  { title: 'Unknown caller asked for a code', detail: 'Call · +27 87 550 1123 · 4 min', group: 'needs', call: true, time: 'Yesterday' },
  { title: '“Your account is suspended” email', detail: 'Email · moved to Bin', group: 'handled', time: 'Yesterday' },
  { title: 'Pharmacy reminder', detail: 'WhatsApp · nothing wrong', group: 'safe', time: 'Mon' },
]

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'info' | 'warn' }) {
  return (
    <div className={cn('grid gap-0.5 rounded-xl border bg-card px-3 py-2.5', tone === 'warn' && 'border-warn-edge bg-warn-soft')}>
      <span className={cn('text-xs text-muted-foreground', tone === 'warn' && 'text-warn')}>{label}</span>
      <strong className={cn('text-2xl', tone === 'info' && 'text-info', tone === 'warn' && 'text-warn')}>{value}</strong>
      <span className={cn('text-xs text-muted-foreground', tone === 'warn' && 'text-warn')}>{note}</span>
    </div>
  )
}

export function DashboardPreview({ className }: { className?: string }) {
  return (
    <figure className={cn('overflow-hidden rounded-2xl border bg-background shadow-xl shadow-foreground/5', className)} aria-label="Example of the family dashboard">
      <div className="flex items-center gap-2 border-b bg-card px-4 py-2.5">
        <span className="size-2.5 rounded-full bg-border" />
        <span className="size-2.5 rounded-full bg-border" />
        <span className="size-2.5 rounded-full bg-border" />
        <span className="ml-2 text-sm font-bold">Today</span>
        <span className="ml-auto rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">Example</span>
      </div>

      <div className="grid gap-4 p-4 sm:p-5" aria-hidden="true">
        <div className="grid gap-0.5">
          <span className="text-sm text-muted-foreground">Tuesday · Good morning</span>
          <strong className="text-xl leading-tight sm:text-2xl">
            Gran is safe. <span className="text-warn">2 things need you.</span>
          </strong>
        </div>

        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <Stat label="Messages checked" value="148" note="Email, SMS and WhatsApp" />
          <Stat label="Calls this week" value="11" note="3 from unknown numbers" />
          <Stat label="Scams handled" value="9" note="4 scammers marked" tone="info" />
          <Stat label="Money at risk" value="R349" note="1 decision waiting" tone="warn" />
        </div>

        <div className="overflow-hidden rounded-xl border-2 border-warn-edge bg-card">
          <div className="bg-warn-soft/50 px-4 py-2.5 text-base font-bold">Waiting for you</div>
          <div className="grid gap-2 border-t border-warn-edge/40 px-4 py-3">
            <strong className="text-base leading-snug">Stop the R349 debit order from “Lifestyle Rewards”?</strong>
            <span className="text-sm text-muted-foreground">Gran says she never signed up. Scam Stop can ask the bank to block it and dispute last month’s payment.</span>
            <div className="flex flex-wrap gap-2">
              <Button tabIndex={-1} className="pointer-events-none h-9 px-4">
                Block and dispute
              </Button>
              <Button tabIndex={-1} variant="outline" className="pointer-events-none h-9 px-4">
                It’s hers, leave it
              </Button>
            </div>
          </div>
        </div>

        <div className="rounded-xl border bg-card px-4 py-3">
          <div className="flex items-center justify-between pb-1">
            <strong className="text-base">What happened recently</strong>
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Lock className="size-3" /> Calls never listened to
            </span>
          </div>
          <ul className="divide-y">
            {ROWS.map((row) => (
              <li key={row.title} className="flex items-center gap-3 py-2.5">
                {row.call ? (
                  <span className="grid size-10 shrink-0 place-items-center rounded-full bg-warn-soft text-warn">
                    <Phone className="size-5" />
                  </span>
                ) : (
                  <GroupIcon group={row.group} />
                )}
                <span className="grid min-w-0 flex-1">
                  <strong className="truncate text-sm sm:text-base">{row.title}</strong>
                  <span className="truncate text-xs text-muted-foreground sm:text-sm">{row.detail}</span>
                </span>
                <span className="hidden justify-items-end gap-1 sm:grid">
                  <GroupBadge group={row.group} />
                  <span className="text-xs text-muted-foreground">{row.time}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </figure>
  )
}
