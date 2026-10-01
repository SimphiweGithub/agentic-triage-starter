import { deviceGaps, type Device } from './devices'
import type { Channel } from './format'
import type { ActionRecord, Incident, KinGuardState, Mailbox, Review } from './types'

export type FailedAction = { incident: Incident; record: ActionRecord }

export type Actions = {
  reviews: Review[]
  gaps: { device: Device; channels: Channel[] }[]
  failed: FailedAction[]
  /** Mailboxes that are not being checked: the person disconnected, or Google refused the connection. */
  mailboxes: Mailbox[]
  total: number
}

/** Everything that is waiting on the caregiver: decisions, coverage gaps, mailbox trouble and actions that did not work. */
export function collectActions(state: KinGuardState, devices: Device[], mailboxes: Mailbox[]): Actions {
  const reviews = state.reviews.filter((item) => item.status === 'PENDING')
  const gaps = devices.map((device) => ({ device, channels: deviceGaps(device) })).filter((item) => item.channels.length > 0)
  const failed = state.incidents
    .filter((incident) => incident.status !== 'RESOLVED' && incident.status !== 'CLOSED')
    .flatMap((incident) =>
      incident.actions
        .map((record, index) => ({ record, index }))
        .filter(({ record, index }) => record.outcome === 'FAILED' && !incident.actions.slice(index + 1).some((later) => later.action.type === record.action.type && later.outcome === 'EXECUTED'))
        .map(({ record }) => ({ incident, record })),
    )
  const broken = mailboxes.filter((item) => item.status !== 'connected')
  return { reviews, gaps, failed, mailboxes: broken, total: reviews.length + gaps.length + failed.length + broken.length }
}
