import { useState } from 'react'
import { toast } from 'sonner'
import { GroupBadge } from '@/components/status'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PERSON, alertGroup, formatTime, money, threatLabel, titleCase } from '@/format'
import type { Dispute, Incident, KinGuardState } from '@/types'

type Props = { state: KinGuardState; onOpenAlert: (incidentId: string) => void }

function amountOf(incident: Incident, state: KinGuardState): string {
  const fromActions = incident.actions.map((item) => item.action.details.amount)
  const fromReviews = state.reviews.filter((item) => item.incident_id === incident.incident_id).map((item) => item.proposed_action?.details.amount)
  return money([...fromActions, ...fromReviews].find((value) => typeof value === 'number'))
}

export function Money({ state, onOpenAlert }: Props) {
  const [openDispute, setOpenDispute] = useState<string | null>(null)
  const companies = state.incidents.filter((item) => item.labels.merchant).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  const disputes = Object.entries(state.world.disputes)
  const current = openDispute ? state.world.disputes[openDispute] : undefined

  return (
    <>
      <header className="grid gap-1">
        <h1 className="text-3xl font-bold tracking-tight">Money</h1>
        <p className="text-lg text-muted-foreground">Companies taking money from {PERSON.name}’s account or asking to, and what KinGuard is doing about them.</p>
      </header>

      {companies.length === 0 ? (
        <p className="my-10 text-center text-muted-foreground">No companies seen yet.</p>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {companies.map((incident) => (
            <li key={incident.incident_id}>
              <button type="button" className="h-full w-full rounded-xl text-left ring-1 ring-foreground/10 transition hover:ring-2 hover:ring-primary" onClick={() => onOpenAlert(incident.incident_id)}>
                <Card className="h-full ring-0">
                  <CardContent className="grid justify-items-start gap-2">
                    <GroupBadge group={alertGroup(incident)} />
                    <strong className="text-lg">{titleCase(incident.labels.merchant)}</strong>
                    {amountOf(incident, state) && <span className="text-3xl font-bold">{amountOf(incident, state)}</span>}
                    <span className="text-sm text-muted-foreground">
                      {threatLabel(incident.labels.threat)} · {formatTime(incident.updated_at)}
                      {incident.labels.reg_no && ` · ${incident.labels.reg_no}`}
                    </span>
                  </CardContent>
                </Card>
              </button>
            </li>
          ))}
        </ul>
      )}

      {disputes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">Disputes ready to lodge</CardTitle>
            <CardDescription>KinGuard wrote them. Only {PERSON.name} or the bank can send them.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {disputes.map(([regNo, dispute]) => (
                <li key={regNo} className="flex items-center gap-3 py-3">
                  <div className="grid min-w-0 flex-1">
                    <strong>Company registration {regNo}</strong>
                    {dispute.dispute_by && <span className="text-sm font-bold text-warn">Lodge by {dispute.dispute_by}</span>}
                  </div>
                  <Button variant="outline" className="h-10 px-4" onClick={() => setOpenDispute(regNo)}>
                    View dispute
                  </Button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">Debits being stopped</CardTitle>
            <CardDescription>Operators the bank is asked to refuse.</CardDescription>
          </CardHeader>
          <CardContent>
            <Tags items={state.world.blocked} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold">Trusted by {PERSON.name}</CardTitle>
            <CardDescription>Companies {PERSON.name} confirmed as their own.</CardDescription>
          </CardHeader>
          <CardContent>
            <Tags items={state.world.trusted.map(titleCase)} />
          </CardContent>
        </Card>
      </div>

      <DisputeDialog regNo={openDispute} dispute={current} onClose={() => setOpenDispute(null)} />
    </>
  )
}

function DisputeDialog({ regNo, dispute, onClose }: { regNo: string | null; dispute?: Dispute; onClose: () => void }) {
  async function copy() {
    if (!dispute) return
    try {
      await navigator.clipboard.writeText(dispute.text)
      toast.success('Dispute text copied')
    } catch {
      toast.error('Could not copy. Select the text and copy it by hand.')
    }
  }

  return (
    <Dialog open={Boolean(dispute)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90svh] gap-4 overflow-y-auto p-6 sm:max-w-xl">
        {dispute && (
          <>
            <DialogHeader>
              <DialogTitle className="text-xl font-bold">Dispute ready to lodge</DialogTitle>
              <DialogDescription>Company registration {regNo}</DialogDescription>
            </DialogHeader>
            {dispute.dispute_by && <p className="font-bold text-warn">Lodge by {dispute.dispute_by}.</p>}
            <blockquote className="rounded-lg bg-background px-4 py-3 break-words">{dispute.text}</blockquote>
            {dispute.steps.length > 0 && (
              <ol className="list-decimal space-y-1 pl-5">
                {dispute.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}
            <Button className="h-10 w-fit px-4" onClick={copy}>
              Copy dispute text
            </Button>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Tags({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-muted-foreground">None.</p>
  return (
    <ul className="flex flex-wrap gap-2">
      {items.map((item) => (
        <li key={item}>
          <Badge variant="outline" className="h-7 font-mono text-sm">
            {item}
          </Badge>
        </li>
      ))}
    </ul>
  )
}
