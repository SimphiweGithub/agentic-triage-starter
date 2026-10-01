import { Ban, Inbox, Landmark, MailX, ShieldCheck, Wallet } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { api } from '@/api'
import { sourceLabel } from '@/format'
import { cn } from '@/lib/utils'

/** `GET /people/{id}/person/stats`: what Scam Stop stopped for the protected person, as counts only. */
export type ProtectionStats = {
  messages_checked: number
  scams_stopped: number
  senders_blocked: number
  emails_binned: number
  debit_orders_blocked: number
  disputes_drafted: number
  money_protected: number
  waiting: number
  channels: Record<string, number>
  weeks: { week_start: string; checked: number; stopped: number }[]
}

export function useProtectionStats(personId: string | undefined): ProtectionStats | null {
  const [stats, setStats] = useState<ProtectionStats | null>(null)
  useEffect(() => {
    if (!personId) return
    let live = true
    const load = () =>
      api<ProtectionStats>(`/people/${personId}/person/stats`)
        .then((next) => live && setStats(next))
        .catch(() => undefined) // the rest of the page still works; the numbers simply wait for the next try
    load()
    const timer = setInterval(load, 30_000)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [personId])
  return stats
}

const RAND = new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', maximumFractionDigits: 0 })
const SHORT_DAY = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' })

function Tile({ icon, label, value, note, tone }: { icon: ReactNode; label: string; value: string; note: string; tone?: 'info' | 'primary' }) {
  return (
    <div className="grid content-start gap-1 rounded-xl border bg-card px-4 py-3">
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className={cn('grid size-7 place-items-center rounded-md bg-muted [&>svg]:size-4', tone === 'info' && 'bg-info-soft text-info', tone === 'primary' && 'bg-primary/12 text-primary')}>
          {icon}
        </span>
        {label}
      </span>
      <strong className="text-3xl">{value}</strong>
      <span className="text-sm text-muted-foreground">{note}</span>
    </div>
  )
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/** Scam messages stopped each week, one bar per week, newest on the right. Hover or focus a bar to see its numbers. */
function WeeklyChart({ weeks }: { weeks: ProtectionStats['weeks'] }) {
  const [active, setActive] = useState<number | null>(null)
  const top = Math.max(1, ...weeks.map((week) => week.stopped))
  const total = weeks.reduce((sum, week) => sum + week.stopped, 0)
  const shown = active ?? weeks.length - 1
  const week = weeks[shown]

  return (
    <figure className="grid gap-3">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <strong className="text-lg">Scam messages stopped each week</strong>
        <span className="text-sm text-muted-foreground">
          Week of {SHORT_DAY.format(new Date(week.week_start))}: {plural(week.stopped, 'scam message', 'scam messages')} stopped, {plural(week.checked, 'message', 'messages')} checked
        </span>
      </figcaption>
      <div className="flex h-36 items-end gap-0.5 border-b border-border" role="list" aria-label={`${total} scam messages stopped over ${weeks.length} weeks`}>
        {weeks.map((item, index) => (
          <button
            key={item.week_start}
            type="button"
            role="listitem"
            aria-label={`Week of ${SHORT_DAY.format(new Date(item.week_start))}: ${plural(item.stopped, 'scam message', 'scam messages')} stopped, ${plural(item.checked, 'message', 'messages')} checked`}
            className="group flex h-full flex-1 items-end justify-center rounded-t-md px-1 outline-none focus-visible:bg-muted"
            onMouseEnter={() => setActive(index)}
            onMouseLeave={() => setActive(null)}
            onFocus={() => setActive(index)}
            onBlur={() => setActive(null)}
          >
            <span
              className={cn('w-full max-w-10 rounded-t-[4px] bg-info transition-opacity', active !== null && active !== index && 'opacity-50')}
              style={{ height: item.stopped === 0 ? '2px' : `${(item.stopped / top) * 100}%` }}
            />
          </button>
        ))}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{SHORT_DAY.format(new Date(weeks[0].week_start))}</span>
        <span>This week</span>
      </div>
    </figure>
  )
}

function Channels({ channels }: { channels: Record<string, number> }) {
  const rows = Object.entries(channels).sort((a, b) => b[1] - a[1])
  const top = Math.max(1, ...rows.map(([, count]) => count))
  return (
    <div className="grid content-start gap-3">
      <strong className="text-lg">Where the scams came from</strong>
      {rows.length === 0 ? (
        <p className="text-muted-foreground">No scams yet. Each one will show here by where it arrived.</p>
      ) : (
        <ul className="grid gap-2.5">
          {rows.map(([source, count]) => (
            <li key={source} className="grid gap-1">
              <span className="flex justify-between text-base">
                <span>{sourceLabel(source)}</span>
                <strong>{count}</strong>
              </span>
              <span className="h-2 rounded-full bg-muted">
                <span className="block h-2 rounded-full bg-info" style={{ width: `${(count / top) * 100}%` }} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The protected person's own dashboard: what has been stopped for them, in plain words and big numbers. */
export function ProtectionDashboard({ stats }: { stats: ProtectionStats | null }) {
  if (!stats) return <p className="text-muted-foreground">Loading your protection…</p>

  const headline =
    stats.scams_stopped === 0
      ? 'No scams have reached you yet.'
      : `Scam Stop has stopped ${plural(stats.scams_stopped, 'scam', 'scams')} for you.`

  return (
    <section aria-labelledby="protection" className="grid gap-5">
      <div className="grid gap-1">
        <h2 id="protection" className="flex items-center gap-2 text-2xl font-bold">
          <ShieldCheck className="size-6 text-info" aria-hidden="true" />
          {headline}
        </h2>
        <p className="text-base text-muted-foreground">
          {stats.messages_checked === 0 ? 'Messages are checked as they arrive.' : `${plural(stats.messages_checked, 'message has', 'messages have')} been checked so far.`}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Tile icon={<ShieldCheck aria-hidden="true" />} tone="info" label="Scams stopped" value={String(stats.scams_stopped)} note="Messages that were scams" />
        <Tile icon={<Inbox aria-hidden="true" />} label="Messages checked" value={String(stats.messages_checked)} note="Email, SMS and WhatsApp" />
        <Tile icon={<Ban aria-hidden="true" />} label="Scammers blocked" value={String(stats.senders_blocked)} note="Their next messages are caught too" />
        <Tile icon={<MailX aria-hidden="true" />} label="Emails moved to the Bin" value={String(stats.emails_binned)} note="Still there for 30 days if needed" />
        <Tile icon={<Landmark aria-hidden="true" />} label="Debit orders blocked" value={String(stats.debit_orders_blocked)} note={`${plural(stats.disputes_drafted, 'dispute', 'disputes')} prepared for your bank`} />
        <Tile
          icon={<Wallet aria-hidden="true" />}
          tone="primary"
          label="Money protected"
          value={RAND.format(stats.money_protected)}
          note="Debits that were stopped or disputed"
        />
      </div>

      {stats.weeks.length > 0 && (
        <div className="grid gap-6 rounded-xl border bg-card p-5 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <WeeklyChart weeks={stats.weeks} />
          <Channels channels={stats.channels} />
        </div>
      )}
    </section>
  )
}
